"""One run carries ordered immutable missions; scheduling stays generic."""
from datetime import datetime, timezone
import json
from job_control import JobControl
from test_leonardo import LeonardoFixture


class GroupedTests(LeonardoFixture):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def issue(self, count=3):
        job = self.enqueue()
        leo = self.start()
        proposals = [dict(question='Question %s?' % i, rationale='Missing evidence',
                          scope='Primary reports', refs=['queue:1']) for i in range(count)]
        state = self.state()
        state['claims'][0]['support'] = ['queue:1']
        self.finish(leo, state, kuifje_missions=proposals)
        return job, leo, state, proposals

    def test_three_missions_one_run_current_machine_capabilities(self):
        job, leo, state, proposals = self.issue()
        self.assertEqual(leo['input']['schema_version'], 2)
        self.assertFalse(leo['output_contract'].startswith('leonardo-output-v'))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 3)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_assignments').fetchone()[0], 1)
        k = self.start('k')
        self.assertEqual(k['input']['schema_version'], 2)
        ids = [m['mission_id'] for m in k['input']['missions']]
        self.assertEqual(ids, ['kuifje:%s:%s' % (job, i) for i in range(1, 4)])
        self.assertEqual(self.conn.execute('SELECT mission_id FROM kuifje_assignment_missions ORDER BY position').fetchall(), [(m,) for m in ids])
        self.assertEqual(self.start('k'), k)
        self.assertEqual(k['result_ref'], 'kuifje-result:job:%s' % k['job_id'])
        self.finish(leo, state, 'replay', kuifje_missions=proposals)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM jobs WHERE role='Kuifje'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_per_mission_fiches_and_complete_ordered_result_feedback(self):
        self.issue()
        k = self.start('k')
        auth = {key:k[key] for key in ('job_id', 'attempt_id', 'token')}
        ids = [m['mission_id'] for m in k['input']['missions']]
        fiche = dict(schema_version=1, date='2026-10-17', topic=2, content='Primary report')
        for mission in ids:
            for i in range(5):
                q = self.queue.add(fiche, mission_id=mission, fiche_id=str(i), claim=auth)
                self.assertEqual(q, self.queue.add(fiche, mission_id=mission, fiche_id=str(i), claim=auth))
            for payload, identity in [(fiche, 'six'), (dict(fiche, content='changed'), '0'), (dict(fiche, topic=3), '0')]:
                with self.assertRaises(ValueError):
                    self.queue.add(payload, mission_id=mission, fiche_id=identity, claim=auth)
        with self.assertRaises(ValueError):
            self.queue.add(fiche, mission_id='kuifje:999:1', fiche_id='0', claim=auth)
        results = [dict(mission_id=m, summary='No independent confirmation', limitations='Limited coverage') for m in ids]
        control = JobControl(self.conn, lambda:self.now)
        args = dict(auth, status='succeeded', output_refs=[k['result_ref']])
        for bad in [results[:-1], results[::-1], results+[results[0]], [dict(results[0], mission_id='foreign')]+results[1:]]:
            with self.assertRaises(ValueError):
                control.scheduled('finish', dict(args, kuifje_result=dict(mission_results=bad)))
        with self.assertRaises(ValueError):
            control.scheduled('finish', dict(args, kuifje_result=dict(summary='x', limitations='x')))
        good = dict(args, kuifje_result=dict(mission_results=results))
        self.assertEqual(control.scheduled('finish', good), control.scheduled('finish', good))
        self.assertEqual(self.start('k'), k)  # Finished activation cannot claim another job.
        self.assertEqual(self.conn.execute('SELECT count(*) FROM job_attempts WHERE job_id=?', (k['job_id'],)).fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_results').fetchone()[0], 1)
        from kuifje import inspect_mission
        report = inspect_mission(self.conn, ids[0])
        self.assertEqual((report['fiche_count'], report['job_fiche_count'], report['mission_count']), (5, 15, 3))
        self.store.reevaluate('feedback', 'dossier:reproduction', 1, kuifje_results=[[k['job_id'], k['attempt_id']]])
        feedback = self.start('feedback')['input']['research_results']
        self.assertEqual([r['mission_id'] for r in feedback], ids)
        self.assertEqual([r['result']['summary'] for r in feedback], [r['summary'] for r in results])
        self.assertEqual(len({r['ref'] for r in feedback}), 3)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_grouped_atomicity_each_commit_stage_and_origin_checks(self):
        from unittest.mock import patch
        import kuifje
        self.enqueue()
        leo = self.start()
        proposals = [dict(question='Question?', rationale='Gap', scope='Primary reports', refs=['queue:1'])]*3
        original = kuifje.commit_missions
        before = list(self.conn.iterdump())
        for field, value in [('topic', 3), ('dossier_id', 'foreign'), ('state_version', 99), ('producer_job_id', 999)]:
            def corrupt(control, args, prepared, created):
                prepared[1]['mission'][field] = value
                return original(control, args, prepared, created)
            with patch('kuifje.commit_missions', side_effect=corrupt), self.assertRaises(ValueError):
                self.finish(leo, kuifje_missions=proposals)
            self.assertEqual(list(self.conn.iterdump()), before)
        # Fail after job and assignment exist, while appending ordered membership.
        self.conn.execute("CREATE TEMP TRIGGER inject_mapping BEFORE INSERT ON kuifje_assignment_missions WHEN NEW.position=2 BEGIN SELECT RAISE(ABORT,'injected'); END")
        self.conn.commit()
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.finish(leo, kuifje_missions=proposals)
        self.assertEqual(list(self.conn.iterdump()), before)
        self.conn.execute('DROP TRIGGER inject_mapping')
        self.conn.commit()
        self.finish(leo, kuifje_missions=proposals)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_assignment_missions').fetchone()[0], 3)

    def test_failed_and_uncertain_grouped_jobs_never_accept_result(self):
        from datetime import timedelta
        self.issue()
        k = self.start('k')
        auth = {key:k[key] for key in ('job_id','attempt_id','token')}
        control = JobControl(self.conn, lambda:self.now)
        result = dict(mission_results=[dict(mission_id=m['mission_id'], summary='x', limitations='x') for m in k['input']['missions']])
        for status in ('failed', 'uncertain'):
            with self.assertRaises(ValueError):
                control.scheduled('finish', dict(auth, status=status, output_refs=[], kuifje_result=result))
        control.scheduled('finish', dict(auth, status='uncertain', output_refs=[], error='Unknown effects'))
        control.execute('reconcile', dict(operation_id='recover',job_id=k['job_id'],attempt_id=k['attempt_id'],decision='retry',evidence_ref='operator:stopped'))
        new = self.start('retry')
        self.assertEqual(new['input'], k['input'])
        with self.assertRaises(ValueError):
            self.queue.add(dict(schema_version=1,date='2026-10-17',topic=2,content='source'), mission_id=k['input']['missions'][0]['mission_id'],fiche_id='a',claim=auth)
        new_auth = {key:new[key] for key in auth}
        control.scheduled('finish',dict(new_auth,status='failed',output_refs=[],error='Unavailable'))
        from kuifje import selected_results
        feedback = selected_results(self.conn,'dossier:reproduction',1,[[new['job_id'],new['attempt_id']]])
        self.assertEqual(len(feedback),3)
        self.assertTrue(all(r['status']=='failed' and r['result'] is None for r in feedback))


class MigrationTests(LeonardoFixture):
    def setUp(self):
        import database
        from unittest.mock import patch
        # Build a real schema-13 database, with actual legacy frozen assignments.
        with patch.object(database, 'SCHEMA_VERSION', 13):
            super().setUp()
            self.now = datetime.now(timezone.utc)
            self.enqueue()
            self.finish(self.start())
            self.legacy = [self.legacy_job(i) for i in (1,2)]

    def legacy_job(self, ordinal):
        from pathlib import Path
        from ariadne_tokens import measure
        from kuifje import digest
        from leonardo import canonical
        from jobs import JobStore
        producer = self.conn.execute('SELECT job_id FROM leonardo_states').fetchone()[0]
        mission = dict(schema_version=1,mission_id='kuifje:%s:%s'%(producer,ordinal),
                       producer_job_id=producer,dossier_id='dossier:reproduction',state_version=1,
                       topic=2,question='Legacy question?',rationale='Gap',scope='Primary reports',refs=['queue:1'])
        content=canonical(mission)
        metrics=measure(content)
        fixture=Path(__file__).parent/'fixtures'
        data=dict(schema_version=1,mission=mission,role_contract=(fixture/'kuifje-schema1-role.md').read_text(),
                  output_contract=(fixture/'kuifje-schema1-output.md').read_text(),tokenizer=metrics['tokenizer'])
        snapshot=canonical(data)
        audit=measure(snapshot)
        job=JobStore(self.conn,lambda:self.now).create('Kuifje',['sha256:'+digest(snapshot)],'sha256:'+digest(data['output_contract']))
        self.conn.execute('INSERT INTO kuifje_missions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (mission['mission_id'],producer,'dossier:reproduction',1,ordinal,content,digest(content),metrics['bytes'],metrics['tokens'],metrics['tokenizer'],self.now.isoformat()))
        self.conn.execute('INSERT INTO kuifje_assignments VALUES (?,?,?,?,?,?,?)',
            (job,mission['mission_id'],snapshot,digest(snapshot),audit['bytes'],audit['tokens'],audit['tokenizer']))
        self.conn.commit()
        if ordinal==1:
            # Terminal legacy output/effect before migration; second job stays ready.
            from jobs import JobStore
            claim=JobStore(self.conn,lambda:self.now).claim(job,'historical')
            result=canonical(dict(summary='Historical result',limitations='Historical limit'))
            a=measure(result)
            self.conn.execute('INSERT INTO ingress_queue(received_at,payload) VALUES (?,?)',(self.now.isoformat(),canonical(dict(schema_version=1,date='2026-10-17',topic=2,content='historical'))))
            queue=self.conn.execute('SELECT max(id) FROM ingress_queue').fetchone()[0]
            self.conn.execute('INSERT INTO kuifje_fiches VALUES (?,?,?,?,?)',(queue,job,claim['attempt_id'],'a','historical-payload-hash'))
            self.conn.execute('INSERT INTO kuifje_results VALUES (?,?,?,?,?,?)',(job,claim['attempt_id'],result,a['bytes'],a['tokens'],a['tokenizer']))
            self.conn.commit()
            JobStore(self.conn,lambda:self.now).finish(claim,'succeeded',['kuifje-result:'+mission['mission_id']])
        return job,mission,snapshot

    def test_schema13_retention_atomic_idempotent_and_legacy_execution(self):
        import database
        import sqlite3
        from unittest.mock import patch
        before={table:self.conn.execute('SELECT * FROM '+table).fetchall() for table in
                ('kuifje_assignments','kuifje_fiches','kuifje_results','jobs','job_attempts','job_operations','executor_activations','kuifje_missions')}
        dump=list(self.conn.iterdump())
        original=database.migration_sql
        with patch('database.migration_sql',side_effect=lambda v:original(v)+'CREATE TABLE jobs(conflict);'):
            with self.assertRaises(sqlite3.Error):
                database.migrate(self.conn)
        self.assertEqual(list(self.conn.iterdump()),dump)
        database.migrate(self.conn)
        after=list(self.conn.iterdump())
        database.migrate(self.conn)
        self.assertEqual(list(self.conn.iterdump()),after)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0],14)
        for table in before.keys()-{'kuifje_assignments','kuifje_fiches'}:
            self.assertEqual(self.conn.execute('SELECT * FROM '+table).fetchall(),before[table])
        self.assertEqual(self.conn.execute('SELECT * FROM kuifje_assignments').fetchall(),[(r[0],*r[2:]) for r in before['kuifje_assignments']])
        self.assertEqual(self.conn.execute('SELECT * FROM kuifje_assignment_missions').fetchall(),[(r[0],1,r[1]) for r in before['kuifje_assignments']])
        for row in before['kuifje_fiches']:
            mission=next(m['mission_id'] for job,m,_ in self.legacy if job==row[1])
            self.assertIn((*row[:3],mission,*row[3:]),self.conn.execute('SELECT * FROM kuifje_fiches').fetchall())
        claim=self.start('legacy:ready')
        job,mission,snapshot=self.legacy[1]
        self.assertEqual(claim['job_id'],job)
        self.assertEqual(claim['input'],json.loads(snapshot))
        self.assertNotIn('missions',claim['input'])
        self.assertEqual(claim['input']['mission'],mission)
        self.assertEqual(claim['result_ref'],'kuifje-result:'+mission['mission_id'])
        auth={k:claim[k] for k in ('job_id','attempt_id','token')}
        control=JobControl(self.conn,lambda:self.now)
        with self.assertRaises(ValueError):
            control.scheduled('finish',dict(auth,status='succeeded',output_refs=[claim['result_ref']],kuifje_result=dict(mission_results=[dict(mission_id=mission['mission_id'],summary='x',limitations='x')])))
        control.scheduled('finish',dict(auth,status='succeeded',output_refs=[claim['result_ref']],kuifje_result=dict(summary='Legacy harvest',limitations='No more sources')))
        from kuifje import selected_results,inspect_mission
        self.assertEqual(len(selected_results(self.conn,'dossier:reproduction',1,[[job,claim['attempt_id']]])),1)
        self.assertEqual(inspect_mission(self.conn,mission['mission_id'])['mission_count'],1)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_database_proves_fiche_membership_after_upgrade(self):
        import database
        import sqlite3
        database.migrate(self.conn)
        job1,mission1,_=self.legacy[0]
        job2,mission2,_=self.legacy[1]
        attempt=self.conn.execute('SELECT id FROM job_attempts WHERE job_id=?',(job1,)).fetchone()[0]
        self.conn.execute("INSERT INTO ingress_queue(received_at,payload) VALUES ('fixture','{}')")
        queue=self.conn.execute('SELECT max(id) FROM ingress_queue').fetchone()[0]
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute('INSERT INTO kuifje_fiches VALUES (?,?,?,?,?,?)',
                              (queue,job1,attempt,mission2['mission_id'],'wrong','hash'))
        self.conn.rollback()
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(),[])
