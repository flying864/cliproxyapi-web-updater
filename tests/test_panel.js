// Node stdlib only; execute actual embedded panel JavaScript.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../cpa-updater.c'),'utf8');
const html=source.split('static const char *html =')[1].split(';\n')[0].trim().split('\n').map(x=>JSON.parse(x.trim())).join('');
assert.equal((html.match(/<button /g)||[]).length,2);
const nodes={};for(const id of ['key','check','update','current','latest','state','when','detail','connection','release'])nodes[id]={value:'',textContent:'',disabled:false,hidden:false,removeAttribute(k){delete this[k]}};
let timers=[],pending=[],calls=[],timerId=0;
const context={document:{getElementById:id=>nodes[id]},confirm:()=>true,encodeURIComponent,AbortController,setTimeout:(f,ms)=>{const id=++timerId;timers.push({id,f,ms});return id},clearTimeout:id=>{timers=timers.filter(t=>t.id!==id)},fetch:(url,options)=>{calls.push({url,options});return new Promise((resolve,reject)=>{const item={resolve,reject};pending.push(item);options.signal.addEventListener('abort',()=>{pending=pending.filter(x=>x!==item);reject(new Error('timeout'))})})}};
vm.runInNewContext(html.match(/<script>([\s\S]*)<\/script>/)[1],context);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
const reply=async body=>{assert.ok(pending.length);pending.shift().resolve({ok:true,status:200,json:async()=>body});await flush()};
const tick=async(ms=2000)=>{const i=timers.findIndex(t=>t.ms===ms);assert.ok(i>=0);const t=timers.splice(i,1)[0];t.f();await flush()};
const ready={protocol:1,state:'ready',current:'v8.0.55',latest:'v8.0.56',detail:'last result',updated_at:'now'};
(async()=>{
assert.ok(nodes.check.disabled);assert.ok(nodes.update.disabled);
nodes.key.value='secret';nodes.key.oninput();await flush();assert.equal(calls.length,1);
await tick(10000);assert.match(nodes.connection.textContent,/重连/);await tick();
await reply({state:'setup_required'});assert.ok(nodes.check.disabled);assert.ok(nodes.update.disabled);
await tick();await reply({...ready,protocol:2});assert.ok(nodes.check.disabled);
await tick();await reply(ready);assert.equal(nodes.check.disabled,false);assert.equal(nodes.update.disabled,false);
assert.equal(nodes.release.href,'https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.56');
nodes.check.onclick();await flush();pending.shift().reject(new TypeError('POST never reached server'));await flush();await tick();await reply({...ready,pending:false});assert.equal(nodes.check.disabled,false);calls=[];
nodes.check.onclick();nodes.check.onclick();nodes.update.onclick();await flush();assert.equal(calls.filter(x=>x.options.method==='POST').length,1);
await reply({message:'queued'});assert.ok(nodes.check.disabled);
await tick();pending.shift().reject(new TypeError('network down'));await flush();assert.equal(nodes.detail.textContent,'last result');assert.match(nodes.connection.textContent,/重连/);assert.ok(nodes.update.disabled);
await tick();await reply({...ready,state:'checking'});assert.ok(nodes.check.disabled);
await tick();await reply({...ready,state:'success',detail:'updated'});assert.equal(nodes.detail.textContent,'updated');assert.equal(nodes.check.disabled,false);
await tick();await reply({...ready,state:'current'});assert.equal(nodes.check.disabled,false);assert.ok(nodes.update.disabled);
await tick();await reply({...ready,state:'needs_recheck'});assert.equal(nodes.check.disabled,false);
await tick();await reply(ready);nodes.update.onclick();nodes.check.onclick();nodes.update.onclick();assert.equal(calls.filter(x=>x.options.method==='POST').length,2);assert.match(calls.at(-1).url,/update\?version=v8.0.56$/);
await reply({});await tick();await reply({...ready,latest:'https://evil.test/<script>'});assert.ok(nodes.release.hidden);
for(const c of calls){assert.equal(c.options.credentials,'omit');assert.equal(c.options.headers.Authorization,'Bearer secret')}
console.log('panel vm: initialization, serial polling, both actions, duplicate suppression, disconnect/recovery, safe links PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
