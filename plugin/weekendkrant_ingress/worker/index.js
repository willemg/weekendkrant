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
const claimSchema=schema({job_id:integer,attempt_id:integer,token:{...textSchema,maxLength:512},lease_until:textSchema},['job_id','attempt_id','token']);
export const TOOL={name:'submit_weekendkrant_fiche',description:'Sla één bronfiche uitsluitend op in de privé Weekendkrant-ingressqueue; publiceert niets publiek. De aangeleverde rolinstructie bepaalt welke transportvelden voor deze job gebruikt mogen worden. Transportvelden zoals run_id, mission_id, fiche_id en claim zijn geen fiche-inhoud. Geeft een compacte status en bij succes queue_item_id.',inputSchema:{type:'object',properties:{run_id:integer,claim:claimSchema,mission_id:{...textSchema,maxLength:128},fiche_id:{...textSchema,maxLength:128}},additionalProperties:true},annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:false,openWorldHint:false}};
export const TOOLS=[TOOL,
 {name:'start_sherlock_run',description:'Maak uitsluitend een nieuwe privé Weekendkrant-runstate aan en ontvang het toegewezen run_id en topic. Gebruik beide identiteiten gedurende die run.',inputSchema:schema({}),annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:false,openWorldHint:false}},
 {name:'filter_sherlock_sources',description:"Filter concrete reeds gereviewde pagina-URL's: leest uitsluitend privé Weekendkrant-state en wijzigt niets. URL's zijn opzoekwaarden en worden niet opgehaald of bezocht. Reserveert of registreert niets en doet geen deduplicatie van verhalen. Verschillende URL's over hetzelfde verhaal mogen terugkomen.",inputSchema:schema({urls:{type:'array',maxItems:50,items:{type:'string'}}}),annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
 {name:'record_sherlock_source',description:'Sla auditmetadata uitsluitend op in de privé Weekendkrant-state. De url wordt alleen als bronidentiteit opgeslagen en gecanonicaliseerd; de tool bezoekt die URL niet en verstuurt of publiceert niets naar die URL of een andere externe partij. Gebruik uitsluitend nadat de concrete pagina daadwerkelijk inhoudelijk beoordeeld is, nooit voor zoekresultaten, zoekfragmenten, ongeopende kandidaten of enkel door filtering geaccepteerde URL\'s. Een gekoppelde job gebruikt de actuele claim. outcome en rationale zijn compacte controleerbare auditnotities, geen verborgen redenering.',inputSchema:schema({run_id:integer,topic:topicSchema,url:textSchema,outcome:textSchema,rationale:textSchema,title:{type:['string','null']},claim:claimSchema},['run_id','topic','url','outcome','rationale']),annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:true,openWorldHint:false}},
 {name:'finish_sherlock_run',description:'Sluit uitsluitend bestaande privé Weekendkrant-runstate definitief af als completed of failed. De run kan daarna niet worden heropend of verder aangevuld.',inputSchema:schema({run_id:integer,status:{type:'string',enum:['completed','failed']}}),annotations:{readOnlyHint:false,destructiveHint:true,idempotentHint:true,openWorldHint:false}}
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
// Scheduled identities are backend-owned; explicit operator claim retains its identity.
const bounded=(x,n=512)=>nonempty(x)&&x.length<=n;
const refs=x=>Array.isArray(x)&&x.length<=32&&x.every(v=>bounded(v));
const boundedSchema=n=>({...textSchema,maxLength:n});
const referenceSchema={type:'array',maxItems:32,items:boundedSchema(512)};
const authoritySchema={job_id:integer,attempt_id:integer,token:boundedSchema(512)};
const authority=x=>positive(x.job_id)&&positive(x.attempt_id)&&bounded(x.token);
const validClaim=x=>strict(x,['job_id','attempt_id','token'],['lease_until'])&&authority(x);
const operationSchema={operation_id:boundedSchema(128)};
const stamp=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/.test(x)&&Number.isFinite(Date.parse(x));
const stateRefs={type:'array',maxItems:256,items:boundedSchema(128)};
const stateItem=schema({id:boundedSchema(128),text:boundedSchema(8192),refs:stateRefs});
const stateItems=item=>({type:'array',maxItems:64,items:item});
const leonardoStateSchema=schema({schema_version:{type:'integer',enum:[1]},dossier_id:boundedSchema(128),
 version:integer,previous_version:{type:'integer',minimum:0},hypotheses:stateItems(stateItem),
 claims:stateItems(schema({id:boundedSchema(128),text:boundedSchema(8192),kind:{type:'string',enum:['source_fact','inference']},support:stateRefs,counterevidence:stateRefs})),
 uncertainties:stateItems(stateItem),open_questions:stateItems(stateItem),processed_refs:stateRefs});
// The backend validates semantics, budgets and revision membership authoritatively.
const validLeonardoState=x=>object(x)&&new TextEncoder().encode(JSON.stringify(x)).length<=32768;
const missionSchema=schema({question:boundedSchema(8192),rationale:boundedSchema(8192),scope:boundedSchema(8192),refs:{...stateRefs,minItems:1}});
const missionsSchema={type:'array',maxItems:4,items:missionSchema};
const kuifjeResultSchema=schema({summary:boundedSchema(8192),limitations:boundedSchema(8192)});
const validMissions=x=>Array.isArray(x)&&x.length<=4&&x.every(m=>strict(m,['question','rationale','scope','refs'])&&['question','rationale','scope'].every(k=>bounded(m[k],8192))&&Array.isArray(m.refs)&&m.refs.length>0&&m.refs.length<=256&&m.refs.every(r=>bounded(r,128)));
const validKuifjeResult=x=>strict(x,['summary','limitations'])&&bounded(x.summary,8192)&&bounded(x.limitations,8192);
const generic=[
 {name:'recall_weekendkrant_part',path:'/jobs/leonardo-recall',description:'Lees één exacte onveranderlijke partrevisie die binnen de provenance van de huidige privé Weekendkrant-job is toegestaan. Vereist actuele claimautoriteit, ook bij retries. Wijzigt geen dossier-, bron- of jobstate; schrijft alleen recallaudit. Kies een attempt-lokale recall_id en herhaal dezelfde ref en recall_id bij een verloren antwoord. Retourneert ref, sha256, content en lokale cl100k_base-tokens en UTF-8-bytes van content. Maakt geen nieuwe job en haalt geen externe bron op.',properties:{...authoritySchema,ref:{type:'string',maxLength:128,pattern:'^part:[1-9][0-9]*:[1-9][0-9]*$'},recall_id:boundedSchema(128)},
 valid:x=>strict(x,['job_id','attempt_id','token','ref','recall_id'])&&authority(x)&&bounded(x.recall_id,128)&&bounded(x.ref,128)&&/^part:[1-9][0-9]*:[1-9][0-9]*$/.test(x.ref),
 result:(r,x)=>strict(r,['ref','sha256','content','bytes','tokens'])&&r.ref===x.ref&&typeof r.sha256==='string'&&/^[a-f0-9]{64}$/.test(r.sha256)&&typeof r.content==='string'&&positive(r.bytes)&&r.bytes===new TextEncoder().encode(r.content).length&&r.bytes<=8388608&&positive(r.tokens)&&r.tokens<=1048576?r:null},
 {name:'start_weekendkrant_executor',path:'/executor/start',description:'Meld de generieke executor aan voor één werkbeslissing. Herhaal zonder argumenten bij een verloren antwoord. executor_id:null betekent stoppen.',properties:{},
 valid:x=>strict(x,[]),
 result:r=>strict(r,['executor_id'])&&(r.executor_id===null||bounded(r.executor_id,128))?r:null},
 {name:'get_weekendkrant_job',path:'/executor/job',description:'Haal uitsluitend het reeds gebonden onveranderlijke jobpakket op met executor_id. Selecteert geen werk en maakt geen attempt. Valideer de ontvangen claim vóór uitvoering.',properties:{executor_id:boundedSchema(128)},
 valid:x=>strict(x,['executor_id'])&&bounded(x.executor_id,128),
 result:(r,x)=>strict(r,['executor_id','claim','role','input','input_refs','role_contract_ref','role_contract','output_contract_ref','output_contract','result_ref'],['run_id'])&&r.executor_id===x.executor_id&&strict(r.claim,['job_id','attempt_id','token','lease_until'])&&authority(r.claim)&&stamp(r.claim.lease_until)&&bounded(r.role,128)&&object(r.input)&&refs(r.input_refs)&&bounded(r.role_contract_ref)&&bounded(r.role_contract,65536)&&bounded(r.output_contract_ref)&&bounded(r.output_contract,65536)&&bounded(r.result_ref)&&(!Object.hasOwn(r,'run_id')||positive(r.run_id))?r:null},
 {name:'claim_weekendkrant_job',path:'/jobs/claim',description:'Claim één expliciet aangeleverde job, zonder werkselectie. Gebruik dezelfde activation_id voor de hele activatie en dezelfde operation_id en argumenten bij iedere transportretry. Een bevestigd antwoord kan een eerder ontvangstbewijs zijn: controleer lease en validate_weekendkrant_claim vóór uitvoering. Claim geen tweede job binnen dezelfde activatie.',properties:{...operationSchema,job_id:integer,activation_id:boundedSchema(128)},
 valid:x=>strict(x,['operation_id','job_id','activation_id'])&&positive(x.job_id)&&bounded(x.operation_id,128)&&bounded(x.activation_id,128),
 result:(r,x)=>strict(r,['claim'])&&r.claim===null?{claim:null}:strict(r,['job_id','attempt_id','token','lease_until','role','input_refs','output_contract_ref'])&&authority(r)&&r.job_id===x.job_id&&stamp(r.lease_until)&&bounded(r.role,128)&&refs(r.input_refs)&&bounded(r.output_contract_ref)?r:null},
 {name:'finish_weekendkrant_job',path:'/jobs/finish',description:'Registreer de terminale uitkomst en outputreferenties van de huidige job zonder inhoud te publiceren. Gebruik exact de velden en outputstructuur uit het aangeleverde outputcontract. Laat bij scheduled uitvoering operation_id weg. Herhaal bij een onzeker antwoord exact dezelfde terminale argumenten en nooit het inhoudelijke werk. succeeded en failed zijn terminaal; uncertain blokkeert de job voor expliciet operatoronderzoek.',properties:{...operationSchema,...authoritySchema,status:{type:'string',enum:['succeeded','failed','uncertain']},output_refs:referenceSchema,leonardo_state:leonardoStateSchema,kuifje_missions:missionsSchema,kuifje_result:kuifjeResultSchema,error:{type:['string','null'],minLength:1,maxLength:2048,pattern:'\\S'}},required:['job_id','attempt_id','token','status','output_refs'],
 valid:x=>strict(x,['job_id','attempt_id','token','status','output_refs'],['error','leonardo_state','kuifje_missions','kuifje_result','operation_id'])&&(!Object.hasOwn(x,'kuifje_missions')||validMissions(x.kuifje_missions))&&(!Object.hasOwn(x,'kuifje_result')||validKuifjeResult(x.kuifje_result))&&(!Object.hasOwn(x,'leonardo_state')||validLeonardoState(x.leonardo_state))&&(!Object.hasOwn(x,'operation_id')||bounded(x.operation_id,128))&&authority(x)&&['succeeded','failed','uncertain'].includes(x.status)&&refs(x.output_refs)&&(x.error==null||bounded(x.error,2048)),
 result:(r,x)=>strict(r,['job_id','attempt_id','job_status'])&&r.job_id===x.job_id&&r.attempt_id===x.attempt_id&&r.job_status===(x.status==='uncertain'?'blocked':x.status)?r:null},
 {name:'abandon_weekendkrant_job',path:'/jobs/abandon',description:'Geef een nog geldige claim op bij onzekere effecten: registreert uncertain en blokkeert de job, zonder toestemming voor nieuw inhoudelijk werk. Geef alleen een compacte foutnotitie, geen verborgen redenering. Laat bij scheduled uitvoering operation_id weg. Herhaal exact dezelfde argumenten als het antwoord verloren gaat.',properties:{...operationSchema,...authoritySchema,error:boundedSchema(2048)},required:['job_id','attempt_id','token','error'],
 valid:x=>strict(x,['job_id','attempt_id','token','error'],['operation_id'])&&(!Object.hasOwn(x,'operation_id')||bounded(x.operation_id,128))&&authority(x)&&bounded(x.error,2048),
 result:(r,x)=>strict(r,['job_id','attempt_id','job_status'])&&r.job_id===x.job_id&&r.attempt_id===x.attempt_id&&r.job_status==='blocked'?r:null},
 {name:'validate_weekendkrant_claim',path:'/jobs/validate',description:'Controleer de actuele claimautoriteit. Dit is een leasegevoelige controle, geen gecachte bevestiging. valid=false verbiedt nieuwe uitvoering of resultaatmutatie. valid=true is geen garantie dat externe neveneffecten exact één keer plaatsvinden.',properties:{...authoritySchema,lease_until:textSchema},required:['job_id','attempt_id','token'],
 valid:x=>strict(x,['job_id','attempt_id','token'],['lease_until'])&&authority(x),
 result:(r,x)=>strict(r,['job_id','attempt_id','claim_status','valid','lease_until'])&&r.job_id===x.job_id&&r.attempt_id===x.attempt_id&&['running','expired','uncertain','succeeded','failed'].includes(r.claim_status)&&r.valid===(r.claim_status==='running')&&stamp(r.lease_until)?r:null}
];
for(const tool of generic){
 const lookup=tool.name==='get_weekendkrant_job';
 const recall=tool.name==='recall_weekendkrant_part';
 TOOLS.push({name:tool.name,description:recall?tool.description:(lookup?'Leest uitsluitend privé Weekendkrant-jobstate; bezoekt geen referenties en wijzigt niets. ':'Werkt uitsluitend op privé Weekendkrant-jobstate; bezoekt geen input- of outputreferenties en publiceert niets extern. Een claimcontrole kan een verlopen attempt als expired markeren en de job blokkeren. ')+tool.description,inputSchema:schema(tool.properties,tool.required),annotations:{readOnlyHint:lookup,destructiveHint:!lookup&&!recall,idempotentHint:true,openWorldHint:false}});
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
 const mission=Object.hasOwn(payload,'mission_id');
 if(mission&&(attributed||!bounded(payload.mission_id,128)||!bounded(payload.fiche_id,128)||!validClaim(payload.claim)))return fail('invalid_payload');
 if(!mission&&Object.hasOwn(payload,'fiche_id'))return fail('invalid_payload');
 if(attributed&&!positive(payload.run_id))return fail('invalid_payload');
 if(Object.hasOwn(payload,'claim')&&((!attributed&&!mission)||!validClaim(payload.claim)))return fail('invalid_payload');
 const response=await post('/ingress',payload,env,fetcher,!attributed&&!mission);
 if(response.status==='error')return response;
 if(!positive(response.result.id))return fail('ingress_response_invalid');
 return {status:'success',queue_item_id:response.result.id};
}
export async function callTool(name,args,env,fetcher=fetch){
 if(name===TOOL.name)return submit(args,env,fetcher);
 if(['start_sherlock_run','start_weekendkrant_executor'].includes(name)&&args===undefined)args={};
 const contract=Object.hasOwn(contracts,name)?contracts[name]:null;
 if(!contract||!contract.valid(args))return fail('invalid_request');
 const response=await post(contract.path,args,env,fetcher);
 if(response.status==='error')return response;
 const result=contract.result(response.result,args);
 if(!result)return fail('response_invalid');
 return name==='start_weekendkrant_executor'?result:{status:'success',...result};
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
