"""Current-input mission provenance and explicit feedback without source fiches."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from job_control import JobControl
from leonardo_operator import inspect_job
from test_leonardo import LeonardoFixture
from test_phase12 import grouped_result


class CorrectionTests(LeonardoFixture):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def mission(self):
        return [dict(question='Independent confirmation?', rationale='Missing replication',
                     scope='Primary reports only', refs=['part:%s:%s' % self.part, 'queue:1'])]

    def kuifje(self):
        self.enqueue()
        leo = self.start()
        self.finish(leo, kuifje_missions=self.mission())
        return self.start('kuifje')

    def terminal(self, claim, status='succeeded'):
        args = {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}
        args.update(status=status, output_refs=[claim['result_ref']] if status == 'succeeded' else [])
        if status == 'succeeded':
            args['kuifje_result'] = grouped_result(claim, 'No usable primary evidence found',
                                                     'Two repositories inaccessible')
        else:
            args['error'] = 'Primary repository unavailable'
        return JobControl(self.conn, lambda: self.now).scheduled('finish', args)

    def test_current_parts_and_queue_are_valid_but_future_revision_is_not(self):
        self.enqueue()
        claim = self.start()
        later = self.add(content='later source')
        self.run_day()
        for ref in (f'part:{self.part[0]}:2', f'queue:{later}'):
            with self.assertRaises(ValueError):
                self.finish(claim, kuifje_missions=[dict(self.mission()[0], refs=[ref])])
            self.assertIsNone(self.store.latest('dossier:reproduction'))
        self.finish(claim, kuifje_missions=self.mission())
        mission = json.loads(self.conn.execute('SELECT content FROM kuifje_missions').fetchone()[0])
        self.assertEqual(mission['refs'], self.mission()[0]['refs'])
        self.assertEqual(self.store.latest('dossier:reproduction'), self.state())

    def test_empty_result_is_immutable_and_frozen_as_real_later_context(self):
        k = self.kuifje()
        with self.assertRaises(ValueError):
            self.store.reevaluate('result:review', 'dossier:reproduction', 1,
                                  kuifje_results=[[k['job_id'], k['attempt_id']]])
        self.terminal(k)
        for table in ('kuifje_results',):
            for sql in ('UPDATE '+table+' SET rowid=rowid', 'DELETE FROM '+table,
                        'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(sql)
                self.conn.rollback()
        before = {t:self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0]
                  for t in ('ingress_queue', 'part_revisions', 'revision_sources', 'kuifje_fiches')}
        selection = [[k['job_id'], k['attempt_id']]]
        job = self.store.reevaluate('result:review', 'dossier:reproduction', 1, kuifje_results=selection)
        self.assertEqual(job, self.store.reevaluate('result:review', 'dossier:reproduction', 1, kuifje_results=selection))
        with self.assertRaises(ValueError):
            self.store.reevaluate('result:review', 'dossier:reproduction', 1)
        claim = self.start('result:review')
        feedback, = claim['input']['research_results']
        self.assertEqual(feedback['mission']['mission_id'], k['input']['missions'][0]['mission_id'])
        self.assertEqual((feedback['job_id'], feedback['attempt_id']), tuple(selection[0]))
        self.assertEqual(feedback['status'], 'succeeded')
        self.assertIn('No usable', feedback['result']['summary'])
        self.assertEqual(claim['input']['parts'], [])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_fiches').fetchone()[0], 0)
        report = inspect_job(self.conn, job, compact=True)
        self.assertEqual(report['context_usage']['research_result_count'], 1)
        self.assertGreater(report['context_usage']['research_result_tokens'], 0)
        from ariadne_tokens import token_count
        frozen, tokens = self.conn.execute('SELECT snapshot,tokens FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()
        self.assertEqual(token_count(frozen), tokens)
        post = self.http_post()
        code, packet = post('/executor/job', dict(executor_id='result:review'))
        self.assertEqual(code, 200)
        self.assertEqual(packet['input']['research_results'], claim['input']['research_results'])
        bad = self.state(2)
        bad['processed_refs'].append(feedback['ref'])
        with self.assertRaises(ValueError):
            self.finish(claim, bad, 'result:bad:source')
        state = self.state(2)
        state['uncertainties'][0]['text'] = 'Independent research found no primary evidence; repositories were inaccessible.'
        self.finish(claim, state, 'result:review:finish')
        self.assertEqual(self.store.latest('dossier:reproduction')['processed_refs'], self.state()['processed_refs'])
        for t, count in before.items():
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0], count)
        self.assertEqual(json.loads(frozen)['research_results'], claim['input']['research_results'])

    def test_binding_rejects_foreign_unknown_and_superseded_attempts(self):
        k = self.kuifje()
        self.now += timedelta(hours=2)
        control = JobControl(self.conn, lambda: self.now)
        auth = {key:k[key] for key in ('job_id', 'attempt_id', 'token')}
        control.validate(auth)
        control.execute('reconcile', dict(operation_id='retry:k', job_id=k['job_id'],
            attempt_id=k['attempt_id'], decision='retry', evidence_ref='operator:stopped'))
        new = self.start('kuifje:retry')
        self.terminal(new)
        self.store.create_dossier('other', 2)
        self.store.enqueue('other:first', 'other', 0, [list(self.part)])
        other_claim = self.start('other:first')
        other_state = self.state()
        other_state['dossier_id'] = 'other'
        self.finish(other_claim, other_state, 'other:first:finish')
        for dossier, pairs in [('dossier:reproduction', [[k['job_id'], k['attempt_id']]]),
                               ('dossier:reproduction', [[new['job_id'], 99999]]),
                               ('other', [[new['job_id'], new['attempt_id']]])]:
            with self.assertRaises(ValueError):
                self.store.enqueue('invalid:'+dossier, dossier, 1,
                                   [list(self.part)], kuifje_results=pairs)
        self.store.reevaluate('valid:new', 'dossier:reproduction', 1,
                              kuifje_results=[[new['job_id'], new['attempt_id']]])

    def test_failed_research_can_be_reviewed_without_a_synthetic_source(self):
        k = self.kuifje()
        self.terminal(k, 'failed')
        self.store.reevaluate('failed:review', 'dossier:reproduction', 1,
                              kuifje_results=[[k['job_id'], k['attempt_id']]])
        claim = self.start('failed:review')
        feedback, = claim['input']['research_results']
        self.assertEqual(feedback['status'], 'failed')
        self.assertIsNone(feedback['result'])
        self.assertIn('unavailable', feedback['error'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_results').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_fiches').fetchone()[0], 0)

    def test_explicit_results_also_join_new_material_snapshot_and_operator_cli(self):
        import subprocess
        import sys
        k = self.kuifje()
        self.terminal(k)
        self.store.enqueue('new:with:feedback', 'dossier:reproduction', 1, [list(self.part)],
                           kuifje_results=[[k['job_id'], k['attempt_id']]])
        claim = self.start('new:with:feedback')
        self.assertEqual(claim['input']['mode'], 'new_material')
        self.assertEqual(len(claim['input']['research_results']), 1)
        self.finish(claim, self.state(2), 'finish:new:with:feedback')
        run = subprocess.run([sys.executable, 'leonardo_operator.py', '--db', str(self.db), 'reevaluate',
                              '--dossier', 'dossier:reproduction', '--base-version', '2',
                              '--operation-id', 'cli:feedback', '--kuifje-result',
                              f"{k['job_id']}:{k['attempt_id']}"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        snapshot, = self.conn.execute('SELECT snapshot FROM leonardo_assignments WHERE job_id=?',
                                     (json.loads(run.stdout)['job_id'],)).fetchone()
        self.assertEqual(json.loads(snapshot)['research_results'][0]['attempt_id'], k['attempt_id'])
