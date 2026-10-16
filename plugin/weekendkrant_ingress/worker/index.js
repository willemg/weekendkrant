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
const claimSchema=schema({job_id:integer,attempt_id:integer,token:{...textSchema,maxLength:512}});
export const TOOL={name:'submit_weekendkrant_fiche',description:'Sla één bronfiche uitsluitend op in de private Weekendkrant-ingressqueue; publiceert niets publiek. Geef voor Sherlock het huidige run_id mee als transportmetadata om de producerende run persistent te koppelen. De backend vereist dan hetzelfde topic en een running run; job-backed runs vereisen tevens claim met job_id, attempt_id en token. Claimgegevens blijven transportmetadata en autoriseren alleen een nog geldige lease. Na de eerste job-backed assignment weigert de backend ook volledig ongekoppelde fiches. Geeft een compacte status en bij succes het queue-item-ID.',inputSchema:{type:'object',properties:{run_id:integer,claim:claimSchema},additionalProperties:true},annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:false,openWorldHint:false}};
export const TOOLS=[TOOL,
 {name:'start_sherlock_run',description:'Start een Sherlock-run: de tool maakt uitsluitend private Weekendkrant-runstate aan; de backend kiest atomair het volgende topic. Gebruik het geretourneerde run_id en topic gedurende die run.',inputSchema:schema({}),annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:false,openWorldHint:false}},
 {name:'filter_sherlock_sources',description:"Filter concrete reeds gereviewde pagina-URLs: leest uitsluitend private Weekendkrant-state en wijzigt niets. URLs zijn lookupwaarden en worden niet opgehaald of bezocht. Reserveert of registreert niets; dit is geen story-deduplicatie. Verschillende URLs over hetzelfde verhaal mogen terugkomen.",inputSchema:schema({urls:{type:'array',maxItems:50,items:{type:'string'}}}),annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
 {name:'record_sherlock_source',description:'Sla auditmetadata uitsluitend op in de private Weekendkrant-state. De url wordt alleen als bronidentiteit opgeslagen/gecanonicaliseerd; de tool bezoekt die URL niet en verstuurt of publiceert niets naar die URL of een andere externe partij. Gebruik uitsluitend nadat de concrete pagina daadwerkelijk inhoudelijk gereviewd is, nooit voor zoekresultaten, snippets, ongeopende kandidaten of enkel door filtering geaccepteerde URLs. Voor een job-backed run is claim met job_id, attempt_id en token verplicht; de backend controleert actuele lease en binding onder de schrijflock. outcome en rationale zijn compacte controleerbare auditnotities, geen private reasoning/chain-of-thought.',inputSchema:schema({run_id:integer,topic:topicSchema,url:textSchema,outcome:textSchema,rationale:textSchema,title:{type:['string','null']},claim:claimSchema},['run_id','topic','url','outcome','rationale']),annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
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
 record_sherlock_source:{path:'/sherlock/sources',valid:x=>strict(x,['run_id','topic','url','outcome','rationale'],['title','claim'])&&(!Object.hasOwn(x,'claim')||validClaim(x.claim))&&positive(x.run_id)&&topic(x.topic)&&['url','outcome','rationale'].every(k=>nonempty(x[k]))&&(!Object.hasOwn(x,'title')||x.title===null||typeof x.title==='string'),result:r=>nonempty(r.canonical_url)?{canonical_url:r.canonical_url}:null},
 finish_sherlock_run:{path:'/sherlock/runs/finish',valid:x=>strict(x,['run_id','status'])&&positive(x.run_id)&&runStatus(x.status),result:(r,x)=>positive(r.run_id)&&r.run_id===x.run_id&&runStatus(r.status)&&r.status===x.status?{run_id:r.run_id,run_status:r.status}:null}
};
// Generic operations select no work and publish no artifacts. Stable IDs are caller-owned.
const bounded=(x,n=512)=>nonempty(x)&&x.length<=n;
const refs=x=>Array.isArray(x)&&x.length<=32&&x.every(v=>bounded(v));
const boundedSchema=n=>({...textSchema,maxLength:n});
const referenceSchema={type:'array',maxItems:32,items:boundedSchema(512)};
const authoritySchema={job_id:integer,attempt_id:integer,token:boundedSchema(512)};
const authority=x=>positive(x.job_id)&&positive(x.attempt_id)&&bounded(x.token);
const validClaim=x=>strict(x,['job_id','attempt_id','token'])&&authority(x);
const operationSchema={operation_id:boundedSchema(128)};
const stamp=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/.test(x)&&Number.isFinite(Date.parse(x));
const generic=[
 {name:'start_weekendkrant_executor',path:'/executor/start',description:'Dispatch maximaal één uitvoerbare opdracht voor één stabiele scheduled activation. Selecteert bestaand ready werk vóór nieuwe productie en bindt claim, rolcontract en activatie atomair; retourneert bij een bezette/geblokkeerde baan claim:null. Eén scheduler, deterministische ready-first dispatcher met persistente pause en harde concurrencygrens. De scheduler levert activation_id; genereer geen nieuwe identiteit bij retries, batches of finish. Gebruik dezelfde operation_id en exacte argumenten bij verloren antwoord. Een receipt is geen actuele uitvoeringsbevoegdheid: valideer de claim vóór werk. Kan eerder verlopen runstate na expliciete recovery afsluiten.',properties:{...operationSchema,activation_id:boundedSchema(128)},
 valid:x=>strict(x,['operation_id','activation_id'])&&bounded(x.operation_id,128)&&bounded(x.activation_id,128),
 result:r=>strict(r,['claim'])&&r.claim===null?{claim:null}:strict(r,['job_id','attempt_id','token','lease_until','role','input','input_refs','role_contract_ref','role_contract','output_contract_ref','output_contract','result_ref'],['run_id'])&&authority(r)&&stamp(r.lease_until)&&bounded(r.role,128)&&object(r.input)&&(r.role!=='Sherlock'||(positive(r.run_id)&&strict(r.input,['topic','date'])&&topic(r.input.topic)&&/^\d{4}-\d{2}-\d{2}$/.test(r.input.date)))&&refs(r.input_refs)&&bounded(r.role_contract_ref)&&bounded(r.role_contract,65536)&&bounded(r.output_contract_ref)&&bounded(r.output_contract,65536)&&bounded(r.result_ref)&&(r.role!=='Sherlock'||r.result_ref===`sherlock-run:${r.run_id}`)?r:null},
 {name:'claim_weekendkrant_job',path:'/jobs/claim',description:'Claim één expliciet aangeleverde job, zonder werkselectie. Gebruik dezelfde globale activation_id voor de hele activatie, en dezelfde operation_id en argumenten bij ieder transportretry. Een bevestigd antwoord kan een oude receipt zijn: controleer lease en validate_weekendkrant_claim vóór uitvoering. Geen tweede job binnen dezelfde activatie.',properties:{...operationSchema,job_id:integer,activation_id:boundedSchema(128)},
 valid:x=>strict(x,['operation_id','job_id','activation_id'])&&positive(x.job_id)&&bounded(x.operation_id,128)&&bounded(x.activation_id,128),
 result:(r,x)=>strict(r,['claim'])&&r.claim===null?{claim:null}:strict(r,['job_id','attempt_id','token','lease_until','role','input_refs','output_contract_ref'])&&authority(r)&&r.job_id===x.job_id&&stamp(r.lease_until)&&bounded(r.role,128)&&refs(r.input_refs)&&bounded(r.output_contract_ref)?r:null},
 {name:'finish_weekendkrant_job',path:'/jobs/finish',description:'Registreer bestaande immutable outputreferenties en uitkomst van één job, zonder publicatie. Claim-ID/token/fencing en lease worden gecontroleerd. Herhaal dezelfde operation_id en exacte argumenten bij onzeker antwoord, nooit het inhoudelijke werk of side effect. Sluit de attempt en een gekoppelde Sherlock-run atomair af; gebruik voor Sherlock de geleverde result_ref als enige output_refs. succeeded en failed zijn terminaal, uncertain blokkeert voor operatoronderzoek.',properties:{...operationSchema,...authoritySchema,status:{type:'string',enum:['succeeded','failed','uncertain']},output_refs:referenceSchema,error:{type:['string','null'],minLength:1,maxLength:2048,pattern:'\\S'}},required:['operation_id','job_id','attempt_id','token','status','output_refs'],
 valid:x=>strict(x,['operation_id','job_id','attempt_id','token','status','output_refs'],['error'])&&authority(x)&&bounded(x.operation_id,128)&&['succeeded','failed','uncertain'].includes(x.status)&&refs(x.output_refs)&&(x.error==null||bounded(x.error,2048)),
 result:(r,x)=>strict(r,['job_id','attempt_id','job_status'])&&r.job_id===x.job_id&&r.attempt_id===x.attempt_id&&r.job_status===(x.status==='uncertain'?'blocked':x.status)?r:null},
 {name:'abandon_weekendkrant_job',path:'/jobs/abandon',description:'Geef een nog geldige claim op met onzekere effecten: registreert uncertain en blokkeert de job, geeft geen toestemming tot retry. Compacte foutnotitie, geen private reasoning. Herhaal dezelfde operation_id en exacte argumenten als het antwoord verloren gaat.',properties:{...operationSchema,...authoritySchema,error:boundedSchema(2048)},
 valid:x=>strict(x,['operation_id','job_id','attempt_id','token','error'])&&authority(x)&&bounded(x.operation_id,128)&&bounded(x.error,2048),
 result:(r,x)=>strict(r,['job_id','attempt_id','job_status'])&&r.job_id===x.job_id&&r.attempt_id===x.attempt_id&&r.job_status==='blocked'?r:null},
 {name:'validate_weekendkrant_claim',path:'/jobs/validate',description:'Controleer huidige claimautoriteit bij de backend. Leasegevoelige actuele state, geen gecachte bevestiging. valid=false verbiedt nieuwe uitvoering/resultaatmutatie; een geldig antwoord is geen fencing of exactly-once-garantie voor externe side effects.',properties:authoritySchema,
 valid:x=>strict(x,['job_id','attempt_id','token'])&&authority(x),
 result:(r,x)=>strict(r,['job_id','attempt_id','claim_status','valid','lease_until'])&&r.job_id===x.job_id&&r.attempt_id===x.attempt_id&&['running','expired','uncertain','succeeded','failed'].includes(r.claim_status)&&r.valid===(r.claim_status==='running')&&stamp(r.lease_until)?r:null}
];
for(const tool of generic){
 TOOLS.push({name:tool.name,description:'Werkt uitsluitend op private Weekendkrant-jobstate; bezoekt geen input-/outputreferenties en publiceert niets extern. Kan verlopen running attempts persistent als expired afsluiten en hun jobs blokkeren, ook bij een geweigerde operatie of receipt-replay. '+tool.description,inputSchema:schema(tool.properties,tool.required),annotations:{readOnlyHint:false,destructiveHint:true,idempotentHint:true,openWorldHint:false}});
 contracts[tool.name]={path:tool.path,valid:tool.valid,result:tool.result};
}

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
 const attributed=Object.hasOwn(payload,'run_id');
 if(attributed&&!positive(payload.run_id))return fail('invalid_payload');
 if(Object.hasOwn(payload,'claim')&&(!attributed||!validClaim(payload.claim)))return fail('invalid_payload');
 const response=await post('/ingress',payload,env,fetcher,!attributed);
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
