"""Real HTTP control routes against isolated persistent SQLite."""
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from ingress_api import Config, create_server
from jobs import JobStore
from dispatcher import Dispatcher
from datetime import datetime, timezone
from unittest.mock import patch


class JobHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        now = datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
        patcher = patch("ingress_api.Dispatcher", side_effect=lambda db: Dispatcher(db, lambda: now))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = create_server(Config(token='worker-secret', recovery_token='operator-secret',
                                           db_path=self.path, port=0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        with sqlite3.connect(self.path) as db:
            self.job = JobStore(db).create('test', ['input:v1'], 'contract:v1')

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, route, args, token='worker-secret'):
        client = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            client.request('POST', route, json.dumps(args), {'Authorization': 'Bearer ' + token})
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def test_claim_validate_finish_and_lost_response_retry(self):
        args = dict(job_id=self.job, operation_id='claim:1', activation_id='activation:1')
        code, claim = self.post('/jobs/claim', args)
        self.assertEqual(code, 200)
        self.assertEqual(self.post('/jobs/claim', args), (code, claim))
        authority = {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}
        self.assertTrue(self.post('/jobs/validate', authority)[1]['valid'])
        finish = dict(authority, operation_id='finish:1', status='succeeded', output_refs=['result:v1'])
        self.assertEqual(self.post('/jobs/finish', finish)[0], 200)
        self.assertEqual(self.post('/jobs/finish', finish)[0], 200)
        self.assertFalse(self.post('/jobs/validate', authority)[1]['valid'])
        self.assertEqual(self.post('/jobs/finish', dict(finish, output_refs=[]))[0], 409)
        self.assertEqual(self.post('/jobs/claim', dict(args, extra=True))[0], 400)
        self.assertEqual(self.post('/jobs/claim', args, 'wrong')[0], 401)

    def test_recovery_is_separate_operator_capability(self):
        _, claim = self.post('/jobs/claim', dict(job_id=self.job, operation_id='claim:1', activation_id='a'))
        authority = {k: claim[k] for k in ('job_id', 'attempt_id', 'token')}
        self.assertEqual(self.post('/jobs/abandon', dict(authority, operation_id='abandon:1', error='unknown'))[0], 200)
        recovery = dict(job_id=self.job, attempt_id=claim['attempt_id'], operation_id='recover:1',
                        decision='retry', evidence_ref='audit:verified-stop-safe-effects')
        self.assertEqual(self.post('/jobs/reconcile', recovery)[0], 401)
        self.assertEqual(self.post('/jobs/reconcile', recovery, 'operator-secret')[0], 200)
        self.assertEqual(self.post('/jobs/reconcile', recovery, 'operator-secret')[0], 200)
        self.assertEqual(self.post('/jobs/finish', dict(authority, operation_id='late', status='succeeded', output_refs=[]))[0], 409)

    def test_recovery_secret_defaults_closed_and_must_be_distinct(self):
        with self.assertRaises(ValueError):
            Config(token='same', recovery_token='same')
        self.assertEqual(Config(token='worker').recovery_token, '')

    def test_executor_start_and_fenced_source_fiche_finish_contract(self):
        args = {}
        for route in ('/executor/start','/executor/sherlock/start'):
            for invalid in ({'operation_id':'old','activation_id':'old'}, {'timestamp':'now'}, {'timezone':'UTC'}):
                self.assertEqual(self.post(route,invalid)[0],400)
        self.assertEqual(self.post('/executor/job', {'executor_id':'unknown'})[0],409)
        self.assertEqual(self.post('/executor/sherlock/start', args, 'wrong')[0], 401)
        self.assertEqual(self.post('/executor/sherlock/start', dict(args, topic=2))[0], 400)
        code, answer = self.post('/executor/sherlock/start', args)
        self.assertEqual(code, 200)
        self.assertEqual(self.post('/executor/sherlock/start', args), (code, answer))
        self.assertEqual(self.post('/executor/sherlock/start', dict(args, operation_id='changed'))[0], 400)
        self.assertEqual(set(answer), {'executor_id'})
        self.assertIsNotNone(answer['executor_id'])
        with self.assertLogs('ingress_api',level='INFO') as audit:
            code, answer = self.post('/executor/job', answer)
        self.assertNotIn(answer['claim']['token'], '\n'.join(audit.output))
        self.assertEqual(code, 200)
        answer.update(answer['claim'])
        authority = {k: answer[k] for k in ('job_id', 'attempt_id', 'token')}
        source = dict(run_id=answer['run_id'], topic=answer['input']['topic'],
            url='https://example.org/phase5', outcome='reviewed', rationale='fixture', claim=authority)
        self.assertEqual(self.post('/sherlock/sources', dict(source, claim=dict(authority, token='forged')))[0], 400)
        self.assertEqual(self.post('/sherlock/sources', source)[0], 201)
        fiche = dict(run_id=answer['run_id'], schema_version=1, topic=answer['input']['topic'],
                     date=answer['input']['date'], content='isolated fixture')
        self.assertEqual(self.post('/ingress', fiche)[0], 409)
        self.assertEqual(self.post('/ingress', dict(fiche, claim=authority))[0], 201)
        finish = dict(authority, status='succeeded', output_refs=[answer['result_ref']])
        self.assertEqual(self.post('/jobs/finish', finish)[0], 200)
        self.assertEqual(self.post('/jobs/finish', finish)[0], 200)
        self.assertEqual(self.post('/ingress', dict(fiche, claim=authority))[0], 409)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sherlock_job_runs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT status FROM sherlock_runs').fetchone()[0], 'completed')
