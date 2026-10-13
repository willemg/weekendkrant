from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

import daily
from ingress_queue import IngressQueue


class QuarterHourTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'app'
        self.root.mkdir()
        self.db, self.output, self.lock = self.base / 'queue.db', self.base / 'parts', self.base / 'lock'
        self.queue = IngressQueue(self.db)

    def add(self, content='bron'):
        return self.queue.add({'schema_version': 1, 'topic': 2, 'date': '2026-10-13', 'content': content})

    def tick(self, minute):
        return daily.run_daily(self.root, self.db, self.output,
                               datetime(2026, 10, 13, 10, minute, tzinfo=timezone.utc), self.lock)

    def rows(self, sql):
        with sqlite3.connect(self.db) as db:
            return db.execute(sql).fetchall()

    def snapshot(self):
        tables = ('ingress_queue', 'source_archive', 'source_materializations',
                  'parts', 'part_revisions', 'revision_sources', 'part_offers', 'attempts')
        return {table: self.rows('SELECT * FROM ' + table + ' ORDER BY 1,2') for table in tables}

    def assert_sources_once(self, identities):
        expected = [(i,) for i in identities]
        self.assertEqual(self.rows('SELECT queue_id FROM source_archive ORDER BY queue_id'), expected)
        self.assertEqual(self.rows('SELECT queue_id FROM source_materializations ORDER BY queue_id'), expected)
        self.assertEqual(self.rows('''SELECT m.queue_id FROM revision_sources m JOIN parts p
            ON p.id=m.part_id AND p.active_revision=m.revision ORDER BY m.queue_id'''), expected)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'), [('processed',)] * len(identities))

    def test_quarter_hour_growth_and_empty_ticks_preserve_registered_files(self):
        a = self.add('A')
        self.assertEqual(self.tick(0)['threads'], 1)
        first = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.rglob('*.txt')}
        b = self.add('B')
        self.assertEqual(self.tick(15)['threads'], 1)
        self.assert_sources_once([a, b])
        self.assertEqual(self.rows('SELECT revision FROM part_revisions ORDER BY revision'), [(1,), (2,)])
        for p, value in first.items():
            self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), value)
        before = self.snapshot()
        files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.rglob('*.txt')}
        with patch.object(daily, 'write_thread', side_effect=AssertionError('Empty tick must not write')):
            for minute in (30, 45):
                self.assertEqual(self.tick(minute)['threads'], 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.rglob('*.txt')}, files)

    def test_failed_registration_retries_next_quarter_without_double_material(self):
        identities = [self.add('A'), self.add('B')]
        with patch.object(daily.PartStore, 'register', side_effect=OSError('registration failure')):
            with self.assertRaises(OSError):
                self.tick(0)
        for table in ('source_archive', 'source_materializations', 'part_revisions'):
            self.assertEqual(self.rows('SELECT * FROM ' + table), [])
        self.assertEqual(self.queue.pending_count(), 2)
        orphans = {p: p.read_bytes() for p in self.output.rglob('*.txt')}
        self.assertTrue(orphans)
        self.tick(15)
        self.assert_sources_once(identities)
        self.assertEqual({p: p.read_bytes() for p in self.output.rglob('*.txt')}, orphans)
        before = self.snapshot()
        self.assertEqual(self.tick(30)['threads'], 0)
        self.assertEqual(self.snapshot(), before)

    def test_real_process_overlap_is_refused_and_late_arrival_waits_for_next_tick(self):
        a = self.add('A')
        entered, release = Event(), Event()
        original = daily.write_thread
        def held_write(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=10):
                raise RuntimeError('Test did not release writer')
            return original(*args, **kwargs)
        # Independent process, independent SQLite connection and same flock path.
        code = '''import sys
from datetime import datetime,timezone
import daily
daily.run_daily(sys.argv[1],sys.argv[2],sys.argv[3],
                datetime(2026,10,13,10,15,tzinfo=timezone.utc),sys.argv[4])
'''
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(daily, 'write_thread', side_effect=held_write):
            running = pool.submit(self.tick, 0)
            try:
                self.assertTrue(entered.wait(timeout=5))
                before = self.snapshot()
                overlap = subprocess.run([sys.executable, '-c', code, str(self.root), str(self.db),
                                          str(self.output), str(self.lock)], capture_output=True, text=True, timeout=5)
                self.assertNotEqual(overlap.returncode, 0)
                self.assertIn('runtime-slot', overlap.stderr)
                self.assertEqual(self.snapshot(), before)
                b = self.add('Late arrival')
            finally:
                release.set()
            self.assertEqual(running.result(timeout=5)['threads'], 1)
        self.assertEqual(self.rows('SELECT queue_id FROM source_archive'), [(a,)])
        self.assertEqual(self.rows('SELECT id,status FROM ingress_queue ORDER BY id'), [(a, 'processed'), (b, 'pending')])
        self.assertNotIn('Late arrival', next(self.output.rglob('*.txt')).read_text())
        self.tick(30)
        self.assert_sources_once([a, b])
        before = self.snapshot()
        self.assertEqual(self.tick(45)['threads'], 0)
        self.assertEqual(self.snapshot(), before)
