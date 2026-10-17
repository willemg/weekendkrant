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
from dispatcher import Dispatcher
from datetime import datetime, timezone
from unittest.mock import patch

# Admission uses an injected backend clock; no clock data enters MCP requests.
def backend_dispatcher(db):
    return Dispatcher(db, lambda: datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0))



class GenericSystemTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('ingress_api.Dispatcher', side_effect=backend_dispatcher)
        patcher.start()
        self.addCleanup(patcher.stop)

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
const startArgs={};
lose=true;
assert.equal((await callTool('start_weekendkrant_executor',startArgs,env,bridge)).code,'backend_unreachable');
const bootstrap=await callTool('start_weekendkrant_executor',startArgs,env,bridge);
assert.deepEqual(Object.keys(bootstrap).sort(),['executor_id']);
const packet=await callTool('get_weekendkrant_job',{executor_id:bootstrap.executor_id},env,bridge);
assert.deepEqual(await callTool('get_weekendkrant_job',{executor_id:bootstrap.executor_id},env,bridge),packet);
const scout={...packet,...packet.claim};
assert.equal(scout.status,'success');assert.equal(scout.role,'Sherlock');
const scoutClaim={job_id:scout.job_id,attempt_id:scout.attempt_id,token:scout.token};
assert.equal((await callTool('validate_weekendkrant_claim',scoutClaim,env,bridge)).valid,true);
assert.equal((await callTool('record_sherlock_source',{run_id:scout.run_id,topic:scout.input.topic,
 url:'https://example.invalid/bridge-phase5',outcome:'fixture',rationale:'isolated system source',claim:scoutClaim},env,bridge)).status,'success');
const fiche=await callTool('submit_weekendkrant_fiche',{run_id:scout.run_id,topic:scout.input.topic,
 schema_version:1,date:scout.input.date,content:'isolated bridge fixture',claim:scoutClaim},env,bridge);
assert.equal(fiche.status,'success');
const scoutFinish={...scoutClaim,status:'succeeded',output_refs:[scout.result_ref]};
lose=true;
assert.equal((await callTool('finish_weekendkrant_job',scoutFinish,env,bridge)).code,'backend_unreachable');
assert.equal((await callTool('finish_weekendkrant_job',scoutFinish,env,bridge)).job_status,'succeeded');
assert.deepEqual(await callTool('start_weekendkrant_executor',startArgs,env,bridge),bootstrap);
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
                    self.assertEqual(db.execute('SELECT count(*) FROM executor_activations').fetchone()[0], 1)
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

# These end-to-end regressions stay in the plugin layer: bibib needs no Node.
sys.path.insert(0, str(REPO / 'tests'))
from test_parts import PartFixture
from leonardo import LeonardoStore


class LeonardoFinishSystemTests(PartFixture):
    def setUp(self):
        super().setUp()
        patcher = patch('ingress_api.Dispatcher', side_effect=backend_dispatcher)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_leonardo_finish_invariants_through_real_mcp_http_and_storage(self):
        self.add()
        self.run_day()
        node = shutil.which('node')
        self.assertIsNotNone(node)
        with sqlite3.connect(self.db) as source:
            part, revision = source.execute('SELECT id,active_revision FROM parts').fetchone()
            for status in ('succeeded', 'failed', 'uncertain', 'abandon'):
                with self.subTest(status=status):
                    path = self.base / (status + '.sqlite3')
                    with sqlite3.connect(path) as db:
                        source.backup(db)
                        store = LeonardoStore(db)
                        store.create_dossier('dossier:mcp', 2)
                        job = store.enqueue('enqueue', 'dossier:mcp', 0, [[part, revision]])
                    state = dict(schema_version=1, dossier_id='dossier:mcp', version=1,
                                 previous_version=0, hypotheses=[], claims=[], uncertainties=[],
                                 open_questions=[], processed_refs=[f'part:{part}:{revision}'])
                    server = create_server(Config(token='fictional-system-token', db_path=path, port=0))
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        script = '''
import assert from 'node:assert/strict';
import {callTool,DISCOVERY} from './plugin/weekendkrant_ingress/worker/index.js';
const env={WEEKENDKRANT_INGRESS_TOKEN:'fictional-system-token'};
const bridge=async(url,options)=>url===DISCOVERY
 ?Response.json({url:'https://fixture.trycloudflare.com/ingress'})
 :fetch(process.argv[1]+new URL(url).pathname,options);
const mode=process.argv[2],state=JSON.parse(process.argv[3]);
const call=(tool,args)=>callTool(tool,args,env,bridge);
const bootstrap=await call('start_weekendkrant_executor',{});
const packet=await call('get_weekendkrant_job',{executor_id:bootstrap.executor_id});
const claim={...packet,...packet.claim};
assert.equal(claim.status,'success');assert.equal(claim.role,'Leonardo');
const authority={job_id:claim.job_id,attempt_id:claim.attempt_id,token:claim.token};
const read={...authority,ref:state.processed_refs[0],recall_id:'recall:1'};
const recalled=await call('recall_weekendkrant_part',read);
assert.equal(recalled.status,'success');
assert.match(recalled.content,/WEEKENDKRANT-PART-1/);
assert.equal(recalled.bytes,new TextEncoder().encode(recalled.content).length);
assert.deepEqual(await call('recall_weekendkrant_part',read),recalled);
assert.equal((await call('recall_weekendkrant_part',{...read,ref:'part:999:1'})).code,'conflict');
if(mode==='abandon'){
 assert.equal((await call('abandon_weekendkrant_job',{...authority,error:'Unknown outcome'})).job_status,'blocked');
}else{
 const args={...authority,status:mode,output_refs:[]};
 if(mode==='succeeded'){
  args.leonardo_state=state;args.output_refs=[claim.result_ref];
  assert.equal((await call('finish_weekendkrant_job',args)).job_status,'succeeded');
  assert.equal((await call('finish_weekendkrant_job',args)).job_status,'succeeded');
  const changed={...state,open_questions:[{id:'q1',text:'Changed question',refs:[]}]};
  assert.equal((await call('finish_weekendkrant_job',{...args,leonardo_state:changed})).code,'conflict');
 }else{
  for(const invalid of [{output_refs:[claim.result_ref]},{leonardo_state:state},
                        {output_refs:[claim.result_ref],leonardo_state:state}])
   assert.equal((await call('finish_weekendkrant_job',{...args,...invalid})).code,'conflict');
  assert.equal((await call('validate_weekendkrant_claim',authority)).valid,true);
  assert.equal((await call('finish_weekendkrant_job',args)).job_status,mode==='uncertain'?'blocked':'failed');
 }
}
'''
                        result = subprocess.run(
                            [node, '--input-type=module', '-e', script,
                             'http://%s:%s' % server.server_address, status, json.dumps(state)],
                            cwd=REPO, capture_output=True, text=True, timeout=20)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        with sqlite3.connect(path) as db:
                            store = JobStore(db)
                            self.assertEqual(db.execute('SELECT count(*) FROM leonardo_recalls').fetchone()[0], 1)
                            expected = [f'leonardo-state:dossier:mcp:1'] if status == 'succeeded' else []
                            self.assertEqual(store.get(job)['output_refs'], expected)
                            self.assertEqual(store.attempts(job)[0]['output_refs'], expected)
                            self.assertEqual(db.execute('SELECT count(*) FROM leonardo_states').fetchone()[0],
                                             1 if status == 'succeeded' else 0)
                            if status == 'succeeded':
                                self.assertEqual(db.execute(
                                    "SELECT count(*) FROM job_operations WHERE operation_id LIKE 'executor-terminal:%'").fetchone()[0], 1)
                                self.assertEqual(db.execute(
                                    "SELECT count(*) FROM job_operations").fetchone()[0], 1)
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join()


from test_leonardo import LeonardoFixture


class KuifjeBridgeSystemTests(LeonardoFixture):
    def test_separate_mission_and_ingress_through_real_bridge_with_lost_answers(self):
        self.now = datetime.now(timezone.utc)
        self.enqueue()
        self.finish(self.start())
        self.store.reevaluate('bridge:reeval', 'dossier:reproduction', 1)
        self.start('bridge:leo')
        server = create_server(Config(token='fictional-system-token', db_path=self.db, port=0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            script = r"""
import assert from 'node:assert/strict';
import {callTool,DISCOVERY} from './plugin/weekendkrant_ingress/worker/index.js';
const env={WEEKENDKRANT_INGRESS_TOKEN:'fictional-system-token'};
let lose=false;
const bridge=async(url,options)=>{
 if(url===DISCOVERY)return Response.json({url:'https://fixture.trycloudflare.com/ingress'});
 const response=await fetch(process.argv[1]+new URL(url).pathname,options);
 if(lose){lose=false;await response.text();throw Error('lost committed answer');}
 return response;
};
const call=(name,args)=>callTool(name,args,env,bridge);
const leo=await call('get_weekendkrant_job',{executor_id:'bridge:leo'});
assert.equal(leo.role,'Leonardo');assert.equal(leo.input.mode,'reevaluation');
assert.deepEqual(leo.input.parts,[]);
const state=JSON.parse(process.argv[2]);
const finish={...leo.claim,status:'succeeded',output_refs:[leo.result_ref],leonardo_state:state,
 kuifje_missions:[1,2,3].map(i=>({question:`Independent replication ${i}?`,rationale:'Confirmation missing',scope:'Primary reports only',refs:state.processed_refs}))};
// Only claim fields belong to finish, not its lease metadata.
delete finish.lease_until;
lose=true;
assert.equal((await call('finish_weekendkrant_job',finish)).code,'backend_unreachable');
assert.equal((await call('finish_weekendkrant_job',finish)).job_status,'succeeded');
const start=await call('start_weekendkrant_executor',{});
const k=await call('get_weekendkrant_job',{executor_id:start.executor_id});
assert.equal(k.role,'Kuifje');
const authority={job_id:k.claim.job_id,attempt_id:k.claim.attempt_id,token:k.claim.token};
const fiche={schema_version:1,date:k.input.date,topic:k.input.missions[0].topic,content:'Independent primary source',
 mission_id:k.input.missions[0].mission_id,fiche_id:'primary:1',claim:authority};
lose=true;
assert.equal((await call('submit_weekendkrant_fiche',fiche)).code,'backend_unreachable');
const published=await call('submit_weekendkrant_fiche',fiche);
assert.equal(published.status,'success');
assert.deepEqual(await call('submit_weekendkrant_fiche',fiche),published);
const done={...authority,status:'succeeded',output_refs:[k.result_ref],kuifje_result:{mission_results:k.input.missions.map(m=>({mission_id:m.mission_id,summary:'One report',limitations:'No second independent source'}))}};
lose=true;
assert.equal((await call('finish_weekendkrant_job',done)).code,'backend_unreachable');
assert.equal((await call('finish_weekendkrant_job',done)).job_status,'succeeded');
console.log(published.queue_item_id);
"""
            with patch('ingress_api.Dispatcher', side_effect=backend_dispatcher):
                result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script,
                    'http://%s:%s' % server.server_address, json.dumps(self.state(2))],
                    cwd=REPO, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            queue_id = int(result.stdout)
            self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 3)
            self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_assignments').fetchone()[0], 1)
            self.assertEqual(self.conn.execute('SELECT count(*) FROM kuifje_fiches').fetchone()[0], 1)
            snapshot, = self.conn.execute('SELECT snapshot FROM kuifje_assignments').fetchone()
            self.run_job_day(dict(input=json.loads(snapshot)))
            self.assertEqual(self.conn.execute('SELECT status FROM ingress_queue WHERE id=?', (queue_id,)).fetchone()[0], 'processed')
            self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main(verbosity=2)
