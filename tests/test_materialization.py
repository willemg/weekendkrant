from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database
import daily
from ingress_queue import IngressQueue
from telemetry import report


class MaterializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.path = self.base / 'db.sqlite3'
        self.queue = IngressQueue(self.path)
        self.now = datetime(2026, 10, 13, 18, tzinfo=timezone.utc)

    def add(self, topic=1, content='é', date='2026-10-12'):
        return self.queue.add({'schema_version': 1, 'topic': topic, 'date': date, 'content': content})

    def rows(self, sql):
        with sqlite3.connect(self.path) as db:
            return db.execute(sql).fetchall()

    def run_at(self, stamp):
        with patch.object(daily, 'materialization_timestamp', return_value=stamp):
            return daily.run_daily(self.base / 'app', self.path, self.base / 'parts',
                                   self.now, self.base / 'lock')

    def test_growth_counts_new_queue_material_not_repeated_revision_membership(self):
        a = self.add()
        b = self.add(topic=2, content='abc')
        self.run_at('2026-10-13T16:00:00+00:00')
        c = self.add(content='D')
        self.run_at('2026-10-13T17:00:00+00:00')
        result = report(self.path, now=self.now)['materialization']
        self.assertEqual(result['queue_items'], 3)
        self.assertEqual(result['content_bytes'], 6)
        self.assertEqual(result['untimed_archived_items'], 0)
        self.assertEqual([e['queue_item_ids'] for e in result['events']], [[a], [b], [c]])
        self.assertEqual(report(self.path, hours=1, now=self.now)['materialization']['queue_items'], 1)
        before = self.rows('SELECT * FROM source_materializations ORDER BY queue_id')
        self.run_at('2026-10-13T17:30:00+00:00')
        self.assertEqual(self.rows('SELECT * FROM source_materializations ORDER BY queue_id'), before)

    def test_failed_provenance_rolls_back_then_retry_records_actual_time(self):
        self.add()
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER reject_time BEFORE INSERT ON source_materializations BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_at('2026-10-13T16:00:00+00:00')
        self.assertEqual(self.rows('SELECT * FROM source_materializations'), [])
        self.assertEqual(self.rows('SELECT * FROM source_archive'), [])
        self.assertEqual(self.rows('SELECT * FROM part_revisions'), [])
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('pending',)])
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER reject_time')
        self.run_at('2026-10-13T17:00:00+00:00')
        self.assertEqual(self.rows('SELECT materialized_at FROM source_materializations'), [('2026-10-13T17:00:00+00:00',)])

    def test_empty_or_only_future_queue_has_no_materialization_event(self):
        self.add(date='2026-10-14')
        self.run_at('2026-10-13T17:00:00+00:00')
        result = report(self.path, now=self.now)['materialization']
        self.assertEqual(result['events'], [])
        self.assertEqual(result['queue_items'], 0)

    def test_old_archive_times_are_unknown_and_migration_preserves_bytes(self):
        old = self.base / 'old.db'
        with sqlite3.connect(old) as db:
            with patch.object(database, 'SCHEMA_VERSION', 5):
                database.migrate(db)
            with db:
                db.execute("INSERT INTO source_archive VALUES (7,1,'2026-01-01',1,?,'hash')", (b'original',))
            before = db.execute('SELECT * FROM source_archive').fetchall()
            self.assertIsNone(report(old, now=self.now)['materialization'])
            database.migrate(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (database.SCHEMA_VERSION,))
            self.assertEqual(db.execute('SELECT * FROM source_archive').fetchall(), before)
            self.assertEqual(db.execute('SELECT * FROM source_materializations').fetchall(), [])
            snapshot = list(db.iterdump())
            database.migrate(db)
            self.assertEqual(list(db.iterdump()), snapshot)
        result = report(old, now=self.now)['materialization']
        self.assertEqual(result['untimed_archived_items'], 1)
        self.assertEqual(result['queue_items'], 0)

    def test_immutable_event_and_replacement_rejected(self):
        identity = self.add()
        self.run_at('2026-10-13T17:00:00+00:00')
        for sql in ("UPDATE source_materializations SET materialized_at='other'", 'DELETE FROM source_materializations',
                    "INSERT OR REPLACE INTO source_materializations VALUES (%s,'other')" % identity):
            with self.subTest(sql=sql), sqlite3.connect(self.path) as db, self.assertRaises(sqlite3.IntegrityError):
                db.execute(sql)

    def test_invalid_times_are_unknown_and_telemetry_is_readonly(self):
        self.add()
        self.run_at('not a timestamp')
        before = self.path.read_bytes()
        result = report(self.path, now=self.now)
        self.assertEqual(result['materialization']['queue_items'], 0)
        self.assertEqual(result['materialization']['invalid_timestamp_items'], 1)
        self.assertTrue(result['warnings'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_sixth_migration_preserves_old_schema_and_version(self):
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 5):
                database.migrate(db)
            before = list(db.iterdump())
            original = database.migration_sql
            with patch.object(database, 'migration_sql', side_effect=lambda v: original(v) + '; CREATE TABLE source_materializations(conflict);'):
                with self.assertRaises(sqlite3.OperationalError):
                    database.migrate(db)
            self.assertEqual(list(db.iterdump()), before)
