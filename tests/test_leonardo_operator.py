"""Only the operator boundary; phase-8 lifecycle tests remain canonical."""
import json
import sqlite3
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from test_parts import PartFixture
from leonardo import LeonardoStore
from parts import PartStore
from leonardo_operator import enqueue_offers, main


class OperatorTests(PartFixture):
    def setUp(self):
        super().setUp()
        self.add()
        self.run_day()
        self.conn = sqlite3.connect(self.db)
        self.addCleanup(self.conn.close)
        self.store = LeonardoStore(self.conn)
        self.store.create_dossier('experiment', 2)
        self.part = self.conn.execute('SELECT id,active_revision FROM parts').fetchone()

    def offer(self):
        return PartStore(self.conn).offer(*self.part).id

    def enqueue(self, offers, operation='trial', dossier='experiment', base=0):
        return enqueue_offers(self.conn, operation, dossier, base, offers)

    def test_only_existing_sealed_offers_and_topic(self):
        for offers in ([999], [], [True]):
            with self.assertRaises(ValueError):
                self.enqueue(offers)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        offer = self.offer()
        self.store.create_dossier('wrong', 1)
        for dossier in ('wrong', 'unknown'):
            with self.assertRaises(ValueError):
                self.enqueue([offer], dossier=dossier)
        with self.assertRaises(ValueError):
            self.enqueue([offer, offer])
        job = self.enqueue([offer])
        self.assertEqual(self.conn.execute('SELECT part_id,revision FROM leonardo_assignment_parts WHERE job_id=?', (job,)).fetchall(), [self.part])

    def test_retry_conflicts_pending_and_stale_base(self):
        offer = self.offer()
        job = self.enqueue([offer])
        self.assertEqual(self.enqueue([offer]), job)
        for kwargs in ({'base': 1}, {'dossier': 'other'}, {'operation': 'new'}):
            with self.assertRaises(ValueError):
                self.enqueue([offer], **kwargs)

    def test_cli_dispatch_and_existing_finish(self):
        from dispatcher import Dispatcher
        from job_control import JobControl
        offer = self.offer()
        output = StringIO()
        with redirect_stdout(output):
            main(['--db', str(self.db), 'enqueue', '--dossier', 'experiment', '--base-version', '0', '--operation-id', 'trial', '--offer', str(offer)])
        job = json.loads(output.getvalue())['job_id']
        snapshot = json.loads(self.conn.execute(
            'SELECT snapshot FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()[0])
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for key, name in (('role_contract', 'leonardo.md'),
                          ('output_contract', 'leonardo-output.md')):
            self.assertEqual(snapshot[key], (root / 'roles' / name).read_bytes().decode('utf-8'))
        # Operator delegates contract loading to enqueue; binding needs no deployment IO.
        with patch('role_contracts.load_contract', side_effect=AssertionError('execution-time IO')):
            claim = Dispatcher(self.conn).start(dict(operation_id='start', activation_id='trial-slot'))
        for key in ('role_contract', 'output_contract'):
            self.assertEqual(claim[key], snapshot[key])
            self.assertEqual(claim['input'][key], snapshot[key])
        self.assertEqual((claim['role'], claim['job_id']), ('Leonardo', job))
        state = dict(schema_version=1, dossier_id='experiment', version=1, previous_version=0,
                     hypotheses=[], claims=[], uncertainties=[], open_questions=[],
                     processed_refs=[p['ref'] for p in claim['input']['parts']])
        JobControl(self.conn).execute('finish', dict(
            {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}, operation_id='finish',
            status='succeeded', output_refs=[claim['result_ref']], leonardo_state=state))
        self.assertEqual(self.store.latest('experiment'), state)
        self.assertEqual(self.enqueue([offer]), job)  # retry after base advanced
        with self.assertRaises(ValueError):
            self.enqueue([offer], operation='stale')
        output = StringIO()
        with redirect_stdout(output):
            main(['--db', str(self.db), 'inspect', '--job', str(job)])
        report = json.loads(output.getvalue())
        self.assertEqual(report['state']['processed_refs'], state['processed_refs'])
        self.assertEqual(report['attempts'][0]['status'], 'succeeded')
        self.assertEqual(report['delta']['processed_refs']['added'], state['processed_refs'])
        self.assertGreater(report['input_bytes'], 0)
        self.assertGreater(report['state_bytes'], 0)
        self.assertEqual(report['offers'][0]['id'], offer)
        self.assertEqual(report['dispatch'][0]['activation_id'], 'trial-slot')
        self.assertNotIn(claim['token'], output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            main(['--db', str(self.db), 'inspect', '--job', str(job), '--compact'])
        compact = json.loads(output.getvalue())
        self.assertEqual(set(compact), {'job_id', 'dossier_id', 'status', 'context_usage'})
        attempt = compact['context_usage']['attempts'][0]
        self.assertEqual(attempt['state_tokens'], report['state_metadata']['tokens'])
        self.assertEqual(attempt['recall_count'], 0)
        self.assertIsNone(attempt['provider_usage'])
        self.assertNotIn(claim['token'], output.getvalue())

    def test_multiple_offers_exact_order_and_changed_operation(self):
        first = self.offer()
        self.add('2026-10-07', content='second')
        self.run_day(7)
        part = self.conn.execute('SELECT id,active_revision FROM parts WHERE is_open=1').fetchone()
        second = PartStore(self.conn).offer(*part).id
        job = self.enqueue([second, first])
        self.assertEqual(self.enqueue([second, first]), job)
        from leonardo_operator import inspect_job
        self.assertEqual([o['id'] for o in inspect_job(self.conn, job)['offers']], [second, first])
        for changed in ([second], [first, second], [first, 999]):
            with self.assertRaises(ValueError):
                self.enqueue(changed)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leonardo_assignment_parts WHERE job_id=?', (job,)).fetchone()[0], 2)

        # A real registered revision on an unoffered part cannot enter via this CLI.
        self.add('2026-10-08', content='unoffered')
        self.run_day(8)
        unoffered = self.conn.execute('SELECT id FROM parts WHERE is_open=1').fetchone()[0]
        self.assertIsNone(self.conn.execute('SELECT id FROM part_offers WHERE part_id=?', (unoffered,)).fetchone())
        with self.assertRaises(ValueError):
            self.enqueue([unoffered], operation='unoffered')

    def test_operator_delegates_and_inspection_is_read_only(self):
        from leonardo_operator import inspect_job
        offer = self.offer()
        with patch.object(LeonardoStore, 'enqueue', autospec=True, return_value=123) as enqueue:
            self.assertEqual(self.enqueue([offer]), 123)
            enqueue.assert_called_once()
            self.assertEqual(enqueue.call_args.args[1:],
                             ('trial', 'experiment', 0, [list(self.part)]))
        job = self.enqueue([offer])
        before = self.conn.total_changes
        first = inspect_job(self.conn, job)
        self.assertEqual(inspect_job(self.conn, job), first)
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.conn.total_changes, before)
        with self.assertRaises(ValueError):
            inspect_job(self.conn, 999)
        self.assertFalse(self.conn.in_transaction)

    def test_inspection_reports_objective_state_deltas(self):
        from dispatcher import Dispatcher
        from job_control import JobControl
        from leonardo_operator import inspect_job
        offer = self.offer()
        def finish(operation, version, hypotheses):
            job = self.enqueue([offer], operation=operation, base=version - 1)
            claim = Dispatcher(self.conn).start(dict(operation_id='start:' + operation,
                                                    activation_id=operation))
            state = dict(schema_version=1, dossier_id='experiment', version=version,
                         previous_version=version - 1, hypotheses=hypotheses, claims=[],
                         uncertainties=[], open_questions=[],
                         processed_refs=[p['ref'] for p in claim['input']['parts']])
            JobControl(self.conn).execute('finish', dict(
                {k: claim[k] for k in ('job_id', 'attempt_id', 'token')},
                operation_id='finish:' + operation, status='succeeded',
                output_refs=[claim['result_ref']], leonardo_state=state))
            return job
        ref = 'part:%s:%s' % self.part
        def item(identity, text):
            return dict(id=identity, text=text, refs=[ref])
        finish('first', 1, [item('removed', 'old'), item('changed', 'before')])
        job = finish('second', 2, [item('changed', 'after'), item('added', 'new')])
        report = inspect_job(self.conn, job)
        self.assertEqual(report['delta']['hypotheses'],
                         dict(added=['added'], removed=['removed'], changed=['changed']))
        for field in ('claims', 'uncertainties', 'open_questions'):
            self.assertEqual(report['delta'][field], dict(added=[], removed=[], changed=[]))
        self.assertEqual(report['delta']['processed_refs'], dict(added=[]))
        self.assertEqual(report['state_metadata']['previous_version'], 1)
        self.assertEqual(report['state_metadata']['version'], 2)

    def test_cli_requires_existing_database(self):
        with self.assertRaises(sqlite3.OperationalError):
            main(['--db', str(self.base / 'missing'), 'offers'])
