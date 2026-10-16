"""Only the operator boundary; phase-8 lifecycle tests remain canonical."""
import json
import sqlite3
import unittest
from contextlib import redirect_stdout
from io import StringIO

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
        claim = Dispatcher(self.conn).start(dict(operation_id='start', activation_id='trial-slot'))
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

    def test_multiple_offers_exact_order_and_changed_operation(self):
        first = self.offer()
        self.add('2026-10-07', content='second')
        self.run_day(7)
        part = self.conn.execute('SELECT id,active_revision FROM parts WHERE is_open=1').fetchone()
        second = PartStore(self.conn).offer(*part).id
        job = self.enqueue([first, second])
        self.assertEqual(self.enqueue([first, second]), job)
        for changed in ([second], [second, first], [first, 999]):
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

    def test_cli_requires_existing_database(self):
        with self.assertRaises(sqlite3.OperationalError):
            main(['--db', str(self.base / 'missing'), 'offers'])
