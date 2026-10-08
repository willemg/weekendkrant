from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ariadne
import daily
from ingress_queue import IngressQueue


class BacklogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / 'app'
        self.root.mkdir()  # Deliberately not a Git repository.
        self.db, self.output, self.lock = base / 'queue.db', base / 'output', base / 'ariadne.lock'
        self.queue = IngressQueue(self.db)

    def add(self, day='2026-10-05', topic=2, content='bron'):
        return self.queue.add(dict(schema_version=1, date=day, topic=topic, content=content))

    def run_day(self, day=6):
        return daily.run_daily(self.root, self.db, self.output,
                              now=datetime(2026, 10, day, 10, tzinfo=timezone.utc),
                              lock_path=self.lock)

    def rows(self, sql):
        with sqlite3.connect(self.db) as db:
            return db.execute(sql).fetchall()

    def test_failed_monday_is_consumed_with_tuesday_and_future_waits(self):
        self.add()
        with patch.object(daily, 'write_thread', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.run_day(5)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('pending',)])
        self.add('2026-10-06')
        self.add('2026-10-07')
        self.add('2026-10-04')
        self.assertEqual(self.run_day()['threads'], 3)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'),
                         [('processed',), ('processed',), ('pending',), ('processed',)])
        self.assertEqual(self.rows('SELECT DISTINCT day FROM sources ORDER BY day'),
                         [('2026-10-04',), ('2026-10-05',), ('2026-10-06',)])
        for path in self.output.rglob('*.txt'):
            self.assertIn('date: ' + path.name[:10], path.read_text())

    def test_late_arrivals_append_after_registered_parts_and_preserve_bytes(self):
        self.add()
        self.run_day(5)
        original = next(self.output.rglob('*.txt'))
        data = original.read_bytes()
        self.add(content='late')
        self.run_day()
        self.assertEqual(original.read_bytes(), data)
        self.assertIn('late', original.with_name('2026-10-05_0002.txt').read_text())
        self.assertEqual(self.rows('SELECT part FROM threads ORDER BY part'), [(1,), (2,)])

    def test_numbering_ignores_orphan_files_and_retry_after_db_failure(self):
        self.add()
        self.run_day(5)
        directory = next(self.output.rglob('*.txt')).parent
        orphan = directory / '2026-10-05_0099.txt'
        orphan.write_text('orphan')
        identity = self.add(content='late')
        with sqlite3.connect(self.db) as db:
            db.execute(f"CREATE TRIGGER refuse BEFORE UPDATE ON ingress_queue WHEN NEW.id={identity} "
                       "BEGIN SELECT RAISE(ABORT, 'db failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_day()
        planned = directory / '2026-10-05_0002.txt'
        data = planned.read_bytes()
        self.assertEqual(self.rows('SELECT part FROM threads'), [(1,)])
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER refuse')
        self.run_day(7)
        self.assertEqual(planned.read_bytes(), data)
        self.assertEqual(orphan.read_text(), 'orphan')
        self.assertEqual(self.rows('SELECT part FROM threads ORDER BY part'), [(1,), (2,)])

    def test_snapshot_includes_backlog_without_runtime_changes(self):
        self.add()
        self.add("2026-10-06")
        self.add("2026-10-07")
        from datetime import date
        with sqlite3.connect(self.db) as db:
            items = self.queue.pending_for_day(db, date(2026, 10, 6))
        self.assertEqual([identity for identity, _ in items], [1, 2])

    def test_numeric_source_order(self):
        for i in range(10):
            self.add(content=str(i))
        self.run_day()
        self.assertEqual(self.rows('SELECT source_path FROM sources ORDER BY position'),
                         [(f'queue:{i}',) for i in range(1, 11)])

    def test_empty_run_has_no_day_closure_or_writes(self):
        self.add('2026-10-07')
        with patch.object(daily, 'write_thread', side_effect=AssertionError('no write')):
            self.assertEqual(self.run_day()['threads'], 0)
        self.assertEqual(self.rows('SELECT * FROM days'), [])
        self.assertEqual(self.rows('SELECT * FROM attempts'), [])
        self.add('2026-10-06')
        self.assertEqual(self.run_day()['threads'], 1)

    def test_daily_never_executes_git_and_uses_external_lock(self):
        self.add()
        with patch.object(subprocess, 'run', side_effect=AssertionError('no subprocess')):
            self.run_day()
        with ariadne.runtime_lock(self.lock):
            with self.assertRaisesRegex(ValueError, 'Ariadne'):
                self.run_day()

    def test_brussels_boundary_controls_future_selection(self):
        self.add('2026-10-06')
        self.add('2026-10-07')
        result = daily.run_daily(self.root, self.db, self.output,
                                now=datetime(2026, 10, 5, 22, 1, tzinfo=timezone.utc),
                                lock_path=self.lock)
        self.assertEqual(result['date'], '2026-10-06')
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'),
                         [('processed',), ('pending',)])

    def test_existing_success_does_not_hide_malformed_pending(self):
        self.add()
        self.run_day(5)
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO ingress_queue(received_at,payload) VALUES ('now','{')")
        with self.assertRaises(ValueError):
            self.run_day(5)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'),
                         [('processed',), ('pending',)])
        self.assertEqual(self.rows('SELECT status FROM days'), [('success',)])

    def test_success_provenance_survives_late_failure(self):
        self.add()
        self.run_day(5)
        self.add()
        with patch.object(daily, 'weave', side_effect=ValueError('budget')):
            with self.assertRaises(ValueError):
                self.run_day(5)
        self.assertEqual(self.rows('SELECT status FROM days'), [('success',)])
        self.assertEqual(self.rows('SELECT status FROM attempts ORDER BY id'),
                         [('success',), ('processing_error',)])
        self.run_day(5)
        self.assertEqual(self.rows('SELECT part FROM threads ORDER BY part'), [(1,), (2,)])

    def test_late_fiche_starts_at_three_after_two_committed_parts(self):
        self.add(content='a')
        self.add(content='b')
        real_weave = daily.weave
        def split(*args, **kwargs):
            return real_weave(*args, **kwargs, count=len, limit=350, reserve=100)
        with patch.object(daily, 'weave', side_effect=split):
            self.run_day(5)
        self.assertEqual(self.rows('SELECT part FROM threads ORDER BY part'), [(1,), (2,)])
        before = {p: p.read_bytes() for p in self.output.rglob('*.txt')}
        self.add(content='late')
        self.run_day()
        self.assertEqual(self.rows('SELECT part FROM threads ORDER BY part'), [(1,), (2,), (3,)])
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_old_data_is_preserved_and_no_vacuum_occurs(self):
        self.add('2026-01-01')
        self.run_day()
        before = {table: self.rows('SELECT * FROM ' + table)
                  for table in ('days', 'attempts', 'threads', 'sources', 'ingress_queue')}
        statements = []
        original = daily.database
        def traced(path):
            db = original(path)
            db.set_trace_callback(statements.append)
            return db
        with patch.object(daily, 'database', side_effect=traced):
            self.run_day(7)
        for table, rows in before.items():
            self.assertEqual(self.rows('SELECT * FROM ' + table), rows)
        self.assertFalse(any('VACUUM' in sql.upper() or sql.upper().startswith('DELETE')
                             for sql in statements))

    def test_removed_prepare_week_cli_cannot_start_runtime(self):
        import io
        from contextlib import redirect_stderr
        with patch('sys.argv', ['ariadne.py', 'prepare-week', '--next-week']), \
                patch.object(ariadne, 'configure_logging') as configure, \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            ariadne.main()
        self.assertEqual(stopped.exception.code, 2)
        configure.assert_not_called()

    def test_unassignable_dates_and_invalid_future_schema_fail(self):
        bad = ['{}', '{"date":"20261005"}', '{"date":"2026-10-05T00:00:00"}',
               '{"date":"2026-10-07","schema_version":true,"topic":2,"content":"x"}',
               '{"date":"2026-10-07","date":"2026-10-08"}']
        for raw in bad:
            with self.subTest(raw=raw):
                with sqlite3.connect(self.db) as db:
                    db.execute('DELETE FROM ingress_queue')
                    db.execute('INSERT INTO ingress_queue(received_at,payload) VALUES (?,?)', ('now', raw))
                with self.assertRaises(ValueError):
                    self.run_day()
                self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('pending',)])
                self.assertEqual(self.rows('SELECT count(*) FROM threads'), [(0,)])
