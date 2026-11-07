# 开发与测试

返回 [README](../README.md)。在源码根目录运行以下命令；这不是生产安装步骤。

## 基础验证

需要 Python 3、gcc；前端测试另需 Node.js。Node 不是生产运行依赖。

```bash
python3 -B scripts/check_release_version.py --tag v0.5.0
python3 -B scripts/validate_registry.py
python3 -B test_plugin.py
node tests/test_panel.js
python3 -B tests/test_sanitizer.py
python3 -B -m unittest discover -s tests -p 'test_store_*.py' -v
```

## 可选浏览器验收（仅开发环境）

`tests/test_panel_browser.py` 用 gcc 编译当前插件，再从真实 ABI 响应中读取 HTML，以 Chromium 验证无点击首屏、普通 iframe 嵌入、轮询按钮稳定、浅色/深色及 320/390/1280px 布局。状态接口全部使用明确的测试夹具，不连接真实管理服务，也不执行升级；普通 iframe 测试不等于已验证用户部署的管理中心。

在独立开发虚拟环境中安装 `playwright`，并运行 `python -m playwright install chromium` 后执行：

```bash
python -B tests/test_panel_browser.py
```

截图保存在忽略目录 `test-output/panel-browser/`。Playwright、Chromium 都不是生产依赖；此可选测试尚未加入完整 CI。Node 标准库测试仍是默认前端回归入口，覆盖轮询中点击排队、重复操作抑制、确认版本绑定、密钥切换隔离及不重放 POST。

视觉参考：[Key Policy 插件](https://github.com/origin652/cpa-plugin-key-policy/tree/c041a48bb5e3c3ab44b24d05fa2a27c77c55caf5/web/src) 的 Quiet Paper 卡片与官方管理中心的暖灰配色。未引入其框架、认证复用或持久化存储；当前主题仍跟随系统明暗设置。

### 自动连接修复的验证范围

源码修订 `09c3581` 修复初始化时密钥为空导致轮询停止、随后静默回填密钥仍不连接的问题。新增测试延迟设置输入框 `.value` 且不触发 input/change，在独立页面与普通 iframe 中验证无需点击即可读取状态；修复前两个场景失败，修复后通过。Node 测试还覆盖重复事件、密钥静默更换/清空、排队与已提交请求隔离、确认框边界换密钥。

这不是浏览器真实密码管理器的端到端测试。受保护的密码预览可能显示圆点但不向脚本暴露值，必须由用户授权；插件不绕过此限制、不读取父页面密钥、不新增持久化。若实际宿主仍需点击，记录 iframe 请求、尺寸和控制台错误，并对照直达页面排查。

## 系统路径与权限测试

需要 bubblewrap 和已授权的 root/非交互 sudo。测试使用私有文件系统/网络隔离；缺少隔离能力应报错，不允许退回宿主直接执行。

```bash
sudo env CPA_TEST_REAL_UID=1 python3 -B tests/test_worker.py
sudo env CPA_TEST_REAL_UID=1 python3 -B tests/test_install.py
python3 -B tests/test_simple_install.py
sudo python3 -B tests/test_runtime.py
```

`CPA_TEST_REAL_UID=1` 要求真实非 root 归档测试。受 AppArmor 限制时，不带此变量只能运行明确的控制流替身，真实 UID 用例会跳过；跳过不等于完整验收。不要解除主机安全策略来绕过测试限制。

## 固定官方宿主集成

以下会下载固定基准官方二进制，但只在测试沙箱启动，不安装生产 systemd 单元、不读取真实密钥、不重启宿主主服务：

```bash
mkdir -p test-output
python3 -B tests/fetch_official.py --output test-output/cli-proxy-api
sudo python3 -B tests/test_official.py --binary test-output/cli-proxy-api --output test-output/official
```

固定基准为 amd64 CLIProxyAPI v8.0.56，涵盖真实插件注册、鉴权、版本确认、并发队列及测试子进程重启后的结果恢复。操作系统边界使用替身的用例与真实宿主集成不能混称；见 [AUDIT](../AUDIT.md)。

## 固定旧版 → 新版安装演练

[升级演练工作流](../.github/workflows/upgrade-rehearsal.yml) 分别检出旧提交 `9d85507225ac7dd26604de8abfdf28b67b0868d6` 与新提交 `31c08eddf0eddb21c4e1f841dc940085c4f1707c`，调用各自未修改的 `install.sh`。测试脚本独立检出，不能把同版本重复安装当成跨版本升级证据。

[历史演练运行 42395864349](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42395864349) 返回 `PASS upgrade`、`PASS rollback`：验证旧插件备份、新插件字节与页面变化、配置/OAuth 测试文件内容和权限保留；新版写入后触发器启用故障能恢复旧插件、页面与配置。这份记录针对 `9d85507 → 31c08ed`，不能当作后续 `09c3581` 的跨版本演练结果。

演练只在 GitHub Ubuntu 24.04 的 bubblewrap 私有文件系统/网络中运行。服务管理和管理 API 使用明确测试替身，真实执行安装脚本、gcc 编译、文件写入及权限操作；不连接生产服务器，也不使用生产密钥。以该工作流精确运行的日志为准，不能据此保证任意线上安装都兼容。

## CI、版本与发布

- [完整验证工作流](../.github/workflows/verify-core.yml) 供 main/PR 和 tag 复用，检出精确 commit。
- [双架构构建](../.github/workflows/build-store.yml) 在 Ubuntu 24.04 的 amd64/arm64 原生 runner 编译，并加载最终生产库做 ABI 冒烟；不等于两个架构都完成真实服务验收。
- README 标题也是机器检查的版本标记，保留 `# CPA Web Updater v版本号` 格式。升级用 `scripts/bump_version.py`，不要只改单处；用法和发布门禁见[发布指南](../STORE_PUBLISHING.md)。
- Actions 结果以精确 commit 的实际运行记录为准。源码测试、CI、源码推送均不等于线上部署，不能据此声称真实 OAuth/模型/反代验收通过。
- Push、tag、Release、官方商店 PR 和生产部署必须分别获得授权。
