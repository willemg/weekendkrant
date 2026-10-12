export const DISCOVERY='https://raw.githubusercontent.com/willemg/weekendkrant/main/config/ingress-endpoint.json';
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const positive=x=>Number.isSafeInteger(x)&&x>0;
const topic=x=>Number.isInteger(x)&&[1,2,3].includes(x);
const nonempty=x=>typeof x==='string'&&x.trim().length>0;
const runStatus=x=>['completed','failed'].includes(x);
const fail=code=>({status:'error',code});
const integer={type:'integer',minimum:1,maximum:Number.MAX_SAFE_INTEGER};
const topicSchema={type:'integer',enum:[1,2,3]};
const textSchema={type:'string',minLength:1,pattern:'\\S'};
const schema=(properties,required=Object.keys(properties))=>({type:'object',properties,required,additionalProperties:false});
export const TOOL={name:'submit_weekendkrant_fiche',description:'Sla één bronfiche uitsluitend op in de private Weekendkrant-ingressqueue; publiceert niets publiek. Geeft een compacte status en bij succes het queue-item-ID.',inputSchema:{type:'object',additionalProperties:true},annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:false,openWorldHint:false}};
export const TOOLS=[TOOL,
 {name:'start_sherlock_run',description:'Start een Sherlock-run: de tool maakt uitsluitend private Weekendkrant-runstate aan; de backend kiest atomair het volgende topic. Gebruik het geretourneerde run_id en topic gedurende die run.',inputSchema:schema({}),annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:false,openWorldHint:false}},
 {name:'filter_sherlock_sources',description:"Filter concrete reeds gereviewde pagina-URLs: leest uitsluitend private Weekendkrant-state en wijzigt niets. URLs zijn lookupwaarden en worden niet opgehaald of bezocht. Reserveert of registreert niets; dit is geen story-deduplicatie. Verschillende URLs over hetzelfde verhaal mogen terugkomen.",inputSchema:schema({urls:{type:'array',maxItems:50,items:{type:'string'}}}),annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
 {name:'record_sherlock_source',description:'Sla auditmetadata uitsluitend op in de private Weekendkrant-state. De url wordt alleen als bronidentiteit opgeslagen/gecanonicaliseerd; de tool bezoekt die URL niet en verstuurt of publiceert niets naar die URL of een andere externe partij. Gebruik uitsluitend nadat de concrete pagina daadwerkelijk inhoudelijk gereviewd is, nooit voor zoekresultaten, snippets, ongeopende kandidaten of enkel door filtering geaccepteerde URLs. outcome en rationale zijn compacte controleerbare auditnotities, geen private reasoning/chain-of-thought.',inputSchema:schema({run_id:integer,topic:topicSchema,url:textSchema,outcome:textSchema,rationale:textSchema,title:{type:['string','null']}},['run_id','topic','url','outcome','rationale']),annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
 {name:'finish_sherlock_run',description:'Sluit uitsluitend bestaande private Weekendkrant-runstate definitief af als completed of failed. De run kan daarna niet worden heropend of verder aangevuld.',inputSchema:schema({run_id:integer,status:{type:'string',enum:['completed','failed']}}),annotations:{readOnlyHint:false,destructiveHint:true,idempotentHint:true,openWorldHint:false}}
];
export function endpoint(value){
 if(typeof value!=='string')return null;
 // Check the raw authority too: URL normalizes explicit :443 and empty ?/#.
 if(!/^https:\/\/[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com\/ingress$/i.test(value))return null;
 try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&!u.hash&&!u.search&&u.pathname==='/ingress'?u.href:null;}catch{return null;}
}
const strict=(x,required,optional=[])=>object(x)&&required.every(k=>Object.hasOwn(x,k))&&Object.keys(x).every(k=>[...required,...optional].includes(k));
const contracts={
 start_sherlock_run:{path:'/sherlock/runs',valid:x=>strict(x,[]),result:r=>positive(r.run_id)&&topic(r.topic)?{run_id:r.run_id,topic:r.topic}:null},
 filter_sherlock_sources:{path:'/sherlock/sources/filter',valid:x=>strict(x,['urls'])&&Array.isArray(x.urls)&&x.urls.length<=50&&x.urls.every(v=>typeof v==='string'),result:r=>Array.isArray(r.unreviewed)&&r.unreviewed.every(v=>typeof v==='string')?{unreviewed:r.unreviewed}:null},
 record_sherlock_source:{path:'/sherlock/sources',valid:x=>strict(x,['run_id','topic','url','outcome','rationale'],['title'])&&positive(x.run_id)&&topic(x.topic)&&['url','outcome','rationale'].every(k=>nonempty(x[k]))&&(!Object.hasOwn(x,'title')||x.title===null||typeof x.title==='string'),result:r=>nonempty(r.canonical_url)?{canonical_url:r.canonical_url}:null},
 finish_sherlock_run:{path:'/sherlock/runs/finish',valid:x=>strict(x,['run_id','status'])&&positive(x.run_id)&&runStatus(x.status),result:(r,x)=>positive(r.run_id)&&r.run_id===x.run_id&&runStatus(r.status)&&r.status===x.status?{run_id:r.run_id,run_status:r.status}:null}
};
async function post(path,payload,env,fetcher,legacy=false){
 let d;
 try{d=await fetcher(DISCOVERY,{redirect:'manual',signal:AbortSignal.timeout(10000),headers:{Accept:'application/json'}});}catch{return fail('discovery_unreachable');}
 if(!d.ok)return fail(d.status===404?'discovery_missing':'discovery_unreachable');
 let config;try{config=await d.json();}catch{return fail('discovery_invalid');}
 if(!object(config)||typeof config.url!=='string')return fail('discovery_invalid');
 const base=endpoint(config.url);if(!base)return fail('endpoint_invalid');
 const token=env.WEEKENDKRANT_INGRESS_TOKEN;
 if(typeof token!=='string'||!token.trim())return fail('secret_not_configured');
 const url=new URL(path,base).href;
 const code=(modern,old)=>legacy?old:modern;
 let r;try{r=await fetcher(url,{method:'POST',redirect:'manual',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(payload)});}catch{return fail(code('backend_unreachable','ingress_unreachable'));}
 if(r.status===401)return fail('authentication_refused');
 if(r.status>=500)return fail(code('backend_server_error','ingress_server_error'));
 if(r.status>=300&&r.status<400)return fail(code('backend_redirect_refused','ingress_redirect_refused'));
 if(!r.ok){const mapped={400:'invalid_request',409:'conflict',413:'payload_too_large'};return fail(legacy?'ingress_rejected':mapped[r.status]||'invalid_request');}
 let result;try{result=await r.json();}catch{return fail(code('response_invalid','ingress_response_invalid'));}
 if(!object(result))return fail(code('response_invalid','ingress_response_invalid'));
 return {result};
}
export async function submit(payload,env,fetcher=fetch){
 if(!object(payload))return fail('invalid_payload');
 const response=await post('/ingress',payload,env,fetcher,true);
 if(response.status==='error')return response;
 if(!positive(response.result.id))return fail('ingress_response_invalid');
 return {status:'success',queue_item_id:response.result.id};
}
export async function callTool(name,args,env,fetcher=fetch){
 if(name===TOOL.name)return submit(args,env,fetcher);
 if(name==='start_sherlock_run'&&args===undefined)args={};
 const contract=Object.hasOwn(contracts,name)?contracts[name]:null;
 if(!contract||!contract.valid(args))return fail('invalid_request');
 const response=await post(contract.path,args,env,fetcher);
 if(response.status==='error')return response;
 const result=contract.result(response.result,args);
 return result?{status:'success',...result}:fail('response_invalid');
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
  if(msg.method==='tools/list')return reply({tools:TOOLS});
  if(msg.method==='tools/call'){
    if(!request.headers.get('oai-authenticated-user-id'))return new Response(null,{status:401});
    if(!TOOLS.some(tool=>tool.name===msg.params?.name))return json({jsonrpc:'2.0',id:msg.id,error:{code:-32602,message:'Unknown tool'}});
    const status=await callTool(msg.params.name,msg.params.arguments,env);
    return reply({content:[{type:'text',text:JSON.stringify(status)}],isError:status.status==='error'});
  }
  return json({jsonrpc:'2.0',id:msg.id,error:{code:-32601,message:'Method not found'}});
}};
