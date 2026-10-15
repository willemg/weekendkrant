"""Temporary deterministic development throttle, backend clock only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from job_control import JobControl
from sherlock_executor import SherlockExecutor


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.executor = SherlockExecutor(self.db, clock=lambda: self.now)

    def start(self, slot):
        return self.executor.start(dict(activation_id=slot, operation_id='start:'+slot))

    def finish(self, answer):
        claim = {k: answer[k] for k in ('job_id', 'attempt_id', 'token')}
        JobControl(self.db, clock=lambda: self.now).execute('finish', dict(claim,
            operation_id='finish:'+str(answer['attempt_id']), status='succeeded',
            output_refs=[answer['result_ref']]))

    def counts(self):
        return [self.db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                for t in ('jobs','job_attempts','sherlock_runs','sherlock_assignments')]

    def test_boundary_receipts_no_rotation_and_no_writes(self):
        first = self.start('0')
        self.finish(first)
        before = self.counts()
        self.now += timedelta(hours=29, minutes=59, seconds=59, microseconds=999999)
        self.assertEqual(self.start('29'), {'claim': None})
        self.assertEqual(self.start('another'), {'claim': None})
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sherlock_activations').fetchone()[0], 3)
        self.now += timedelta(microseconds=1)
        self.assertEqual(self.start('29'), {'claim': None})
        self.assertEqual(self.db.execute('SELECT count(*) FROM sherlock_activations').fetchone()[0], 3)
        second = self.start('30')
        self.assertEqual(second['input']['topic'], 2)
        self.assertEqual(self.counts(), [2, 2, 2, 2])

    def test_recent_legacy_and_timestamp_order_not_row_order(self):
        for stamp, topic in ((self.now, 2), (self.now-timedelta(days=3), 1)):
            self.db.execute("INSERT INTO sherlock_runs(topic,started_at,status,finished_at) VALUES (?,?,'failed',?)",
                            (topic, stamp.isoformat(), stamp.isoformat()))
        self.db.commit()
        self.assertEqual(self.start('recent'), {'claim': None})
        self.assertEqual(self.counts(), [0, 0, 2, 0])
        self.now += timedelta(hours=30)
        self.assertIn('job_id', self.start('allowed'))

    def test_recovery_bypasses_production_throttle_and_resets_clock(self):
        first = self.start('0')
        claim = {k: first[k] for k in ('job_id','attempt_id','token')}
        control = JobControl(self.db, clock=lambda: self.now)
        control.execute('abandon', dict(claim, operation_id='abandon', error='unknown'))
        self.assertEqual(self.start('blocked'), {'claim': None})
        control.execute('reconcile', dict(job_id=first['job_id'], attempt_id=first['attempt_id'],
            operation_id='recover', decision='retry', evidence_ref='audit:stopped-safe'))
        self.now += timedelta(hours=2)
        retry = self.start('retry')
        self.assertEqual(retry['job_id'], first['job_id'])
        self.assertNotEqual(retry['run_id'], first['run_id'])
        self.finish(retry)
        self.now += timedelta(hours=28)
        self.assertEqual(self.start('old-boundary'), {'claim': None})
        self.now += timedelta(hours=2)
        self.assertEqual(self.start('new-boundary')['input']['topic'], 2)

    def test_concurrent_different_activations_cannot_bypass_throttle(self):
        first = self.start('first')
        self.finish(first)
        def start(slot):
            with sqlite3.connect(self.path, timeout=5) as db:
                return SherlockExecutor(db, clock=lambda: self.now).start(
                    dict(activation_id=str(slot), operation_id='start:'+str(slot)))
        with ThreadPoolExecutor(4) as pool:
            self.assertEqual(list(pool.map(start, range(4))), [{'claim': None}]*4)
        self.assertEqual(self.counts(), [1, 1, 1, 1])
