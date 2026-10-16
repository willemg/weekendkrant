import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{submit,endpoint,TOOL,TOOLS,callTool,DISCOVERY} from '../worker/index.js';
const env={WEEKENDKRANT_INGRESS_TOKEN:'fictional-test-only'};
const ok=x=>Response.json(x);
const good='https://fictional.trycloudflare.com/ingress';
test('fiche remains a write tool with arbitrary object schema',async()=>{
 const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',body:JSON.stringify({id:1,method:'tools/list'})}),{});
 assert.deepEqual((await r.json()).result.tools,TOOLS);assert.equal(TOOL.annotations.readOnlyHint,false);
 assert.equal(TOOL.inputSchema.additionalProperties,true);
 assert.equal(TOOL.inputSchema.properties.run_id.type,'integer');
});
test('attributed fiche forwards run_id and returns canonical queue ID',async()=>{
 const payload={run_id:17,schema_version:1,topic:2,date:'2026-10-13',content:'# Fiche'};
 let count=0;
 const r=await submit(payload,env,async(url,options)=>{
  if(!count++)return ok({url:good});
  assert.deepEqual(JSON.parse(options.body),payload);
  return ok({id:42});
 });
 assert.deepEqual(r,{status:'success',queue_item_id:42});
 for(const run_id of [null,true,0,-1,1.5,'17',Number.MAX_SAFE_INTEGER+1]){
  assert.equal((await submit({...payload,run_id},env,()=>assert.fail('network'))).code,'invalid_payload');
 }
 let n=0;
 assert.equal((await submit(payload,env,async()=>n++?new Response('',{status:409}):ok({url:good}))).code,'conflict');
});
test('endpoint restrictions',()=>{
 for(const u of ['http://a.trycloudflare.com/ingress','https://evil.test/','https://trycloudflare.com/','https://a.trycloudflare.com.evil.test/','https://user@a.trycloudflare.com/','https://a.trycloudflare.com:444/','https://a.trycloudflare.com/#x'])assert.equal(endpoint(u),null);
 assert.equal(endpoint(good),good);
});
test('missing, unreachable and invalid discovery',async()=>{
 for(const [r,code] of [[new Response('',{status:404}),'discovery_missing'],[new Response('',{status:503}),'discovery_unreachable'],[new Response('broken'),'discovery_invalid'],[ok({}),'discovery_invalid'],[ok({url:'https://evil.test'}),'endpoint_invalid']])assert.equal((await submit({},env,async()=>r)).code,code);
 assert.equal((await submit({},env,async()=>{throw Error('private detail');})).code,'discovery_unreachable');
});
test('payload cannot choose destination, POST body exact, redirects disabled',async()=>{
 const payload={url:'https://evil.test',fictional:true};let count=0;
 const result=await submit(payload,env,async(url,options)=>{
  assert.equal(options.redirect,'manual');
  if(count++===0){assert.equal(url,DISCOVERY);assert.equal(options.headers.Authorization,undefined);return ok({url:good});}
  assert.equal(url,good);assert.equal(options.method,'POST');assert.equal(options.body,JSON.stringify(payload));assert.equal(options.headers.Authorization,`Bearer ${env.WEEKENDKRANT_INGRESS_TOKEN}`);return ok({id:42,private:'discarded'});
 });assert.deepEqual(result,{status:'success',queue_item_id:42});assert.equal(count,2);
});
test('compact errors and no secret echo',async()=>{
 for(const [response,code] of [[new Response(env.WEEKENDKRANT_INGRESS_TOKEN,{status:401}),'authentication_refused'],[new Response('',{status:502}),'ingress_server_error'],[new Response('',{status:302,headers:{Location:'https://evil.test'}}),'ingress_redirect_refused'],[new Response('',{status:400}),'ingress_rejected'],[ok({id:env.WEEKENDKRANT_INGRESS_TOKEN}),'ingress_response_invalid'],[new Response('bad'),'ingress_response_invalid']]){
  let n=0;const r=await submit({},env,async()=>n++?response:ok({url:good}));assert.equal(r.code,code);assert.ok(!JSON.stringify(r).includes(env.WEEKENDKRANT_INGRESS_TOKEN));
 }
 let n=0;assert.equal((await submit({},env,async()=>{if(n++)throw Error(env.WEEKENDKRANT_INGRESS_TOKEN);return ok({url:good});})).code,'ingress_unreachable');
 assert.equal((await submit({}, {},async()=>ok({url:good}))).code,'secret_not_configured');
});
test('unauthenticated MCP write denied',async()=>{
 const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',body:JSON.stringify({id:1,method:'tools/call',params:{name:TOOL.name,arguments:{}}})}),env);assert.equal(r.status,401);
});

const record={run_id:17,topic:2,url:'https://example.com/a',outcome:'selected',rationale:'Primary evidence'};
const cases=[['start_sherlock_run',{},'/sherlock/runs',{run_id:17,topic:2},{status:'success',run_id:17,topic:2}],['filter_sherlock_sources',{urls:['https://example.com/a?b=1']},'/sherlock/sources/filter',{unreviewed:['https://example.com/a?b=1']},{status:'success',unreviewed:['https://example.com/a?b=1']}],['record_sherlock_source',record,'/sherlock/sources',{canonical_url:record.url},{status:'success',canonical_url:record.url}],['finish_sherlock_run',{run_id:17,status:'completed'},'/sherlock/runs/finish',{run_id:17,status:'completed'},{status:'success',run_id:17,run_status:'completed'}]];
const invoke=(name,args,result)=>{let n=0;return callTool(name,args,env,async()=>n++?Response.json(result):Response.json({url:good}));};
test('original five tools retain names and schemas',async()=>{
 const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',body:JSON.stringify({id:1,method:'tools/list'})}),{});
 assert.deepEqual((await r.json()).result.tools,TOOLS);
 assert.deepEqual(TOOLS.slice(0,5).map(t=>t.name),['submit_weekendkrant_fiche',...cases.map(c=>c[0])]);
 for(const t of TOOLS){if(t.name!=='submit_weekendkrant_fiche')assert.equal(t.inputSchema.additionalProperties,false);}
 assert.deepEqual(TOOLS[1].inputSchema.properties,{});
 assert.equal(TOOLS[2].inputSchema.properties.urls.maxItems,50);
 assert.deepEqual(TOOLS[3].inputSchema.required,['run_id','topic','url','outcome','rationale']);
 assert.deepEqual(TOOLS[4].inputSchema.properties.status.enum,['completed','failed']);
});
const annotationMatrix=[
 ['submit_weekendkrant_fiche',false,false,false,false],
 ['start_sherlock_run',false,false,false,false],
 ['filter_sherlock_sources',true,false,true,false],
 ['record_sherlock_source',false,false,true,false],
 ['finish_sherlock_run',false,true,true,false],
 ['claim_weekendkrant_job',false,true,true,false],
 ['finish_weekendkrant_job',false,true,true,false],
 ['abandon_weekendkrant_job',false,true,true,false],
 ['validate_weekendkrant_claim',false,true,true,false]
];
for(const [name,readOnlyHint,destructiveHint,idempotentHint,openWorldHint] of annotationMatrix)test(`${name} advertises exact bounded annotations`,async()=>{
 const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',body:JSON.stringify({id:1,method:'tools/list'})}),{});
 const tool=(await r.json()).result.tools.find(t=>t.name===name);
 assert.deepEqual(tool.annotations,{readOnlyHint,destructiveHint,idempotentHint,openWorldHint});
});
test('descriptions identify the private workspace and bounded effects',()=>{
 const descriptions=Object.fromEntries(TOOLS.map(t=>[t.name,t.description]));
 for(const description of Object.values(descriptions))assert.match(description,/private Weekendkrant/);
 assert.match(descriptions.submit_weekendkrant_fiche,/ingressqueue/);
 assert.match(descriptions.submit_weekendkrant_fiche,/publiceert niets publiek/);
 assert.match(descriptions.start_sherlock_run,/runstate/);
 assert.match(descriptions.start_sherlock_run,/maakt.*aan/);
 assert.match(descriptions.filter_sherlock_sources,/leest uitsluitend/);
 assert.match(descriptions.filter_sherlock_sources,/wijzigt niets/);
 assert.match(descriptions.filter_sherlock_sources,/URLs.*niet.*opgehaald.*bezocht/);
 assert.match(descriptions.record_sherlock_source,/auditmetadata/);
 assert.match(descriptions.record_sherlock_source,/inhoudelijk gereviewd/);
 assert.match(descriptions.record_sherlock_source,/bronidentiteit.*opgeslagen.*gecanonicaliseerd/);
 assert.match(descriptions.record_sherlock_source,/bezoekt.*URL niet/);
 assert.match(descriptions.record_sherlock_source,/verstuurt of publiceert niets.*URL.*externe partij/);
 assert.match(descriptions.finish_sherlock_run,/runstate.*definitief/);
 assert.match(descriptions.finish_sherlock_run,/niet.*heropend.*aangevuld/);
});
test('strict discovery rejects normalized explicit ports, query, fragment and paths',()=>{
 for(const u of ['http://fictional.trycloudflare.com/ingress','https://fictional.trycloudflare.com/','https://fictional.trycloudflare.com/other','https://fictional.trycloudflare.com/ingress?x=1','https://fictional.trycloudflare.com/ingress#x','https://user@fictional.trycloudflare.com/ingress','https://fictional.trycloudflare.com:444/ingress','https://fictional.trycloudflare.com:443/ingress','https://a.b.trycloudflare.com/ingress','https://fictional.trycloudflare.com/ingress?','https://fictional.trycloudflare.com/ingress#'])assert.equal(endpoint(u),null,u);
 assert.equal(endpoint(good),good);
});
for(const [name,args,path,backend,expected] of cases)test(`${name} exact authenticated POST and compact output`,async()=>{
 let n=0;const r=await callTool(name,args,env,async(url,o)=>{
 assert.equal(o.redirect,'manual');assert.ok(o.signal);
 if(!n++){assert.equal(o.headers.Authorization,undefined);return Response.json({url:good});}
 assert.equal(url,`https://fictional.trycloudflare.com${path}`);assert.equal(o.method,'POST');assert.equal(o.headers.Authorization,`Bearer ${env.WEEKENDKRANT_INGRESS_TOKEN}`);assert.deepEqual(JSON.parse(o.body),args);return Response.json({...backend,private:'discard'});
 });assert.deepEqual(r,expected);assert.equal(n,2);
});
test('local input validation never accesses network',async()=>{
 const invalid=[['start_sherlock_run',{topic:1}],['filter_sherlock_sources',{urls:Array(51).fill('x')}],['filter_sherlock_sources',{urls:[1]}],['filter_sherlock_sources',{urls:[],extra:1}],['filter_sherlock_sources',{}],['filter_sherlock_sources',{urls:'x'}],['finish_sherlock_run',{run_id:17,status:'running'}]];
 for(const key of ['run_id','topic','url','outcome','rationale']){const x={...record};delete x[key];invalid.push(['record_sherlock_source',x]);}
 for(const [key,values] of Object.entries({run_id:[0,-1,1.5,Number.MAX_SAFE_INTEGER+1,'17'],topic:[0,4,1.5,'2'],url:['',' ',null],outcome:['',' ',null],rationale:['',' ',null],title:[42],extra:[true]}))for(const v of values)invalid.push(['record_sherlock_source',{...record,[key]:v}]);
 for(const [name,args] of invalid)assert.equal((await callTool(name,args,env,()=>assert.fail('network'))).code,'invalid_request');
});
test('filter accepts empty and 50 URLs unchanged, validates response',async()=>{
 for(const urls of [[],Array(50).fill('HTTP://Example.com/a?x=1#f')])assert.deepEqual(await invoke('filter_sherlock_sources',{urls},{unreviewed:urls}),{status:'success',unreviewed:urls});
 for(const unreviewed of [null,'x',[1]])assert.equal((await invoke('filter_sherlock_sources',{urls:[]},{unreviewed})).code,'response_invalid');
});
test('record optional and null titles, response validation',async()=>{
 for(const title of [null,'A title'])assert.equal((await invoke('record_sherlock_source',{...record,title},{canonical_url:record.url})).status,'success');
 for(const canonical_url of ['',null,12])assert.equal((await invoke('record_sherlock_source',record,{canonical_url})).code,'response_invalid');
});
test('start and finish validate responses, including both finish statuses',async()=>{
 for(const result of [{run_id:0,topic:1},{run_id:1.5,topic:2},{run_id:17,topic:4},{run_id:17,topic:'2'},{}])assert.equal((await invoke('start_sherlock_run',{},result)).code,'response_invalid');
 for(const status of ['completed','failed'])assert.deepEqual(await invoke('finish_sherlock_run',{run_id:17,status},{run_id:17,status}),{status:'success',run_id:17,run_status:status});
 for(const result of [{run_id:0,status:'completed'},{run_id:18,status:'completed'},{run_id:17,status:'failed'},{run_id:17,status:'running'}])assert.equal((await invoke('finish_sherlock_run',{run_id:17,status:'completed'},result)).code,'response_invalid');
});
test('shared error mapping never leaks upstream text or secret',async()=>{
 for(const [status,code] of [[400,'invalid_request'],[401,'authentication_refused'],[409,'conflict'],[413,'payload_too_large'],[503,'backend_server_error'],[302,'backend_redirect_refused']]){
 let n=0;const r=await callTool('start_sherlock_run',{},env,async()=>n++?new Response(env.WEEKENDKRANT_INGRESS_TOKEN,{status}):Response.json({url:good}));assert.deepEqual(r,{status:'error',code});}
 for(const failure of ['network','json']){let n=0;const r=await callTool('start_sherlock_run',{},env,async()=>{if(!n++)return Response.json({url:good});if(failure==='network')throw Error(env.WEEKENDKRANT_INGRESS_TOKEN);return new Response(env.WEEKENDKRANT_INGRESS_TOKEN);});assert.equal(r.code,failure==='network'?'backend_unreachable':'response_invalid');assert.ok(!JSON.stringify(r).includes(env.WEEKENDKRANT_INGRESS_TOKEN));}
});
test('all calls require authenticated user and unknown tool is RPC error',async()=>{
 for(const t of TOOLS){const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',body:JSON.stringify({id:1,method:'tools/call',params:{name:t.name,arguments:{}}})}),env);assert.equal(r.status,401);}
 const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',headers:{'oai-authenticated-user-id':'test'},body:JSON.stringify({id:1,method:'tools/call',params:{name:'unknown'}})}),env);assert.equal((await r.json()).error.code,-32602);
});
test('authenticated MCP dispatch reaches each tool and wraps compact status',async()=>{
 const original=globalThis.fetch;
 try{
  for(const [name,args,path,backend,expected] of [[TOOL.name,{fictional:true},'/ingress',{id:42},{status:'success',queue_item_id:42}],...cases]){
   let n=0;globalThis.fetch=async(url)=>{if(!n++)return ok({url:good});assert.equal(url,`https://fictional.trycloudflare.com${path}`);return ok(backend);};
   const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',headers:{'oai-authenticated-user-id':'fictional-user'},body:JSON.stringify({jsonrpc:'2.0',id:7,method:'tools/call',params:{name,arguments:args}})}),env);
   assert.deepEqual(await r.json(),{jsonrpc:'2.0',id:7,result:{content:[{type:'text',text:JSON.stringify(expected)}],isError:false}});assert.equal(n,2);
  }
 }finally{globalThis.fetch=original;}
});
test('Sherlock discovery failures and missing secret stay compact',async()=>{
 for(const [r,code] of [[new Response('',{status:404}),'discovery_missing'],[new Response('',{status:302}),'discovery_unreachable'],[new Response('broken'),'discovery_invalid'],[ok({}),'discovery_invalid'],[ok({url:'https://evil.test/ingress'}),'endpoint_invalid']])assert.deepEqual(await callTool('start_sherlock_run',{},env,async()=>r),{status:'error',code});
 assert.equal((await callTool('start_sherlock_run',{},env,async()=>{throw Error(env.WEEKENDKRANT_INGRESS_TOKEN);})).code,'discovery_unreachable');
 assert.equal((await callTool('start_sherlock_run',{}, {},async()=>ok({url:good}))).code,'secret_not_configured');
});

test('parameterless start accepts omitted MCP arguments',async()=>{
 assert.deepEqual(await invoke('start_sherlock_run',undefined,{run_id:17,topic:2}),{status:'success',run_id:17,topic:2});
});

test('generic claim/finish/abandon/validate preserve operation and claim identities',async()=>{
 const authority={job_id:3,attempt_id:7,token:'claim-secret'};
 const cases=[
  ['claim_weekendkrant_job','/jobs/claim',{job_id:3,activation_id:'activation:1',operation_id:'claim:1'},
   {...authority,lease_until:'2026-10-14T20:00:00.000000+00:00',role:'test',input_refs:['input:v1'],output_contract_ref:'contract:v1'}],
  ['finish_weekendkrant_job','/jobs/finish',{...authority,operation_id:'finish:1',status:'succeeded',output_refs:['result:v1']},
   {job_id:3,attempt_id:7,job_status:'succeeded'}],
  ['abandon_weekendkrant_job','/jobs/abandon',{...authority,operation_id:'abandon:1',error:'unknown effects'},
   {job_id:3,attempt_id:7,job_status:'blocked'}],
  ['validate_weekendkrant_claim','/jobs/validate',authority,
   {job_id:3,attempt_id:7,claim_status:'expired',valid:false,lease_until:'2026-10-14T20:00:00.000000+00:00'}]
 ];
 for(const [name,path,args,result] of cases){
  let n=0;
  assert.deepEqual(await callTool(name,args,env,async(url,options)=>{
   if(n++===0)return ok({url:good});
   assert.equal(new URL(url).pathname,path);assert.deepEqual(JSON.parse(options.body),args);
   return ok(result);
  }),{status:'success',...result});
  assert.equal((await callTool(name,{...args,extra:1},env,()=>assert.fail('network'))).code,'invalid_request');
  n=0;
  assert.equal((await callTool(name,args,env,async()=>n++?ok({...result,job_id:999}):ok({url:good}))).code,'response_invalid');
 }
 assert.equal(TOOLS.some(t=>t.name.includes('reconcile')),false);
 for(const t of TOOLS.filter(t=>t.name.includes('job')||t.name.includes('claim'))){
  assert.equal(t.annotations.idempotentHint,true);
  assert.equal(t.inputSchema.additionalProperties,false);
 }
});
test('generic tools reject malformed identity and bound content before network',async()=>{
 const args={job_id:3,activation_id:'a',operation_id:'op'};
 for(const bad of [true,0,1.2,Number.MAX_SAFE_INTEGER+1])
  assert.equal((await callTool('claim_weekendkrant_job',{...args,job_id:bad},env,()=>assert.fail('network'))).code,'invalid_request');
 for(const bad of ['', ' ', 'x'.repeat(129)])
  assert.equal((await callTool('claim_weekendkrant_job',{...args,operation_id:bad},env,()=>assert.fail('network'))).code,'invalid_request');
 const finish={job_id:3,attempt_id:7,token:'secret',operation_id:'op',status:'succeeded',output_refs:[]};
 for(const output_refs of [null,[''],Array(33).fill('ref'),['x'.repeat(513)]])
  assert.equal((await callTool('finish_weekendkrant_job',{...finish,output_refs},env,()=>assert.fail('network'))).code,'invalid_request');
});
test('generic lost answer remains an error, no automatic request retry or fresh identity',async()=>{
 let n=0;
 const r=await callTool('claim_weekendkrant_job',{job_id:3,activation_id:'a',operation_id:'op'},env,async()=>{
  if(n++===0)return ok({url:good});throw Error('response lost');
 });
 assert.equal(n,2);assert.equal(r.code,'backend_unreachable');
});

test('generic null claims, forged responses and finish failure states are explicit',async()=>{
 const args={job_id:3,activation_id:'a',operation_id:'op'};
 assert.deepEqual(await invoke('claim_weekendkrant_job',args,{claim:null}),{status:'success',claim:null});
 for(const result of [{claim:null,token:'unexpected'},{job_id:3,attempt_id:7,token:'',lease_until:'invalid',role:'r',input_refs:[],output_contract_ref:'c'}])
  assert.equal((await invoke('claim_weekendkrant_job',args,result)).code,'response_invalid');
 for(const status of ['failed','uncertain']){
  const finish={job_id:3,attempt_id:7,token:'secret',operation_id:'op',status,output_refs:[],error:null};
  const result={job_id:3,attempt_id:7,job_status:status==='uncertain'?'blocked':status};
  assert.deepEqual(await invoke('finish_weekendkrant_job',finish,result),{status:'success',...result});
 }
});

test('executor start advertises exact annotations and forwards stable occurrence identities',async()=>{
 const tool=TOOLS.find(t=>t.name==='start_weekendkrant_executor');
 assert.deepEqual(tool.annotations,{readOnlyHint:false,destructiveHint:true,idempotentHint:true,openWorldHint:false});
 const args={operation_id:'start:occurrence',activation_id:'scheduler:occurrence'};
 assert.deepEqual(await invoke(tool.name,args,{claim:null}),{status:'success',claim:null});
 let n=0;
 const result={job_id:3,attempt_id:7,token:'secret',lease_until:'2026-10-15T20:00:00.000000+00:00',
  role:'Sherlock',run_id:9,input:{topic:2,date:'2026-10-15'},input_refs:['sha256:input','sha256:role'],
  role_contract_ref:'sha256:role',role_contract:'role text',output_contract_ref:'sha256:output',
  output_contract:'output text',result_ref:'sherlock-run:9'};
 assert.deepEqual(await callTool(tool.name,args,env,async(url,options)=>{
  if(!n++)return ok({url:good});
  assert.equal(new URL(url).pathname,'/executor/start');
  assert.deepEqual(JSON.parse(options.body),args);return ok(result);
 }),{status:'success',...result});
 const future={...result,role:'TestRole',input:{state_ref:'state:v1'},result_ref:'result:v1'};
 delete future.run_id;
 assert.deepEqual(await invoke(tool.name,args,future),{status:'success',...future});
 for(const bad of [{...args,extra:true},{...args,activation_id:''},{}])
  assert.equal((await callTool(tool.name,bad,env,()=>assert.fail('network'))).code,'invalid_request');
 for(const bad of [{...result,role:''},{...result,input:{topic:4,date:'x'}},{...result,run_id:0},{...result,result_ref:'sherlock-run:8'},{...result,extra:'secret'}])
  assert.equal((await invoke(tool.name,args,bad)).code,'response_invalid');
});
test('job-backed source and fiche forward exact claim while refusing malformed claims locally',async()=>{
 const claim={job_id:3,attempt_id:7,token:'secret'};
 assert.equal((await invoke('record_sherlock_source',{...record,claim},{canonical_url:record.url})).status,'success');
 const payload={run_id:17,schema_version:1,topic:2,date:'2026-10-15',content:'fiche',claim};
 let n=0;
 assert.equal((await submit(payload,env,async(url,options)=>{
  if(!n++)return ok({url:good});assert.deepEqual(JSON.parse(options.body),payload);return ok({id:42});
 })).queue_item_id,42);
 for(const bad of [null,{}, {...claim,extra:true},{...claim,job_id:true}]){
  assert.equal((await callTool('record_sherlock_source',{...record,claim:bad},env,()=>assert.fail('network'))).code,'invalid_request');
  assert.equal((await submit({...payload,claim:bad},env,()=>assert.fail('network'))).code,'invalid_payload');
 }
});

test('Leonardo assignment and atomic state finish use existing generic tools',async()=>{
 const state={schema_version:1,dossier_id:'dossier:1',version:1,previous_version:0,
  hypotheses:[],claims:[],uncertainties:[],open_questions:[],processed_refs:['part:1:1']};
 const claim={job_id:4,attempt_id:8,token:'secret',lease_until:'2026-10-16T14:00:00.000000+00:00',role:'Leonardo',
  input:{state:null,parts:[{ref:'part:1:1',content:'source'}]},input_refs:['sha256:input'],
  role_contract_ref:'sha256:role',role_contract:'Leonardo',output_contract_ref:'sha256:output',output_contract:'state-v1',result_ref:'leonardo-state:dossier:1:1'};
 assert.deepEqual(await invoke('start_weekendkrant_executor',{operation_id:'start:leo',activation_id:'leo'},claim),{status:'success',...claim});
 const args={job_id:4,attempt_id:8,token:'secret',operation_id:'finish:leo',status:'succeeded',output_refs:[claim.result_ref],leonardo_state:state};
 const result={job_id:4,attempt_id:8,job_status:'succeeded'};
 assert.deepEqual(await invoke('finish_weekendkrant_job',args,result),{status:'success',...result});
 for(const invalid of [null,[],{text:'x'.repeat(32769)}])
  assert.equal((await callTool('finish_weekendkrant_job',{...args,leonardo_state:invalid},env,()=>assert.fail('network'))).code,'invalid_request');
});
