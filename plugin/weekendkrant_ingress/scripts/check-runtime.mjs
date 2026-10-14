// Test/build requirement only; the deployed worker has its own hosting runtime.
// Response.json() sets the boundary: absent in 18.2.0, present in 18.3.0.
const [major,minor]=process.versions.node.split('.').map(Number);
const features={
 fetch:typeof globalThis.fetch==='function',
 Request:typeof globalThis.Request==='function',
 'Response.json':typeof globalThis.Response!=='undefined'&&typeof globalThis.Response.json==='function',
 'AbortSignal.timeout':typeof globalThis.AbortSignal!=='undefined'&&typeof globalThis.AbortSignal.timeout==='function',
 'Object.hasOwn':typeof Object.hasOwn==='function'
};
const missing=Object.keys(features).filter(name=>!features[name]);
if(major<18||(major===18&&minor<3)||missing.length){
 console.error(`Weekendkrant tests/build require Node.js >=18.3.0 with fetch, Request, Response.json(), AbortSignal.timeout() and Object.hasOwn(); found ${process.version}${missing.length?`; missing: ${missing.join(', ')}`:''}.`);
 process.exit(1);
}
