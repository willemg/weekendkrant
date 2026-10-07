from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ingress_queue import IngressQueue


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'queue.sqlite3'
        connect = sqlite3.connect
        def temporary_connect(path, *args, **kwargs):
            if Path(path) != self.path:
                raise AssertionError('Test mag alleen eigen tijdelijke database openen')
            return connect(path, *args, **kwargs)
        guard = patch('sqlite3.connect', side_effect=temporary_connect)
        guard.start()
        self.addCleanup(guard.stop)
        self.queue = IngressQueue(self.path)

    def test_add_persist_unique_and_pending(self):
        payload = {'source': 'https://example.org', 'summary': 'één'}
        first = self.queue.add(payload)
        second = self.queue.add({})
        self.assertNotEqual(first, second)
        self.assertEqual(IngressQueue(self.path).pending_count(), 2)
        with sqlite3.connect(self.path) as db:
            rows = db.execute('SELECT id, received_at, payload, status FROM ingress_queue ORDER BY id').fetchall()
        self.assertEqual(rows[0][0], first)
        self.assertEqual(json.loads(rows[0][2]), payload)
        self.assertEqual(rows[0][3], 'pending')
        self.assertIsNotNone(datetime.fromisoformat(rows[0][1]).tzinfo)

    def test_status_schema_has_no_pending_only_constraint(self):
        with sqlite3.connect(self.path) as db:
            schema = db.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'ingress_queue'").fetchone()[0]
        self.assertNotIn('CHECK', schema.upper())
        self.assertIn("status TEXT NOT NULL DEFAULT 'pending'", schema)

    def test_only_json_objects(self):
        for payload in ([], 'text', 1, None, True, {'bad': float('nan')}, {'bad': object()}):
            with self.subTest(payload=payload), self.assertRaises((ValueError, TypeError)):
                self.queue.add(payload)
        self.assertEqual(self.queue.pending_count(), 0)

    def test_existing_database_tables_preserved(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE days (day TEXT)')
            db.execute("INSERT INTO days VALUES ('2026-10-07')")
        IngressQueue(self.path).add({})
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT day FROM days').fetchone()[0], '2026-10-07')
