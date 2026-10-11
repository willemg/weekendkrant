import http.client
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from ingress_api import Config, create_server
from ingress_queue import IngressQueue


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'queue.sqlite3'
        connect = sqlite3.connect
        def temporary_connect(path, *args, **kwargs):
            if path != ':memory:' and Path(path) != self.path:
                raise AssertionError('Test mag alleen eigen tijdelijke database openen')
            return connect(path, *args, **kwargs)
        guard = patch('sqlite3.connect', side_effect=temporary_connect)
        guard.start()
        self.addCleanup(guard.stop)
        self.token = secrets.token_urlsafe(24)
        self.server = create_server(Config(token=self.token, db_path=self.path, port=0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, token=None, headers=None):
        headers = dict(headers or {})
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        client = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            client.request(method, path, body, headers)
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def test_health_and_loopback(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        status, body = self.request('GET', '/health')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'status': 'ok', 'pending': 0})

    def test_ingest_persistent(self):
        status, body = self.request('POST', '/ingress', '{"summary":"test"}', self.token)
        self.assertEqual(status, 201)
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT payload,status FROM ingress_queue WHERE id=?', (body['id'],)).fetchone()
        self.assertEqual(row, ('{"summary": "test"}', 'pending'))
        self.assertEqual(IngressQueue(self.path).pending_count(), 1)

    def test_unauthorized(self):
        for token in (None, secrets.token_urlsafe(24), 'é'):
            with self.subTest(token=token):
                self.assertEqual(self.request('POST', '/ingress', '{}', token)[0], 401)
        self.assertEqual(IngressQueue(self.path).pending_count(), 0)

    def test_bad_json_and_non_objects(self):
        for body in ('{', '[]', '"text"', '1', 'null', 'true', '{"x":NaN}', b'\xff'):
            with self.subTest(body=body):
                self.assertEqual(self.request('POST', '/ingress', body, self.token)[0], 400)
        self.assertEqual(IngressQueue(self.path).pending_count(), 0)

    def test_no_queue_endpoint(self):
        self.assertEqual(self.request('GET', '/queue')[0], 404)

    def test_invalid_content_length(self):
        self.assertEqual(self.request('POST', '/ingress', '{}', self.token,
                                     {'Content-Length': '-1'})[0], 400)

    def test_sherlock_endpoints_require_ingress_bearer_token(self):
        for path in ('/sherlock/runs', '/sherlock/sources/filter',
                     '/sherlock/sources', '/sherlock/runs/finish'):
            with self.subTest(path=path):
                status, body = self.request('POST', path, '{}')
                self.assertEqual((status, body), (401, {'error': 'unauthorized'}))

    def test_sherlock_run_rotation_source_filter_registration_and_finish(self):
        created = []
        for topic in (1, 2, 3):
            status, body = self.request('POST', '/sherlock/runs', '{}', self.token)
            self.assertEqual(status, 201)
            self.assertEqual(body['topic'], topic)
            created.append(body['run_id'])
        status, body = self.request('POST', '/sherlock/runs', '{}', self.token)
        self.assertEqual((status, body['topic']), (201, 1))
        run_id = body['run_id']

        payload = {'run_id': run_id, 'topic': 1,
                   'url': 'https://Example.com/a?utm_source=x',
                   'title': None, 'outcome': 'afgewezen', 'rationale': 'Geen bewijs.'}
        status, body = self.request('POST', '/sherlock/sources', json.dumps(payload), self.token)
        self.assertEqual((status, body), (201, {'canonical_url': 'https://example.com/a'}))
        status, body = self.request('POST', '/sherlock/sources/filter', json.dumps({
            'urls': ['https://example.com/a?gclid=x', 'https://example.com/b?utm_source=x',
                     'https://example.com/b#fragment']}), self.token)
        self.assertEqual((status, body), (200, {
            'unreviewed': ['https://example.com/b?utm_source=x']}))
        status, body = self.request('POST', '/sherlock/runs/finish', json.dumps({
            'run_id': run_id, 'status': 'completed'}), self.token)
        self.assertEqual((status, body), (200, {'run_id': run_id, 'status': 'completed'}))

        duplicate_run, duplicate_meta = self.request('POST', '/sherlock/runs', '{}', self.token)
        self.assertEqual((duplicate_run, duplicate_meta['topic']), (201, 2))
        duplicate = dict(payload, run_id=duplicate_meta['run_id'], topic=2)
        status, body = self.request('POST', '/sherlock/sources', json.dumps(duplicate), self.token)
        self.assertEqual((status, body), (409, {'error': 'source_conflict'}))
        payload['url'] = 'https://example.com/b'
        status, body = self.request('POST', '/sherlock/sources', json.dumps(payload), self.token)
        self.assertEqual((status, body), (409, {'error': 'run_conflict'}))
        status, body = self.request('POST', '/sherlock/runs/finish', json.dumps({
            'run_id': run_id, 'status': 'failed'}), self.token)
        self.assertEqual(status, 409)

    def test_sherlock_rejects_bad_json_schema_and_topic_mismatch(self):
        for body in ('{', '[]', '{"urls":"bad"}'):
            status, _ = self.request('POST', '/sherlock/sources/filter', body, self.token)
            self.assertEqual(status, 400)
        self.assertEqual(self.request('POST', '/sherlock/sources/filter', '{"urls":[]}', self.token)[0], 200)
        status, started = self.request('POST', '/sherlock/runs', '{}', self.token)
        self.assertEqual(status, 201)
        wrong_topic = {'run_id': started['run_id'], 'topic': 2, 'url': 'https://example.com/a',
                       'outcome': 'afgewezen', 'rationale': 'Geen bewijs.'}
        status, body = self.request('POST', '/sherlock/sources', json.dumps(wrong_topic), self.token)
        self.assertEqual((status, body), (409, {'error': 'run_conflict'}))

    def test_sherlock_database_failure_returns_503(self):
        with patch('ingress_api.SherlockState.start_next_run', side_effect=sqlite3.OperationalError('down')):
            status, body = self.request('POST', '/sherlock/runs', '{}', self.token)
        self.assertEqual((status, body), (503, {'error': 'database_unavailable'}))


class ConfigTests(unittest.TestCase):
    def test_environment_and_overrides_without_opening_runtime_db(self):
        token = secrets.token_urlsafe(24)
        with patch.dict('os.environ', {'WEEKENDKRANT_INGRESS_TOKEN': token}, clear=True):
            config = Config.from_environment(['--host', '127.0.0.1', '--port', '9000', '--db', '/tmp/test.sqlite3'])
        self.assertEqual((config.token, config.port, config.db_path), (token, 9000, Path('/tmp/test.sqlite3')))
        self.assertNotIn(token, repr(config))

    def test_default_config_only_never_opens_database(self):
        with patch.dict('os.environ', {'WEEKENDKRANT_INGRESS_TOKEN': secrets.token_urlsafe(24)}, clear=True):
            config = Config.from_environment([])
        self.assertEqual(config.host, '127.0.0.1')
        self.assertEqual(config.db_path, Path('/home/weekendkrant/weekendkrant.sqlite3'))

    def test_missing_or_empty_token_fails_before_database(self):
        for env in ({}, {'WEEKENDKRANT_INGRESS_TOKEN': ''}):
            with patch.dict('os.environ', env, clear=True), self.assertRaises(ValueError):
                Config.from_environment([])
