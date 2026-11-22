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
"/* Refined Quiet Studio surfaces harmonizing with CPA Management Center;\n"
"   zero external UI/font dependencies, full light & dark adaptive palette. */\n"
":root {\n"
"  color-scheme: light dark;\n"
"  --bg: #f6f5f0; --glow: rgb(186 168 136 / .16);\n"
"  --card: #ffffff; --surface: #f2f0ea; --surface-hover: #eae6dd;\n"
"  --text: #1f1d1a; --muted: #69635b; --border: #e2ded4; --border-strong: #cec8bb;\n"
"  --action: #24211d; --hover: #3b3630; --on-action: #faf9f5;\n"
"  --ring: rgb(53 50 46 / .15);\n"
"  --ok: #16653b; --ok-bg: #eaf6ef; --ok-border: #bce3cd;\n"
"  --info: #1b569e; --info-bg: #ecf4fd; --info-border: #bfd8f6;\n"
"  --warning: #884518; --warning-bg: #fdf5ea; --warning-border: #efd7b4;\n"
"  --danger: #9f2727; --danger-bg: #fdf0f0; --danger-border: #f1c4c4;\n"
"  --shadow: 0 1px 2px rgb(24 21 17 / .04), 0 8px 22px -16px rgb(24 21 17 / .08);\n"
"}\n"
"@media (prefers-color-scheme: dark) {\n"
"  :root {\n"
"    --bg: #171614; --glow: rgb(222 204 172 / .06);\n"
"    --card: #211f1c; --surface: #2a2823; --surface-hover: #33302a;\n"
"    --text: #f0ece4; --muted: #a9a297; --border: #393630; --border-strong: #4f4a41;\n"
"    --action: #ece7dd; --hover: #ffffff; --on-action: #1b1916;\n"
"    --ring: rgb(236 231 221 / .18);\n"
"    --ok: #78d6a0; --ok-bg: rgb(32 126 75 / .2); --ok-border: rgb(74 178 120 / .35);\n"
"    --info: #8ec3ff; --info-bg: rgb(42 114 206 / .2); --info-border: rgb(98 158 238 / .35);\n"
"    --warning: #efc28d; --warning-bg: rgb(176 104 38 / .2); --warning-border: rgb(216 150 84 / .35);\n"
"    --danger: #f59898; --danger-bg: rgb(192 56 56 / .2); --danger-border: rgb(226 106 106 / .36);\n"
"    --shadow: 0 1px 2px rgb(0 0 0 / .28), inset 0 1px 0 rgb(255 255 255 / .03);\n"
"  }\n"
"}\n"
"* { box-sizing: border-box; }\n"
"body { margin: 0; background: var(--bg) radial-gradient(900px 300px at 50% -120px, var(--glow), transparent 72%) no-repeat; color: var(--text); font: 14px/1.5 system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; -webkit-font-smoothing: antialiased; }\n"
"main { width: min(100%, 1120px); margin: 0 auto; padding: 12px 18px 16px; }\n"
"header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 10px; }\n"
".eyebrow { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; font-weight: 500; letter-spacing: .02em; }\n"
".eyebrow::before { content: ''; width: 6px; height: 6px; border-radius: 99px; background: var(--action); opacity: .65; }\n"
"h1 { margin: 2px 0; font-size: 21px; font-weight: 700; line-height: 1.3; letter-spacing: -.025em; }\n"
"h2 { font-size: 15px; font-weight: 650; margin: 0; letter-spacing: -.01em; }\n"
"p { margin: 6px 0; }\n"
".header-sub { margin: 2px 0 0; font-size: 13px; }\n"
".header-badge { padding: 4px 10px; border: 1px solid var(--border); border-radius: 999px; background: var(--card); color: var(--muted); font-size: 12px; font-weight: 500; white-space: nowrap; box-shadow: var(--shadow); }\n"
".muted, dt, .help { color: var(--muted); }\n"
".help { font-size: 12.5px; line-height: 1.45; }\n"
".card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 13px 15px; min-width: 0; box-shadow: var(--shadow); }\n"
".card-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 9px; }\n"
".tag { padding: 2px 9px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface); color: var(--muted); font-size: 11.5px; font-weight: 500; white-space: nowrap; }\n"
".access { margin-bottom: 10px; display: grid; grid-template-columns: minmax(200px, .72fr) minmax(0, 1.28fr); gap: 8px 18px; align-items: center; }\n"
".access h2 { margin-bottom: 3px; }\n"
"label { display: block; font-size: 12.5px; font-weight: 600; margin-bottom: 4px; }\n"
"input[type='password'] { width: 100%; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 9px; padding: 9px 12px; font: inherit; transition: border-color .15s, box-shadow .15s, background .15s; }\n"
"input[type='password']:hover { border-color: var(--border-strong); }\n"
"input[type='password']:focus { outline: none; background: var(--card); border-color: var(--action); box-shadow: 0 0 0 3px var(--ring); }\n"
"input::placeholder { color: var(--muted); opacity: .8; }\n"
".connection { display: inline-flex; align-items: center; gap: 6px; margin: 6px 0 0; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); font-size: 12px; font-weight: 500; overflow-wrap: anywhere; max-width: 100%; }\n"
".connection::before { content: ''; width: 7px; height: 7px; border-radius: 99px; background: currentColor; opacity: .65; flex-shrink: 0; }\n"
".connection.is-ok { color: var(--ok); background: var(--ok-bg); border-color: var(--ok-border); }\n"
".connection.is-ok::before, .state-pill.is-ok::before, .state-pill.is-ready::before { opacity: 1; }\n"
".connection.is-warn { color: var(--warning); background: var(--warning-bg); border-color: var(--warning-border); }\n"
".connection.is-err { color: var(--danger); background: var(--danger-bg); border-color: var(--danger-border); }\n"
".workspace { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(0, 1.05fr); gap: 12px; align-items: stretch; }\n"
".versions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; margin: 0 0 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }\n"
".versions div { padding: 9px 12px; min-width: 0; }\n"
".versions div + div { border-left: 1px solid var(--border); }\n"
"dt { font-size: 12px; font-weight: 500; }\n"
"dd { margin: 3px 0 0; font: 650 clamp(17px, 2.3vw, 22px)/1.35 ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; letter-spacing: -.03em; overflow-wrap: anywhere; }\n"
"dd.is-ready { color: var(--ok); }\n"
"#release { display: inline-flex; align-items: center; gap: 4px; margin: 0 0 2px; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--info-border); background: var(--info-bg); color: var(--info); font-size: 12.5px; font-weight: 500; text-decoration: none; transition: filter .15s; }\n"
"#release:hover { filter: brightness(.96); }\n"
".actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 9px; }\n"
"button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 44px; padding: 9px 16px; border: 1px solid var(--border-strong); border-radius: 9px; background: var(--card); color: var(--text); font: inherit; font-weight: 600; cursor: pointer; transition: background .14s, border-color .14s, transform .08s, box-shadow .14s; }\n"
"button svg { width: 15px; height: 15px; flex-shrink: 0; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }\n"
"button:not(:disabled):hover { background: var(--surface); border-color: var(--muted); }\n"
"button:not(:disabled):active { transform: translateY(1px); }\n"
".primary { background: var(--action); border-color: var(--action); color: var(--on-action); box-shadow: 0 1px 2px rgb(0 0 0 / .14); }\n"
".primary:not(:disabled):hover { background: var(--hover); border-color: var(--hover); }\n"
".danger-btn:not(:disabled) { color: var(--danger); border-color: var(--danger-border); background: var(--danger-bg); }\n"
".danger-btn:not(:disabled):hover { filter: brightness(.97); border-color: var(--danger); }\n"
".pager { min-height: 36px; padding: 6px 12px; font-size: 12.5px; }\n"
"button:disabled { opacity: .44; cursor: not-allowed; box-shadow: none; }\n"
":focus-visible { outline: 2px solid var(--action); outline-offset: 2px; }\n"
"a { color: var(--text); text-underline-offset: 3px; }\n"
"a:hover { text-decoration-thickness: 2px; }\n"
".docs { font-size: 12.5px; font-weight: 500; white-space: nowrap; }\n"
".notice { margin: 9px 0 0; background: var(--warning-bg); color: var(--warning); border: 1px solid var(--warning-border); border-left: 3px solid var(--warning); padding: 8px 11px; border-radius: 9px; font-size: 12.5px; line-height: 1.45; }\n"
".notice strong { display: block; margin-bottom: 2px; font-size: 12.5px; }\n"
".status-box { padding: 10px 12px; border-radius: 10px; background: var(--surface); border: 1px solid var(--border); }\n"
".status-line { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; }\n"
"#state { display: inline-flex; align-items: center; gap: 7px; font-size: 14px; font-weight: 650; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--card); overflow-wrap: anywhere; }\n"
"#state::before { content: ''; width: 8px; height: 8px; border-radius: 99px; background: currentColor; opacity: .55; flex-shrink: 0; }\n"
"#state.is-ok, #state.is-ready { color: var(--ok); background: var(--ok-bg); border-color: var(--ok-border); }\n"
"#state.is-busy { color: var(--info); background: var(--info-bg); border-color: var(--info-border); }\n"
"#state.is-busy::before { opacity: 1; animation: pulse 1.3s ease-in-out infinite; }\n"
"#state.is-warn { color: var(--warning); background: var(--warning-bg); border-color: var(--warning-border); }\n"
"#state.is-err { color: var(--danger); background: var(--danger-bg); border-color: var(--danger-border); }\n"
"@keyframes pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(.65); opacity: .4; } }\n"
"@media (prefers-reduced-motion: reduce) { #state.is-busy::before { animation: none; } button { transition: none; } }\n"
".timestamp { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }\n"
"pre { max-height: 152px; overflow-y: auto; margin: 9px 0 0; padding: 9px 11px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); white-space: pre-wrap; overflow-wrap: anywhere; font: 12.5px/1.55 ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace; }\n"
"pre:empty { display: none; }\n"
".result-help { border-top: 1px solid var(--border); padding-top: 9px; margin-top: 10px; }\n"
".backup-drawer { margin-top: 12px; padding: 0; overflow: hidden; }\n"
".backup-drawer summary { list-style: none; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 15px; cursor: pointer; font-weight: 650; font-size: 14.5px; user-select: none; transition: background .14s; }\n"
".backup-drawer summary::-webkit-details-marker { display: none; }\n"
".backup-drawer summary:hover { background: var(--surface); }\n"
".summary-left { display: inline-flex; align-items: center; gap: 8px; }\n"
".summary-chevron { display: inline-block; font-size: 12px; color: var(--muted); transition: transform .16s ease; }\n"
".backup-drawer[open] .summary-chevron { transform: rotate(90deg); }\n"
".backup-drawer[open] summary { border-bottom: 1px solid var(--border); background: var(--surface); }\n"
".backup-content { padding: 12px 15px 14px; }\n"
".backup-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; margin-top: 8px; }\n"
".btn-row, .pager-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }\n"
".backup-banner { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin: 10px 0 0; padding: 8px 11px; border-radius: 9px; background: var(--surface); border: 1px solid var(--border); font-size: 12.5px; }\n"
"#backup-state { margin: 0; font-weight: 500; overflow-wrap: anywhere; }\n"
"#backup-total { margin: 0; padding: 2px 9px; border-radius: 999px; background: var(--card); border: 1px solid var(--border); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }\n"
".pager-bar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin-top: 8px; }\n"
"#backup-page { margin: 0; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }\n"
"#backup-list { display: grid; gap: 8px; margin-top: 10px; }\n"
"#backup-list:empty { display: none; }\n"
".backup-item { display: flex; gap: 10px; align-items: flex-start; min-height: 44px; margin: 0; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--card); cursor: pointer; overflow-wrap: anywhere; transition: border-color .14s, background .14s; }\n"
".backup-item:hover { border-color: var(--border-strong); background: var(--surface); }\n"
".backup-item.is-selected { border-color: var(--ok); background: var(--ok-bg); }\n"
".backup-item.is-protected { background: var(--surface); opacity: .82; cursor: default; }\n"
".backup-item input[type='checkbox'] { width: 17px; height: 17px; margin: 2px 0 0; flex-shrink: 0; accent-color: var(--ok); cursor: inherit; }\n"
".backup-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; font-weight: 400; }\n"
".backup-top, .backup-sub { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 6px 10px; }\n"
".backup-name { font: 600 13px/1.4 ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace; color: var(--text); overflow-wrap: anywhere; }\n"
".backup-badges { display: inline-flex; flex-wrap: wrap; gap: 6px; align-items: center; }\n"
".mini-tag { padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); font-size: 11.5px; font-weight: 500; white-space: nowrap; }\n"
".mini-tag.mono { font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace; color: var(--text); }\n"
".backup-sub { font-size: 12px; color: var(--muted); }\n"
".reason-tag { padding: 1px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 500; }\n"
".reason-tag.is-ok { color: var(--ok); background: var(--ok-bg); border: 1px solid var(--ok-border); }\n"
".reason-tag.is-locked { color: var(--warning); background: var(--warning-bg); border: 1px solid var(--warning-border); }\n"
"footer { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 14px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; }\n"
".footer-left { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 10px; }\n"
"[hidden] { display: none !important; }\n"
"@media (max-width: 800px) {\n"
"  .workspace { grid-template-columns: 1fr; }\n"
"}\n"
"@media (max-width: 600px) {\n"
"  main { padding: 10px 12px 14px; }\n"
"  header { align-items: flex-start; margin-bottom: 8px; }\n"
"  .header-badge { display: none; }\n"
"  .card { padding: 11px 12px; border-radius: 12px; }\n"
"  .backup-drawer { padding: 0; }\n"
"  .backup-drawer summary, .backup-content { padding: 11px 12px; }\n"
"  .access { grid-template-columns: 1fr; gap: 5px; margin-bottom: 8px; }\n"
"  .versions { grid-template-columns: repeat(2, minmax(0, 1fr)); }\n"
"  .versions div { padding: 8px 10px; }\n"
"  .versions div + div { border-left: 1px solid var(--border); }\n"
"  .actions button, .btn-row button { flex: 1; padding-inline: 10px; }\n"
"}\n"
"</style>\n"
"</head>\n"
"<body>\n"
"<main>\n"
"<header>\n"
"<div><div class='eyebrow'>CLIProxyAPI / 插件</div><h1>版本更新</h1><p class='muted header-sub'>掌握当前版本，按需安全更新服务。</p></div>\n"
"<span class='header-badge'>手动确认 · 故障回滚</span>\n"
"</header>\n"
"<section class='card access' aria-labelledby='access-title'>\n"
"<div><h2 id='access-title'>连接管理服务</h2><p class='help'>管理密钥仅在当前页面内存中使用。</p><p id='connection' class='connection' role='status' aria-live='polite'>未复用登录时请输入管理密钥，自动读取状态</p></div>\n"
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
"<button id='check' type='button' disabled><svg aria-hidden='true' viewBox='0 0 24 24'><path d='M21 12a9 9 0 1 1-2.64-6.36'/><path d='M21 3v6h-6'/></svg>检查版本</button>\n"
"<button id='update' type='button' class='primary' disabled><svg aria-hidden='true' viewBox='0 0 24 24'><circle cx='12' cy='12' r='9'/><path d='m8.5 12.5 3.5-3.5 3.5 3.5'/><path d='M12 9v6.5'/></svg>立即更新</button>\n"
"</div>\n"
"<p class='help'>手动确认后才会升级，不会自动安装更新。</p>\n"
"<div class='notice'><strong>更新前请留意</strong>升级会短暂中断 API，请避开使用高峰。失败时尝试恢复旧二进制，<b>不恢复配置或 OAuth 数据</b>。</div>\n"
"</section>\n"
"<section class='card' aria-labelledby='result-title'>\n"
"<div class='card-head'><h2 id='result-title'>最近状态</h2><span class='tag'>自动同步</span></div>\n"
"<div class='status-box'><div class='status-line'><strong id='state' class='state-pill' role='status' aria-live='polite'>等待连接</strong><span class='timestamp'>状态更新时间 · <span id='when'>—</span></span></div></div>\n"
"<pre id='detail' aria-label='最近操作详情' tabindex='0'></pre>\n"
"<p class='help result-help'>服务重启时页面会自动重连。短暂断线不代表更新失败，请以恢复后的状态为准。</p>\n"
"</section>\n"
"</div>\n"
"<details class='card backup-drawer'><summary><span class='summary-left'><span class='summary-chevron' aria-hidden='true'>▸</span><span>备份管理</span></span><span class='tag'>按需扫描 · 安全清理</span></summary>\n"
"<div class='backup-content'>\n"
"<p class='help'>仅主动扫描，默认不勾选；最近完整成功备份、活动事务与未登记历史目录自动受保护。单次最多永久删除 20 组，不可恢复。</p>\n"
"<div class='backup-toolbar'><div class='btn-row'><button id='backup-scan' type='button' disabled><svg aria-hidden='true' viewBox='0 0 24 24'><circle cx='11' cy='11' r='7'/><path d='m20 20-3.5-3.5'/></svg>扫描 / 刷新预览</button><button id='backup-delete' type='button' class='danger-btn' disabled><svg aria-hidden='true' viewBox='0 0 24 24'><path d='M3 6h18'/><path d='M8 6V4h8v2'/><path d='m19 6-1 14H6L5 6'/></svg>永久删除所选</button></div></div>\n"
"<div class='backup-banner'><p id='backup-state' role='status' aria-live='polite'>请先连接并主动扫描</p><p id='backup-total'>已选择 0 组 · 0 字节</p></div>\n"
"<div class='pager-bar'><p id='backup-page'></p><div class='pager-row'><button id='backup-prev' type='button' class='pager' disabled>上一页</button><button id='backup-next' type='button' class='pager' disabled>下一页</button></div></div>\n"
"<div id='backup-list'></div>\n"
"</div>\n"
"</details>\n"
"<footer><span class='footer-left'><span>CPA Web Updater · 第三方更新插件</span><a class='docs' href='https://github.com/flying864/cliproxyapi-web-updater#readme' target='_blank' rel='noopener noreferrer'>使用文档 ↗</a></span><span>检查 → 确认 → 更新</span></footer>\n"
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
"const stateTones = {\n"
"  ready: 'is-ready', current: 'is-ok', up_to_date: 'is-ok', success: 'is-ok',\n"
"  checking: 'is-busy', updating: 'is-busy', downloading: 'is-busy', backing_up: 'is-busy', installing: 'is-busy', verifying: 'is-busy',\n"
"  needs_recheck: 'is-warn', rolled_back: 'is-warn', interrupted: 'is-warn', setup_required: 'is-warn', needs_setup: 'is-warn',\n"
"  error: 'is-err', failed: 'is-err', rollback_failed: 'is-err'\n"
"};\n"
"const api='/v0/management/plugins/cpa-updater',el=id=>document.getElementById(id);\n"
"let last=null,inflight=false,online=false,waiting=false,uncertain=false,baseline='',timer=null,queued=null,generation=0,observedKey='';\n"
"const version=v=>typeof v==='string'&&v.length<40&&/^v[0-9]+[.][0-9]+[.][0-9]+$/.test(v);\n"
"const terminal=new Set(['idle','ready','current','needs_recheck','up_to_date','success','error','failed','rollback_failed','rolled_back','interrupted','setup_required','needs_setup']);\n"
"const signature=j=>JSON.stringify([j.state,j.updated_at,j.detail,j.current,j.latest]);\n"
"let backup=null,backupBusy=false,backupBaseline='',backupQueued=null,backupReceived=0;\n"
"const selected=new Map(),hex=v=>typeof v==='string'&&/^[a-f0-9]{32}$/.test(v);\n"
"function setConn(text,tone=''){\n"
"  const c=el('connection');c.textContent=text;c.className='connection'+(tone?' '+tone:'');\n"
"}\n"
"function backupButtons(enabled){\n"
"  if(!el('backup-scan'))return;\n"
"  if(backup&&hex(backup.token)&&Date.now()-backupReceived>=600000){\n"
"    backup.token='';selected.clear();\n"
"    for(const row of el('backup-list').children||[]){const b=row.children&&row.children[0];if(b){b.checked=false;b.disabled=true;}row.className='backup-item is-protected';}\n"
"    el('backup-state').textContent='预览已过期，请重新扫描后选择；未执行删除。';\n"
"    el('backup-total').textContent='已选择 0 组 · 0 字节';\n"
"  }\n"
"  el('backup-scan').disabled=!(enabled&&last.backups_protocol===1&&!backupBusy);el('backup-prev').disabled=el('backup-scan').disabled||!backup||!(backup.page>0);el('backup-next').disabled=el('backup-scan').disabled||!backup||!(backup.page+1<backup.page_count);\n"
"  el('backup-delete').disabled=!(enabled&&last.backups_protocol===1&&!backupBusy&&backup&&hex(backup.token)&&selected.size>0&&selected.size<=20);\n"
"  if(last&&last.backups_protocol!==1)el('backup-state').textContent='备份后台需要更新；原版本检查与更新仍可使用';\n"
"}\n"
"function selection(){\n"
"  let size=0;for(const item of selected.values())size+=item.size_bytes;\n"
"  el('backup-total').textContent='已选择 '+selected.size+' 组 · '+backupSize(size);buttons();\n"
"}\n"
"function clearBackups(){\n"
"  backup=null;backupBusy=false;backupQueued=null;selected.clear();\n"
"  if(el('backup-list')){el('backup-list').replaceChildren();el('backup-page').textContent='';el('backup-state').textContent='请主动扫描备份';selection();}\n"
"}\n"
"const backupReason=r=>({'unregistered or unsafe backup':'历史未登记或不安全，需人工核查','backup identity or content changed':'文件已变化，禁止清理','unsafe backup':'备份不安全，禁止清理','latest successful backup':'保留：最近完整成功备份','active transaction':'正在恢复，禁止清理'}[r]||r||'可选择');\n"
"const backupSize=n=>n>=1073741824?(n/1073741824).toFixed(2)+' GiB':n>=1048576?(n/1048576).toFixed(2)+' MiB':n>=1024?(n/1024).toFixed(2)+' KiB':n+' 字节';\n"
"function renderBackups(j){\n"
"  selected.clear();backup=null;el('backup-list').replaceChildren();\n"
"  if(j.protocol!==1||!Array.isArray(j.items)||j.items.length>100){el('backup-state').textContent='无效备份结果';selection();return;}\n"
"  backup=j;backupReceived=Date.now();el('backup-page').textContent=j.state==='ready'?'第 '+((j.page||0)+1)+' / '+(j.page_count||1)+' 页 · 共 '+j.total_count+' 组':'请重新扫描核对剩余备份';el('backup-state').textContent=({ready:'预览就绪',success:'清理完成',error:'未完成'}[j.state]||String(j.state||''))+' · '+String(j.detail||'')+(j.truncated?' · 当前仅显示本页，请翻页查看其余备份':'');\n"
"  for(const item of j.items){\n"
"    const row=document.createElement('label'),box=document.createElement('input'),body=document.createElement('span');\n"
"    const top=document.createElement('span'),name=document.createElement('span'),badges=document.createElement('span'),kindTag=document.createElement('span'),sizeTag=document.createElement('span');\n"
"    const sub=document.createElement('span'),when=document.createElement('span'),reason=document.createElement('span');\n"
"    const ok=item.deletable===true&&hex(item.id)&&hex(j.token)&&Number.isSafeInteger(item.size_bytes)&&item.size_bytes>=0;\n"
"    row.className=ok?'backup-item':'backup-item is-protected';body.className='backup-body';top.className='backup-top';name.className='backup-name';badges.className='backup-badges';kindTag.className='mini-tag';sizeTag.className='mini-tag mono';sub.className='backup-sub';reason.className=ok?'reason-tag is-ok':'reason-tag is-locked';\n"
"    box.type='checkbox';box.checked=false;box.disabled=!ok;\n"
"    box.onchange=()=>{if(box.disabled)return;if(box.checked){if(selected.size>=20){box.checked=false;return;}selected.set(item.id,item);}else selected.delete(item.id);row.className=box.checked?'backup-item is-selected':'backup-item';selection();};\n"
"    name.textContent=String(item.name);kindTag.textContent=item.kind==='runtime'?'主程序备份':'安装快照';sizeTag.textContent=backupSize(item.size_bytes);\n"
"    when.textContent=String(item.created_at||'时间未登记');reason.textContent=backupReason(item.reason);\n"
"    badges.appendChild(kindTag);badges.appendChild(sizeTag);top.appendChild(name);top.appendChild(badges);sub.appendChild(when);sub.appendChild(reason);body.appendChild(top);body.appendChild(sub);\n"
"    row.appendChild(box);row.appendChild(body);el('backup-list').appendChild(row);\n"
"  }\n"
"  selection();\n"
"}\n"
"function backupSubmit(clean=false,page){\n"
"  if(syncKey()){request('/status');return;}\n"
"  buttons();if(el(clean?'backup-delete':'backup-scan').disabled||waiting||backupBusy)return;\n"
"  let path=Number.isInteger(page)?'/backups?page='+page:'/backups';\n"
"  if(clean){\n"
"    const token=backup.token,ids=[...selected.keys()].join(',');\n"
"    if(!confirm('永久删除 '+selected.size+' 组备份（'+el('backup-total').textContent+'）？不可恢复。'))return;\n"
"    if(syncKey()){request('/status');return;}\n"
"    if(!backup||backup.token!==token)return;\n"
"    path='/cleanup?preview='+token+'&ids='+ids;\n"
"  }\n"
"  backupBaseline=JSON.stringify(backup);backupBusy=true;backupQueued=path;selected.clear();selection();\n"
"  if(!inflight){backupQueued=null;request(path,'POST');}\n"
"}\n"
"el('backup-scan').onclick=()=>backupSubmit();\n"
"el('backup-delete').onclick=()=>backupSubmit(true);el('backup-prev').onclick=()=>backupSubmit(false,(backup?.page||0)-1);el('backup-next').onclick=()=>backupSubmit(false,(backup?.page||0)+1);\n"
"function buttons(){\n"
"  const enabled=!!el('key').value.trim()&&el('key').value.trim()===observedKey&&online&&!waiting&&last&&last.pending!==true&&last.protocol===1&&terminal.has(last.state)&&!['setup_required','needs_setup'].includes(last.state);\n"
"  backupButtons(enabled);\n"
"  el('check').disabled=!enabled||backupBusy;\n"
"  el('update').disabled=!(enabled&&!backupBusy&&last.state==='ready'&&version(last.latest));\n"
"}\n"
"function render(j){\n"
"  last=j;\n"
"  for(const [id,key] of [['current','current'],['latest','latest'],['when','updated_at'],['detail','detail']])el(id).textContent=typeof j[key]==='string'?j[key]:'—';\n"
"  el('latest').className=j.state==='ready'&&version(j.latest)?'is-ready':'';\n"
"  const st=el('state');st.textContent=stateLabels[j.state]||'未知状态（'+String(j.state||'未提供')+'）';\n"
"  st.className='state-pill'+(stateTones[j.state]?' '+stateTones[j.state]:'');\n"
"  const link=el('release');\n"
"  link.hidden=!version(j.latest);\n"
"  if(!link.hidden)link.href='https://github.com/router-for-me/CLIProxyAPI/releases/tag/'+j.latest;\n"
"  else link.removeAttribute('href');\n"
"}\n"
"function schedule(){\n"
"  clearTimeout(timer);\n"
"  timer=setTimeout(()=>request(backupBusy?'/backups':'/status'),2000);\n"
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
"      setConn('HTTP '+r.status+'：'+(j.error||'请求未被接受'),'is-err');\n"
"      if(method==='POST'){waiting=false;backupBusy=false;}if(path.startsWith('/backups')){clearBackups();el('backup-state').textContent='无法读取备份结果，请重新扫描；不会自动重试删除。';}\n"
"      return;\n"
"    }\n"
"    online=true;\n"
"    setConn('已连接','is-ok');\n"
"    if(path.split('?')[0]==='/backups'&&method==='GET'){\n"
"      if(j.pending!==true){backupBusy=false;if(JSON.stringify(j)!==backupBaseline)renderBackups(j);else{clearBackups();el('backup-state').textContent='未取得新的操作结果；可能未提交或已中断，请重新扫描核对。';}}\n"
"    }else if(method==='GET'){\n"
"      if(waiting&&(signature(j)!==baseline||(uncertain&&j.pending===false&&terminal.has(j.state)))){\n"
"        waiting=false;\n"
"        uncertain=false;\n"
"      }\n"
"      render(j);\n"
"    }\n"
"    else{\n"
"      if(path.startsWith('/backups')||path.startsWith('/cleanup'))el('backup-state').textContent='请求已排队，等待后台结果；尚未确认删除';\n"
"      setConn('请求已提交，等待状态更新','is-warn');\n"
"    }\n"
"  }\n"
"  catch(e){\n"
"    syncKey();\n"
"    if(epoch!==generation)return;\n"
"    if(method==='POST')uncertain=true;\n"
"    online=false;\n"
"    setConn('连接中断，正在重连；操作结果以恢复后的状态为准','is-warn');\n"
"  }\n"
"  finally{\n"
"    clearTimeout(timeout);\n"
"    inflight=false;\n"
"    syncKey();\n"
"    if(epoch!==generation){request('/status');return;}\n"
"    if(backupQueued){\n"
"      const next=backupQueued;backupQueued=null;\n"
"      if(online&&last&&last.backups_protocol===1&&last.pending!==true&&terminal.has(last.state)){request(next,'POST');return;}\n"
"      backupBusy=false;el('backup-state').textContent='操作未提交：后台忙或连接不可用，请重新扫描';\n"
"    }\n"
"    if(queued){\n"
"      const path=queued;queued=null;\n"
"      if(online&&last&&last.protocol===1&&last.pending!==true&&terminal.has(last.state)&&!['setup_required','needs_setup'].includes(last.state)&&(path==='/check'||(last.state==='ready'&&version(last.latest)))){waiting=true;uncertain=false;baseline=signature(last);request(path,'POST');return;}\n"
"      waiting=false;\n"
"      setConn(el('connection').textContent+' · 操作未提交：状态已变化或连接不可用，请核对后重试','is-warn');\n"
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
"  clearBackups();\n"
"  for(const id of ['current','latest','when'])el(id).textContent='—';\n"
"  el('latest').className='';\n"
"  el('detail').textContent='';el('release').hidden=true;el('release').removeAttribute('href');\n"
"  const st=el('state');st.textContent=key?'正在连接':'等待连接';st.className=key?'state-pill is-busy':'state-pill';\n"
"  setConn(key?'正在读取版本状态…':'未复用登录时请输入管理密钥，自动读取状态',key?'is-warn':'');\n"
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
#define DELIVER_FMT "{\"ok\":true,\"result\":{\"StatusCode\":%d,\"Headers\":{\"Content-Type\":[\"%s\"],\"Cache-Control\":[\"no-store\"]},\"Body\":\"%s\"}}"
static int deliver(cliproxy_buffer *r,int status,const char *content_type,const char *body){
  char *encoded=base64((const uint8_t*)body,strlen(body));if(!encoded)return 1;
  size_t ct_len=strlen(content_type),enc_len=strlen(encoded);
  if(enc_len>SIZE_MAX-ct_len-sizeof(DELIVER_FMT)-32){free(encoded);return 1;}
  size_t needed=sizeof(DELIVER_FMT)+ct_len+enc_len+32;
  char *json=malloc(needed);if(!json){free(encoded);return 1;}
  int written=snprintf(json,needed,DELIVER_FMT,status,content_type,encoded);
  int rc=(written>0&&(size_t)written<needed)?respond(r,json):1;
  free(json);free(encoded);return rc;
}
static int send_error(cliproxy_buffer *r,int status,const char *message){
  char safe[256];size_t i=0;for(const char *p=message;*p&&i<sizeof(safe)-1;p++)if(*p!='"'&&*p!='\\'&&*p!='\n')safe[i++]=*p;safe[i]=0;
  char data[384];snprintf(data,sizeof(data),"{\"error\":\"%s\"}",safe);
  return deliver(r,status,"application/json; charset=utf-8",data);
}
/* Token offsets are bounded by the ABI length. Validate separators as jsmn
 * alone deliberately tokenizes some non-JSON syntax. Never search nested keys. */
typedef struct { const char *s; size_t len; jsmntok_t *t; int capacity; jsmntok_t small[1024]; int n; } document;
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
static int parse_tokens(document *d,const char *s,size_t len,jsmntok_t *tokens,int capacity){
  d->t=tokens;d->capacity=capacity;
  if(!s || !len || memchr(s,0,len))return 0;
  d->s=s;d->len=len;jsmn_parser p;jsmn_init(&p);
  d->n=jsmn_parse(&p,s,len,d->t,(unsigned)capacity);
  if(d->n<1 || d->t[0].type!=JSMN_OBJECT)return 0;
  int i=0,pos=0;if(!grammar(d,&i,&pos,0))return 0;
  whitespace(d,&pos);return i==d->n && (size_t)pos==len;
}
static int parse(document *d,const char *s,size_t len){return parse_tokens(d,s,len,d->small,1024);}
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
  document d;if(n<=0 || !parse(&d,buf,(size_t)n) || member(&d,0,"pending")>=0)return 0;
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
  char task[1025];
  if(!strcmp(action,"backups")||!strcmp(action,"cleanup")){
    document d;parse(&d,status,(size_t)status_n);int i=member(&d,0,"backups_protocol");
    if(i<0||d.t[i].type!=JSMN_PRIMITIVE||d.t[i].end-d.t[i].start!=1||status[d.t[i].start]!='1')return send_error(r,503,"备份后台需要更新");
    if(!strcmp(action,"cleanup"))snprintf(task,sizeof(task),"cleanup %s",expected);
    else if(expected)snprintf(task,sizeof(task),"backups %s",expected);
    else strcpy(task,"backups");
  }else
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

static int hex32(const char *s){
  if(strlen(s)!=32)return 0;
  for(int i=0;i<32;i++)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return 0;
  return 1;
}
static int get_backups(cliproxy_buffer *r){
  /* Never expose a previous operation's result while any request is queued. */
  struct stat queued;
  if(lstat(REQUEST_FILE,&queued)==0||errno!=ENOENT||lstat(PROCESSING_FILE,&queued)==0||errno!=ENOENT)
    return deliver(r,200,"application/json; charset=utf-8","{\"protocol\":1,\"pending\":true,\"state\":\"pending\",\"token\":\"\",\"items\":[]}");
  int fd=open(CPA_PUBLIC "/backups.json",O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
  if(fd<0){
    if(errno==ENOENT)return deliver(r,200,"application/json; charset=utf-8","{\"protocol\":1,\"state\":\"error\",\"pending\":false,\"token\":\"\",\"items\":[],\"detail\":\"尚无扫描结果，请重新扫描\"}");
    return send_error(r,503,"无法读取备份预览");
  }
  struct stat st;
  if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid!=CPA_STATUS_UID||(st.st_mode&022)||st.st_nlink!=1||st.st_size<=0||st.st_size>65536){close(fd);return send_error(r,503,"无效备份清单");}
  char *buf=malloc(65537); document *d=calloc(1,sizeof(*d)); jsmntok_t *tokens=calloc(16384,sizeof(*tokens));
  if(!buf||!d||!tokens){close(fd);free(buf);free(d);free(tokens);return 1;}
  size_t n=0;int bad=0;
  while(n<65537){ssize_t got=read(fd,buf+n,65537-n);if(got<0&&errno==EINTR)continue;if(got<0){bad=1;break;}if(!got)break;n+=(size_t)got;}
  close(fd);
  int ok=!bad&&n==(size_t)st.st_size&&n<=65536&&parse_tokens(d,buf,n,tokens,16384);
  if(ok){int i=member(d,0,"items"),proto=member(d,0,"protocol");ok=i>=0&&d->t[i].type==JSMN_ARRAY&&d->t[i].size<=100&&proto>=0&&d->t[proto].type==JSMN_PRIMITIVE&&d->t[proto].end-d->t[proto].start==1&&buf[d->t[proto].start]=='1';}
  int rc;if(ok){buf[n]=0;rc=deliver(r,200,"application/json; charset=utf-8",buf);}else rc=send_error(r,503,"无效备份清单");
  free(buf);free(d);free(tokens);return rc;
}
static int cleanup_request(cliproxy_buffer *r,const document *d,int query){
  char token[33],ids[660],command[700];
  int a=member(d,query,"preview"),b=member(d,query,"ids");
  if(query<0||d->t[query].size!=2||a<0||b<0||d->t[a].type!=JSMN_ARRAY||d->t[a].size!=1||d->t[b].type!=JSMN_ARRAY||d->t[b].size!=1||!string_value(d,a+1,token,sizeof(token))||!hex32(token)||!string_value(d,b+1,ids,sizeof(ids)))return send_error(r,400,"无效清理参数");
  char copy[660];strcpy(copy,ids);char *cursor=copy,*part;char *seen[20];int count=0;
  while((part=strsep(&cursor,","))!=NULL){
    if(count==20||!hex32(part))return send_error(r,400,"无效备份标识");
    for(int i=0;i<count;i++)if(!strcmp(seen[i],part))return send_error(r,400,"重复备份标识");
    seen[count++]=part;
  }
  if(!count)return send_error(r,400,"未选择备份");
  snprintf(command,sizeof(command),"%s %s",token,ids);return queue_job(r,"cleanup",command);
}
static int plugin_call(char *method,uint8_t *req,size_t len,cliproxy_buffer *response){
  response->ptr=NULL;response->len=0;
  if(!strcmp(method,"plugin.register")||!strcmp(method,"plugin.reconfigure"))
    return respond(response,"{\"ok\":true,\"result\":{\"schema_version\":1,\"metadata\":{\"Name\":\"CPA Web Updater\",\"Version\":\"0.5.1\",\"Author\":\"Local deployment\",\"GitHubRepository\":\"https://github.com/flying864/cliproxyapi-web-updater\",\"Logo\":\"\",\"ConfigFields\":[]},\"capabilities\":{\"management_api\":true}}}");
  if(!strcmp(method,"management.register"))
    return respond(response,"{\"ok\":true,\"result\":{\"routes\":[{\"Method\":\"GET\",\"Path\":\"/plugins/cpa-updater/status\"},{\"Method\":\"POST\",\"Path\":\"/plugins/cpa-updater/check\"},{\"Method\":\"POST\",\"Path\":\"/plugins/cpa-updater/update\"},{\"Method\":\"GET\",\"Path\":\"/plugins/cpa-updater/backups\"},{\"Method\":\"POST\",\"Path\":\"/plugins/cpa-updater/backups\"},{\"Method\":\"POST\",\"Path\":\"/plugins/cpa-updater/cleanup\"}],\"resources\":[{\"Path\":\"/panel\",\"Menu\":\"CPA 一键更新\",\"Description\":\"检查版本、安装更新和回滚\"}]}}");
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
  if(!strcmp(path,"/v0/management/plugins/cpa-updater/backups")){if(is_get)return get_backups(response);if(is_post){
    if(query<0||d.t[query].size==0)return queue_job(response,"backups",NULL);
    int page=member(&d,query,"page");char number[4];
    if(d.t[query].type!=JSMN_OBJECT||d.t[query].size!=1||page<0||d.t[page].type!=JSMN_ARRAY||d.t[page].size!=1||!string_value(&d,page+1,number,sizeof(number))||!number[0])return send_error(response,400,"无效页码");
    for(int k=0;number[k];k++)if(number[k]<'0'||number[k]>'9')return send_error(response,400,"无效页码");
    return queue_job(response,"backups",number);
  }}
  if(!strcmp(path,"/v0/management/plugins/cpa-updater/cleanup")&&is_post)return cleanup_request(response,&d,query);
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
