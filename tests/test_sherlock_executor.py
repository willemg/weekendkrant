"""Phase-5 production, retries and fenced legacy adapters."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_control import JobControl, ControlConflict
from jobs import JobStore
from sherlock_state import SherlockState
from ingress_queue import IngressQueue, FicheRunConflict
from sherlock_executor import SherlockExecutor


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.executor = SherlockExecutor(self.db)

    def start(self, identity='one', executor=None):
        return (executor or self.executor).start(dict(operation_id='start:'+identity,
                                                     activation_id='scheduled:'+identity))

    @staticmethod
    def authority(answer):
        return {k: answer[k] for k in ('job_id', 'attempt_id', 'token')}

    def finish(self, answer, status='succeeded'):
        return JobControl(self.db).execute('finish', dict(self.authority(answer),
            operation_id='finish:'+str(answer['attempt_id']), status=status,
            output_refs=[answer['result_ref']]))

    # Isolate protocol/rotation from the development cadence (tested separately).
    @patch('sherlock_executor.SHERLOCK_NEW_JOB_COOLDOWN', timedelta(0))
    def test_restart_replay_rotation_and_one_job_per_activation(self):
        first = self.start()
        self.assertEqual((first['role'], first['input']['topic']), ('Sherlock', 1))
        self.assertIn('20', first['role_contract'])
        self.finish(first)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(self.start(executor=SherlockExecutor(db)), first)
        with self.assertRaises(ControlConflict):
            self.executor.start(dict(operation_id='different', activation_id='scheduled:one'))
        second = self.start('two')
        self.assertEqual(second['input']['topic'], 2)
        self.finish(second)
        third = self.start('three')
        self.assertEqual(third['input']['topic'], 3)
        self.finish(third)
        self.assertEqual(self.start('four')['input']['topic'], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 4)
        self.assertNotIn(first['token'], repr(self.db.execute('SELECT * FROM executor_activations').fetchall()))

    def test_busy_receipt_stays_empty_and_legacy_writes_cannot_bypass_claim(self):
        answer = self.start()
        self.assertEqual(self.start('busy'), {'claim': None})
        state = SherlockState(self.db)
        args = (answer['run_id'], answer['input']['topic'], 'https://example.org/page', 'reviewed', 'reason')
        with self.assertRaises(ValueError):
            state.record_reviewed_source(*args)
        state.record_reviewed_source(*args, claim=self.authority(answer))
        with self.assertRaises(ValueError):
            state.finish_run(answer['run_id'], 'completed')
        with self.assertRaises(ValueError):
            state.start_next_run()
        self.finish(answer)
        self.assertEqual(self.start('busy'), {'claim': None})
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs').fetchone()[0], 'completed')

    def test_fiche_provenance_and_expired_claim_are_enforced_at_write(self):
        answer = self.start()
        queue = IngressQueue(self.path)
        fiche = dict(schema_version=1, topic=answer['input']['topic'], date=answer['input']['date'], content='A real source')
        with self.assertRaises(FicheRunConflict):
            queue.add(fiche)  # Omitting all transport metadata cannot bypass fencing.
        with self.assertRaises(FicheRunConflict):
            queue.add(fiche, run_id=answer['run_id'])
        item = queue.add(fiche, run_id=answer['run_id'], claim=self.authority(answer))
        self.assertEqual(self.db.execute('''SELECT f.queue_item_id,r.job_id,r.attempt_id
            FROM sherlock_fiches f JOIN sherlock_job_runs r USING(run_id)''').fetchone(),
            (item, answer['job_id'], answer['attempt_id']))
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        JobStore(self.db, clock=lambda: future).recover_expired()
        with self.assertRaises(FicheRunConflict):
            queue.add(fiche, run_id=answer['run_id'], claim=self.authority(answer))
        with self.assertRaises(ValueError):
            SherlockState(self.db).record_reviewed_source(answer['run_id'], fiche['topic'],
                'https://example.org/late', 'reviewed', 'late', claim=self.authority(answer))
        self.assertEqual(self.start('blocked'), {'claim': None})
        self.assertEqual(queue.pending_count(), 1)

    # Isolate protocol/rotation from the development cadence (tested separately).
    @patch('sherlock_executor.SHERLOCK_NEW_JOB_COOLDOWN', timedelta(0))
    def test_uncertain_recovery_reuses_job_topic_with_new_attempt_and_run(self):
        answer = self.start()
        JobControl(self.db).execute('abandon', dict(self.authority(answer), operation_id='abandon', error='unknown'))
        self.assertEqual(self.start('blocked'), {'claim': None})
        JobControl(self.db).execute('reconcile', dict(operation_id='recovery', job_id=answer['job_id'],
            attempt_id=answer['attempt_id'], decision='retry', evidence_ref='audit:stopped-and-safe'))
        old_attempt = self.db.execute('SELECT * FROM job_attempts WHERE id=?', (answer['attempt_id'],)).fetchone()
        old_run = self.db.execute('SELECT * FROM sherlock_runs WHERE id=?', (answer['run_id'],)).fetchone()
        self.assertEqual(self.db.execute('SELECT status FROM jobs').fetchone()[0], 'ready')
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs').fetchone()[0], 'failed')
        retry = self.start('retry')
        self.assertEqual(self.db.execute('SELECT * FROM job_attempts WHERE id=?', (answer['attempt_id'],)).fetchone(), old_attempt)
        self.assertEqual(self.db.execute('SELECT * FROM sherlock_runs WHERE id=?', (answer['run_id'],)).fetchone(), old_run)
        self.assertEqual(retry['job_id'], answer['job_id'])
        self.assertEqual(retry['input'], answer['input'])
        self.assertNotEqual(retry['run_id'], answer['run_id'])
        self.assertNotEqual(retry['attempt_id'], answer['attempt_id'])
        with self.assertRaises(ValueError):
            SherlockState(self.db).record_reviewed_source(answer['run_id'], 1,
                'https://example.org/stale', 'reviewed', 'old', claim=self.authority(answer))
        self.finish(retry)
        self.assertEqual(self.start('next')['input']['topic'], 2)

    def recovery_snapshot(self):
        return {table: self.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                for table in ('jobs', 'job_attempts', 'sherlock_runs',
                              'job_recoveries', 'job_operations')}

    def quarantine(self, answer, mode):
        control = JobControl(self.db)
        if mode == 'expiry':
            JobStore(self.db, clock=lambda: datetime.now(timezone.utc) + timedelta(hours=2)).recover_expired()
        elif mode == 'abandon':
            control.execute('abandon', dict(self.authority(answer), operation_id='abandon', error='unknown'))
        else:
            self.finish(answer, 'uncertain')
        return dict(operation_id='recovery', job_id=answer['job_id'],
                    attempt_id=answer['attempt_id'], evidence_ref='audit:investigated')

    # Isolate protocol/rotation from the development cadence (tested separately).
    @patch('sherlock_executor.SHERLOCK_NEW_JOB_COOLDOWN', timedelta(0))
    def test_successful_recovery_preserves_attempt_and_replays_without_mutation(self):
        for mode in ('uncertain', 'abandon', 'expiry'):
            with self.subTest(mode=mode):
                answer = self.start(mode)
                args = dict(self.quarantine(answer, mode), operation_id='recovery:'+mode,
                            decision='succeeded', output_refs=[answer['result_ref']])
                before = self.db.execute('SELECT * FROM job_attempts WHERE id=?', (answer['attempt_id'],)).fetchone()
                control = JobControl(self.db)
                result = control.execute('reconcile', args)
                self.assertEqual(result['job_status'], 'succeeded')
                self.assertEqual(self.db.execute('SELECT status,output_refs FROM jobs WHERE id=?', (answer['job_id'],)).fetchone(),
                                 ('succeeded', '["'+answer['result_ref']+'"]'))
                self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs WHERE id=?', (answer['run_id'],)).fetchone()[0], 'completed')
                self.assertEqual(self.db.execute('SELECT * FROM job_attempts WHERE id=?', (answer['attempt_id'],)).fetchone(), before)
                self.assertEqual(self.db.execute('SELECT output_refs FROM job_recoveries WHERE attempt_id=?', (answer['attempt_id'],)).fetchone()[0], '["'+answer['result_ref']+'"]')
                snapshot = self.recovery_snapshot()
                self.assertEqual(control.execute('reconcile', args), result)
                self.assertEqual(self.recovery_snapshot(), snapshot)

    # Isolate protocol/rotation from the development cadence (tested separately).
    @patch('sherlock_executor.SHERLOCK_NEW_JOB_COOLDOWN', timedelta(0))
    def test_successful_recovery_preserves_original_run_finished_at(self):
        for mode in ('uncertain', 'abandon'):
            with self.subTest(mode=mode):
                answer = self.start(mode)
                args = dict(self.quarantine(answer, mode), operation_id='recovery:'+mode,
                            decision='succeeded', output_refs=[answer['result_ref']])
                original = self.db.execute('SELECT finished_at FROM sherlock_runs WHERE id=?',
                                           (answer['run_id'],)).fetchone()[0]
                self.assertIsNotNone(original)
                later = datetime.now(timezone.utc) + timedelta(hours=2)
                JobControl(self.db, clock=lambda: later).execute('reconcile', args)
                self.assertEqual(self.db.execute('SELECT status,finished_at FROM sherlock_runs WHERE id=?',
                                                 (answer['run_id'],)).fetchone(),
                                 ('completed', original))

    def test_successful_recovery_rejects_missing_empty_and_wrong_results(self):
        answer = self.start()
        args = dict(self.quarantine(answer, 'abandon'), decision='succeeded')
        snapshot = self.recovery_snapshot()
        for refs in (None, [], ['sherlock-run:999999'], ['artifact:other'],
                     [answer['result_ref'], 'artifact:extra']):
            with self.subTest(refs=refs):
                request = dict(args)
                if refs is not None:
                    request['output_refs'] = refs
                with self.assertRaises(ControlConflict):
                    JobControl(self.db).execute('reconcile', request)
                self.assertEqual(self.recovery_snapshot(), snapshot)

    def test_failed_recovery_closes_run_and_preserves_attempt(self):
        answer = self.start()
        args = dict(self.quarantine(answer, 'expiry'), decision='failed')
        before = self.db.execute('SELECT * FROM job_attempts').fetchall()
        JobControl(self.db).execute('reconcile', args)
        self.assertEqual(self.db.execute('SELECT status FROM jobs').fetchone()[0], 'failed')
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs').fetchone()[0], 'failed')
        self.assertEqual(self.db.execute('SELECT * FROM job_attempts').fetchall(), before)

    def test_recovery_failure_rolls_back_job_recovery_run_and_receipt(self):
        answer = self.start()
        args = dict(self.quarantine(answer, 'abandon'), decision='succeeded', output_refs=[answer['result_ref']])
        for boundary in ('run', 'receipt'):
            with self.subTest(boundary=boundary):
                target = 'UPDATE ON sherlock_runs' if boundary == 'run' else 'INSERT ON job_operations'
                self.db.execute("CREATE TRIGGER fail_recovery BEFORE "+target+
                                " BEGIN SELECT RAISE(ABORT,'injected'); END")
                self.db.commit()
                snapshot = self.recovery_snapshot()
                with self.assertRaises(sqlite3.IntegrityError):
                    JobControl(self.db).execute('reconcile', args)
                self.assertEqual(self.recovery_snapshot(), snapshot)
                self.db.execute('DROP TRIGGER fail_recovery')
                self.db.commit()
        JobControl(self.db).execute('reconcile', args)

    # Isolate protocol/rotation from the development cadence (tested separately).
    @patch('sherlock_executor.SHERLOCK_NEW_JOB_COOLDOWN', timedelta(0))
    def test_concurrent_same_and_distinct_activations(self):
        def start(identity):
            with sqlite3.connect(self.path, timeout=5) as db:
                return self.start(identity, SherlockExecutor(db))
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(start, ['one'] * 4))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
        self.finish(results[0])
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(start, ['a','b','c','d']))
        self.assertEqual(sum('job_id' in r for r in results), 1)

    def test_receipt_failure_rolls_back_production_run_and_claim(self):
        self.db.execute("""CREATE TRIGGER fail_start BEFORE INSERT ON executor_activations
            BEGIN SELECT RAISE(ABORT,'injected'); END""")
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.start()
        for table in ('jobs','job_attempts','sherlock_runs','sherlock_assignments'):
            self.assertEqual(self.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        self.db.execute('DROP TRIGGER fail_start')
        self.db.commit()
        self.assertEqual(self.start()['input']['topic'], 1)

    def test_real_crash_before_and_after_atomic_start_commit(self):
        import subprocess
        import sys
        for boundary in ('before', 'after'):
            path = Path(self.tmp.name) / boundary
            with sqlite3.connect(path) as db:
                SherlockExecutor(db)
            script = '''
import os, sqlite3, sys
from sherlock_executor import SherlockExecutor
class CrashDB(sqlite3.Connection):
    def commit(self):
        if self.in_transaction and self.execute('SELECT count(*) FROM executor_activations').fetchone()[0]:
            if sys.argv[2] == 'before': os._exit(19)
            super().commit()
            os._exit(19)
        super().commit()
db=sqlite3.connect(sys.argv[1], factory=CrashDB)
SherlockExecutor(db).start(dict(operation_id='start:one',activation_id='scheduled:one'))
'''
            result = subprocess.run([sys.executable, '-c', script, str(path), boundary], timeout=5)
            self.assertEqual(result.returncode, 19)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], int(boundary == 'after'))
                answer = self.start(executor=SherlockExecutor(db))
                self.assertEqual(self.start(executor=SherlockExecutor(db)), answer)
                for table in ('jobs', 'job_attempts', 'sherlock_runs', 'sherlock_assignments', 'executor_activations'):
                    self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0], 1)

    def test_schema_nine_upgrade_rollback_and_immutable_snapshots(self):
        import database
        import hashlib
        from unittest.mock import patch
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 8):
                old = JobStore(db)
                legacy = db.execute("INSERT INTO sherlock_runs(topic,started_at) VALUES (2,'2026-10-14T00:00:00+00:00')").lastrowid
                db.commit()
            before = list(db.iterdump())
            original = database.migration_sql
            with patch('database.migration_sql', side_effect=lambda v: original(v)+'CREATE TABLE sherlock_contracts(conflict);'):
                with self.assertRaises(sqlite3.Error):
                    database.migrate(db)
            self.assertEqual(list(db.iterdump()), before)
            executor = SherlockExecutor(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 10)
            # A running legacy producer must be stopped explicitly, not silently adopted.
            self.assertEqual(self.start(executor=executor), {'claim': None})
            SherlockState(db).finish_run(legacy, 'completed')
            answer = self.start('next', executor)
            self.assertEqual(answer['input']['topic'], 3)
            for ref in answer['input_refs']+[answer['output_contract_ref']]:
                content = db.execute('SELECT content FROM sherlock_contracts WHERE ref=?', (ref,)).fetchone()[0]
                self.assertEqual(ref, 'sha256:'+hashlib.sha256(content.encode()).hexdigest())
            for table in ('sherlock_contracts','sherlock_assignments','sherlock_job_runs','executor_activations'):
                for sql in ('DELETE FROM '+table, 'UPDATE '+table+' SET rowid=rowid', 'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute(sql)
                    db.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('''INSERT OR REPLACE INTO executor_activations
                    SELECT 'new-operation',activation_id,job_id,attempt_id,response,confirmed_at
                    FROM executor_activations WHERE attempt_id IS NOT NULL''')
            db.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('''INSERT OR REPLACE INTO sherlock_job_runs
                    SELECT run_id+100,job_id,attempt_id FROM sherlock_job_runs''')
            db.rollback()
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_finish_requires_bound_result_and_operation_namespaces_cannot_collide(self):
        answer = self.start()
        claim = self.authority(answer)
        control = JobControl(self.db)
        with self.assertRaises(ControlConflict):
            control.execute('finish', dict(claim, operation_id='wrong', status='succeeded', output_refs=['nonexistent']))
        with self.assertRaises(ControlConflict):
            control.execute('finish', dict(claim, operation_id='start:one', status='succeeded', output_refs=[answer['result_ref']]))
        with self.assertRaises(ControlConflict):
            control.execute('claim', dict(job_id=answer['job_id'], activation_id='another', operation_id='direct-claim'))
        self.finish(answer)
        with self.assertRaises(ControlConflict):
            self.executor.start(dict(activation_id='different', operation_id='finish:'+str(answer['attempt_id'])))
        other = JobStore(self.db).create('other', [], 'contract')
        with self.assertRaises(ControlConflict):
            control.execute('claim', dict(job_id=other, activation_id='scheduled:one', operation_id='other-claim'))
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs').fetchone()[0], 'completed')

    def test_recovered_old_run_rejects_all_late_effects_and_cannot_take_second_job(self):
        answer = self.start()
        now = datetime.now(timezone.utc) + timedelta(hours=2)
        JobStore(self.db, clock=lambda: now).recover_expired()
        JobControl(self.db).execute('reconcile', dict(operation_id='recover', job_id=answer['job_id'],
            attempt_id=answer['attempt_id'], decision='retry', evidence_ref='audit:stopped-safe'))
        retry = self.start('retry')
        with self.assertRaises(ControlConflict):
            self.finish(answer)
        with self.assertRaises(ValueError):
            SherlockState(self.db).record_reviewed_source(retry['run_id'], retry['input']['topic'],
                'https://example.org/forged', 'reviewed', 'forged', claim=self.authority(answer))
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs WHERE id=?', (answer['run_id'],)).fetchone()[0], 'failed')
        self.finish(retry)
        self.assertEqual(self.start(), answer)
        self.assertFalse(JobControl(self.db).validate(self.authority(answer))['valid'])

    def test_replay_uses_snapshot_even_without_deployment_contract_files(self):
        from unittest.mock import patch
        answer = self.start()
        with patch('pathlib.Path.read_text', side_effect=OSError('deployment file missing')):
            self.assertEqual(self.start(), answer)

    def test_source_waiting_for_write_lock_rechecks_expiry(self):
        from threading import Event
        from unittest.mock import patch
        answer = self.start()
        entered = Event()
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        def write():
            with sqlite3.connect(self.path, timeout=5) as db:
                state = SherlockState(db)
                entered.set()
                return state.record_reviewed_source(answer['run_id'], 1,
                    'https://example.org/waiting', 'reviewed', 'waited', claim=self.authority(answer))
        self.db.execute('BEGIN IMMEDIATE')
        with patch('sherlock_executor.datetime') as clock:
            clock.now.return_value = future
            with ThreadPoolExecutor(1) as pool:
                result = pool.submit(write)
                self.assertTrue(entered.wait(2))
                self.db.rollback()
                with self.assertRaises(ValueError):
                    result.result(timeout=5)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sherlock_sources').fetchone()[0], 0)
        self.assertFalse(JobControl(self.db, clock=lambda: future).validate(self.authority(answer))['valid'])
