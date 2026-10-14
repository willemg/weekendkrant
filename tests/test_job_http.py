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


class JobHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
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
