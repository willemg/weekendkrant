"""Actual JS bridge -> HTTP backend -> SQLite, with lost committed answers.

Only discovery/destination mapping is injected; actual payloads, bearer headers,
HTTP handler, lifecycle, migrations and persistent receipts run unchanged.
"""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest

from ingress_api import Config, create_server
from jobs import JobStore


class GenericSystemTests(unittest.TestCase):
    def test_bridge_to_persistent_control_with_lost_claim_and_finish_responses(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node.js >=18.3.0 is required for the generic system gate')
        root = Path(__file__).resolve().parents[1]
        preflight = subprocess.run([node, str(root /
            'plugin/weekendkrant_ingress/scripts/check-runtime.mjs')],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(preflight.returncode, 0, 'Node runtime preflight: ' + preflight.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'system.sqlite3'
            server = create_server(Config(token='fictional-system-token', db_path=path, port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sqlite3.connect(path) as db:
                    store = JobStore(db)
                    job = store.create('system-fixture', ['input:immutable:1'], 'contract:immutable:1')
                    other = store.create('system-fixture', [], 'contract:immutable:1')
                script = '''
import assert from 'node:assert/strict';
import {callTool,DISCOVERY} from './plugin/weekendkrant_ingress/worker/index.js';
const env={WEEKENDKRANT_INGRESS_TOKEN:'fictional-system-token'};
let lose=true;
const bridge=async(url,options)=>{
 if(url===DISCOVERY)return Response.json({url:'https://fixture.trycloudflare.com/ingress'});
 const response=await fetch(process.argv[1]+new URL(url).pathname,options);
 if(lose){lose=false;await response.text();throw Error('lost committed answer');}
 return response;
};
const job_id=Number(process.argv[2]);
const args={job_id,activation_id:'system:activation',operation_id:'system:claim'};
assert.equal((await callTool('claim_weekendkrant_job',args,env,bridge)).code,'backend_unreachable');
const claim=await callTool('claim_weekendkrant_job',args,env,bridge);
assert.equal(claim.status,'success');
assert.deepEqual(claim.input_refs,['input:immutable:1']);
const authority={job_id,attempt_id:claim.attempt_id,token:claim.token};
assert.equal((await callTool('validate_weekendkrant_claim',authority,env,bridge)).valid,true);
const finish={...authority,operation_id:'system:finish',status:'succeeded',output_refs:['result:immutable:1']};
lose=true;
assert.equal((await callTool('finish_weekendkrant_job',finish,env,bridge)).code,'backend_unreachable');
assert.equal((await callTool('finish_weekendkrant_job',finish,env,bridge)).job_status,'succeeded');
assert.equal((await callTool('validate_weekendkrant_claim',authority,env,bridge)).valid,false);
assert.equal((await callTool('claim_weekendkrant_job',{...args,operation_id:'system:second',job_id:Number(process.argv[3])},env,bridge)).code,'conflict');
console.log(JSON.stringify({job_id,attempt_id:claim.attempt_id}));
'''
                result = subprocess.run([node, '--input-type=module', '-e', script,
                    'http://%s:%s' % server.server_address, str(job), str(other)],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                identity = json.loads(result.stdout)
                with sqlite3.connect(path) as db:
                    store = JobStore(db)
                    self.assertEqual(store.get(job)['status'], 'succeeded')
                    self.assertEqual(store.get(job)['output_refs'], ['result:immutable:1'])
                    attempts = store.attempts(job)
                    self.assertEqual(len(attempts), 1)
                    self.assertEqual(attempts[0]['id'], identity['attempt_id'])
                    self.assertEqual(store.attempts(other), [])
                    self.assertEqual(db.execute('SELECT count(*) FROM job_operations').fetchone()[0], 2)
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
