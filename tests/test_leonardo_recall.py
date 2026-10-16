"""Historical reads are fenced by the immutable dossier assignment, not topic."""
from datetime import timedelta
import hashlib
import sqlite3
from unittest.mock import patch

import database
from job_control import ControlConflict, JobControl
from leonardo import LeonardoStore
from leonardo_operator import inspect_job
from part_format_v1 import token_count
from revision_storage import reconstruct
import test_leonardo


class RecallTests(test_leonardo.LeonardoFixture):
    # Reuse fixture helpers, without rediscovering the whole parent regression set.
    def request(self, claim, ref=None, recall_id='read:1'):
        return dict({k: claim[k] for k in ('job_id', 'attempt_id', 'token')},
                    ref=ref or 'part:%s:%s' % self.part, recall_id=recall_id)

    def recall(self, args):
        return self.store.recall(args)

    def test_historical_exact_reconstruction_retry_audit_and_finish(self):
        self.enqueue()
        self.finish(self.start())
        old = self.part
        self.add(content='nieuw spoor')
        self.run_day()
        self.part = self.conn.execute('SELECT id,active_revision FROM parts').fetchone()
        self.store.enqueue('next', 'dossier:reproduction', 1, [list(self.part)])
        claim = self.start('next')
        self.assertEqual(len(claim['input']['parts']), 1)
        before = {table: self.conn.execute('SELECT * FROM '+table).fetchall()
                  for table in ('jobs', 'job_attempts', 'leonardo_states', 'part_revisions',
                                'revision_sources', 'source_archive')}
        path = self.conn.execute('SELECT path FROM part_revisions WHERE part_id=? AND revision=?', old).fetchone()[0]
        from pathlib import Path
        Path(path).unlink(missing_ok=True)
        args = self.request(claim, 'part:%s:%s' % old)
        result = self.recall(args)
        data = reconstruct(self.conn, *old)
        self.assertEqual(result, dict(ref=args['ref'], content=data.decode(),
            sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), tokens=token_count(data.decode())))
        self.assertEqual(self.recall(args), result)
        self.recall(self.request(claim, recall_id='read:2'))  # New input is allowed too.
        for table, rows in before.items():
            self.assertEqual(self.conn.execute('SELECT * FROM '+table).fetchall(), rows)
        # inspect normally expects sealed offers; use compact metrics directly.
        usage = inspect_job(self.conn, claim['job_id'], compact=True)['context_usage']
        self.assertEqual(usage['attempts'][0]['recall_count'], 2)
        self.assertEqual([r['ref'] for r in usage['attempts'][0]['recalls']],
                         [args['ref'], 'part:%s:%s' % self.part])
        self.assertEqual(usage['attempts'][0]['recall_tokens'], sum(r['tokens'] for r in usage['attempts'][0]['recalls']))
        self.assertIsNone(usage['attempts'][0]['provider_usage'])
        row = self.conn.execute('SELECT dossier_id,job_id,attempt_id,ref,bytes,tokens FROM leonardo_recalls ORDER BY id LIMIT 1').fetchone()
        self.assertEqual(row, ('dossier:reproduction', claim['job_id'], claim['attempt_id'], args['ref'], result['bytes'], result['tokens']))
        with self.assertRaises(ValueError):
            self.recall(dict(args, ref='part:%s:%s' % self.part))
        state = self.state(2)
        state['processed_refs'].insert(0, args['ref'])
        self.finish(claim, state, 'finish:2')
        usage = inspect_job(self.conn, claim['job_id'], compact=True)['context_usage']
        self.assertEqual(usage['attempts'][0]['state_tokens'], self.conn.execute('SELECT tokens FROM leonardo_states WHERE job_id=?', (claim['job_id'],)).fetchone()[0])
        with self.assertRaises(ControlConflict):
            self.recall(args)  # Even receipt retries require current authority.

    def test_ref_authorization_and_invalid_claims(self):
        self.add(topic=1)
        self.add(content='not yet processed')
        self.run_day()
        other_topic = self.conn.execute('SELECT id,active_revision FROM parts WHERE topic=1').fetchone()
        unprocessed = self.conn.execute('SELECT id,active_revision FROM parts WHERE topic=2').fetchone()
        # Our original older revision is all this dossier is authorized to read.
        self.enqueue()
        claim = self.start()
        self.store.create_dossier('other', 2)
        LeonardoStore(self.conn, lambda: self.now).enqueue('other', 'other', 0, [list(unprocessed)])
        for ref in ['part:%s:%s' % other_topic, 'part:%s:%s' % unprocessed,
                    'part:999:1', 'part:01:1', 'nonsense']:
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.recall(self.request(claim, ref))
        for change in [dict(token='wrong'), dict(attempt_id=999), dict(job_id=999)]:
            with self.assertRaises(ControlConflict):
                self.recall(dict(self.request(claim), **change))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leonardo_recalls').fetchone()[0], 0)

    def test_expiry_during_reconstruction_and_recovery_fences_read(self):
        self.enqueue()
        claim = self.start()
        def slow(*args):
            data = reconstruct(*args)
            self.now += timedelta(hours=2)
            return data
        with patch('leonardo.reconstruct', side_effect=slow), self.assertRaises(ControlConflict):
            self.recall(self.request(claim))
        self.assertEqual(self.conn.execute('SELECT status FROM jobs').fetchone()[0], 'running')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leonardo_recalls').fetchone()[0], 0)
        control = JobControl(self.conn, lambda: self.now)
        control.validate({k: claim[k] for k in ('job_id','attempt_id','token')})
        control.execute('reconcile', dict(operation_id='recover', job_id=claim['job_id'],
            attempt_id=claim['attempt_id'], decision='retry', evidence_ref='operator:stopped'))
        new = self.start('retry')
        self.recall(self.request(new))
        usage = inspect_job(self.conn, claim['job_id'], compact=True)['context_usage']['attempts']
        self.assertEqual([a['status'] for a in usage], ['expired', 'running'])
        self.assertEqual([a['recall_count'] for a in usage], [0, 1])
        self.assertTrue(all(a['provider_usage'] is None for a in usage))
        with self.assertRaises(ControlConflict):
            self.recall(self.request(claim))

    def test_http_recall_and_refusal_audit(self):
        self.enqueue()
        claim = self.start()
        post = self.http_post()
        with patch('ingress_api.LeonardoStore', side_effect=lambda db: LeonardoStore(db, lambda: self.now)):
            with self.assertLogs('ingress_api', level='INFO') as logs:
                self.assertEqual(post('/jobs/leonardo-recall', self.request(claim))[0], 200)
                self.assertEqual(post('/jobs/leonardo-recall', self.request(claim, 'part:999:1'))[0], 409)
            self.assertTrue(any('http_status=409' in s for s in logs.output))
            self.assertNotIn(claim['token'], str(logs.output))
            self.assertTrue(any('job_id=%s attempt_id=%s ref=part:999:1' % (claim['job_id'], claim['attempt_id']) in s for s in logs.output))

    def test_real_input_over_35k_and_technical_bounds(self):
        # Distinct genuine revisions, each below the existing 30K part ceiling.
        self.add(content='onderzoek met onafhankelijke bronnen. ' * 2400)
        self.run_day()
        first = self.conn.execute('SELECT id,active_revision FROM parts ORDER BY id DESC').fetchone()
        self.add(content='nieuwe resultaten. ' * 2300)
        self.run_day()
        second = self.conn.execute('SELECT id,active_revision FROM parts ORDER BY id DESC').fetchone()
        job = self.store.enqueue('large', 'dossier:reproduction', 0, [list(first), list(second)])
        self.assertGreater(self.conn.execute('SELECT tokens FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()[0], 35000)
        self.store.create_dossier('bounds', 2)
        from leonardo import MAX_CONTEXT_TOKENS, encoded_state
        with patch('leonardo.token_count', return_value=MAX_CONTEXT_TOKENS+1), self.assertRaisesRegex(ValueError, 'technical'):
            self.store.enqueue('excess', 'bounds', 0, [list(self.part)])
        with patch('leonardo.MAX_CONTEXT_BYTES', 10), self.assertRaisesRegex(ValueError, 'technical'):
            self.store.enqueue('bytes', 'bounds', 0, [list(self.part)])
        with patch('leonardo.token_count', return_value=4001), self.assertRaisesRegex(ValueError, 'State token'):
            encoded_state(self.state())
        claim = self.start()
        with patch('leonardo.MAX_CONTEXT_TOKENS', 1), self.assertRaisesRegex(ValueError, 'technical'):
            self.recall(self.request(claim, 'part:%s:%s' % first))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leonardo_recalls').fetchone()[0], 0)

    def test_cumulative_limits_retries_and_audit_immutability(self):
        self.enqueue()
        claim = self.start()
        args = self.request(claim)
        first = self.recall(args)
        snapshot, tokens = self.conn.execute('SELECT snapshot,tokens FROM leonardo_assignments').fetchone()
        with patch('leonardo.MAX_CONTEXT_TOKENS', tokens + first['tokens']):
            self.assertEqual(self.recall(args), first)  # Lost-answer retry still fits.
            with self.assertRaisesRegex(ControlConflict, 'technical'):
                self.recall(dict(args, recall_id='again'))
        with patch('leonardo.MAX_CONTEXT_BYTES', len(snapshot.encode()) + first['bytes']):
            with self.assertRaisesRegex(ControlConflict, 'technical'):
                self.recall(dict(args, recall_id='again'))
        self.recall(dict(args, recall_id='again'))  # Intentional rereading counts twice.
        from leonardo_operator import context_usage
        attempt = context_usage(self.conn, claim['job_id'])['attempts'][0]
        self.assertEqual(attempt['recall_count'], 2)
        self.assertEqual(attempt['recall_tokens'], 2 * first['tokens'])
        for sql in ['UPDATE leonardo_recalls SET rowid=rowid', 'DELETE FROM leonardo_recalls',
                    'INSERT OR REPLACE INTO leonardo_recalls SELECT * FROM leonardo_recalls']:
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(sql)
            self.conn.rollback()

    def test_parallel_exact_read_retries_have_one_logical_delivery(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.enqueue()
        claim = self.start()
        args = self.request(claim)
        ready = Barrier(2)
        def read():
            with sqlite3.connect(self.db) as db:
                store = LeonardoStore(db, lambda: self.now)
                ready.wait(timeout=5)
                return store.recall(args)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(read) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leonardo_recalls').fetchone()[0], 1)

    def test_non_leonardo_claim_cannot_read_dossier(self):
        from jobs import JobStore
        jobs = JobStore(self.conn, lambda: self.now)
        job = jobs.create('Sherlock', ['source:fixture'], 'output:fixture')
        claim = jobs.claim(job, 'other-worker')
        with self.assertRaises(ControlConflict):
            self.recall(self.request(claim))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM leonardo_recalls').fetchone()[0], 0)

    def test_schema_11_migration_preserves_immutable_data_and_rollback(self):
        self.enqueue()
        self.finish(self.start())
        self.store.enqueue('second', 'dossier:reproduction', 1, [list(self.part)])
        self.finish(self.start('second'), self.state(2), 'finish:second')
        # Construct a populated actual schema-11 database from its canonical DDL.
        with sqlite3.connect(':memory:') as old:
            with patch.object(database, 'SCHEMA_VERSION', 11):
                database.migrate(old)
            old.execute('PRAGMA foreign_keys=OFF')
            for table in ['jobs','job_attempts','leonardo_dossiers','parts','part_revisions',
                          'leonardo_assignments','leonardo_assignment_parts','leonardo_states']:
                for row in self.conn.execute('SELECT * FROM '+table):
                    old.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in row)+')', row)
            old.commit()
            before = list(old.iterdump())
            original = database.migration_sql
            with patch('database.migration_sql', side_effect=lambda v: original(v)+'CREATE TABLE jobs(conflict);'):
                with self.assertRaises(sqlite3.Error):
                    database.migrate(old)
            self.assertEqual(list(old.iterdump()), before)
            database.migrate(old)
            self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0], 12)
            self.assertEqual(old.execute('PRAGMA foreign_key_check').fetchall(), [])
            for table in ['leonardo_assignments','leonardo_assignment_parts','leonardo_states']:
                self.assertEqual(old.execute('SELECT * FROM '+table).fetchall(), self.conn.execute('SELECT * FROM '+table).fetchall())
                for sql in ['UPDATE '+table+' SET rowid=rowid', 'DELETE FROM '+table,
                            'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table]:
                    with self.assertRaises(sqlite3.IntegrityError):
                        old.execute(sql)
                    old.rollback()
