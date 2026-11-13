const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../cpa-updater.c'),'utf8');
const html=source.split('static const char *html =')[1].split(';\n')[0].trim().split('\n').map(x=>JSON.parse(x.trim())).join('');
assert.match(html,/<details[^>]*>[\s\S]*备份管理/);
const nodes={};function node(){return {value:'',textContent:'',disabled:false,hidden:false,children:[],appendChild(x){this.children.push(x)},replaceChildren(){this.children=[]},removeAttribute(k){delete this[k]}}}
for(const m of html.matchAll(/id='([^']+)'/g))nodes[m[1]]=node();
let calls=[],pending=[],timers=[],confirmed=false;
let clock=Date.now();const TestDate=class extends Date{static now(){return clock}};
const context={Date:TestDate,document:{getElementById:id=>nodes[id],createElement:node},confirm:()=>confirmed,encodeURIComponent,AbortController,setTimeout:(f,ms)=>{timers.push({f,ms});return f},clearTimeout:f=>{timers=timers.filter(t=>t.f!==f)},fetch:(url,options)=>{calls.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}))}};
vm.runInNewContext(html.match(/<script>([\s\S]*)<\/script>/)[1],context);
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve()};
const reply=async j=>{assert.ok(pending.length);pending.shift().resolve({ok:true,status:200,json:async()=>j});await flush()};
const tick=async()=>{const i=timers.findIndex(t=>t.ms===2000);assert.ok(i>=0);timers.splice(i,1)[0].f();await flush()};
const ready={protocol:1,backups_protocol:1,state:'ready',latest:'v1.2.3',pending:false};
const preview={protocol:1,state:'ready',token:'a'.repeat(32),items:[{id:'b'.repeat(32),name:'safe',kind:'runtime',created_at:'now',size_bytes:42,deletable:true,reason:''},{id:'c'.repeat(32),name:'protected',kind:'install',created_at:'then',size_bytes:99,deletable:false,reason:'latest'}],total_count:2,truncated:false};
(async()=>{
nodes.key.value='secret';nodes.key.oninput();await reply(ready);
assert.equal(calls.filter(c=>c.options.method==='POST').length,0);
nodes['backup-scan'].onclick();await flush();assert.equal(calls.at(-1).options.method,'POST');assert.match(calls.at(-1).url,/\/backups$/);
await reply({message:'queued'});assert.match(nodes['backup-state'].textContent,/排队/);assert.ok(nodes.check.disabled);
await tick();assert.match(calls.at(-1).url,/\/backups$/);await reply({...preview,pending:true});assert.equal(nodes['backup-list'].children.length,0,'pending does not show stale preview');assert.ok(nodes.check.disabled);await tick();await reply(preview);
assert.equal(nodes['backup-delete'].disabled,true);
const box=nodes['backup-list'].children[0].children[0];assert.equal(box.checked,false);box.checked=true;box.onchange();assert.match(nodes['backup-total'].textContent,/1.*42/);
nodes['backup-delete'].onclick();assert.equal(pending.length,0,'cancel sends no POST');
confirmed=true;nodes['backup-delete'].onclick();assert.match(calls.at(-1).url,/cleanup\?preview=a{32}&ids=b{32}$/);await reply({});
assert.match(nodes['backup-state'].textContent,/排队/);await tick();await reply({...preview,state:'success',token:'',items:[],detail:'deleted'});assert.match(nodes['backup-state'].textContent,/deleted/);
await tick();await reply(ready);
// Failed delivery with an unchanged preview must unlock without replaying POST.
nodes['backup-scan'].onclick();await reply({});await tick();await reply(preview);
nodes['backup-scan'].onclick();pending.shift().reject(new Error('not delivered'));await flush();
const countBefore=calls.filter(c=>c.options.method==='POST').length;await tick();await reply(preview);
assert.equal(nodes['backup-scan'].disabled,false);assert.equal(nodes.check.disabled,false);assert.match(nodes['backup-state'].textContent,/重新扫描/);assert.equal(calls.filter(c=>c.options.method==='POST').length,countBefore);
await tick();await reply(ready);
// Pagination clears previous selections and uses a bound numeric page command.
nodes['backup-scan'].onclick();await reply({});await tick();await reply({...preview,page:0,page_count:2,total_count:102,truncated:true});
assert.equal(nodes['backup-next'].disabled,false);nodes['backup-next'].onclick();assert.match(calls.at(-1).url,/backups\?page=1$/);await reply({});await tick();await reply({...preview,token:'e'.repeat(32),page:1,page_count:2});
assert.equal(nodes['backup-prev'].disabled,false);assert.equal(nodes['backup-next'].disabled,true);assert.equal(nodes['backup-list'].children[0].children[0].checked,false);
const expiring=nodes['backup-list'].children[0].children[0];expiring.checked=true;expiring.onchange();clock+=600001;nodes['backup-delete'].onclick();assert.equal(pending.length,0);assert.match(nodes['backup-state'].textContent,/过期/);assert.equal(nodes['backup-delete'].disabled,true);
await tick();await reply(ready);
// A backup action shares the existing in-flight GET gate with upgrades.
await tick();const before=calls.length;nodes['backup-scan'].onclick();nodes.check.onclick();assert.equal(calls.length,before);await reply(ready);assert.equal(calls.length,before+1);assert.match(calls.at(-1).url,/\/backups$/);await reply({});await tick();
const many={...preview,token:'d'.repeat(32),items:Array.from({length:21},(_,i)=>({...preview.items[0],id:i.toString(16).padStart(32,'0')}))};await reply(many);
for(const row of nodes['backup-list'].children){const input=row.children[0];input.checked=true;input.onchange()}
assert.match(nodes['backup-total'].textContent,/20.*840/);assert.equal(nodes['backup-list'].children[20].children[0].checked,false);
nodes['backup-scan'].onclick();pending.shift().reject(new Error('timeout'));await flush();const posts=calls.filter(c=>c.options.method==='POST').length;await tick();await reply(preview);assert.equal(calls.filter(c=>c.options.method==='POST').length,posts);
await tick();await reply(ready);nodes['backup-scan'].onclick();nodes.key.value='other';nodes.key.oninput();await reply({});assert.equal(nodes['backup-list'].children.length,0);await reply({...ready,backups_protocol:undefined});assert.equal(nodes['backup-scan'].disabled,true);assert.equal(nodes.check.disabled,false);assert.match(nodes['backup-state'].textContent,/后台.*更新/);
console.log('backup panel: manual scan, unchecked selection, cancel, token binding, queue result GET, no replay, key isolation, legacy worker PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
