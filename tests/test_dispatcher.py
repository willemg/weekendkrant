"""State-driven dispatch, independent of any production role's activation path."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import database
from dispatcher import Dispatcher
from jobs import JobStore
from job_control import JobControl, ControlConflict


class TestRole:
    role = 'TestRole'
    def __init__(self, dispatcher):
        self.db = dispatcher.db
    def prepare(self):
        return None
    def ready(self, job_id):
        return True  # Test-only role with an empty, concrete input/output contract.
    def produce(self, now, prepared):
        return None
    def bind(self, job_id, claim, now):
        return dict(claim, role=self.role, input={}, input_refs=[],
                    role_contract_ref='test:role:v1', role_contract='Test role',
                    output_contract_ref='test:output:v1', output_contract='Test output',
                    result_ref='test:result:'+str(job_id))


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.dispatcher = Dispatcher(self.db, lambda: self.now, (TestRole,))
        self.store = JobStore(self.db, lambda: self.now)

    def start(self, identity='one', dispatcher=None):
        return (dispatcher or self.dispatcher).start(dict(operation_id='start:'+identity, activation_id=identity))

    def job(self, role='TestRole'):
        return self.store.create(role, [], 'test:output:v1')

    def finish(self, claim, status='succeeded'):
        return JobControl(self.db, lambda: self.now).execute('finish',
            dict(operation_id='finish:'+str(claim['attempt_id']),
                 **{k: claim[k] for k in ('job_id','attempt_id','token')},
                 status=status, output_refs=[claim['result_ref']]))

    def policy(self, **values):
        for name, value in values.items():
            self.db.execute('UPDATE dispatcher_policy SET '+name+'=? WHERE id=1', (value,))
        self.db.commit()

    def test_ready_fifo_before_sherlock_production_and_generic_replay(self):
        first, second = self.job(), self.job()
        dispatcher = Dispatcher(self.db, lambda: self.now,
                                (type(self.dispatcher.producers[0]), __import__('sherlock_executor').SherlockProducer))
        claim = self.start(dispatcher=dispatcher)
        self.assertEqual(claim['job_id'], first)
        self.assertNotIn('run_id', claim)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sherlock_runs').fetchone()[0], 0)
        self.finish(claim)
        self.policy(paused=1)
        # No adapter or contract-file access is needed for replay, even after finish/pause.
        empty_registry = Dispatcher(self.db, lambda: self.now, ())
        self.assertEqual(self.start(dispatcher=empty_registry), claim)
        with self.assertRaises(ControlConflict):
            JobControl(self.db).execute('claim', dict(operation_id='second', activation_id='one', job_id=second))
        self.assertEqual(self.store.get(second)['status'], 'ready')
        self.assertEqual(self.db.execute('SELECT count(*) FROM job_attempts').fetchone()[0], 1)

    def test_pause_is_persistent_and_does_not_revoke_running_authority(self):
        self.job()
        claim = self.start()
        self.policy(paused=1)
        self.job('Other')
        restarted = Dispatcher(self.db, lambda: self.now, (TestRole,))
        self.assertEqual(self.start('paused', restarted), {'claim': None})
        self.assertTrue(JobControl(self.db, lambda: self.now).validate(
            {k: claim[k] for k in ('job_id','attempt_id','token')})['valid'])
        self.finish(claim)
        ready = self.job()
        self.assertEqual(JobControl(self.db).execute('claim', dict(operation_id='direct', activation_id='direct', job_id=ready)), {'claim': None})
        self.policy(paused=0)
        self.assertEqual(self.start('paused'), {'claim': None})
        self.assertEqual(self.start('unpaused')['job_id'], ready)

    def test_global_running_expiry_quarantine_and_explicit_recovery(self):
        other = self.job('Other')
        claim = self.store.claim(other, 'external')
        ready = self.job()
        self.assertEqual(self.start(), {'claim': None})
        self.now += timedelta(hours=2)
        self.assertEqual(self.start('expired'), {'claim': None})
        self.assertEqual(self.store.get(other)['status'], 'blocked')
        JobControl(self.db, lambda: self.now).execute('reconcile', dict(operation_id='recover', job_id=other,
            attempt_id=claim['attempt_id'], decision='failed', evidence_ref='audit:stopped-effects-known'))
        self.assertEqual(self.start('recovered')['job_id'], ready)

    def test_limit_can_expand_without_same_role_conflict(self):
        self.policy(max_running=2)
        self.job('Other')
        self.store.claim(1, 'other')
        self.job()
        self.job()
        claim = self.start()
        self.assertEqual(claim['job_id'], 2)
        self.assertEqual(self.start('full'), {'claim': None})
        self.policy(max_running=3)
        self.assertEqual(self.start('same-role'), {'claim': None})
        self.finish(claim, 'uncertain')
        self.policy(max_running=4)
        self.assertEqual(self.start('blocked'), {'claim': None})

    def test_unsupported_ready_does_not_create_work(self):
        self.job('Leonardo')
        self.assertEqual(self.start(), {'claim': None})
        self.job()
        self.assertEqual(self.start(), {'claim': None})
        self.assertEqual(self.start('next')['role'], 'TestRole')

    def test_concurrent_distinct_activations_share_one_lane(self):
        for _ in range(4):
            self.job()
        def start(identity):
            with sqlite3.connect(self.path, timeout=5) as db:
                return self.start(identity, Dispatcher(db, lambda: self.now, (TestRole,)))
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(start, ['a','b','c','d']))
        self.assertEqual(sum('job_id' in result for result in results), 1)

    def test_schema_nine_receipts_migrate_and_replay_without_sherlock_adapter(self):
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 9):
                store = JobStore(db, lambda: self.now)
                job = store.create('Sherlock', [], 'output:v1')
                claim = store.claim(job, 'legacy')
                for ref, content in [('role:v1','role text'), ('output:v1','output text')]:
                    db.execute('INSERT INTO sherlock_contracts VALUES (?,?)', (ref, content))
                response = dict(claim, role='Sherlock', role_contract_ref='role:v1', output_contract_ref='output:v1')
                response.pop('token')
                db.execute('INSERT INTO sherlock_activations VALUES (?,?,?,?,?,?)',
                           ('start:legacy','legacy',job,claim['attempt_id'],json.dumps(response),self.now.isoformat()))
                db.execute('INSERT INTO sherlock_activations VALUES (?,?,NULL,NULL,?,?)',
                           ('start:empty','empty','{"claim":null}',self.now.isoformat()))
                db.commit()
            before = list(db.iterdump())
            original = database.migration_sql
            with patch('database.migration_sql', side_effect=lambda v: original(v)+'CREATE TABLE executor_activations(conflict);'):
                with self.assertRaises(sqlite3.Error):
                    database.migrate(db)
            self.assertEqual(list(db.iterdump()), before)
            dispatcher = Dispatcher(db, lambda: self.now, ())
            result = self.start('legacy', dispatcher)
            self.assertEqual(result['token'], claim['token'])
            self.assertEqual(result['role_contract'], 'role text')
            self.assertEqual(self.start('empty', dispatcher), {'claim': None})
            self.assertEqual(db.execute('SELECT count(*) FROM sherlock_activations').fetchone()[0], 2)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
