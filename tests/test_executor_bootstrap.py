"""Server-owned scheduled protocol over existing immutable activation state."""
from datetime import timedelta
import unittest
from unittest.mock import patch

from test_dispatcher import DispatcherTests, TestRole
from dispatcher import Dispatcher
from job_control import ControlConflict


class BootstrapTests(unittest.TestCase):
    setUp = DispatcherTests.setUp
    job = DispatcherTests.job

    def test_bootstrap_replay_and_snapshot(self):
        self.job()
        result = self.dispatcher.bootstrap({})
        self.assertEqual(set(result), {'executor_id'})
        identity = result['executor_id']
        self.assertIsInstance(identity, str)
        with patch.object(TestRole, 'prepare', side_effect=AssertionError('no preparation')):
            self.assertEqual(self.dispatcher.bootstrap({}), result)
            package = self.dispatcher.get_job({'executor_id': identity})
            self.assertEqual(self.dispatcher.get_job({'executor_id': identity}), package)
        self.assertEqual(package['executor_id'], identity)
        self.assertEqual(package['role_contract'], 'Test role')
        self.assertEqual(package['output_contract'], 'Test output')
        claim = package['claim']
        self.assertEqual(set(claim), {'job_id','attempt_id','token','lease_until'})
        self.assertTrue(self.dispatcher.control.validate({k:claim[k] for k in ('job_id','attempt_id','token')})['valid'])
        receipt = self.db.execute('SELECT response FROM executor_activations').fetchone()[0]
        self.assertNotIn(claim['token'], receipt)
        self.assertEqual(self.db.execute('SELECT count(*) FROM job_attempts').fetchone()[0], 1)

    def test_real_role_snapshot_and_scheduled_run_finish(self):
        dispatch = Dispatcher(self.db, lambda:self.now)
        bootstrap = dispatch.bootstrap({})
        original = dispatch.get_job(bootstrap)
        with patch('role_contracts.load_contract', side_effect=OSError('deployment files unavailable')):
            empty = Dispatcher(self.db, lambda:self.now, ())
            self.assertEqual(empty.get_job(bootstrap),original)
            self.assertEqual(empty.bootstrap({}),bootstrap)
        args = {k:original['claim'][k] for k in ('job_id','attempt_id','token')}
        args.update(status='failed',output_refs=[original['result_ref']],error='fixture')
        result = dispatch.control.scheduled('finish',args)
        self.assertEqual(dispatch.control.scheduled('finish',args),result)
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs WHERE id=?',
                         (original['run_id'],)).fetchone()[0],'failed')
        token = original['claim']['token']
        for table in ('job_operations','executor_activations'):
            for (response,) in self.db.execute('SELECT response FROM '+table):
                self.assertNotIn(token,response)

    def test_public_identity_rejection_and_unknown_lookup(self):
        for args in ({'activation_id':'x'}, {'operation_id':'x'}, {'timestamp':'x'}):
            with self.assertRaises(ValueError):
                self.dispatcher.bootstrap(args)
        for identity in ('unknown', '', None, 1):
            with self.assertRaises(ValueError):
                self.dispatcher.get_job({'executor_id':identity})
        self.assertEqual(self.db.execute('SELECT count(*) FROM job_attempts').fetchone()[0], 0)

    def test_empty_occurrence_is_durable(self):
        self.assertEqual(self.dispatcher.bootstrap({}), {'executor_id':None})
        self.job()
        self.assertEqual(self.dispatcher.bootstrap({}), {'executor_id':None})
        self.now += timedelta(hours=1)
        self.assertIsNotNone(self.dispatcher.bootstrap({})['executor_id'])

    def test_retry_crossing_admission_edge_replays_same_occurrence(self):
        self.job()
        first = self.dispatcher.bootstrap({})
        self.now += timedelta(minutes=16)
        self.assertEqual(self.dispatcher.bootstrap({}),first)
        self.assertEqual(self.db.execute('SELECT count(*) FROM job_attempts').fetchone()[0],1)

    def test_backend_admission(self):
        self.job()
        self.now += timedelta(minutes=16)
        self.assertEqual(self.dispatcher.bootstrap({}), {'executor_id':None})
        self.assertEqual(self.db.execute('SELECT count(*) FROM job_attempts').fetchone()[0], 0)

    def test_terminal_retries_and_conflicts_without_ids(self):
        self.job()
        identity = self.dispatcher.bootstrap({})['executor_id']
        package = self.dispatcher.get_job({'executor_id':identity})
        args = {k:package['claim'][k] for k in ('job_id','attempt_id','token')}
        args.update(status='succeeded',output_refs=[package['result_ref']])
        first = self.dispatcher.control.scheduled('finish',args)
        self.assertEqual(self.dispatcher.control.scheduled('finish',args), first)
        with self.assertRaises(ControlConflict):
            self.dispatcher.control.scheduled('finish',dict(args,status='failed'))
        with self.assertRaises(ControlConflict):
            self.dispatcher.control.scheduled('abandon',{k:v for k,v in dict(args,error='uncertain').items() if k not in ('status','output_refs')})

    def test_public_pause_concurrency_blocked(self):
        for mode in ('paused','running','blocked'):
            with self.subTest(mode=mode):
                import sqlite3
                from jobs import JobStore
                with sqlite3.connect(':memory:') as db:
                    dispatch = Dispatcher(db, lambda:self.now, (TestRole,))
                    store = JobStore(db, lambda:self.now)
                    if mode == 'paused':
                        db.execute('UPDATE dispatcher_policy SET paused=1')
                        db.commit()
                    else:
                        job = store.create('Other', [], 'out:v1')
                        claim = store.claim(job, 'other')
                        if mode == 'blocked':
                            store.finish(claim,'uncertain',[])
                    self.assertEqual(dispatch.bootstrap({}), {'executor_id':None})
                    self.assertEqual(dispatch.bootstrap({}), {'executor_id':None})
                    with self.assertRaises(ControlConflict):
                        dispatch.get_job({'executor_id':db.execute('SELECT activation_id FROM executor_activations').fetchone()[0]})

    def test_lost_answer_and_concurrent_server_starts(self):
        from concurrent.futures import ThreadPoolExecutor
        import sqlite3
        self.job()
        def start(_):
            with sqlite3.connect(self.path, timeout=5) as db:
                return Dispatcher(db, lambda:self.now, (TestRole,)).bootstrap({})
        with ThreadPoolExecutor(4) as pool:
            answers = list(pool.map(start,range(4)))
        self.assertTrue(all(answer==answers[0] for answer in answers))
        self.assertEqual(start(None),answers[0])  # discarded committed answer
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM job_attempts').fetchone()[0],1)

    def test_fetch_after_expiry_restores_token_without_authority(self):
        self.job()
        bootstrap = self.dispatcher.bootstrap({})
        original = self.dispatcher.get_job(bootstrap)
        self.now += timedelta(hours=2)
        package = self.dispatcher.get_job(bootstrap)
        self.assertEqual(package,original)
        self.assertFalse(self.dispatcher.control.validate(package['claim'])['valid'])
        args = {k:package['claim'][k] for k in ('job_id','attempt_id','token')}
        with self.assertRaises(ControlConflict):
            self.dispatcher.control.scheduled('finish',dict(args,status='succeeded',output_refs=[]))

    def test_abandon_retry(self):
        self.job()
        package = self.dispatcher.get_job(self.dispatcher.bootstrap({}))
        args = {k:package['claim'][k] for k in ('job_id','attempt_id','token')}
        args['error'] = 'unknown effects'
        first = self.dispatcher.control.scheduled('abandon',args)
        self.assertEqual(first['job_status'],'blocked')
        self.assertEqual(self.dispatcher.control.scheduled('abandon',args),first)
        with self.assertRaises(ControlConflict):
            self.dispatcher.control.scheduled('abandon',dict(args,error='changed'))

# Imported fixture class must not be discovered as an additional suite.
del DispatcherTests
