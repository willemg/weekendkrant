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

    def test_attributed_fiche_preserves_consumer_payload_and_queue_identity(self):
        run_id = self.start_audit_run()
        payload = {'run_id': run_id, 'schema_version': 1, 'topic': 1,
                   'date': '2026-10-13', 'content': '# Bronfiche'}
        audit = self.audit_request('/ingress', payload, 'submit_weekendkrant_fiche',
                                   201, {'id': 1}, run_id)
        self.assertNotIn(payload['content'], audit)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT * FROM sherlock_fiches').fetchall(), [(1, run_id)])
            expected = {k: v for k, v in payload.items() if k != 'run_id'}
            self.assertEqual(json.loads(db.execute('SELECT payload FROM ingress_queue').fetchone()[0]), expected)

    def test_attributed_fiche_rejects_invalid_or_closed_run_and_topic_mismatch(self):
        run_id = self.start_audit_run()
        payload = {'run_id': run_id, 'schema_version': 1, 'topic': 1,
                   'date': '2026-10-13', 'content': '# Bronfiche'}
        for change, status in [({'run_id': None}, 400), ({'run_id': True}, 400),
                               ({'run_id': 999}, 409), ({'topic': 2}, 409)]:
            self.assertEqual(self.request('POST', '/ingress', json.dumps(dict(payload, **change)), self.token)[0], status)
        self.request('POST', '/sherlock/runs/finish', json.dumps({'run_id': run_id, 'status': 'completed'}), self.token)
        self.assertEqual(self.request('POST', '/ingress', json.dumps(payload), self.token)[0], 409)
        self.assertEqual(IngressQueue(self.path).pending_count(), 0)

    def test_ingress_rejects_ambiguous_duplicate_run_id(self):
        body = '{"run_id":1,"run_id":2,"schema_version":1,"topic":1,"date":"2026-10-13","content":"x"}'
        self.assertEqual(self.request('POST', '/ingress', body, self.token)[0], 400)

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

    def audit_request(self, path, payload, tool, status, body, run_id=None,
                      finished_run_id=None, token=None):
        with self.assertLogs('ingress_api', level='INFO') as logs:
            result = self.request('POST', path, json.dumps(payload),
                                  self.token if token is None else token)
        self.assertEqual(result, (status, body))
        received = 'weekendkrant_tool_call phase=received tool=' + tool
        finished = 'weekendkrant_tool_call phase=finished tool=' + tool
        if run_id is not None:
            received += ' run_id=' + str(run_id)
        if finished_run_id is None:
            finished_run_id = run_id
        if finished_run_id is not None:
            finished += ' run_id=' + str(finished_run_id)
        finished += ' http_status=' + str(status)
        self.assertEqual([record.getMessage() for record in logs.records],
                         [received, finished])
        self.assertTrue(all(record.created > 0 for record in logs.records))
        audit = '\n'.join(logs.output)
        self.assertNotIn(self.token, audit)
        return audit

    def start_audit_run(self):
        status, started = self.request('POST', '/sherlock/runs', '{}', self.token)
        self.assertEqual(status, 201)
        return started['run_id']

    def test_audit_start_logs_created_run_only_on_finished(self):
        self.audit_request('/sherlock/runs', {}, 'start_sherlock_run', 201,
                           {'run_id': 1, 'topic': 1}, finished_run_id=1)

    def test_audit_record_source_logs_metadata_without_content(self):
        run_id = self.start_audit_run()
        payload = {'run_id': run_id, 'topic': 1,
                   'url': 'https://example.com/private-audit-source',
                   'title': 'Geheime testtitel', 'outcome': 'afgewezen',
                   'rationale': 'Geheime testmotivatie'}
        audit = self.audit_request('/sherlock/sources', payload,
                                   'record_sherlock_source', 201,
                                   {'canonical_url': payload['url']}, run_id)
        for field in ('url', 'title', 'outcome', 'rationale'):
            self.assertNotIn(payload[field], audit)

    def test_audit_finish_logs_run_and_success_status(self):
        run_id = self.start_audit_run()
        for state, status in (('completed', 200), ('failed', 409)):
            with self.subTest(state=state):
                body = ({'run_id': run_id, 'status': state} if status == 200
                        else {'error': 'run_conflict'})
                self.audit_request('/sherlock/runs/finish',
                                   {'run_id': run_id, 'status': state},
                                   'finish_sherlock_run', status, body, run_id)

    def test_audit_filter_has_no_run_id_or_urls(self):
        url = 'https://example.com/private-filter-source'
        audit = self.audit_request('/sherlock/sources/filter', {'urls': [url]},
                                   'filter_sherlock_sources', 200, {'unreviewed': [url]})
        self.assertNotIn('run_id=', audit)
        self.assertNotIn(url, audit)

    def test_audit_ingress_has_no_run_id_or_payload(self):
        payload = {'summary': 'Vertrouwelijke fiche', 'token': 'fictief-geheim-token',
                   'url': 'https://example.com/private-fiche',
                   'rationale': 'Vertrouwelijke rationale'}
        audit = self.audit_request('/ingress', payload, 'submit_weekendkrant_fiche',
                                   201, {'id': 1})
        self.assertNotIn('run_id=', audit)
        for value in payload.values():
            self.assertNotIn(str(value), audit)

    def test_audit_database_failure_still_logs_received_and_finished(self):
        with patch('ingress_api.SherlockState.start_next_run',
                   side_effect=sqlite3.OperationalError('Geheime foutinhoud')):
            audit = self.audit_request('/sherlock/runs', {}, 'start_sherlock_run',
                                       503, {'error': 'database_unavailable'})
        self.assertNotIn('Geheime foutinhoud', audit)

    def test_audit_invalid_run_id_cannot_inject_payload_into_log(self):
        for run_id in ('secret\nphase=finished', True, {'secret': 'value'}):
            with self.subTest(run_id=run_id):
                self.audit_request('/sherlock/runs/finish',
                                   {'run_id': run_id, 'status': 'completed'},
                                   'finish_sherlock_run', 400, {'error': 'invalid_request'})

    def test_audit_unauthorized_request_does_not_log_bearer_value(self):
        token = 'fictieve-authorization-token'
        audit = self.audit_request('/ingress', {}, 'submit_weekendkrant_fiche',
                                   401, {'error': 'unauthorized'}, token=token)
        self.assertNotIn(token, audit)

    def test_audit_malformed_json_is_received_and_finished(self):
        with self.assertLogs('ingress_api', level='INFO') as logs:
            result = self.request('POST', '/ingress', '{', self.token)
        self.assertEqual(result, (400, {'error': 'invalid_json_object'}))
        self.assertEqual([r.getMessage() for r in logs.records], [
            'weekendkrant_tool_call phase=received tool=submit_weekendkrant_fiche',
            'weekendkrant_tool_call phase=finished tool=submit_weekendkrant_fiche http_status=400'])

    def test_audit_excludes_health_unknown_routes_and_other_methods(self):
        with patch('ingress_api.logging.getLogger') as logger:
            self.request('GET', '/health')
            self.request('GET', '/ingress')
            self.request('POST', '/unknown', '{}', self.token)
        logger.assert_not_called()


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

