// Synthetic credentials only. Official enc::v2:: fixture, commit 953fb2444350c6c36052dda46cac0abce6b23ea6.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../cpa-updater.c'),'utf8');
const html=source.split('static const char *html =')[1].split(';\n')[0].trim().split('\n').map(x=>JSON.parse(x.trim())).join('');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
const origin='https://panel.test:8317';
function fixture(state={},version=0){
 const data=Buffer.from(JSON.stringify({state:{apiBase:origin,managementKey:'synthetic-key',rememberPassword:true,...state},version}));
 const salt=Buffer.from('cli-proxy-api-webui::secure-storage|panel.test:8317');
 return 'enc::v2::'+Buffer.from(data.map((b,i)=>b^salt[i%salt.length])).toString('base64');
}
function boot({raw=fixture(),logged='true',top=false,cross=false,denied=false}={}){
 const nodes={};for(const id of ['key','check','update','current','latest','state','when','detail','connection','release'])nodes[id]={value:'',textContent:'',disabled:false,removeAttribute(k){delete this[k]}};
 const reads=[],calls=[],events={},timers=[];let storage={getItem(k){reads.push(k);if(denied)throw Error('denied');assert.ok(['cli-proxy-auth','isLoggedIn'].includes(k));return k==='cli-proxy-auth'?raw:logged}};
 const window={localStorage:storage,location:new URL(origin+'/plugin'),addEventListener:(k,f)=>events[k]=f};
 window.parent=top?window:{document:{},location:new URL(origin+'/management.html'),localStorage:storage};
 if(cross)Object.defineProperty(window.parent,'document',{get(){throw Error('cross origin')}});
 const context={window,document:{getElementById:id=>nodes[id]},URL,TextEncoder,TextDecoder,Uint8Array,atob,AbortController,confirm:()=>true,setTimeout:(f,ms)=>{timers.push({f,ms});return timers.length},clearTimeout:()=>{},fetch:(url,options)=>{calls.push({url,options});return new Promise(()=>{})}};
 vm.runInNewContext(script,context);
 return {nodes,calls,reads,context,events,timers,change(value,login='true',key='cli-proxy-auth'){raw=value;logged=login;events.storage?.({key,storageArea:storage});},run(s){return vm.runInNewContext(s,context)}};
}
const b=boot();assert.equal(b.nodes.key.value,'synthetic-key','same-origin remembered session is reused');assert.equal(b.calls.length,1);assert.equal(b.calls[0].options.headers.Authorization,'Bearer synthetic-key');
for(const opts of [{top:true},{cross:true},{denied:true},{logged:null},{logged:'false'},{raw:fixture({rememberPassword:false})},{raw:fixture({managementKey:'  '})},{raw:fixture({},1)},{raw:'enc::v1::AAAA'},{raw:'enc::v2::!!!!'},{raw:JSON.stringify({state:{}})}]){
 const x=boot(opts);assert.equal(x.nodes.key.value,'');assert.equal(x.calls.length,0);
 if(opts.top||opts.cross)assert.equal(x.reads.length,0);
}
for(const apiBase of [origin+'/prefix',origin+'/v0/management',origin+'?x',origin+'#x','https://panel.test:8318','https://other.test:8317','https://user@panel.test:8317'])assert.equal(boot({raw:fixture({apiBase})}).calls.length,0);
assert.equal(boot({raw:fixture({apiBase:origin+'/'})}).nodes.key.value,'synthetic-key');
const logout=boot();logout.run("render({protocol:1,state:'ready',latest:'v8.0.56',detail:'old-secret-result'});online=true;buttons()");
logout.change(null,null);assert.equal(logout.nodes.key.value,'');assert.equal(logout.nodes.detail.textContent,'');assert.ok(logout.nodes.check.disabled);logout.nodes.check.onclick();assert.equal(logout.calls.length,1);
const manual=boot();manual.nodes.key.value='manual-key';manual.nodes.key.oninput();manual.change(fixture({managementKey:'another-key'}));assert.equal(manual.nodes.key.value,'manual-key');manual.nodes.key.value='';manual.nodes.key.oninput();manual.change(fixture());assert.equal(manual.nodes.key.value,'');
const noEvent=boot();noEvent.change(null,null,'unrelated');assert.equal(noEvent.nodes.key.value,'synthetic-key');noEvent.run("request('/check','POST')");assert.equal(noEvent.nodes.key.value,'');assert.equal(noEvent.calls.length,1,'preflight revocation blocks POST even without a storage event');
const once=boot({raw:null});once.change(fixture(), 'true','unrelated');once.run('syncKey()');assert.equal(once.nodes.key.value,'','polling cannot import');once.change(fixture());assert.equal(once.nodes.key.value,'synthetic-key','explicit storage event may import');
console.log('PASS official v2 reuse, schema/origin/storage guards, logout invalidation, manual precedence and event-only imports');
