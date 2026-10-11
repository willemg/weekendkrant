export const DISCOVERY='https://raw.githubusercontent.com/willemg/weekendkrant/main/config/ingress-endpoint.json';
export const TOOL={name:'submit_weekendkrant_fiche',description:'Lever één bronfiche af aan de Weekendkrant-ingress. Geeft een compacte status en bij succes het queue-item-ID.',inputSchema:{type:'object',additionalProperties:true},annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:false,openWorldHint:true}};
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const fail=code=>({status:'error',code});
export function endpoint(value){
  if(typeof value!=='string') return null;
  try {const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&!u.hash&&/^[a-z0-9-]+\.trycloudflare\.com$/.test(u.hostname)?u.href:null;}catch{return null;}
}
export async function submit(payload,env,fetcher=fetch){
  if(!object(payload)) return fail('invalid_payload');
  let d;
  try{d=await fetcher(DISCOVERY,{redirect:'manual',signal:AbortSignal.timeout(10000),headers:{Accept:'application/json'}});}catch{return fail('discovery_unreachable');}
  if(!d.ok) return fail(d.status===404?'discovery_missing':'discovery_unreachable');
  let config;try{config=await d.json();}catch{return fail('discovery_invalid');}
  if(!object(config)||typeof config.url!=='string')return fail('discovery_invalid');
  const url=endpoint(config.url);if(!url)return fail('endpoint_invalid');
  const token=env.WEEKENDKRANT_INGRESS_TOKEN;
  if(typeof token!=='string'||!token.trim())return fail('secret_not_configured');
  let r;try{r=await fetcher(url,{method:'POST',redirect:'manual',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(payload)});}catch{return fail('ingress_unreachable');}
  if(r.status===401)return fail('authentication_refused');
  if(r.status>=500)return fail('ingress_server_error');
  if(r.status>=300&&r.status<400)return fail('ingress_redirect_refused');
  if(!r.ok)return fail('ingress_rejected');
  let result;try{result=await r.json();}catch{return fail('ingress_response_invalid');}
  // Only a numeric SQLite ID is returned; never forward arbitrary upstream text.
  if(!object(result)||!Number.isSafeInteger(result.id)||result.id<1)return fail('ingress_response_invalid');
  return {status:'success',queue_item_id:result.id};
}
const json=(value,status=200)=>Response.json(value,{status});
export default {async fetch(request,env){
  const url=new URL(request.url);
  if(url.pathname!=='/mcp')return new Response('<!doctype html><html lang="nl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Weekendkrant Ingress</title><body style="font:1rem system-ui;margin:3rem"><h1>Weekendkrant Ingress</h1><p>Persoonlijke bronfiche-ingang voor Sherlock.</p></body></html>',{headers:{'Content-Type':'text/html; charset=utf-8'}});
  if(request.method!=='POST')return new Response(null,{status:405});
  let msg;try{msg=await request.json();}catch{return json({jsonrpc:'2.0',id:null,error:{code:-32700,message:'Invalid JSON'}});}
  if(!object(msg))return json({jsonrpc:'2.0',id:null,error:{code:-32600,message:'Invalid request'}});
  if(!('id' in msg))return new Response(null,{status:202});
  const reply=result=>json({jsonrpc:'2.0',id:msg.id,result});
  if(msg.method==='initialize')return reply({protocolVersion:'2025-03-26',capabilities:{tools:{}},serverInfo:{name:'Weekendkrant Ingress',version:'1.0.0'}});
  if(msg.method==='ping')return reply({});
  if(msg.method==='tools/list')return reply({tools:[TOOL]});
  if(msg.method==='tools/call'){
    if(!request.headers.get('oai-authenticated-user-id'))return new Response(null,{status:401});
    if(msg.params?.name!==TOOL.name)return json({jsonrpc:'2.0',id:msg.id,error:{code:-32602,message:'Unknown tool'}});
    const status=await submit(msg.params.arguments,env);
    return reply({content:[{type:'text',text:JSON.stringify(status)}],isError:status.status==='error'});
  }
  return json({jsonrpc:'2.0',id:msg.id,error:{code:-32601,message:'Method not found'}});
}};
