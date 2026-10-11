import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{submit,endpoint,TOOL,DISCOVERY} from '../worker/index.js';
const env={WEEKENDKRANT_INGRESS_TOKEN:'fictional-test-only'};
const ok=x=>Response.json(x);
const good='https://fictional.trycloudflare.com/ingress';
test('exactly one write tool, arbitrary object schema',async()=>{
 const r=await worker.fetch(new Request('https://site.test/mcp',{method:'POST',body:JSON.stringify({id:1,method:'tools/list'})}),{});
 assert.deepEqual((await r.json()).result.tools,[TOOL]);assert.equal(TOOL.annotations.readOnlyHint,false);
 assert.deepEqual(TOOL.inputSchema,{type:'object',additionalProperties:true});
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
