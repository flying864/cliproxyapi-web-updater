// Node stdlib only; execute actual embedded panel JavaScript.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../cpa-updater.c'),'utf8');
const html=source.split('static const char *html =')[1].split(';\n')[0].trim().split('\n').map(x=>JSON.parse(x.trim())).join('');
assert.match(html, /prefers-color-scheme: dark/);
assert.match(html, /aria-describedby='key-help'/);
assert.match(html, /<main/);
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
await tick();assert.equal(calls.length,0,'empty key must not send unauthenticated requests');
nodes.key.value='secret';await tick();assert.equal(calls.length,1,'silent autofill starts status read');
nodes.key.oninput();nodes.key.onchange();assert.equal(calls.length,1,'duplicate events do not restart authentication');
await tick(10000);assert.match(nodes.connection.textContent,/重连/);await tick();
await reply({state:'setup_required'});assert.ok(nodes.check.disabled);assert.ok(nodes.update.disabled);
await tick();await reply({...ready,protocol:2});assert.ok(nodes.check.disabled);
await tick();await reply(ready);assert.equal(nodes.check.disabled,false);assert.equal(nodes.update.disabled,false);
assert.equal(nodes.state.textContent,'发现可用更新');
assert.match(html, /:focus-visible/);
assert.match(html, /grid-template-columns: 1fr/);
assert.match(html, /aria-live='polite'/);
assert.doesNotMatch(html, /sessionStorage|innerHTML|setItem\s*\(/);
assert.equal(nodes.release.href,'https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.56');
await tick();
assert.equal(nodes.check.disabled,false,'background GET must not disable check');
assert.equal(nodes.update.disabled,false,'background GET must not disable update');
const beforeQueued=calls.length;
nodes.check.onclick();nodes.check.onclick();nodes.update.onclick();await flush();
assert.equal(calls.length,beforeQueued,'action waits for GET instead of overlapping');
assert.ok(nodes.check.disabled,'queued action locks buttons');
await reply(ready);
assert.equal(calls.length,beforeQueued+1,'GET completion dispatches exactly one queued POST');
assert.equal(calls.at(-1).options.method,'POST');
await reply({});await tick();await reply({...ready,updated_at:'after queued check'});
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
// A queued update is bound to the version confirmed at click time, not the next poll.
await tick();await reply(ready);await tick();
let confirmation='';context.confirm=message=>{confirmation=message;return true};
const posts=()=>calls.filter(x=>x.options.method==='POST').length;
let count=posts();nodes.update.onclick();nodes.update.onclick();
assert.match(confirmation,/v8.0.56/);assert.equal(posts(),count);
await reply({...ready,latest:'v8.0.57'});
assert.equal(posts(),count+1);assert.match(calls.at(-1).url,/update\?version=v8.0.56$/);
await reply({});assert.ok(nodes.check.disabled);
await tick();await reply({...ready,latest:'v8.0.57',updated_at:'done'});
// The fresh GET may veto a queued operation: worker pending, busy, incompatible or offline.
for(const status of [{...ready,pending:true},{...ready,state:'updating'},{...ready,protocol:2},{...ready,state:'setup_required'},null]){
  await tick();nodes.check.onclick();count=posts();
  if(status)await reply(status);
  else {pending.shift().reject(new TypeError('offline'));await flush()}
  assert.equal(posts(),count);assert.ok(nodes.check.disabled);assert.ok(nodes.update.disabled);
  await tick();await reply(ready);
}
// A queued update must still be actionable after the pending GET returns.
for(const state of ['current','needs_recheck','error']){
  await tick();nodes.update.onclick();count=posts();
  await reply({...ready,state});
  assert.equal(posts(),count,'queued update must not dispatch after state becomes '+state);
  assert.match(nodes.connection.textContent,/未提交/);
  await tick();await reply(ready);
}
// Changing a key invalidates the old GET and cancels unsent actions.
await tick();nodes.check.onclick();count=posts();
nodes.key.value='replacement';nodes.key.oninput();assert.ok(nodes.check.disabled);
await reply({...ready,latest:'v8.0.99'});
assert.ok(nodes.check.disabled,'old key response cannot authorize replacement');
assert.notEqual(nodes.latest.textContent,'v8.0.99');assert.equal(posts(),count);
assert.equal(calls.at(-1).options.headers.Authorization,'Bearer replacement');
assert.equal(calls.at(-1).options.method,'GET');
await reply(ready);assert.equal(nodes.check.disabled,false);
// An already submitted POST is never replayed under a replacement key.
nodes.check.onclick();count=posts();nodes.key.value='third';nodes.key.oninput();
await reply({});assert.equal(posts(),count);assert.ok(nodes.check.disabled);
assert.equal(calls.at(-1).options.method,'GET');
assert.equal(calls.at(-1).options.headers.Authorization,'Bearer third');
await reply({...ready,pending:true});assert.ok(nodes.check.disabled);
await tick();await reply(ready);assert.equal(nodes.check.disabled,false);
await tick();nodes.key.value='';nodes.key.oninput();await reply(ready);
assert.ok(nodes.check.disabled);assert.ok(nodes.update.disabled);
assert.equal(pending.length,0);assert.equal(posts(),count);
// Silent key replacement must discard old GET/queued actions, just like input.
nodes.key.value='third';nodes.key.oninput();await reply(ready);
await tick();nodes.check.onclick();count=posts();nodes.key.value='silent';
await reply({...ready,current:'v9.9.99'});
assert.equal(posts(),count);assert.equal(nodes.current.textContent,'—');
assert.equal(calls.at(-1).options.headers.Authorization,'Bearer silent');
await reply(ready);assert.equal(nodes.check.disabled,false);
// A click immediately after silent replacement cannot submit using stale state.
nodes.key.value='click-race';nodes.update.onclick();assert.equal(posts(),count);
assert.equal(calls.at(-1).options.method,'GET');await reply(ready);
// Clearing without events invalidates a pending response and stops network reads.
await tick();nodes.key.value='';await reply(ready);
assert.equal(nodes.current.textContent,'—');assert.equal(nodes.state.textContent,'等待连接');
assert.ok(nodes.check.disabled);assert.equal(pending.length,0);
const beforeEmpty=calls.length;await tick();assert.equal(calls.length,beforeEmpty);
// A change-only fill also wakes the connection; opening never submits a POST.
nodes.key.value='change-only';nodes.key.onchange();await reply(ready);
assert.equal(nodes.check.disabled,false);assert.equal(posts(),count);
// A key changed while confirmation is open must not inherit the old approval.
context.confirm=()=>{nodes.key.value='confirmation-race';return true};
nodes.update.onclick();assert.equal(posts(),count,'confirmation key change must not POST');
assert.equal(calls.at(-1).options.method,'GET');await reply(ready);
context.confirm=()=>true;
// Same-value input/change events must preserve a submitted action lock.
nodes.check.onclick();count=posts();nodes.key.oninput();nodes.key.onchange();
assert.ok(nodes.check.disabled);assert.equal(posts(),count);
nodes.key.value='post-replacement';await reply({});
assert.equal(posts(),count);assert.equal(calls.at(-1).options.method,'GET');await reply(ready);
for(const c of calls)assert.equal(c.options.credentials,'omit');
console.log('panel vm: silent autofill, key isolation, polling stability, queued actions, no POST replay PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
