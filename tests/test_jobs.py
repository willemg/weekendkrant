"""Job lifecycle contracts on independent durable SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import database
from jobs import JobStore


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'jobs.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.store = JobStore(self.db, clock=lambda: self.now)
        self.job = self.store.create('sherlock', ['revision:1:2'], 'contract:v1', lease_seconds=60)

    def claim(self, activation='activation:1'):
        return self.store.claim(self.job, activation)

    def expire(self):
        self.now += timedelta(seconds=60)
        self.assertEqual(self.store.recover_expired(), 1)

    def test_identity_attempt_and_exact_retries(self):
        claim = self.claim()
        self.assertEqual(self.claim(), claim)
        self.assertIsNone(self.claim('activation:2'))
        self.store.finish(claim, 'succeeded', ['artifact:result'])
        self.store.finish(claim, 'succeeded', ['artifact:result'])
        with self.assertRaises(ValueError):
            self.store.finish(claim, 'succeeded', ['artifact:other'])
        self.assertEqual(self.store.get(self.job)['status'], 'succeeded')
        self.assertEqual(self.store.get(self.job)['input_refs'], ['revision:1:2'])
        self.assertEqual(self.store.attempts(self.job)[0]['output_refs'], ['artifact:result'])
        other = self.store.create('sherlock', [], 'contract:v1')
        with self.assertRaises(ValueError):
            self.store.claim(other, 'activation:1')

    def test_expiry_blocks_retry_and_fences_late_result(self):
        old = self.claim()
        self.expire()
        self.assertEqual(self.store.recover_expired(), 0)
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')
        self.assertIsNone(self.claim('activation:2'))
        with self.assertRaises(ValueError):
            self.store.finish(old, 'succeeded', ['late'])
        self.store.reconcile(self.job, old['attempt_id'], 'retry', 'audit:stopped-no-effects')
        new = self.claim('activation:2')
        self.assertGreater(new['attempt_id'], old['attempt_id'])
        self.assertNotEqual(new['token'], old['token'])
        with self.assertRaises(ValueError):
            self.store.finish(old, 'succeeded', [])
        self.store.finish(new, 'succeeded', [])
        self.assertEqual([a['status'] for a in self.store.attempts(self.job)], ['expired', 'succeeded'])

    def test_expired_without_sweeper_cannot_finish_or_claim(self):
        claim = self.claim()
        self.now += timedelta(seconds=60)
        with self.assertRaises(ValueError):
            self.store.finish(claim, 'succeeded', [])
        self.assertIsNone(self.claim('activation:2'))
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')

    def test_uncertain_effects_require_reconciliation(self):
        claim = self.claim()
        self.store.finish(claim, 'uncertain', [], 'publication acknowledgement lost')
        self.assertIsNone(self.claim('activation:2'))
        self.store.reconcile(self.job, claim['attempt_id'], 'succeeded', 'audit:found-output', ['queue:7'])
        self.assertEqual(self.store.get(self.job)['output_refs'], ['queue:7'])
        self.assertEqual(self.store.attempts(self.job)[0]['status'], 'uncertain')
        self.assertEqual(self.store.get(self.job)['recovery_ref'], 'audit:found-output')
        with self.assertRaises(ValueError):
            self.store.reconcile(self.job, claim['attempt_id'], 'retry', 'audit:other')

    def test_restart_preserves_claim_and_recovery(self):
        old = self.claim()
        with sqlite3.connect(self.path) as db:
            restarted = JobStore(db, clock=lambda: self.now)
            self.assertEqual(restarted.claim(self.job, 'activation:1'), old)
            self.now += timedelta(seconds=61)
            self.assertEqual(restarted.recover_expired(), 1)
            restarted.reconcile(self.job, old['attempt_id'], 'failed', 'audit:stopped')
        self.assertEqual(self.store.get(self.job)['status'], 'failed')

    def test_token_and_attempt_are_both_required(self):
        claim = self.claim()
        for key, value in [('token', 'forged'), ('attempt_id', 999), ('job_id', 999)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.finish(dict(claim, **{key: value}), 'succeeded', [])
        self.assertEqual(self.store.get(self.job)['status'], 'running')

    def test_concurrent_claims_one_winner(self):
        ready = Barrier(8)
        def run(i):
            with sqlite3.connect(self.path) as db:
                store = JobStore(db, clock=lambda: self.now)
                ready.wait(timeout=5)
                return store.claim(self.job, 'activation:'+str(i))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, range(8)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.store.attempts(self.job)), 1)

    def test_finish_recovery_race_is_serialized(self):
        claim = self.claim()
        ready = Barrier(2)
        def run(recover):
            with sqlite3.connect(self.path) as db:
                store = JobStore(db, clock=lambda: self.now + timedelta(seconds=60 if recover else 59))
                ready.wait(timeout=5)
                try:
                    return store.recover_expired() if recover else store.finish(claim, 'succeeded', ['result'])
                except ValueError:
                    return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, [True, False]))
        self.assertIn(self.store.get(self.job)['status'], ('blocked', 'succeeded'))
        a = self.store.attempts(self.job)[0]
        self.assertEqual(a['status'], 'expired' if self.store.get(self.job)['status'] == 'blocked' else 'succeeded')

    def test_validation_and_caller_transaction(self):
        for kwargs in [dict(lease_seconds=0), dict(lease_seconds=True), dict(lease_seconds=86401)]:
            with self.assertRaises(ValueError):
                self.store.create('sherlock', [], 'v1', **kwargs)
        for refs in [[''] , ['x']*33, ['x'*513], 'not-a-list']:
            with self.assertRaises(ValueError):
                self.store.create('sherlock', refs, 'v1')
        self.db.execute('UPDATE jobs SET role=role')
        with self.assertRaises(ValueError):
            self.claim()
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()

    def test_claim_failure_rolls_back_both_records(self):
        self.db.execute("CREATE TRIGGER reject_attempt BEFORE INSERT ON job_attempts BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.claim()
        self.assertEqual(self.store.get(self.job)['status'], 'ready')
        self.assertEqual(self.store.attempts(self.job), [])
        self.assertFalse(self.db.in_transaction)

    def test_v6_upgrade_preserves_data_and_schema(self):
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 6):
                database.migrate(db)
            db.execute("INSERT INTO attempts(day,status) VALUES ('2026-10-14','success')")
            db.commit()
            before = {r[0]: r[1] for r in db.execute('SELECT name,sql FROM sqlite_master')}
            data = db.execute('SELECT * FROM attempts').fetchall()
            database.migrate(db)
            after = dict(db.execute('SELECT name,sql FROM sqlite_master'))
            self.assertTrue(all(after[k] == v for k,v in before.items()))
            self.assertEqual(db.execute('SELECT * FROM attempts').fetchall(), data)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            snapshot = list(db.iterdump())
            database.migrate(db)
            self.assertEqual(list(db.iterdump()), snapshot)

    def test_process_crash_before_and_after_claim_commit(self):
        # Real abrupt exits: an uncommitted write is rolled back by SQLite;
        # a committed claim survives even without a finish or clean close.
        uncommitted = """
import os, sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute('BEGIN IMMEDIATE')
con.execute("UPDATE jobs SET status='running' WHERE id=1")
os._exit(9)
"""
        result = subprocess.run([sys.executable, '-c', uncommitted, str(self.path)], timeout=10)
        self.assertEqual(result.returncode, 9)
        self.assertEqual(self.store.get(self.job)['status'], 'ready')
        committed = """
import os, sqlite3, sys
from datetime import datetime, timezone
from jobs import JobStore
store = JobStore(sqlite3.connect(sys.argv[1]), clock=lambda: datetime(2026,10,14,tzinfo=timezone.utc))
store.claim(1, 'crashed-activation')
os._exit(9)
"""
        result = subprocess.run([sys.executable, '-c', committed, str(self.path)], timeout=10)
        self.assertEqual(result.returncode, 9)
        self.assertEqual(self.store.get(self.job)['status'], 'running')
        self.assertIsNone(self.claim('another-activation'))
        self.expire()
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')

    def test_same_activation_cannot_claim_two_jobs_concurrently(self):
        other = self.store.create('sherlock', [], 'contract:v1')
        ready = Barrier(2)
        def run(identity):
            with sqlite3.connect(self.path) as db:
                store = JobStore(db, clock=lambda: self.now)
                ready.wait(timeout=5)
                try:
                    return store.claim(identity, 'one-activation')
                except ValueError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, [self.job, other]))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_finish_failure_rolls_back_attempt_and_job(self):
        claim = self.claim()
        self.db.execute("CREATE TRIGGER reject_finish BEFORE UPDATE ON jobs WHEN NEW.status='succeeded' BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.finish(claim, 'succeeded', ['result'])
        self.assertEqual(self.store.attempts(self.job)[0]['status'], 'running')
        self.assertEqual(self.store.get(self.job)['status'], 'running')
        self.db.execute('DROP TRIGGER reject_finish')
        self.store.finish(claim, 'succeeded', ['result'])

    def test_recovery_failure_rolls_back_decision_and_state(self):
        claim = self.claim()
        self.expire()
        self.db.execute("CREATE TRIGGER reject_recovery BEFORE UPDATE ON jobs WHEN NEW.status='ready' BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.reconcile(self.job, claim['attempt_id'], 'retry', 'audit:checked')
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')
        self.assertEqual(self.db.execute('SELECT count(*) FROM job_recoveries').fetchone()[0], 0)

    def test_seventh_migration_failure_is_atomic(self):
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 6):
                database.migrate(db)
            before = list(db.iterdump())
            original = database.migration_sql
            with patch('database.migration_sql', side_effect=lambda v: original(v) + 'CREATE TABLE jobs(conflict);'):
                with self.assertRaises(sqlite3.OperationalError):
                    database.migrate(db)
            self.assertEqual(list(db.iterdump()), before)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)

    def test_closed_audit_and_identity_cannot_be_overwritten(self):
        claim = self.claim()
        self.store.finish(claim, 'failed', [], 'known failure')
        for sql in ["UPDATE jobs SET role='other'", "DELETE FROM jobs",
                    "UPDATE job_attempts SET status='running',finished_at=NULL", "DELETE FROM job_attempts"]:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
            self.db.rollback()
        self.assertEqual(self.store.get(self.job)['status'], 'failed')

    def test_audit_replacement_rejected(self):
        claim = self.claim()
        self.expire()
        self.store.reconcile(self.job, claim['attempt_id'], 'failed', 'audit:checked')
        for table in ('jobs', 'job_attempts', 'job_recoveries'):
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute('INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table)
            self.db.rollback()
        self.assertEqual(self.store.get(self.job)['status'], 'failed')

    def test_reconciliation_requires_evidence_and_current_attempt(self):
        claim = self.claim()
        with self.assertRaises(ValueError):
            self.store.reconcile(self.job, claim['attempt_id'], 'retry', 'audit:still-running')
        self.expire()
        for evidence in ('', ' ', 'x'*513):
            with self.assertRaises(ValueError):
                self.store.reconcile(self.job, claim['attempt_id'], 'retry', evidence)
        with self.assertRaises(ValueError):
            self.store.reconcile(self.job, claim['attempt_id'], 'retry', 'audit:checked', ['unhandled-output'])
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')

    def test_expired_claim_retry_commits_quarantine(self):
        self.claim()
        self.now += timedelta(seconds=60)
        with self.assertRaises(ValueError):
            self.claim()
        self.assertEqual(self.store.get(self.job)['status'], 'blocked')
        self.assertEqual(self.store.attempts(self.job)[0]['status'], 'expired')

    def test_default_lease_accepts_long_healthy_job_until_one_hour(self):
        identity = self.store.create('sherlock', [], 'contract:v1')
        self.assertEqual(self.store.get(identity)['lease_seconds'], 3600)
        claim = self.store.claim(identity, 'long-healthy-activation')
        self.assertEqual(claim['lease_until'], (self.now + timedelta(seconds=3600)).isoformat(timespec='microseconds'))
        self.now += timedelta(seconds=3599)
        self.store.finish(claim, 'succeeded', ['artifact:long-result'])
        self.assertEqual(self.store.get(identity)['status'], 'succeeded')

    def test_default_lease_expires_at_one_hour_and_upper_bound_remains_configurable(self):
        identity = self.store.create('sherlock', [], 'contract:v1')
        claim = self.store.claim(identity, 'one-hour-activation')
        maximum = self.store.create('sherlock', [], 'contract:v1', lease_seconds=86400)
        max_claim = self.store.claim(maximum, 'maximum-lease-activation')
        self.assertEqual(max_claim['lease_until'], (self.now + timedelta(seconds=86400)).isoformat(timespec='microseconds'))
        self.now += timedelta(seconds=3600)
        with self.assertRaises(ValueError):
            self.store.finish(claim, 'succeeded', [])
        self.assertEqual(self.store.get(identity)['status'], 'blocked')
        self.assertEqual(self.store.get(maximum)['status'], 'running')
