"""Small integration gate for the zero-input → mission → ingress feedback loop."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from test_leonardo import LeonardoFixture
from job_control import JobControl
from leonardo_operator import inspect_job


def frozen_leonardo(prefix):
    from unittest.mock import patch
    from leonardo import canonical
    def encode(value):
        if isinstance(value, dict) and 'role_contract' in value and 'parts' in value:
            value = dict(value, schema_version=1, output_contract=prefix + '\n' + value['output_contract'])
        return canonical(value)
    return patch('leonardo.canonical', side_effect=encode)


def grouped_result(claim, summary, limitations):
    return dict(mission_results=[dict(mission_id=m['mission_id'], summary=summary, limitations=limitations)
                                for m in claim['input']['missions']])


class Phase12Tests(LeonardoFixture):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def reevaluate(self):
        self.enqueue()
        self.finish(self.start())
        return self.store.reevaluate('reeval:1', 'dossier:reproduction', 1)

    def proposals(self):
        return [dict(question='Can an independent team reproduce this result?',
                     rationale='Independent confirmation is missing.',
                     scope='Find at most three primary reports; exclude commentary.',
                     refs=['part:%s:%s' % self.part])]

    def issue(self):
        job = self.reevaluate()
        claim = self.start('reeval')
        self.finish(claim, self.state(2), 'reeval:finish', kuifje_missions=self.proposals())
        return job, claim

    def test_zero_input_is_explicit_preserves_provenance_and_recall(self):
        with self.assertRaises(ValueError):
            self.store.reevaluate('empty', 'dossier:reproduction', 0)
        job = self.reevaluate()
        self.assertEqual(job, self.store.reevaluate('reeval:1', 'dossier:reproduction', 1))
        claim = self.start('reeval')
        self.assertEqual(claim['input']['mode'], 'reevaluation')
        self.assertEqual(claim['input']['parts'], [])
        self.assertEqual(self.conn.execute('SELECT * FROM leonardo_assignment_parts WHERE job_id=?', (job,)).fetchall(), [])
        authority = {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}
        recalled = self.store.recall(dict(authority, ref=self.state()['processed_refs'][0], recall_id='old'))
        self.assertIn('WEEKENDKRANT-PART-1', recalled['content'])
        self.finish(claim, self.state(2), 'reeval:finish')
        self.assertEqual(self.store.latest('dossier:reproduction')['processed_refs'], self.state()['processed_refs'])
        report = inspect_job(self.conn, job, compact=True)
        self.assertEqual(report['context_usage']['new_part_count'], 0)
        self.assertEqual(report['base_version'], 1)
        self.assertEqual(report['mission_count'], 0)

    def test_mission_separation_immutability_frozen_context_and_exact_retries(self):
        job, leo = self.issue()
        from kuifje import inspect_mission
        report = inspect_mission(self.conn, 'kuifje:%s:1' % job)
        self.assertEqual(report['producer_job_id'], job)
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(report['refs'], self.proposals()[0]['refs'])
        self.assertEqual(self.store.latest('dossier:reproduction'), self.state(2))
        self.finish(leo, self.state(2), 'reeval:finish', kuifje_missions=self.proposals())
        self.finish(leo, self.state(2), 'another:finish', kuifje_missions=self.proposals())
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.finish(leo, self.state(2), 'changed:finish', kuifje_missions=[])
        for table in ('kuifje_missions', 'kuifje_assignments', 'kuifje_assignment_missions'):
            for sql in ('UPDATE '+table+' SET rowid=rowid', 'DELETE FROM '+table,
                        'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(sql)
                self.conn.rollback()
        with patch('role_contracts.load_contract', side_effect=AssertionError('frozen')):
            claim = self.start('kuifje')
        self.assertEqual(claim['role'], 'Kuifje')
        self.assertEqual(claim['input']['missions'][0]['mission_id'], report['mission_id'])
        self.assertIn('Kuifje', claim['role_contract'])
        self.assertEqual(self.start('kuifje'), claim)
        from ariadne_tokens import measure
        for table, column in [('kuifje_missions', 'content'), ('kuifje_assignments', 'snapshot')]:
            content, tokens, size, tokenizer = self.conn.execute('SELECT '+column+',tokens,bytes,tokenizer FROM '+table).fetchone()
            self.assertEqual(measure(content), dict(tokens=tokens, bytes=size, tokenizer=tokenizer))

    def test_invalid_mission_and_injected_failure_roll_back_all_effects(self):
        job = self.reevaluate()
        claim = self.start('reeval')
        for refs in (['part:999:1'], ['queue:999']):
            bad = dict(self.proposals()[0], refs=refs)
            with self.assertRaises(ValueError):
                self.finish(claim, self.state(2), 'bad', kuifje_missions=[bad])
            self.assertEqual(self.store.latest('dossier:reproduction')['version'], 1)
            self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 0)
        with patch('job_control._AtomicStore.create', side_effect=ValueError('disk simulation')):
            with self.assertRaises(ValueError):
                self.finish(claim, self.state(2), 'bad', kuifje_missions=self.proposals())
        self.assertEqual(self.store.latest('dossier:reproduction')['version'], 1)
        self.assertEqual(self.conn.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone()[0], 'running')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 0)
        self.finish(claim, self.state(2), 'bad', kuifje_missions=self.proposals())

    def test_kuifje_ingress_fencing_terminal_retry_and_ariadne_materialization(self):
        self.issue()
        claim = self.start('kuifje')
        authority = {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}
        mission = claim['input']['missions'][0]['mission_id']
        fiche = dict(schema_version=1, date=claim['input']['date'], topic=2, content='Independent primary report é')
        queue_id = self.queue.add(fiche, mission_id=mission, fiche_id='source:1', claim=authority)
        self.assertEqual(queue_id, self.queue.add(fiche, mission_id=mission, fiche_id='source:1', claim=authority))
        with self.assertRaises(ValueError):
            self.queue.add(dict(fiche, content='changed'), mission_id=mission, fiche_id='source:1', claim=authority)
        result = grouped_result(claim, 'One primary report found.', 'No third replication.')
        args = dict(authority, status='succeeded', output_refs=[claim['result_ref']], kuifje_result=result)
        control = JobControl(self.conn, lambda: self.now)
        self.assertEqual(control.scheduled('finish', args), control.scheduled('finish', args))
        with self.assertRaises(ValueError):
            self.queue.add(fiche, mission_id=mission, fiche_id='source:2', claim=authority)
        self.run_job_day(claim)
        self.assertEqual(self.conn.execute('SELECT status FROM ingress_queue WHERE id=?', (queue_id,)).fetchone()[0], 'processed')
        part, revision = self.conn.execute('SELECT part_id,revision FROM revision_sources WHERE queue_id=? ORDER BY revision DESC LIMIT 1', (queue_id,)).fetchone()
        self.store.enqueue('feedback', 'dossier:reproduction', 2, [[part, revision]])
        feedback = self.start('feedback')
        self.assertIn(fiche['content'], feedback['input']['parts'][0]['content'])
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_kuifje_expiry_recovery_uses_same_mission_and_fences_old_attempt(self):
        self.issue()
        old = self.start('kuifje')
        self.now += timedelta(hours=2)
        control = JobControl(self.conn, lambda: self.now)
        authority = {k: old[k] for k in ('job_id', 'attempt_id', 'token')}
        self.assertFalse(control.validate(authority)['valid'])
        control.execute('reconcile', dict(operation_id='recover:k', job_id=old['job_id'],
            attempt_id=old['attempt_id'], decision='retry', evidence_ref='operator:stopped'))
        new = self.start('kuifje:retry')
        self.assertEqual(old['input'], new['input'])
        with self.assertRaises(ValueError):
            control.scheduled('finish', dict(authority, status='succeeded', output_refs=[old['result_ref']],
                kuifje_result=dict(summary='empty', limitations='none found')))

    def test_http_mission_finish_kuifje_package_and_same_fiche_ingress(self):
        self.reevaluate()
        post = self.http_post()
        # Existing fixture start uses the explicit internal dispatcher entrypoint.
        leo = self.start('reeval')
        args = {k: leo[k] for k in ('job_id', 'attempt_id', 'token')}
        args.update(status='succeeded', output_refs=[leo['result_ref']],
                    leonardo_state=self.state(2), kuifje_missions=self.proposals())
        self.assertEqual(post('/jobs/finish', args)[0], 200)
        self.assertEqual(post('/jobs/finish', args)[0], 200)
        k = self.start('kuifje')
        status, package = post('/executor/job', dict(executor_id='kuifje'))
        self.assertEqual(status, 200)
        self.assertEqual(package['role'], 'Kuifje')
        self.assertEqual(package['input'], k['input'])
        fiche = dict(schema_version=1, date=k['input']['date'], topic=2, content='Primary source https://example.org/report',
                     mission_id=k['input']['missions'][0]['mission_id'], fiche_id='report', claim=package['claim'])
        first = post('/ingress', fiche)
        self.assertEqual(first[0], 201)
        self.assertEqual(post('/ingress', fiche), first)
        stored = json.loads(self.conn.execute('SELECT payload FROM ingress_queue WHERE id=?', (first[1]['id'],)).fetchone()[0])
        self.assertEqual(set(stored), {'schema_version', 'date', 'topic', 'content'})
        bad = dict(fiche, mission_id='kuifje:foreign:1')
        self.assertEqual(post('/ingress', bad)[0], 409)
        finish = {key: k[key] for key in ('job_id', 'attempt_id', 'token')}
        finish.update(status='succeeded', output_refs=[k['result_ref']],
                      kuifje_result=grouped_result(k, 'Found report', 'Only one source'))
        self.assertEqual(post('/jobs/finish', finish)[0], 200)
        self.assertEqual(post('/jobs/finish', finish)[0], 200)
        self.assertEqual(post('/ingress', fiche)[0], 409)

    def test_mission_queue_membership_old_contract_and_state_schema_boundary(self):
        self.reevaluate()
        claim = self.start('reeval')
        state = self.state(2)
        state['kuifje_missions'] = self.proposals()
        with self.assertRaises(ValueError):
            self.finish(claim, state, 'bad:state')
        # Existing archived queue member is allowed without enlarging processed_refs.
        missions = [dict(self.proposals()[0], refs=['queue:1'])]
        self.finish(claim, self.state(2), 'queue:mission', kuifje_missions=missions)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 1)

    def test_reevaluation_audit_uses_canonical_primitive_outside_write_lock(self):
        self.enqueue()
        self.finish(self.start())
        import ariadne_tokens
        original = ariadne_tokens.token_count
        calls = []
        def count(text):
            self.assertFalse(self.conn.in_transaction)
            calls.append(text)
            return original(text)
        with patch('leonardo.token_count', side_effect=count):
            job = self.store.reevaluate('reeval:1', 'dossier:reproduction', 1)
        snapshot, tokens = self.conn.execute('SELECT snapshot,tokens FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()
        self.assertIn(snapshot, calls)
        self.assertEqual(tokens, original(snapshot))
        self.assertEqual(json.loads(snapshot)['tokenizer'], ariadne_tokens.TOKENIZER)
        self.assertEqual(inspect_job(self.conn, job, compact=True)['context_usage']['start_input_bytes'], len(snapshot.encode()))

    def test_schema13_migration_is_additive_atomic_and_idempotent(self):
        import database
        with sqlite3.connect(':memory:') as db:
            with patch.object(database, 'SCHEMA_VERSION', 12):
                database.migrate(db)
            before = list(db.iterdump())
            original = database.migration_sql
            with patch('database.migration_sql', side_effect=lambda v: original(v) + 'CREATE TABLE jobs(conflict);'):
                with self.assertRaises(sqlite3.Error):
                    database.migrate(db)
            self.assertEqual(list(db.iterdump()), before)
            database.migrate(db)
            after = list(db.iterdump())
            database.migrate(db)
            self.assertEqual(list(db.iterdump()), after)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_provenance_is_prior_immutable_membership_and_mission_counts_are_bounded(self):
        self.reevaluate()
        later = self.add(content='only in newer revision')
        self.run_day()
        claim = self.start('reeval')
        for bad in ([dict(self.proposals()[0], refs=[f'queue:{later}'])],
                    [dict(self.proposals()[0], refs=[f'part:{self.part[0]}:2'])],
                    self.proposals() * 5,
                    [dict(self.proposals()[0], mission_id='invented')]):
            with self.assertRaises(ValueError):
                self.finish(claim, self.state(2), 'invalid', kuifje_missions=bad)
        self.finish(claim, self.state(2), 'two', kuifje_missions=[self.proposals()[0],
                    dict(self.proposals()[0], question='What evidence contradicts it?')])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_assignments').fetchone()[0], 1)
        self.assertEqual(inspect_job(self.conn, claim['job_id'], compact=True)['mission_count'], 2)

    def test_frozen_v2_cannot_issue_missions_and_no_phantom_success_or_direct_claim(self):
        self.enqueue()
        self.finish(self.start())
        with frozen_leonardo('leonardo-output-v2:'):
            self.store.reevaluate('legacy', 'dossier:reproduction', 1)
        claim = self.start('legacy')
        with self.assertRaises(ValueError):
            self.finish(claim, self.state(2), 'legacy:bad', kuifje_missions=self.proposals())
        self.finish(claim, self.state(2), 'legacy:okay')
        self.store.reevaluate('current', 'dossier:reproduction', 2)
        claim = self.start('current')
        self.finish(claim, self.state(3), 'current:finish', kuifje_missions=self.proposals())
        job, = self.conn.execute('SELECT job_id FROM kuifje_assignments').fetchone()
        control = JobControl(self.conn, lambda: self.now)
        with self.assertRaises(ValueError):
            control.execute('claim', dict(operation_id='bypass', job_id=job, activation_id='bypass'))
        kuifje = self.start('kuifje')
        authority = {k: kuifje[k] for k in ('job_id', 'attempt_id', 'token')}
        for invalid in (dict(status='succeeded', output_refs=[kuifje['result_ref']]),
                        dict(status='failed', output_refs=[kuifje['result_ref']]),
                        dict(status='failed', output_refs=[], kuifje_result=dict(summary='x', limitations='x')),
                        dict(status='succeeded', output_refs=[kuifje['result_ref']],
                             kuifje_result=dict(summary='empty', limitations='none'), kuifje_missions=self.proposals())):
            with self.assertRaises(ValueError):
                control.scheduled('finish', dict(authority, **invalid))
        control.scheduled('finish', dict(authority, status='succeeded', output_refs=[kuifje['result_ref']],
                          kuifje_result=grouped_result(kuifje, 'Empty harvest', 'No primary report found')))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_fiches').fetchone()[0], 0)

    def test_fiche_authority_topic_bound_and_recovery_retry_preserve_original_producer(self):
        self.issue()
        claim = self.start('kuifje')
        authority = {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}
        mission = claim['input']['missions'][0]['mission_id']
        fiche = dict(schema_version=1, date=claim['input']['date'], topic=2, content='report')
        for bad_claim in (dict(authority, token='wrong'), dict(authority, attempt_id=999)):
            with self.assertRaises(ValueError):
                self.queue.add(fiche, mission_id=mission, fiche_id='one', claim=bad_claim)
        with self.assertRaises(ValueError):
            self.queue.add(dict(fiche, topic=3), mission_id=mission, fiche_id='one', claim=authority)
        qid = self.queue.add(fiche, mission_id=mission, fiche_id='one', claim=authority)
        self.now += timedelta(hours=2)
        control = JobControl(self.conn, lambda: self.now)
        control.validate(authority)
        control.execute('reconcile', dict(operation_id='recover:fiche', job_id=claim['job_id'],
            attempt_id=claim['attempt_id'], decision='retry', evidence_ref='operator:effects-checked'))
        # Ingress samples actual UTC, so use a fresh real-clock lease for this fixture.
        self.now = datetime.now(timezone.utc)
        retry = self.start('retry:fiche')
        new_authority = {k: retry[k] for k in ('job_id', 'attempt_id', 'token')}
        self.assertEqual(qid, self.queue.add(fiche, mission_id=mission, fiche_id='one', claim=new_authority))
        self.assertEqual(self.conn.execute('SELECT attempt_id FROM kuifje_fiches WHERE queue_item_id=?', (qid,)).fetchone()[0], claim['attempt_id'])
        for i in range(2, 6):
            self.queue.add(fiche, mission_id=mission, fiche_id=str(i), claim=new_authority)
        with self.assertRaises(ValueError):
            self.queue.add(fiche, mission_id=mission, fiche_id='six', claim=new_authority)

    def test_legacy_schema1_capabilities_remain_frozen(self):
        from leonardo import supports_capability
        for prefix, fine, missions in [('leonardo-output-v1:', False, False),
                                      ('leonardo-output-v2:', True, False),
                                      ('leonardo-output-v3:', True, True)]:
            data = dict(schema_version=1, output_contract=prefix + ' frozen')
            self.assertEqual(supports_capability(data, 'fine_provenance'), fine)
            self.assertEqual(supports_capability(data, 'missions'), missions)
        with frozen_leonardo('leonardo-output-v3:'):
            self.enqueue()
        leo = self.start()
        state = self.state()
        state['claims'][0]['support'] = ['queue:1']
        self.finish(leo, state, kuifje_missions=self.proposals())
        self.assertEqual(leo['input']['schema_version'], 1)
        self.assertEqual(self.start('legacy:child')['input']['schema_version'], 2)

    def test_new_operation_cannot_append_missions_to_already_confirmed_empty_output(self):
        self.reevaluate()
        claim = self.start('reeval')
        self.finish(claim, self.state(2), 'first:no-missions')
        with self.assertRaises(ValueError):
            self.finish(claim, self.state(2), 'later:append', kuifje_missions=self.proposals())
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 0)
