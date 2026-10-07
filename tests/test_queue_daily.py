from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import ariadne
import daily
from ingress_queue import IngressQueue
from test_prepare_week_runtime import RuntimeGitFixture

DAY = date(2026, 10, 5)


def payload(**changes):
    item = dict(schema_version=1, topic=2, date=str(DAY), content='# Bron é\n\nExacte bytes\n')
    item.update(changes)
    return item


class QueueDailyTests(RuntimeGitFixture):
    def setUp(self):
        super().setUp()
        self.db = self.root.parent / 'queue.sqlite3'
        self.output = self.root.parent / 'draden'
        self.queue = IngressQueue(self.db)

    def run_daily(self):
        return daily.run_daily(self.root, self.db, self.output,
                               now=datetime(2026, 10, 4, 22, 1, tzinfo=timezone.utc))

    def rows(self, sql):
        with sqlite3.connect(self.db) as db:
            return db.execute(sql).fetchall()

    def assert_pending_error(self):
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('pending',), ('pending',)])
        self.assertEqual(self.rows('SELECT status FROM days'), [('processing_error',)])
        for table in ('sources', 'threads'):
            self.assertEqual(self.rows('SELECT count(*) FROM ' + table), [(0,)])

    def test_snapshot_provenance_dates_and_processed(self):
        first = self.queue.add(payload(topic=3))
        second = self.queue.add(payload(topic=2))
        self.queue.add(payload(date='2026-10-04'))
        self.queue.add(payload(date='2026-10-06'))
        done = self.queue.add(payload())
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE ingress_queue SET status='processed' WHERE id=?", (done,))
        before = self.git('status', '--porcelain'), self.git('rev-parse', 'HEAD')
        real_git = ariadne._git
        def no_transport(root, *args, **kwargs):
            self.assertEqual(args[0], 'rev-parse', 'daily gebruikt Git uitsluitend voor clone_lock')
            return real_git(root, *args, **kwargs)
        with patch.object(ariadne, '_git', side_effect=no_transport):
            result = self.run_daily()
        self.assertEqual(result['threads'], 2)
        self.assertEqual(before, (self.git('status', '--porcelain'), self.git('rev-parse', 'HEAD')))
        self.assertFalse(self.weekroot.exists())
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'),
                         [('processed',), ('processed',), ('pending',), ('pending',), ('processed',)])
        digest = hashlib.sha256(payload()['content'].encode()).hexdigest()
        self.assertEqual(self.rows('SELECT source_path,sha256 FROM sources ORDER BY source_path'),
                         [(f'queue:{first}', digest), (f'queue:{second}', digest)])
        self.assertEqual(self.rows('SELECT commit_sha,manifest_sha256 FROM days'), [(None, None)])
        files = {p: p.read_bytes() for p in self.output.rglob('*.txt')}
        for topic, identity in ((3, first), (2, second)):
            path = self.output / '2026_W41' / f'topic_{topic}' / '2026-10-05_0001.txt'
            self.assertIn(f'SOURCE queue:{identity}'.encode(), files[path])
            self.assertIn(payload()['content'].encode(), files[path])
        late = self.queue.add(payload())
        with patch.object(daily, 'write_thread', side_effect=AssertionError('no-op')):
            self.run_daily()
        self.assertEqual(files, {p: p.read_bytes() for p in self.output.rglob('*.txt')})
        self.assertEqual(self.rows(f'SELECT status FROM ingress_queue WHERE id={late}'), [('pending',)])
        self.assertEqual(self.rows('SELECT count(*) FROM attempts'), [(1,)])

    def test_empty_success_is_also_idempotent(self):
        self.queue.add(payload(date='2026-10-04'))
        self.assertEqual(self.run_daily()['threads'], 0)
        self.queue.add(payload())
        self.run_daily()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('pending',), ('pending',)])

    def test_invalid_payloads_abort_entire_day(self):
        invalid = ['{', '[]', 'null', json.dumps({'date': str(DAY)}),
                   json.dumps(payload(extra=1)), json.dumps(payload(schema_version=2)),
                   json.dumps(payload(schema_version=True)), json.dumps(payload(topic=True)),
                   json.dumps(payload(topic=4)), json.dumps(payload(topic=2.0)),
                   json.dumps(payload(date='2026-02-30')), json.dumps(payload(date=1)),
                   json.dumps(payload(content='')), json.dumps(payload(content='  \n')),
                   json.dumps(payload(content=12)), json.dumps(payload(content=None)),
                   json.dumps(payload()).replace('"schema_version": 1', '"schema_version": NaN'),
                   json.dumps(payload()).replace('"topic": 2', '"topic": Infinity'),
                   '{"date":"2026-10-05","date":"2026-10-04"}']
        for raw in invalid:
            with self.subTest(raw=raw):
                with sqlite3.connect(self.db) as db:
                    db.execute('DELETE FROM ingress_queue')
                self.queue.add(payload())
                with sqlite3.connect(self.db) as db:
                    db.execute('INSERT INTO ingress_queue(received_at,payload) VALUES (?,?)', ('now', raw))
                with self.assertRaises(ValueError):
                    self.run_daily()
                self.assert_pending_error()
                self.assertFalse(self.output.exists())

    def test_weave_failure_preserves_pending(self):
        self.queue.add(payload()); self.queue.add(payload())
        with patch.object(daily, 'weave', side_effect=ValueError('tokenbudget')):
            with self.assertRaises(ValueError): self.run_daily()
        self.assert_pending_error()

    def test_partial_write_failure_and_deterministic_retry(self):
        self.queue.add(payload(topic=2)); self.queue.add(payload(topic=3))
        real_write = daily.write_thread
        written = {}
        def fail_second(path, data):
            if written: raise OSError('disk full')
            real_write(path, data)
            written[path] = data
        with patch.object(daily, 'write_thread', side_effect=fail_second):
            with self.assertRaises(OSError): self.run_daily()
        self.assert_pending_error()
        self.run_daily()
        for path, data in written.items(): self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('processed',), ('processed',)])

    def test_database_failure_rolls_back_queue_and_provenance(self):
        self.queue.add(payload()); self.queue.add(payload(topic=3))
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER refuse BEFORE UPDATE ON ingress_queue WHEN NEW.id=2 "
                       "BEGIN SELECT RAISE(ABORT, 'database failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.run_daily()
        self.assert_pending_error()
        with sqlite3.connect(self.db) as db: db.execute('DROP TRIGGER refuse')
        self.run_daily()
        self.assertEqual(self.rows('SELECT count(*) FROM sources'), [(2,)])

    def test_commit_failure_rolls_back_and_registers_error(self):
        self.queue.add(payload()); self.queue.add(payload(topic=3))
        class FailCommit(sqlite3.Connection):
            fail_commit = False
            def commit(self):
                if self.fail_commit:
                    self.fail_commit = False
                    raise sqlite3.OperationalError('commit failure')
                return super().commit()
        original_database = daily.database
        original_connect = sqlite3.connect
        def failing_database(path):
            with patch('sqlite3.connect', side_effect=lambda target: original_connect(target, factory=FailCommit)):
                db = original_database(path)
            db.fail_commit = True
            return db
        with patch.object(daily, 'database', side_effect=failing_database):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'commit failure'):
                self.run_daily()
        self.assert_pending_error()
        self.run_daily()
        self.assertEqual(self.rows('SELECT count(*) FROM sources'), [(2,)])

    def test_items_are_pending_until_files_and_provenance_can_commit(self):
        self.queue.add(payload()); self.queue.add(payload(topic=3))
        original_write = daily.write_thread
        def inspect_then_write(path, data):
            self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('pending',), ('pending',)])
            self.assertEqual(self.rows('SELECT count(*) FROM sources'), [(0,)])
            self.assertEqual(self.rows('SELECT count(*) FROM days'), [(0,)])
            original_write(path, data)
        with patch.object(daily, 'write_thread', side_effect=inspect_then_write):
            self.run_daily()

    def producer_during(self, operation):
        first = self.queue.add(payload())
        second = self.queue.add(payload(topic=3))
        original = getattr(daily, operation)
        original_connect = sqlite3.connect
        arrivals = []
        def produce_then_continue(*args, **kwargs):
            # Exercise the real producer on a separate connection, with a short
            # busy timeout so a retained consumer lock fails quickly.
            with patch('sqlite3.connect', side_effect=lambda path: original_connect(path, timeout=0.05)):
                arrivals.append(self.queue.add(payload(content='Na de snapshot')))
            return original(*args, **kwargs)
        with patch.object(daily, operation, side_effect=produce_then_continue):
            self.run_daily()
        self.assertTrue(arrivals)
        self.assertEqual(self.rows('SELECT id,status FROM ingress_queue ORDER BY id'),
                         [(first, 'processed'), (second, 'processed')] +
                         [(identity, 'pending') for identity in arrivals])
        self.assertEqual(self.rows('SELECT source_path FROM sources ORDER BY source_path'),
                         [(f'queue:{first}',), (f'queue:{second}',)])
        for path in self.output.rglob('*.txt'):
            self.assertNotIn('Na de snapshot', path.read_text())

    def test_producer_can_add_during_weave_without_entering_snapshot(self):
        self.producer_during('weave')

    def test_producer_can_add_during_thread_write_without_entering_snapshot(self):
        self.producer_during('write_thread')

    def test_changed_snapshot_status_refuses_final_transaction(self):
        first = self.queue.add(payload())
        second = self.queue.add(payload(topic=3))
        original = daily.weave
        def change_status(*args, **kwargs):
            with sqlite3.connect(self.db, timeout=0.05) as db:
                db.execute("UPDATE ingress_queue SET status='processed' WHERE id=?", (first,))
            return original(*args, **kwargs)
        with patch.object(daily, 'weave', side_effect=change_status):
            with self.assertRaisesRegex(ValueError, 'niet pending'):
                self.run_daily()
        self.assertEqual(self.rows('SELECT id,status FROM ingress_queue ORDER BY id'),
                         [(first, 'processed'), (second, 'pending')])
        self.assertEqual(self.rows('SELECT status FROM days'), [('processing_error',)])
        self.assertEqual(self.rows('SELECT count(*) FROM sources'), [(0,)])
        self.assertEqual(self.rows('SELECT count(*) FROM threads'), [(0,)])

    def test_shared_runtime_lock(self):
        with ariadne.clone_lock(self.root):
            with self.assertRaises(ValueError): self.run_daily()


class QueueValidationTests(unittest.TestCase):
    def test_date_mismatch_rejected_by_fiche_validator(self):
        with self.assertRaises(ValueError):
            daily.queue_fiche(2, payload(date='2026-10-04'), DAY)
