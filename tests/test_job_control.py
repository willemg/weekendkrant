"""Control-plane retries survive lost responses and independent connections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
from pathlib import Path
from threading import Barrier
import unittest

from jobs import JobStore
from job_control import JobControl, ControlConflict


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.control = JobControl(self.db, clock=lambda: self.now)
        self.store = JobStore(self.db)
        self.job = self.store.create('test', ['input:v1'], 'contract:v1', 60)

    def claim(self, operation='claim:1', activation='activation:1', job=None):
        return self.control.execute('claim', dict(operation_id=operation,
            activation_id=activation, job_id=self.job if job is None else job))

    def finish(self, claim, operation='finish:1', status='succeeded', **extra):
        return self.control.execute('finish', dict(operation_id=operation,
            **{k: claim[k] for k in ('job_id', 'attempt_id', 'token')},
            status=status, output_refs=['output:v1'], **extra))

    def test_lost_response_replay_after_restart_and_finish(self):
        claim = self.claim()
        self.assertEqual(claim['input_refs'], ['input:v1'])
        result = self.finish(claim)
        with sqlite3.connect(self.path) as db:
            other = JobControl(db)
            self.assertEqual(other.execute('claim', dict(operation_id='claim:1',
                activation_id='activation:1', job_id=self.job)), claim)
            self.assertEqual(other.execute('finish', dict(operation_id='finish:1',
                **{k: claim[k] for k in ('job_id', 'attempt_id', 'token')},
                status='succeeded', output_refs=['output:v1'])), result)
        self.assertEqual(len(self.store.attempts(self.job)), 1)
        with self.assertRaises(ControlConflict):
            self.finish(claim, status='failed')
        with self.assertRaises(ControlConflict):
            self.claim('claim:2')
        audit = self.db.execute('SELECT * FROM job_operations').fetchall()
        self.assertNotIn(claim['token'], repr(audit))

    def test_expiry_validation_and_stale_finish(self):
        claim = self.claim()
        args = {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}
        self.assertEqual(self.control.validate(args)['claim_status'], 'running')
        self.now += timedelta(seconds=60)
        with self.assertRaises(ControlConflict):
            self.finish(claim)
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')
        self.assertEqual(self.control.validate(args)['claim_status'], 'expired')
        self.assertEqual(self.claim(), claim)  # receipt, never execution permission
        with self.assertRaises(ControlConflict):
            self.control.validate(dict(args, token='forged'))

    def test_abandon_and_recovery_retries_never_blindly_reexecute(self):
        claim = self.claim()
        args = dict(operation_id='abandon:1',
            **{k: claim[k] for k in ('job_id', 'attempt_id', 'token')}, error='unknown effects')
        result = self.control.execute('abandon', args)
        self.assertEqual(self.control.execute('abandon', args), result)
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')
        self.assertIsNone(self.claim('other', 'other')['claim'])
        recovery = dict(operation_id='recovery:1', job_id=self.job,
            attempt_id=claim['attempt_id'], decision='retry', evidence_ref='audit:stopped-safe')
        answer = self.control.execute('reconcile', recovery)
        new = self.claim('next', 'next')
        self.assertEqual(self.control.execute('reconcile', recovery), answer)
        with self.assertRaises(ControlConflict):
            self.finish(claim)
        self.assertGreater(new['attempt_id'], claim['attempt_id'])
        self.assertEqual(len(self.store.attempts(self.job)), 2)

    def test_same_operation_id_different_operation_or_job_conflicts(self):
        claim = self.claim()
        with self.assertRaises(ControlConflict):
            self.claim(job=self.store.create('other', [], 'contract'))
        with self.assertRaises(ControlConflict):
            self.finish(claim, operation='claim:1')

    def test_unavailable_claim_receipt_stays_unavailable(self):
        self.claim()
        self.assertEqual(self.claim('busy', 'busy'), {'claim': None})
        self.assertEqual(self.claim('busy', 'busy'), {'claim': None})

    def test_concurrent_duplicate_claim_and_finish(self):
        def run(operation, args):
            barrier = Barrier(2)
            def call(_):
                with sqlite3.connect(self.path, timeout=5) as db:
                    control = JobControl(db)
                    barrier.wait()
                    return control.execute(operation, args)
            with ThreadPoolExecutor(2) as pool:
                return list(pool.map(call, range(2)))
        args = dict(operation_id='claim:1', activation_id='activation:1', job_id=self.job)
        claims = run('claim', args)
        self.assertEqual(claims[0], claims[1])
        claim = claims[0]
        args = dict(operation_id='finish:1', status='succeeded', output_refs=[],
            **{k: claim[k] for k in ('job_id', 'attempt_id', 'token')})
        answers = run('finish', args)
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(len(self.store.attempts(self.job)), 1)

    def test_invalid_payload_and_audit_immutability(self):
        for args in ({}, {'job_id': True, 'operation_id': 'x', 'activation_id': 'a'},
                     {'job_id': 10**100, 'operation_id': 'x', 'activation_id': 'a'},
                     {'job_id': self.job, 'operation_id': 'x', 'activation_id': 'a', 'extra': 1}):
            with self.assertRaises(ValueError):
                self.control.execute('claim', args)
        self.claim()
        for sql in ('DELETE FROM job_operations', "UPDATE job_operations SET operation_id='other'",
                    'INSERT OR REPLACE INTO job_operations SELECT * FROM job_operations'):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
            self.db.rollback()

    def test_receipt_insert_failure_rolls_back_attempt_and_job(self):
        self.db.execute("""CREATE TRIGGER fail_receipt BEFORE INSERT ON job_operations
            BEGIN SELECT RAISE(ABORT,'injected receipt failure'); END""")
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.claim()
        self.assertEqual(self.store.get(self.job)['status'], 'ready')
        self.assertEqual(self.store.attempts(self.job), [])
        self.db.execute('DROP TRIGGER fail_receipt')
        self.db.commit()
        claim = self.claim()
        self.assertEqual(len(self.store.attempts(self.job)), 1)
        self.assertEqual(self.claim(), claim)

    def test_actual_process_crash_before_and_after_control_commit(self):
        import subprocess
        import sys
        for boundary in ('before', 'after'):
            with self.subTest(boundary=boundary):
                job = self.store.create('crash', [], 'contract')
                script = '''
import os, sqlite3, sys
from job_control import JobControl
class CrashDB(sqlite3.Connection):
    def commit(self):
        if self.in_transaction and self.execute("SELECT count(*) FROM job_operations WHERE operation_id=?", (sys.argv[3],)).fetchone()[0]:
            if sys.argv[4] == 'before': os._exit(19)
            super().commit()
            os._exit(19)
        super().commit()
db = sqlite3.connect(sys.argv[1], factory=CrashDB)
JobControl(db).execute('claim', dict(job_id=int(sys.argv[2]), operation_id=sys.argv[3], activation_id=sys.argv[3]))
'''
                result = subprocess.run([sys.executable, '-c', script, str(self.path), str(job),
                                         'crash:' + boundary, boundary], check=False)
                self.assertEqual(result.returncode, 19)
                attempts = self.store.attempts(job)
                self.assertEqual(len(attempts), 0 if boundary == 'before' else 1)
                answer = self.claim('crash:' + boundary, 'crash:' + boundary, job)
                self.assertEqual(len(self.store.attempts(job)), 1)
                if boundary == 'after':
                    self.assertEqual(answer['attempt_id'], attempts[0]['id'])
                    self.assertEqual(answer['token'], attempts[0]['token'])

    def test_activation_cannot_move_to_second_job_after_completion(self):
        claim = self.claim()
        self.finish(claim)
        other = self.store.create('other', [], 'contract')
        with self.assertRaises(ControlConflict):
            self.claim('another-operation', 'activation:1', other)
        self.assertEqual(self.store.attempts(other), [])

    def test_schema_eight_upgrade_and_failure_are_atomic(self):
        from unittest.mock import patch
        import database
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 7):
                old = JobStore(db)
                job = old.create('old', [], 'contract')
                claim = old.claim(job, 'old:activation')
            original = database.migration_sql
            with patch('database.migration_sql', side_effect=lambda v: original(v) + 'CREATE TABLE job_operations(conflict);'):
                with self.assertRaises(sqlite3.Error):
                    database.migrate(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='job_operations'").fetchone())
            with patch.object(database, 'SCHEMA_VERSION', 8):
                JobControl(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 8)
            self.assertEqual(JobStore(db).attempts(job)[0]['token'], claim['token'])
            database.migrate(db)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_lease_is_sampled_after_lock_not_before_wait(self):
        import threading
        claim = self.claim()
        self.db.execute('BEGIN IMMEDIATE')
        entered = threading.Event()
        def finish():
            with sqlite3.connect(self.path, timeout=5) as db:
                control = JobControl(db, clock=lambda: self.now)
                entered.set()
                return self.finish_on(control, claim)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(finish)
            self.assertTrue(entered.wait(2))
            self.now += timedelta(seconds=60)
            self.db.rollback()
            with self.assertRaises(ControlConflict):
                future.result(timeout=5)
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')

    @staticmethod
    def finish_on(control, claim):
        return control.execute('finish', dict(operation_id='finish:1', status='succeeded', output_refs=[],
            **{k: claim[k] for k in ('job_id', 'attempt_id', 'token')}))

    def test_lock_failure_can_retry_same_identity_without_new_attempt(self):
        self.db.execute('BEGIN IMMEDIATE')
        with sqlite3.connect(self.path, timeout=0) as db:
            control = JobControl(db, clock=lambda: self.now)
            with self.assertRaises(sqlite3.OperationalError):
                control.execute('claim', dict(job_id=self.job, operation_id='claim:1', activation_id='activation:1'))
        self.db.rollback()
        self.assertEqual(self.store.attempts(self.job), [])
        claim = self.claim()
        self.assertEqual(self.claim(), claim)
        self.assertEqual(len(self.store.attempts(self.job)), 1)
