#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>
#define JSMN_PARENT_LINKS
#define JSMN_STATIC
#define JSMN_STRICT
#include "jsmn.h"

typedef struct { void *ptr; size_t len; } cliproxy_buffer;
typedef int (*host_call_fn)(void*, const char*, const uint8_t*, size_t, cliproxy_buffer*);
typedef void (*host_free_fn)(void*, size_t);
typedef struct { uint32_t abi_version; void *host_ctx; host_call_fn call; host_free_fn free_buffer; } cliproxy_host_api;
typedef int (*plugin_call_fn)(char*, uint8_t*, size_t, cliproxy_buffer*);
typedef void (*plugin_free_fn)(void*, size_t);
typedef void (*plugin_shutdown_fn)(void);
typedef struct { uint32_t abi_version; plugin_call_fn call; plugin_free_fn free_buffer; plugin_shutdown_fn shutdown; } cliproxy_plugin_api;

#ifndef CPA_TEST
#undef CPA_RUN
#undef CPA_PUBLIC
#undef CPA_STATUS_UID
#define CPA_RUN "/run/cliproxy-updater"
#define CPA_STATUS_UID 0
#define CPA_PUBLIC "/var/lib/cliproxy-updater-status"
#endif
#define REQUEST_FILE CPA_RUN "/inbox/request"
#define PROCESSING_FILE CPA_RUN "/processing"
#define STATUS_FILE CPA_PUBLIC "/status.json"

static const char *html =
"<!doctype html>\n"
"<html lang='zh-CN'>\n"
"<head>\n"
"<meta charset='utf-8'>\n"
"<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
"<meta name='color-scheme' content='light dark'>\n"
"<title>版本更新 · CLIProxyAPI</title>\n"
"<style>\n"
"/* Quiet Paper surfaces reference CPA Management Center and the store's Key Policy\n"
"   plugin. Compact hierarchy and high-contrast actions; no external UI dependencies. */\n"
":root {\n"
"  color-scheme: light dark;\n"
"  --bg: #faf9f5; --card: #ffffff; --surface: #f4f3ef;\n"
"  --text: #2d2a26; --muted: #6d6760; --border: #dedbd4;\n"
"  --action: #35322e; --hover: #504b44; --on-action: #fff;\n"
"  --warning: #854321; --warning-bg: #faf3e8;\n"
"}\n"
"@media (prefers-color-scheme: dark) {\n"
"  :root {\n"
"    --bg: #1e1d1b; --card: #26241f; --surface: #2f2d28;\n"
"    --text: #ede9e3; --muted: #b8b2a9; --border: #49453e;\n"
"    --action: #e5e1d8; --hover: #ffffff; --on-action: #24221f;\n"
"    --warning: #ebc297; --warning-bg: #352c22;\n"
"  }\n"
"}\n"
"* { box-sizing: border-box; }\n"
"body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 system-ui, -apple-system, 'Segoe UI', sans-serif; }\n"
"main { width: min(100%, 1120px); margin: 0 auto; padding: 14px 18px; }\n"
"header { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 12px; }\n"
".eyebrow { color: var(--muted); font-size: 12px; }\n"
"h1 { margin: 4px 0; font-size: 22px; line-height: 1.35; letter-spacing: -.025em; }\n"
"h2 { font-size: 16px; margin: 0; }\n"
"p { margin: 8px 0; }\n"
".muted, dt, .help { color: var(--muted); }\n"
".help { font-size: 13px; }\n"
".card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; min-width: 0; box-shadow: 0 1px 2px rgb(0 0 0 / .025); }\n"
".card-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 10px; }\n"
".tag { padding: 3px 9px; border: 1px solid var(--border); border-radius: 6px; color: var(--muted); font-size: 12px; white-space: nowrap; }\n"
".access { margin-bottom: 10px; display: grid; grid-template-columns: minmax(180px, .65fr) minmax(0, 1.35fr); gap: 8px 18px; align-items: start; }\n"
".access h2 { margin-bottom: 4px; }\n"
"label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; }\n"
"input { width: 100%; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font: inherit; }\n"
"input::placeholder { color: var(--muted); }\n"
".workspace { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr); gap: 12px; align-items: start; }\n"
".versions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; margin: 0 0 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }\n"
".versions div { padding: 10px 12px; min-width: 0; }\n"
".versions div + div { border-left: 1px solid var(--border); }\n"
"dt { font-size: 13px; }\n"
"dd { margin: 4px 0 0; font: 600 clamp(18px, 2.5vw, 23px)/1.4 ui-monospace, monospace; letter-spacing: -.04em; overflow-wrap: anywhere; }\n"
".actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }\n"
"button { min-height: 44px; padding: 10px 18px; border: 1px solid var(--border); border-radius: 8px; background: var(--card); color: var(--text); font: inherit; font-weight: 600; cursor: pointer; }\n"
"button:not(:disabled):hover { background: var(--surface); border-color: var(--muted); }\n"
".primary { background: var(--action); border-color: var(--action); color: var(--on-action); }\n"
".primary:not(:disabled):hover { background: var(--hover); }\n"
"button:disabled { opacity: .45; cursor: not-allowed; }\n"
":focus-visible { outline: 2px solid var(--muted); outline-offset: 3px; }\n"
"a { color: var(--text); text-underline-offset: 4px; }\n"
"a:hover { text-decoration-thickness: 2px; }\n"
".docs { font-size: 13px; white-space: nowrap; }\n"
".connection { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }\n"
".notice { margin: 10px 0 0; background: var(--warning-bg); color: var(--warning); padding: 10px 12px; border-radius: 8px; font-size: 13px; }\n"
".notice strong { display: block; margin-bottom: 4px; }\n"
".status-line { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }\n"
"#state { font-size: 15px; overflow-wrap: anywhere; }\n"
".timestamp { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }\n"
"pre { max-height: 160px; overflow-y: auto; margin: 10px 0 0; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.6 ui-monospace, monospace; }\n"
"pre:empty { display: none; }\n"
".result-help { border-top: 1px solid var(--border); padding-top: 10px; margin-top: 10px; }\n"
"footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; margin-top: 10px; color: var(--muted); font-size: 12px; }\n"
"[hidden] { display: none !important; }\n"
"@media (max-width: 800px) {\n"
"  .workspace { grid-template-columns: 1fr; }\n"
"}\n"
"@media (max-width: 600px) {\n"
"  main { padding: 12px; }\n"
"  header { align-items: flex-start; }\n"
"  .card { padding: 12px; }\n"
"  .access { grid-template-columns: 1fr; gap: 6px; }\n"
"  .versions { grid-template-columns: repeat(2, minmax(0, 1fr)); }\n"
"  .versions div { padding: 10px 12px; }\n"
"  .versions div + div { border-left: 1px solid var(--border); }\n"
"  .actions button { flex: 1; padding-inline: 10px; }\n"
"}\n"
"</style>\n"
"</head>\n"
"<body>\n"
"<main>\n"
"<header>\n"
"<div><div class='eyebrow'>CLIProxyAPI / 插件</div><h1>版本更新</h1><p class='muted'>掌握当前版本，按需更新服务。</p></div>\n"
"</header>\n"
"<section class='card access' aria-labelledby='access-title'>\n"
"<div><h2 id='access-title'>连接管理服务</h2><p class='help'>管理密钥仅在当前页面使用。</p><p id='connection' class='connection' role='status' aria-live='polite'>未复用登录时请输入管理密钥，自动读取状态</p></div>\n"
"<div><label for='key'>管理密钥</label><input id='key' type='password' autocomplete='off' spellcheck='false' aria-describedby='key-help' placeholder='输入 CLIProxyAPI 管理密钥'>\n"
"<p id='key-help' class='help'>不是客户端 API Key。同源管理中心已记住密码时自动复用；否则请手动输入。插件不保存密钥。</p></div>\n"
"</section>\n"
"<div class='workspace'>\n"
"<section class='card' aria-labelledby='version-title'>\n"
"<div class='card-head'><h2 id='version-title'>版本信息</h2><span class='tag'>官方正式版</span></div>\n"
"<dl class='versions'>\n"
"<div><dt>当前运行版本</dt><dd id='current'>—</dd></div>\n"
"<div><dt>最新正式版本</dt><dd id='latest'>—</dd></div>\n"
"</dl>\n"
"<a id='release' hidden target='_blank' rel='noopener noreferrer'>查看官方更新日志 ↗</a>\n"
"<div class='actions'>\n"
"<button id='check' type='button' disabled>检查版本</button>\n"
"<button id='update' type='button' class='primary' disabled>立即更新</button>\n"
"</div>\n"
"<p class='help'>手动确认后才会升级，不会自动安装更新。</p>\n"
"<div class='notice'><strong>更新前请留意</strong>升级会短暂中断 API，请避开使用高峰。失败时尝试恢复旧二进制，<b>不恢复配置或 OAuth 数据</b>。</div>\n"
"</section>\n"
"<section class='card' aria-labelledby='result-title'>\n"
"<div class='card-head'><h2 id='result-title'>最近状态</h2><span class='tag'>自动同步</span></div>\n"
"<div class='status-line'><strong id='state' role='status' aria-live='polite'>等待连接</strong><span class='timestamp'>状态更新时间 · <span id='when'>—</span></span></div>\n"
"<pre id='detail' aria-label='最近操作详情' tabindex='0'></pre>\n"
"<p class='help result-help'>服务重启时页面会自动重连。短暂断线不代表更新失败，请以恢复后的状态为准。</p>\n"
"</section>\n"
"</div>\n"
"<footer><span>CPA Web Updater · 第三方更新插件</span><a class='docs' href='https://github.com/flying864/cliproxyapi-web-updater#readme' target='_blank' rel='noopener noreferrer'>使用文档 ↗</a><span>检查 → 确认 → 更新</span></footer>\n"
"<noscript><p class='notice'>请启用 JavaScript 后使用版本检查与更新功能。</p></noscript>\n"
"</main>\n"
"<script>\n"
"// Presentation labels do not change backend state values or action guards.\n"
"const stateLabels = {\n"
"  idle: '等待检查', ready: '发现可用更新', current: '已是最新版本',\n"
"  needs_recheck: '请重新检查版本', up_to_date: '已是最新版本',\n"
"  checking: '正在检查版本', updating: '正在更新，请勿关闭服务',\n"
"  downloading: '正在下载并校验发布包', backing_up: '正在备份程序与数据',\n"
"  installing: '正在安装更新，API 将短暂断开', verifying: '正在验证版本与服务健康',\n"
"  success: '更新成功', error: '操作失败，请查看详情', failed: '更新失败',\n"
"  rollback_failed: '恢复失败，需要人工处理', rolled_back: '已恢复旧版本',\n"
"  interrupted: '操作中断，请重新检查', setup_required: '请先完成服务端安装',\n"
"  needs_setup: '请先完成服务端安装'\n"
"}\n"
";\n"
"const api='/v0/management/plugins/cpa-updater',el=id=>document.getElementById(id);\n"
"let last=null,inflight=false,online=false,waiting=false,uncertain=false,baseline='',timer=null,queued=null,generation=0,observedKey='';\n"
"const version=v=>typeof v==='string'&&v.length<40&&/^v[0-9]+[.][0-9]+[.][0-9]+$/.test(v);\n"
"const terminal=new Set(['idle','ready','current','needs_recheck','up_to_date','success','error','failed','rollback_failed','rolled_back','interrupted','setup_required','needs_setup']);\n"
"const signature=j=>JSON.stringify([j.state,j.updated_at,j.detail,j.current,j.latest]);\n"
"function buttons(){\n"
"  const enabled=!!el('key').value.trim()&&el('key').value.trim()===observedKey&&online&&!waiting&&last&&last.pending!==true&&last.protocol===1&&terminal.has(last.state)&&!['setup_required','needs_setup'].includes(last.state);\n"
"  el('check').disabled=!enabled;\n"
"  el('update').disabled=!(enabled&&last.state==='ready'&&version(last.latest));\n"
"}\n"
"function render(j){\n"
"  last=j;\n"
"  for(const [id,key] of [['current','current'],['latest','latest'],['when','updated_at'],['detail','detail']])el(id).textContent=typeof j[key]==='string'?j[key]:'—';\n"
"  el('state').textContent=stateLabels[j.state]||'未知状态（'+String(j.state||'未提供')+'）';\n"
"  const link=el('release');\n"
"  link.hidden=!version(j.latest);\n"
"  if(!link.hidden)link.href='https://github.com/router-for-me/CLIProxyAPI/releases/tag/'+j.latest;\n"
"  else link.removeAttribute('href');\n"
"}\n"
"function schedule(){\n"
"  clearTimeout(timer);\n"
"  timer=setTimeout(()=>request('/status'),2000);\n"
"}\n"
"async function request(path,method='GET'){\n"
"  if(syncKey()&&method==='POST'){request('/status');return;}\n"
"  if(inflight)return;\n"
"  const key=el('key').value.trim();\n"
"  if(!key){\n"
"    buttons();\n"
"    schedule(); // Local value check only; no unauthenticated network request.\n"
"    return;\n"
"  }\n"
"  const epoch=generation;\n"
"  inflight=true;\n"
"  buttons();\n"
"  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);\n"
"  try{\n"
"    const r=await fetch(api+path,{method,signal:controller.signal,cache:'no-store',credentials:'omit',headers:{Authorization:'Bearer '+key}});\n"
"    const j=await r.json();\n"
"    syncKey();\n"
"    if(epoch!==generation)return;\n"
"    if(!r.ok){\n"
"      online=false;\n"
"      el('connection').textContent='HTTP '+r.status+'：'+(j.error||'请求未被接受');\n"
"      if(method==='POST')waiting=false;\n"
"      return;\n"
"    }\n"
"    online=true;\n"
"    el('connection').textContent='已连接';\n"
"    if(method==='GET'){\n"
"      if(waiting&&(signature(j)!==baseline||(uncertain&&j.pending===false&&terminal.has(j.state)))){\n"
"        waiting=false;\n"
"        uncertain=false;\n"
"      }\n"
"      render(j);\n"
"    }\n"
"    else{\n"
"      el('connection').textContent='请求已提交，等待状态更新';\n"
"    }\n"
"  }\n"
"  catch(e){\n"
"    syncKey();\n"
"    if(epoch!==generation)return;\n"
"    if(method==='POST')uncertain=true;\n"
"    online=false;\n"
"    el('connection').textContent='连接中断，正在重连；操作结果以恢复后的状态为准';\n"
"  }\n"
"  finally{\n"
"    clearTimeout(timeout);\n"
"    inflight=false;\n"
"    syncKey();\n"
"    if(epoch!==generation){request('/status');return;}\n"
"    if(queued){\n"
"      const path=queued;queued=null;\n"
"      if(online&&last&&last.protocol===1&&last.pending!==true&&terminal.has(last.state)&&!['setup_required','needs_setup'].includes(last.state)&&(path==='/check'||(last.state==='ready'&&version(last.latest)))){waiting=true;uncertain=false;baseline=signature(last);request(path,'POST');return;}\n"
"      waiting=false;\n"
"      el('connection').textContent+=' · 操作未提交：状态已变化或连接不可用，请核对后重试';\n"
"    }\n"
"    buttons();\n"
"    schedule();\n"
"  }\n"
"}\n"
"function submit(action){\n"
"  if(syncKey()){request('/status');return;}\n"
"  if(el(action).disabled||waiting)return;\n"
"  const v=last.latest;\n"
"  if(action==='update'&&!confirm('确认升级至 '+v+'？API 将短暂断开。'))return;\n"
"  if(syncKey()){request('/status');return;}\n"
"  waiting=true;\n"
"  uncertain=false;\n"
"  baseline=signature(last);\n"
"  buttons();\n"
"  const path=action==='check'?'/check':'/update?version='+encodeURIComponent(v);\n"
"  if(inflight)queued=path;\n"
"  else request(path,'POST');\n"
"}\n"
"el('check').onclick=()=>submit('check');\n"
"el('update').onclick=()=>submit('update');\n"
"// Official persisted schema/version and v2 codec: Management Center 953fb2444350c6c36052dda46cac0abce6b23ea6.\n"
"let authStorage=null,automaticKey='',manualAuth=false;\n"
"function savedKey(){\n"
"  try{\n"
"    if(!authStorage||authStorage.getItem('isLoggedIn')!=='true')return '';\n"
"    const raw=authStorage.getItem('cli-proxy-auth');\n"
"    if(typeof raw!=='string'||!raw.startsWith('enc::v2::')||raw.length>65536)return '';\n"
"    const binary=atob(raw.slice(9)),salt=new TextEncoder().encode('cli-proxy-api-webui::secure-storage|'+window.location.host);\n"
"    const bytes=Uint8Array.from(binary,(c,i)=>c.charCodeAt(0)^salt[i%salt.length]);\n"
"    const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));\n"
"    if(!data||data.version!==0||!data.state||typeof data.state!=='object')return '';\n"
"    const s=data.state;\n"
"    if(s.rememberPassword!==true||typeof s.managementKey!=='string'||!s.managementKey.trim()||typeof s.apiBase!=='string')return '';\n"
"    // Root API only: no prefix, query, credentials, fragment or alternate origin/port.\n"
"    if(s.apiBase.replace(/\\/+$/,'')!==window.location.origin)return '';\n"
"    return s.managementKey.trim();\n"
"  }catch(e){return '';}\n"
"}\n"
"function refreshSavedAuth(importKey=false){\n"
"  if(manualAuth)return;\n"
"  const key=savedKey();\n"
"  if(automaticKey&&el('key').value.trim()!==automaticKey){manualAuth=true;automaticKey='';return;}\n"
"  if(automaticKey&&key!==automaticKey){el('key').value='';automaticKey='';syncKey();}\n"
"  if(importKey&&key&&!automaticKey&&!el('key').value.trim()){automaticKey=key;el('key').value=key;syncKey();}\n"
"}\n"
"function initSavedAuth(){\n"
"  try{\n"
"    if(typeof window==='undefined'||window.parent===window||!window.parent.document||window.parent.location.origin!==window.location.origin)return;\n"
"    authStorage=window.localStorage; // Receiver-realm Storage identity matches storage events.\n"
"    window.addEventListener('storage',event=>{\n"
"      if(event.storageArea!==authStorage||(event.key!==null&&event.key!=='cli-proxy-auth'&&event.key!=='isLoggedIn'))return;\n"
"      refreshSavedAuth(true);request('/status');\n"
"    });\n"
"    refreshSavedAuth(true);\n"
"  }catch(e){authStorage=null;}\n"
"}\n"
"function syncKey(){\n"
"  refreshSavedAuth();\n"
"  const key=el('key').value.trim();\n"
"  if(key===observedKey)return false;\n"
"  observedKey=key;generation++;online=false;last=null;queued=null;waiting=false;uncertain=false;\n"
"  for(const id of ['current','latest','when'])el(id).textContent='—';\n"
"  el('detail').textContent='';el('release').hidden=true;el('release').removeAttribute('href');\n"
"  el('state').textContent=key?'正在连接':'等待连接';\n"
"  el('connection').textContent=key?'正在读取版本状态…':'未复用登录时请输入管理密钥，自动读取状态';\n"
"  buttons();\n"
"  return true;\n"
"}\n"
"el('key').oninput=el('key').onchange=()=>{\n"
"  manualAuth=true;automaticKey='';\n"
"  if(syncKey()){clearTimeout(timer);request('/status');}\n"
"};\n"
"initSavedAuth();\n"
"buttons();\n"
"request('/status');\n"
"</script>\n"
"</body>\n"
"</html>\n";

static const char enc[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
static char *base64(const uint8_t *b, size_t n){
  size_t outlen=4*((n+2)/3); char *out=malloc(outlen+1); if(!out)return NULL;
  size_t i=0,k=0; while(i<n){ uint32_t v=(uint32_t)b[i++]<<16; int count=1;
    if(i<n){v|=(uint32_t)b[i++]<<8;count++;} if(i<n){v|=b[i++];count++;}
    out[k++]=enc[(v>>18)&63];out[k++]=enc[(v>>12)&63];out[k++]=(count>=2?enc[(v>>6)&63]:'=');out[k++]=(count>=3?enc[v&63]:'=');
  }out[k]=0;return out;
}
static int respond(cliproxy_buffer *resp, const char *s){
  size_t n=strlen(s); char *p=malloc(n+1); if(!p)return 1;memcpy(p,s,n+1);resp->ptr=p;resp->len=n;return 0;
}
static int deliver(cliproxy_buffer *r,int status,const char *content_type,const char *body){
  char *encoded=base64((const uint8_t*)body,strlen(body));if(!encoded)return 1;
  size_t needed=strlen(encoded)+300;char *json=malloc(needed);if(!json){free(encoded);return 1;}
  snprintf(json,needed,"{\"ok\":true,\"result\":{\"StatusCode\":%d,\"Headers\":{\"Content-Type\":[\"%s\"],\"Cache-Control\":[\"no-store\"]},\"Body\":\"%s\"}}",status,content_type,encoded);
  int rc=respond(r,json);free(json);free(encoded);return rc;
}
static int send_error(cliproxy_buffer *r,int status,const char *message){
  char safe[256];size_t i=0;for(const char *p=message;*p&&i<sizeof(safe)-1;p++)if(*p!='"'&&*p!='\\'&&*p!='\n')safe[i++]=*p;safe[i]=0;
  char data[384];snprintf(data,sizeof(data),"{\"error\":\"%s\"}",safe);
  return deliver(r,status,"application/json; charset=utf-8",data);
}
/* Token offsets are bounded by the ABI length. Validate separators as jsmn
 * alone deliberately tokenizes some non-JSON syntax. Never search nested keys. */
typedef struct { const char *s; size_t len; jsmntok_t t[1024]; int n; } document;
static void whitespace(const document *d,int *p){
  while((size_t)*p<d->len && strchr(" \t\r\n",d->s[*p]))++*p;
}
static int grammar(document *d,int *i,int *pos,int depth){
  if(depth>32 || *i>=d->n)return 0;
  jsmntok_t *t=&d->t[(*i)++];whitespace(d,pos);
  if(*pos!=t->start-(t->type==JSMN_STRING))return 0;
  if(t->type==JSMN_OBJECT || t->type==JSMN_ARRAY){
    int object=t->type==JSMN_OBJECT,first=1; ++*pos;
    while(*i<d->n && d->t[*i].start<t->end-1){
      whitespace(d,pos);
      if(!first){if(d->s[(*pos)++]!=',')return 0;whitespace(d,pos);}first=0;
      if(object){
        if(d->t[*i].type!=JSMN_STRING)return 0;
        int key=*i;
        if(!grammar(d,i,pos,depth+1))return 0;
        /* Disallow escaped keys and duplicate direct keys. */
        if(memchr(d->s+d->t[key].start,'\\',(size_t)(d->t[key].end-d->t[key].start)))return 0;
        for(int k=key-1;k>=0;k--){
          if(d->t[k].parent!=d->t[key].parent || d->t[k].type!=JSMN_STRING)continue;
          int n=d->t[key].end-d->t[key].start;
          if(d->t[k].end-d->t[k].start==n && !memcmp(d->s+d->t[k].start,d->s+d->t[key].start,(size_t)n))return 0;
        }
        whitespace(d,pos);if(d->s[(*pos)++]!=':')return 0;
      }
      if(!grammar(d,i,pos,depth+1))return 0;
    }
    whitespace(d,pos);
    if(*pos!=t->end-1 || d->s[(*pos)++]!=(object?'}':']'))return 0;
  }else{
    if(t->type==JSMN_PRIMITIVE){
      const char *s=d->s+t->start;size_t n=(size_t)(t->end-t->start);
      if(!((n==4&&!memcmp(s,"true",4))||(n==5&&!memcmp(s,"false",5))||(n==4&&!memcmp(s,"null",4)))){
        size_t p=0;if(p<n&&s[p]=='-')p++;
        if(p>=n)return 0;
        if(s[p]=='0')p++;else{if(s[p]<'1'||s[p]>'9')return 0;while(p<n&&s[p]>='0'&&s[p]<='9')p++;}
        if(p<n&&s[p]=='.'){p++;size_t a=p;while(p<n&&s[p]>='0'&&s[p]<='9')p++;if(p==a)return 0;}
        if(p<n&&(s[p]=='e'||s[p]=='E')){p++;if(p<n&&(s[p]=='+'||s[p]=='-'))p++;size_t a=p;while(p<n&&s[p]>='0'&&s[p]<='9')p++;if(p==a)return 0;}
        if(p!=n)return 0;
      }
    }else for(int k=t->start;k<t->end;k++)if((unsigned char)d->s[k]<32)return 0;
    *pos=t->end+(t->type==JSMN_STRING);
  }
  return 1;
}
static int parse(document *d,const char *s,size_t len){
  if(!s || !len || memchr(s,0,len))return 0;
  d->s=s;d->len=len;jsmn_parser p;jsmn_init(&p);
  d->n=jsmn_parse(&p,s,len,d->t,1024);
  if(d->n<1 || d->t[0].type!=JSMN_OBJECT)return 0;
  int i=0,pos=0;if(!grammar(d,&i,&pos,0))return 0;
  whitespace(d,&pos);return i==d->n && (size_t)pos==len;
}
static int member(const document *d,int object,const char *name){
  if(object<0 || d->t[object].type!=JSMN_OBJECT)return -1;
  for(int i=object+1;i<d->n && d->t[i].start<d->t[object].end;i++)
    if(d->t[i].parent==object && d->t[i].type==JSMN_STRING &&
       d->t[i].end-d->t[i].start==(int)strlen(name) &&
       !memcmp(d->s+d->t[i].start,name,strlen(name)))return i+1;
  return -1;
}
static int string_value(const document *d,int i,char *out,size_t cap){
  if(i<0 || i>=d->n || d->t[i].type!=JSMN_STRING)return 0;
  size_t n=(size_t)(d->t[i].end-d->t[i].start);
  if(n>=cap || memchr(d->s+d->t[i].start,'\\',n))return 0;
  memcpy(out,d->s+d->t[i].start,n);out[n]=0;return 1;
}
static int field(const document *d,const char *key,char *out,size_t cap){
  return string_value(d,member(d,0,key),out,cap);
}
static int valid_version(const char *s){
  if(*s++!='v')return 0;
  for(int part=0;part<3;part++){
    const char *start=s;while(*s>='0'&&*s<='9')s++;
    if(start==s)return 0;
    if(part<2){if(*s++!='.')return 0;}else if(*s)return 0;
  }return 1;
}
/* Trust only worker-owned single-link regular files, never writable by others. */
static int read_status(char *buf,size_t cap){
  int fd=open(STATUS_FILE,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
  if(fd<0)return errno==ENOENT?0:-1;
  struct stat st;
  if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid!=CPA_STATUS_UID||
     (st.st_mode&022)||st.st_nlink!=1||st.st_size<=0||st.st_size>8192){close(fd);return -1;}
  size_t n=0;
  while(n<cap-1){ssize_t got=read(fd,buf+n,cap-1-n);if(got<0&&errno==EINTR)continue;
    if(got<0){close(fd);return -1;}if(!got)break;n+=(size_t)got;}
  close(fd);buf[n]=0;
  document d;if(n!=(size_t)st.st_size || !parse(&d,buf,n))return -1;
  return (int)n;
}
static int compatible(const char *buf,int n){
  document d;if(n<=0 || !parse(&d,buf,(size_t)n))return 0;
  int i=member(&d,0,"protocol");
  return i>=0 && d.t[i].type==JSMN_PRIMITIVE && d.t[i].end-d.t[i].start==1 && buf[d.t[i].start]=='1';
}
static int get_status(cliproxy_buffer *r){
  char buf[8194];int n=read_status(buf,sizeof(buf));
  if(n<0)return send_error(r,503,"无效状态文件");
  if(!n)return deliver(r,200,"application/json; charset=utf-8","{\"state\":\"setup_required\",\"detail\":\"请先初始化更新组件\"}");
  if(!compatible(buf,n))return deliver(r,200,"application/json; charset=utf-8","{\"state\":\"needs_setup\",\"detail\":\"更新组件协议不兼容，请重新初始化\"}");
  /* Derived queue hint; no task system or extra persistent record. */
  struct stat st;int pending=0;
  if(lstat(REQUEST_FILE,&st)==0)pending=1;else if(errno!=ENOENT)pending=1;
  if(lstat(PROCESSING_FILE,&st)==0)pending=1;else if(errno!=ENOENT)pending=1;
  size_t end=(size_t)n;while(end&&strchr(" \t\r\n",buf[end-1]))end--;
  if(!end||buf[end-1]!='}')return send_error(r,503,"无效状态对象");
  char result[8256];memcpy(result,buf,end-1);
  snprintf(result+end-1,sizeof(result)-(end-1),",\"pending\":%s}",pending?"true":"false");
  return deliver(r,200,"application/json; charset=utf-8",result);
}
static int queue_job(cliproxy_buffer *r,const char *action,const char *expected){
  char status[8194];int status_n=read_status(status,sizeof(status));
  if(!compatible(status,status_n))return send_error(r,503,"请先初始化兼容的更新组件");
  char task[64];
  if(!strcmp(action,"update")){
    if(!expected || !valid_version(expected))return send_error(r,409,"缺少或无效的确认版本");
    char state[32],latest[40];
    document d;
    if(!parse(&d,status,(size_t)status_n) || !field(&d,"state",state,sizeof(state)) || strcmp(state,"ready") ||
       !field(&d,"latest",latest,sizeof(latest)) || !valid_version(latest) || strcmp(latest,expected))
      return send_error(r,409,"版本已变化，请重新检查并确认");
    snprintf(task,sizeof(task),"update %s",expected);
  }else strcpy(task,"check");
  struct stat st;
  if(lstat(PROCESSING_FILE,&st)==0)return send_error(r,409,"已有任务正在执行");
  if(errno!=ENOENT)return send_error(r,503,"无法检查任务状态");
  char tmp[]=CPA_RUN "/inbox/.request.XXXXXX";
  int fd=mkostemp(tmp,O_CLOEXEC);
  if(fd<0)return send_error(r,503,"无法创建任务请求");
  size_t len=strlen(task);ssize_t n=write(fd,task,len);int flush=fsync(fd);int close_rc=close(fd);
  if(n!=(ssize_t)len||flush||close_rc){unlink(tmp);return send_error(r,503,"任务请求写入失败");}
  /* The worker always observes exactly one link, even during publication. */
  int rc=renameat2(AT_FDCWD,tmp,AT_FDCWD,REQUEST_FILE,RENAME_NOREPLACE);
  int saved=errno;if(rc)unlink(tmp);
  if(rc)return send_error(r,saved==EEXIST?409:503,"无法提交任务或已有任务排队");
  return deliver(r,202,"application/json; charset=utf-8","{\"message\":\"任务已提交\"}");
}

static int plugin_call(char *method,uint8_t *req,size_t len,cliproxy_buffer *response){
  response->ptr=NULL;response->len=0;
  if(!strcmp(method,"plugin.register")||!strcmp(method,"plugin.reconfigure"))
    return respond(response,"{\"ok\":true,\"result\":{\"schema_version\":1,\"metadata\":{\"Name\":\"CPA Web Updater\",\"Version\":\"0.5.0\",\"Author\":\"Local deployment\",\"GitHubRepository\":\"https://github.com/flying864/cliproxyapi-web-updater\",\"Logo\":\"\",\"ConfigFields\":[]},\"capabilities\":{\"management_api\":true}}}");
  if(!strcmp(method,"management.register"))
    return respond(response,"{\"ok\":true,\"result\":{\"routes\":[{\"Method\":\"GET\",\"Path\":\"/plugins/cpa-updater/status\"},{\"Method\":\"POST\",\"Path\":\"/plugins/cpa-updater/check\"},{\"Method\":\"POST\",\"Path\":\"/plugins/cpa-updater/update\"}],\"resources\":[{\"Path\":\"/panel\",\"Menu\":\"CPA 一键更新\",\"Description\":\"检查版本、安装更新和回滚\"}]}}");
  if(strcmp(method,"management.handle"))return respond(response,"{\"ok\":false,\"error\":{\"code\":\"unknown_method\",\"message\":\"Unknown plugin method\"}}");
  if(len>65536)return send_error(response,413,"请求过长");
  document d;
  if(!parse(&d,(const char*)req,len))return send_error(response,400,"无效 JSON 请求");
  char http_method[16]={0},path[256]={0},expected[40]={0};
  if(!field(&d,"Method",http_method,sizeof(http_method)) || !field(&d,"Path",path,sizeof(path)))
    return send_error(response,400,"缺少请求方法或路径");
  int query=member(&d,0,"Query"),version=member(&d,query,"version");
  if(version>=0 && d.t[version].type==JSMN_ARRAY && d.t[version].size==1)
    string_value(&d,version+1,expected,sizeof(expected));
  int is_get=!strcmp(http_method,"GET"),is_post=!strcmp(http_method,"POST");
  if(!strcmp(path,"/v0/management/plugins/cpa-updater/status")&&is_get)return get_status(response);
  if(!strcmp(path,"/v0/management/plugins/cpa-updater/check")&&is_post)return queue_job(response,"check",NULL);
  if(!strcmp(path,"/v0/management/plugins/cpa-updater/update")&&is_post)return queue_job(response,"update",expected);
  if((!strcmp(path,"/panel")||!strcmp(path,"/v0/resource/plugins/cpa-updater/panel"))&&is_get)
    return deliver(response,200,"text/html; charset=utf-8",html);
  return send_error(response,404,"未知插件接口");
}
static void plugin_free(void *ptr,size_t size){(void)size;free(ptr);}
static void plugin_shutdown(void){}
__attribute__((visibility("default"))) int cliproxy_plugin_init(const cliproxy_host_api *host,cliproxy_plugin_api *plugin){
  (void)host;if(!plugin)return 1;plugin->abi_version=1;plugin->call=plugin_call;plugin->free_buffer=plugin_free;plugin->shutdown=plugin_shutdown;return 0;
}
