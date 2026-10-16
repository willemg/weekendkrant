"""Offline process-level gate; run with unittest discover -p test_system_e2e.py."""
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
ENCODING_URL = 'https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken'
CACHE_KEY = hashlib.sha1(ENCODING_URL.encode()).hexdigest()
ENCODING_SHA = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'


def copy_encoding_cache(source, target):
    """Fail offline, before tiktoken can try a download; never modify source cache."""
    path = source / CACHE_KEY
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != ENCODING_SHA:
        raise AssertionError('tokenizer preflight: cl100k_base cache ontbreekt/is corrupt; '
                             'zie docs/daily-runtime.md#systeemtest-en-operationele-gate')
    target.mkdir()
    (target / CACHE_KEY).write_bytes(path.read_bytes())


class OfflineCacheTests(unittest.TestCase):
    def test_missing_or_corrupt_cache_fails_without_creating_target(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for value in (None, b'corrupt'):
                if value is not None:
                    (root / CACHE_KEY).write_bytes(value)
                with self.assertRaisesRegex(AssertionError, 'tokenizer preflight'):
                    copy_encoding_cache(root, root / 'copy')
                self.assertFalse((root / 'copy').exists())


class SystemE2ETests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='weekendkrant-system-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.db = self.base / 'queue.sqlite3'
        self.output = self.base / 'draden'
        self.log = self.base / 'ariadne.log'
        cache = Path(os.environ.get('TIKTOKEN_CACHE_DIR', os.environ.get(
            'DATA_GYM_CACHE_DIR', str(Path(tempfile.gettempdir()) / 'data-gym-cache'))))
        copy_encoding_cache(cache, self.base / 'cache')
        # Only the test child environment loads this guard. Real entrypoints and
        # tokenizer run unchanged; an unexpected external connection fails closed.
        guard = self.base / 'guard'
        guard.mkdir()
        (guard / 'sitecustomize.py').write_text('''import sys

def offline(event, args):
    if event == 'socket.connect':
        address = args[1]
        if not isinstance(address, tuple) or address[0] != '127.0.0.1':
            raise RuntimeError('systemtest forbids external network: %r' % (address,))
sys.addaudithook(offline)
''', encoding='utf-8')
        with (guard / 'sitecustomize.py').open('a') as setup:
            setup.write("\nimport datetime\nsys.path.insert(0, " + repr(str(REPO)) +
                        ")\nimport executor_slot\nexecutor_slot.SLOT_TOLERANCE = datetime.timedelta(minutes=30)\n")
        self.env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(self.base),
                    'LANG': 'C.UTF-8', 'PYTHONPATH': str(guard),
                    'TIKTOKEN_CACHE_DIR': str(self.base / 'cache'),
                    'WEEKENDKRANT_INGRESS_TOKEN': 'synthetic-system-test-token'}
        self.server_log = self.base / 'ingress.log'
        stream = self.server_log.open('w')
        self.addCleanup(stream.close)
        self.server = subprocess.Popen(
            [sys.executable, str(REPO / 'ingress_api.py'), '--host', '127.0.0.1',
             '--port', '0', '--db', str(self.db)], cwd=self.base, env=self.env,
            stdout=stream, stderr=stream)
        self.addCleanup(self.stop_server)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            diagnostic = self.server_log.read_text()
            match = re.search(r'ingress_ready host=127\.0\.0\.1 port=(\d+)', diagnostic)
            if match:
                self.port = int(match[1])
                status, body = self.request('GET', '/health')
                self.assertEqual((status, body), (200, {'status': 'ok', 'pending': 0}),
                                 'ingest ready-state')
                return
            if self.server.poll() is not None:
                break
            Event().wait(0.02)  # Poll explicit ready-state, never guess startup time.
        self.fail('ingest startup/ready-state failed:\n' + self.server_log.read_text())

    def stop_server(self):
        if self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)

    def request(self, method, path, payload=None):
        with closing(http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)) as client:
            body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
            client.request(method, path, body=body, headers={
                'Authorization': 'Bearer ' + self.env['WEEKENDKRANT_INGRESS_TOKEN'],
                'Content-Type': 'application/json'})
            response = client.getresponse()
            return response.status, json.loads(response.read())

    def rows(self, sql):
        with closing(sqlite3.connect('file:' + str(self.db) + '?mode=ro', uri=True)) as db:
            return db.execute(sql).fetchall()

    def daily(self, threads):
        command = [sys.executable, str(REPO / 'ariadne.py'), 'daily', '--repo', str(REPO),
                   '--db', str(self.db), '--output', str(self.output),
                   '--lock', str(self.base / 'ariadne.lock'), '--log', str(self.log)]
        try:
            result = subprocess.run(command, cwd=self.base, env=self.env,
                                    capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired as error:
            self.fail('materialisatie timeout: %s\n%s' % (error, self.diagnostics()))
        self.assertEqual(result.returncode, 0, 'materialisatie CLI: ' + result.stderr + self.diagnostics())
        report = json.loads(result.stdout)
        self.assertEqual((report['status'], report['threads']), ('success', threads),
                         'materialisatie resultaat: ' + result.stdout + self.diagnostics())

    def diagnostics(self):
        return '\n'.join(p.read_text() for p in (self.server_log, self.log) if p.exists())

    def snapshot(self):
        tables = [row[0] for row in self.rows(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: self.rows('SELECT * FROM "' + name + '" ORDER BY rowid') for name in tables}

    def test_http_queue_materialization_and_confirmed_replay(self):
        status, run = self.request('POST', '/sherlock/runs', {})
        self.assertEqual(status, 201, 'ingest Sherlock run: ' + str(run))
        content = '# Synthetische bronfiche\n\nBron: https://example.invalid/system-gate\n'
        content += 'Résumé: één coöperatie toetst besluitvorming.\nClaim en onzekerheid blijven gescheiden.\n'
        fiche = dict(schema_version=1, topic=run['topic'], date='2026-10-05', content=content)
        status, receipt = self.request('POST', '/ingress', dict(fiche, run_id=run['run_id']))
        self.assertEqual(status, 201, 'ingest fiche: ' + str(receipt))
        identity = receipt['id']
        rows = self.rows('SELECT id,payload,status FROM ingress_queue')
        self.assertEqual(len(rows), 1, 'queue: exactly one persisted item')
        self.assertEqual((rows[0][0], json.loads(rows[0][1]), rows[0][2]),
                         (identity, fiche, 'pending'), 'queue: exact consumer payload, metadata stripped')
        self.assertEqual(self.rows('SELECT queue_item_id,run_id FROM sherlock_fiches'),
                         [(identity, run['run_id'])], 'queue: Sherlock provenance')
        self.stop_server()  # Prove persistence independently of the producer process.
        self.daily(1)
        data = content.encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        artifact = self.output / '2026_W41' / f"topic_{run['topic']}" / 'part_0001' / 'rev_0001.txt'
        self.assertEqual(list(self.output.rglob('*.txt')), [artifact], 'artifact: week/topic/part/revision')
        text = artifact.read_bytes()
        self.assertTrue(text.startswith(b'WEEKENDKRANT-PART-1'), 'artifact: format')
        self.assertEqual(text.count(data), 1, 'artifact: exact source bytes once')
        self.assertEqual(text.count(f'--- SOURCE queue:{identity} date='.encode()), 1, 'artifact: source identity once')
        self.assertEqual(self.rows('SELECT id,status FROM ingress_queue'), [(identity, 'processed')], 'queue: processed')
        self.assertEqual(self.rows('SELECT queue_id,schema_version,date,topic,content,sha256 FROM source_archive'),
                         [(identity, 1, fiche['date'], fiche['topic'], data, digest)], 'provenance: source archive')
        part = self.rows('SELECT id,week,topic,part,is_open,active_revision FROM parts')
        self.assertEqual(len(part), 1, 'provenance: single part')
        part_id = part[0][0]
        self.assertEqual(part[0][1:], ('2026_W41', fiche['topic'], 1, 1, 1), 'provenance: active revision')
        self.assertEqual(self.rows('SELECT part_id,revision,path,sha256 FROM part_revisions'),
                         [(part_id, 1, str(artifact), hashlib.sha256(text).hexdigest())], 'provenance: revision hash/path')
        self.assertEqual(self.rows('SELECT part_id,revision,position,queue_id FROM revision_sources'),
                         [(part_id, 1, 0, identity)], 'provenance: membership')
        materializations = self.rows('SELECT queue_id,materialized_at FROM source_materializations')
        self.assertEqual(len(materializations), 1, 'provenance: single materialization')
        self.assertEqual(materializations[0][0], identity, 'provenance: materialization')
        self.assertTrue(materializations[0][1], 'provenance: registration time')
        metrics = self.rows('SELECT tokens,tokenizer,reserved_tokens FROM part_revisions')
        self.assertEqual(metrics[0][1:], ('cl100k_base', 5000), 'artifact: tokenizer/reserve')
        self.assertTrue(0 < metrics[0][0] <= 30000, 'artifact: token budget')
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [], 'provenance: foreign keys')
        before = self.snapshot()
        files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.rglob('*') if p.is_file()}
        for _ in range(2):
            self.daily(0)
            self.assertEqual(self.snapshot(), before, 'replay: persistent state unchanged')
            self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns)
                              for p in self.output.rglob('*') if p.is_file()}, files,
                             'replay: immutable artifacts unchanged')

    def test_generic_sherlock_job_to_materialized_source(self):
        args = {}
        code, start = self.request('POST', '/executor/sherlock/start', args)
        self.assertEqual(code, 200, str(start))
        self.assertEqual(self.request('POST', '/executor/sherlock/start', args), (code, start))
        bootstrap = start
        code, start = self.request('POST', '/executor/job', bootstrap)
        self.assertEqual(code, 200)
        self.assertEqual(self.request('POST', '/executor/job', bootstrap), (200, start))
        claim = {k: start['claim'][k] for k in ('job_id', 'attempt_id', 'token')}
        self.assertTrue(self.request('POST', '/jobs/validate', claim)[1]['valid'])
        source = dict(run_id=start['run_id'], topic=start['input']['topic'],
            url='https://example.invalid/generic-system-gate', outcome='fixture',
            rationale='synthetic isolated system source', claim=claim)
        self.assertEqual(self.request('POST', '/sherlock/sources', source)[0], 201)
        fiche = dict(schema_version=1, topic=start['input']['topic'], date='2026-10-05',
            content='# Generic system source\n\nhttps://example.invalid/generic-system-gate\n')
        code, receipt = self.request('POST', '/ingress', dict(fiche, run_id=start['run_id'], claim=claim))
        self.assertEqual(code, 201)
        finish = dict(claim, status='succeeded', output_refs=[start['result_ref']])
        answer = self.request('POST', '/jobs/finish', finish)
        self.assertEqual(answer[0], 200)
        self.assertEqual(self.request('POST', '/jobs/finish', finish), answer)
        self.assertEqual(self.request('POST', '/executor/sherlock/start', args), (200, bootstrap))
        self.assertFalse(self.request('POST', '/jobs/validate', claim)[1]['valid'])
        self.assertEqual(self.request('POST', '/ingress', dict(fiche, run_id=start['run_id'], claim=claim))[0], 409)
        self.assertEqual(self.rows('''SELECT s.run_id,r.job_id,r.attempt_id,f.queue_item_id
            FROM sherlock_sources s JOIN sherlock_job_runs r USING(run_id)
            JOIN sherlock_fiches f USING(run_id)'''),
            [(start['run_id'], claim['job_id'], claim['attempt_id'], receipt['id'])])
        self.assertEqual(json.loads(self.rows('SELECT payload FROM ingress_queue')[0][0]), fiche)
        self.assertEqual(self.rows('SELECT status FROM sherlock_runs'), [('completed',)])
        self.assertEqual(self.rows('SELECT status FROM jobs'), [('succeeded',)])
        self.stop_server()
        self.daily(1)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('processed',)])
        self.assertEqual(self.rows('SELECT queue_id FROM source_archive'), [(receipt['id'],)])
        self.assertEqual(self.rows('SELECT queue_id FROM revision_sources'), [(receipt['id'],)])
        before = self.snapshot()
        self.daily(0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])
