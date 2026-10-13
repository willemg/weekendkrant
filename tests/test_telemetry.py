from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import ariadne
from database import migrate
from telemetry import report


NOW = datetime(2026, 10, 13, 18, tzinfo=timezone.utc)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'baseline #?.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        migrate(self.db)

    def inspect(self, **kwargs):
        self.db.commit()
        before = self.path.read_bytes()
        result = report(self.path, now=NOW, **kwargs)
        self.assertEqual(self.path.read_bytes(), before)
        return result

    def run_fixture(self, identity, topic, status, start, finish, sources):
        self.db.execute('INSERT INTO sherlock_runs VALUES (?,?,?,?,?)',
                        (identity, topic, start, finish, status))
        for n in range(sources):
            url = 'https://example.org/%s/%s' % (identity, n)
            self.db.execute('INSERT INTO sherlock_sources VALUES (?,?,?,?,?,?,?,?)',
                            (url, url, topic, identity, start, None, 'reviewed', 'fixture'))

    def test_empty_initialized_database(self):
        result = self.inspect()
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['sherlock']['runs'], 0)
        self.assertIsNone(result['sherlock']['completed_sources_mean'])
        self.assertIsNone(result['sherlock']['completed_duration_median_seconds'])
        self.assertEqual(result['queue']['pending'], 0)
        self.assertIsNone(result['queue']['oldest_pending'])
        self.assertEqual(result['parts']['open'], [])
        self.assertEqual(result['parts']['offers'], [])

    def test_empty_uninitialized_database_is_not_migrated(self):
        path = Path(self.tmp.name) / 'empty.sqlite3'
        path.touch()
        result = report(path, now=NOW)
        self.assertEqual(path.read_bytes(), b'')
        self.assertEqual(len(result['warnings']), 4)
        for section in ('sherlock', 'queue', 'parts', 'materialization'):
            self.assertIsNone(result[section])

    def test_missing_database_is_not_created(self):
        path = Path(self.tmp.name) / 'missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):
            report(path, now=NOW)
        self.assertFalse(path.exists())

    def test_connection_enforces_read_only_and_single_snapshot(self):
        connect = sqlite3.connect
        statements = []

        def readonly(database_uri, **kwargs):
            self.assertTrue(database_uri.endswith('?mode=ro'))
            self.assertEqual(kwargs, {'uri': True})
            db = connect(database_uri, **kwargs)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("INSERT INTO ingress_queue(received_at,payload) VALUES ('now','{}')")
            db.rollback()
            db.set_trace_callback(statements.append)
            return db

        with patch('telemetry.sqlite3.connect', side_effect=readonly):
            self.inspect()
        self.assertEqual(statements[:2], ['PRAGMA query_only=ON', 'BEGIN'])
        self.assertEqual(sum(s == 'BEGIN' for s in statements), 1)

    def test_statuses_topics_zero_source_runs_and_period_boundaries(self):
        self.run_fixture(1, 1, 'completed', '2026-10-13T17:00:00Z', '2026-10-13T17:04:00Z', 4)
        self.run_fixture(2, 2, 'completed', '2026-10-13T18:30:00+02:00', '2026-10-13T18:40:00+02:00', 2)
        self.run_fixture(3, 3, 'failed', '2026-10-13T15:00:00Z', '2026-10-13T15:02:00Z', 3)
        self.run_fixture(4, 1, 'running', '2026-10-13T17:30:00Z', None, 1)
        # Exact lower boundary is included, zero-source completed runs count.
        self.run_fixture(5, 3, 'completed', '2026-10-12T18:00:00Z', '2026-10-12T18:01:00Z', 0)
        self.run_fixture(6, 1, 'completed', '2026-10-12T17:59:59Z', '2026-10-12T18:10:00Z', 20)
        self.run_fixture(7, 2, 'running', '2026-10-13T18:00:01Z', None, 0)
        result = self.inspect()['sherlock']
        self.assertEqual(result['runs'], 5)
        self.assertEqual(result['statuses'], {'completed': 3, 'failed': 1, 'running': 1})
        self.assertEqual(result['registered_sources'], 10)
        self.assertEqual(result['completed_sources_mean'], 2)
        self.assertEqual(result['completed_sources_min'], 0)
        self.assertEqual(result['completed_sources_max'], 4)
        self.assertEqual(result['completed_duration_mean_seconds'], 300)
        self.assertEqual(result['completed_duration_median_seconds'], 240)
        self.assertEqual(result['by_topic']['1']['registered_sources'], 5)
        self.assertEqual(result['by_topic']['2']['runs'], 1)
        self.assertEqual(self.inspect(hours=1)['sherlock']['runs'], 2)

    def test_invalid_start_or_duration_is_reported_without_guessing(self):
        self.run_fixture(1, 1, 'completed', '2026-10-13T17:00:00Z', '2026-10-13T16:00:00Z', 2)
        self.run_fixture(2, 1, 'completed', '2026-10-13T17:00:00', '2026-10-13T17:01:00Z', 1)
        self.run_fixture(3, 2, 'completed', '2026-10-13T17:00:00Z', '2026-10-13T19:00:00Z', 1)
        result = self.inspect()
        self.assertEqual(result['sherlock']['runs'], 2)
        self.assertEqual(result['sherlock']['completed_duration_samples'], 0)
        self.assertIsNone(result['sherlock']['completed_duration_mean_seconds'])
        self.assertEqual(len(result['warnings']), 3)

    def test_queue_stock_oldest_by_timestamp_not_id_and_unknown_status(self):
        for identity, received, status in [
                (1, '2026-10-13T17:00:00Z', 'pending'),
                (2, '2026-10-13T18:00:00+02:00', 'pending'),
                (3, '2026-10-12T00:00:00Z', 'processed'),
                (4, '2026-10-12T00:00:00Z', 'other')]:
            self.db.execute('INSERT INTO ingress_queue VALUES (?,?,?,?)', (identity, received, '{}', status))
        queue = self.inspect()['queue']
        self.assertEqual((queue['pending'], queue['processed']), (2, 1))
        self.assertEqual(queue['oldest_pending']['id'], 2)
        self.assertEqual(queue['oldest_pending']['age_seconds'], 7200)
        self.assertEqual(queue['other_statuses'], {'other': 1})
        self.db.execute("UPDATE ingress_queue SET received_at='not a time' WHERE id=1")
        result = self.inspect()
        self.assertIsNone(result['queue']['oldest_pending'])
        self.assertEqual(len(result['warnings']), 1)

    def test_future_pending_age_is_unknown(self):
        self.db.execute("INSERT INTO ingress_queue VALUES (1,'2026-10-14T00:00:00Z','{}','pending')")
        result = self.inspect()
        self.assertIsNone(result['queue']['oldest_pending']['age_seconds'])
        self.assertTrue(result['warnings'])

    def test_parts_revisions_open_closed_and_offered(self):
        for identity, week, topic in [(1, '2026_W42', 1), (2, '2026_W42', 2), (3, '2026_W41', 3)]:
            self.db.execute('INSERT INTO parts VALUES (?,?,?,1,1,NULL)', (identity, week, topic))
            for rev in (1, 2):
                self.db.execute('INSERT INTO part_revisions VALUES (?,?,?,?,?,?,?)',
                                (identity, rev, '/fixture/%s/%s' % (identity, rev), 'hash',
                                 100 * rev, 'cl100k_base', 5000))
            self.db.execute('UPDATE parts SET active_revision=2 WHERE id=?', (identity,))
        self.db.execute('UPDATE parts SET is_open=0 WHERE id=2')
        self.db.execute("INSERT INTO part_offers VALUES (1,3,2,'2026-10-13T12:00:00Z')")
        result = self.inspect()['parts']
        self.assertEqual((result['parts'], result['open_parts'], result['revisions']), (3, 1, 6))
        self.assertEqual(result['open'][0]['active_revision'], 2)
        self.assertEqual(result['open'][0]['tokens'], 200)
        self.assertEqual(result['offers'][0]['part_id'], 3)
        self.assertEqual(len(result['by_week_topic']), 3)

    def test_invalid_window(self):
        for hours in (0, -1, float('nan'), float('inf'), 1e100):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                report(self.path, hours=hours, now=NOW)

    def test_cli_json_without_logging_lock_or_daily(self):
        self.db.commit()
        stdout = io.StringIO()
        with patch('sys.argv', ['ariadne.py', 'telemetry', '--db', str(self.path), '--hours', '48']), \
                patch.object(ariadne, 'configure_logging', side_effect=AssertionError('no logging')), \
                patch.object(ariadne, 'runtime_lock', side_effect=AssertionError('no lock')), \
                redirect_stdout(stdout):
            ariadne.main()
        self.assertEqual(json.loads(stdout.getvalue())['sherlock']['runs'], 0)
        stderr = io.StringIO()
        with patch('sys.argv', ['ariadne.py', 'telemetry', '--db', str(self.path), '--hours', '0']), \
                redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
            ariadne.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn('Telemetry mislukt', stderr.getvalue())
