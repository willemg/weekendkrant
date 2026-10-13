from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database
from daily import run_daily
from ingress_queue import IngressQueue
from sherlock_state import SherlockState
from telemetry import report


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'queue.sqlite3'
        self.queue = IngressQueue(self.path)
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.state = SherlockState(self.db)
        self.run_id = self.state.start_run(1)
        self.fiche = {'schema_version': 1, 'topic': 1, 'date': '2026-10-13', 'content': '# Test\néén'}

    def test_atomic_publication_persists_mapping_after_processing_and_finish(self):
        identities = [self.queue.add(self.fiche, run_id=self.run_id) for _ in range(2)]
        self.assertEqual(self.db.execute('SELECT queue_item_id,run_id FROM sherlock_fiches ORDER BY queue_item_id').fetchall(),
                         [(i, self.run_id) for i in identities])
        for raw, in self.db.execute('SELECT payload FROM ingress_queue'):
            self.assertEqual(json.loads(raw), self.fiche)
        result = run_daily(Path(self.tmp.name) / 'app', db_path=self.path,
                           output=Path(self.tmp.name) / 'parts',
                           lock_path=Path(self.tmp.name) / 'ariadne.lock',
                           now=datetime(2026, 10, 13, 18, tzinfo=timezone.utc))
        self.assertEqual(result['status'], 'success')
        self.state.finish_run(self.run_id, 'completed')
        result = report(self.path, now=datetime.now(timezone.utc))['sherlock']
        self.assertEqual(result['published_fiches'], 2)
        self.assertEqual(result['by_run'][0]['queue_item_ids'], identities)
        self.assertEqual(result['by_topic']['1']['published_fiches'], 2)
        self.assertEqual(result['by_run'][0]['published_fiches'], 2)
        self.assertEqual(result['by_run'][0]['registered_sources'], 0)

    def test_multiple_topics_sources_and_failed_running_publications(self):
        run2 = self.state.start_run(2)
        run3 = self.state.start_run(3)
        for run_id, topic, count in [(self.run_id, 1, 3), (run2, 2, 1), (run3, 3, 2)]:
            for n in range(count):
                self.state.record_reviewed_source(run_id, topic,
                    'https://example.org/%s/%s' % (run_id, n), 'reviewed', 'fixture')
            self.queue.add(dict(self.fiche, topic=topic), run_id=run_id)
        self.state.finish_run(self.run_id, 'completed')
        self.state.finish_run(run2, 'failed')
        result = report(self.path)['sherlock']
        self.assertEqual(result['published_fiches'], 3)
        self.assertEqual(result['registered_sources'], 6)
        self.assertEqual([r['published_fiches'] for r in result['by_run']], [1, 1, 1])
        self.assertEqual([r['registered_sources'] for r in result['by_run']], [3, 1, 2])

    def test_concurrent_finish_and_publish_are_serialized(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        ready = Barrier(2)
        def finish():
            with sqlite3.connect(self.path) as db:
                state = SherlockState(db)
                ready.wait(timeout=5)
                state.finish_run(self.run_id, 'completed')
        def publish():
            ready.wait(timeout=5)
            try:
                return self.queue.add(self.fiche, run_id=self.run_id)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            ended = pool.submit(finish)
            published = pool.submit(publish)
            identity = published.result(timeout=10)
            ended.result(timeout=10)
        rows = self.db.execute('SELECT queue_item_id FROM sherlock_fiches').fetchall()
        self.assertEqual(rows, [] if identity is None else [(identity,)])
        self.assertEqual(self.queue.pending_count(), len(rows))

    def test_legacy_fiches_are_unattributed_without_guessing(self):
        self.queue.add(self.fiche)
        result = report(self.path)['sherlock']
        self.assertEqual(result['published_fiches'], 0)
        self.assertEqual(result['by_run'][0]['queue_item_ids'], [])
        self.assertEqual(report(self.path)['queue']['unattributed_items'], 1)

    def test_bad_run_id_topic_schema_and_closed_run_never_insert(self):
        for run_id in (True, 0, -1, 1.5, '1', 999):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.queue.add(self.fiche, run_id=run_id)
        for change in ({'topic': 2}, {'topic': True}, {'content': ''}, {'date': 'bad'}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.queue.add(dict(self.fiche, **change), run_id=self.run_id)
        self.state.finish_run(self.run_id, 'failed')
        with self.assertRaises(ValueError):
            self.queue.add(self.fiche, run_id=self.run_id)
        self.assertEqual(self.queue.pending_count(), 0)

    def test_failed_mapping_rolls_back_queue_insert(self):
        with self.db:
            self.db.execute("CREATE TRIGGER reject_fiche BEFORE INSERT ON sherlock_fiches BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.queue.add(self.fiche, run_id=self.run_id)
        self.assertEqual(self.queue.pending_count(), 0)

    def test_mapping_is_immutable_and_foreign_keys_are_enforced(self):
        identity = self.queue.add(self.fiche, run_id=self.run_id)
        for sql in ('UPDATE sherlock_fiches SET run_id=99', 'DELETE FROM sherlock_fiches'):
            with self.assertRaises(sqlite3.IntegrityError), self.db:
                self.db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute('INSERT INTO sherlock_fiches VALUES (?,?)', (identity + 99, self.run_id))

    @patch.object(database, 'SCHEMA_VERSION', 5)
    def test_v4_upgrade_preserves_legacy_and_no_backfill(self):
        path = Path(self.tmp.name) / 'old.sqlite3'
        with sqlite3.connect(path) as db:
            with patch.object(database, 'SCHEMA_VERSION', 4):
                database.migrate(db)
            with db:
                db.execute("INSERT INTO ingress_queue(received_at,payload) VALUES ('old','{}')")
                db.execute("INSERT INTO sherlock_runs(topic,started_at) VALUES (1,'old')")
            before = list(db.execute('SELECT * FROM ingress_queue'))
            old_report = report(path)
            self.assertIsNone(old_report['sherlock']['published_fiches'])
            database.migrate(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (5,))
            self.assertEqual(list(db.execute('SELECT * FROM ingress_queue')), before)
            self.assertEqual(db.execute('SELECT * FROM sherlock_fiches').fetchall(), [])
            snapshot = list(db.iterdump())
            database.migrate(db)
            self.assertEqual(list(db.iterdump()), snapshot)

    def test_failed_fifth_migration_rolls_back(self):
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 4):
                database.migrate(db)
            before = list(db.iterdump())
            sql = database.migration_sql
            with patch.object(database, 'migration_sql', side_effect=lambda v: sql(v) + '; CREATE TABLE sherlock_fiches(conflict);'):
                with self.assertRaises(sqlite3.OperationalError):
                    database.migrate(db)
            self.assertEqual(list(db.iterdump()), before)
