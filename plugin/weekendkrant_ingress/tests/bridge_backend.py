"""Optional plugin-development integration test; never part of bibib discovery.

Actual JS bridge -> HTTP backend -> SQLite, with lost committed answers.

Only discovery/destination mapping is injected; actual payloads, bearer headers,
HTTP handler, lifecycle, migrations and persistent receipts run unchanged.
"""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from ingress_api import Config, create_server
from jobs import JobStore


class GenericSystemTests(unittest.TestCase):
    def test_bridge_control_and_sherlock_executor_with_lost_committed_answers(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node.js >=18.3.0 is required for the plugin-development integration test')
        root = REPO
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
const startArgs={operation_id:'start:phase5',activation_id:'system:phase5'};
lose=true;
assert.equal((await callTool('start_weekendkrant_executor',startArgs,env,bridge)).code,'backend_unreachable');
const scout=await callTool('start_weekendkrant_executor',startArgs,env,bridge);
assert.equal(scout.status,'success');assert.equal(scout.role,'Sherlock');
const scoutClaim={job_id:scout.job_id,attempt_id:scout.attempt_id,token:scout.token};
assert.equal((await callTool('validate_weekendkrant_claim',scoutClaim,env,bridge)).valid,true);
assert.equal((await callTool('record_sherlock_source',{run_id:scout.run_id,topic:scout.input.topic,
 url:'https://example.invalid/bridge-phase5',outcome:'fixture',rationale:'isolated system source',claim:scoutClaim},env,bridge)).status,'success');
const fiche=await callTool('submit_weekendkrant_fiche',{run_id:scout.run_id,topic:scout.input.topic,
 schema_version:1,date:scout.input.date,content:'isolated bridge fixture',claim:scoutClaim},env,bridge);
assert.equal(fiche.status,'success');
const scoutFinish={...scoutClaim,operation_id:'finish:phase5',status:'succeeded',output_refs:[scout.result_ref]};
lose=true;
assert.equal((await callTool('finish_weekendkrant_job',scoutFinish,env,bridge)).code,'backend_unreachable');
assert.equal((await callTool('finish_weekendkrant_job',scoutFinish,env,bridge)).job_status,'succeeded');
assert.deepEqual(await callTool('start_weekendkrant_executor',startArgs,env,bridge),scout);
assert.equal((await callTool('validate_weekendkrant_claim',scoutClaim,env,bridge)).valid,false);
console.log(JSON.stringify({job_id,attempt_id:claim.attempt_id,scout_job:scout.job_id,
 scout_attempt:scout.attempt_id,run_id:scout.run_id,queue_id:fiche.queue_item_id}));
'''
                result = subprocess.run([node, '--input-type=module', '-e', script,
                    'http://%s:%s' % server.server_address, str(job), str(other)],
                    cwd=REPO, capture_output=True, text=True, timeout=20)
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
                    self.assertEqual(db.execute('SELECT count(*) FROM job_operations').fetchone()[0], 3)
                    self.assertEqual(db.execute('SELECT count(*) FROM sherlock_activations').fetchone()[0], 1)
                    self.assertEqual(db.execute('''SELECT r.job_id,r.attempt_id,r.run_id,f.queue_item_id
                        FROM sherlock_job_runs r JOIN sherlock_fiches f USING(run_id)''').fetchone(),
                        (identity['scout_job'], identity['scout_attempt'], identity['run_id'], identity['queue_id']))
                    self.assertEqual(len(store.attempts(identity['scout_job'])), 1)
                    self.assertEqual(store.get(identity['scout_job'])['status'], 'succeeded')
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main(verbosity=2)
