# 开发与测试

返回 [README](../README.md)。在源码根目录运行以下命令；这不是生产安装步骤。

## 基础验证

需要 Python 3、gcc；前端测试另需 Node.js。Node 不是生产运行依赖。

```bash
python3 -B scripts/check_release_version.py --tag v0.5.0
python3 -B test_plugin.py
node tests/test_panel.js
node tests/test_panel_auth.js
node tests/test_panel_backups.js
python3 -B tests/test_backup_manager.py
python3 -B tests/test_backup_install.py
python3 -B tests/test_sanitizer.py
python3 -B tests/test_version.py
python3 -B tests/test_permissions.py
python3 -B tests/test_native.py
python3 -B tests/test_workflows.py
python3 -B tests/test_private_json.py
python3 -B tests/test_hot_install.py
python3 -B tests/test_hot_cleanup.py
python3 -B tests/test_update_command.py
```

## 浏览器验收（仅开发环境）

`tests/test_panel_browser.py` 用 gcc 编译当前插件，再从真实 ABI 响应中读取 HTML，以 Chromium 验证无点击首屏、普通 iframe 嵌入、轮询按钮稳定、浅色/深色及 320/390/1280px 布局。状态接口全部使用明确的测试夹具，不连接真实管理服务，也不执行升级；普通 iframe 测试不等于已验证用户部署的管理中心。

在独立开发虚拟环境中安装 `playwright`，并运行 `python -m playwright install chromium` 后执行：

```bash
python -B tests/test_panel_browser.py
```

截图保存在忽略目录 `test-output/panel-browser/`。Playwright、Chromium 都不是生产依赖；完整 CI 使用独立虚拟环境运行此测试，Playwright 固定为 1.64.1。Node 标准库测试仍是默认前端回归入口，覆盖轮询中点击排队、重复操作抑制、确认版本绑定、密钥切换隔离及不重放 POST。

视觉参考：[Key Policy 插件](https://github.com/origin652/cpa-plugin-key-policy/tree/c041a48bb5e3c3ab44b24d05fa2a27c77c55caf5/web/src) 的 Quiet Paper 卡片与官方管理中心的暖灰配色。未引入其框架、认证复用或持久化存储；当前主题仍跟随系统明暗设置。

### 自动连接修复的验证范围

源码修订 `09c3581` 修复初始化时密钥为空导致轮询停止、随后静默回填密钥仍不连接的问题。新增测试延迟设置输入框 `.value` 且不触发 input/change，在独立页面与普通 iframe 中验证无需点击即可读取状态；修复前两个场景失败，修复后通过。Node 测试还覆盖重复事件、密钥静默更换/清空、排队与已提交请求隔离、确认框边界换密钥。

这不是浏览器真实密码管理器的端到端测试。受保护的密码预览可能显示圆点但不向脚本暴露值，必须由用户授权；插件不绕过此限制、不读取父页面密钥、不新增持久化。若实际宿主仍需点击，记录 iframe 请求、尺寸和控制台错误，并对照直达页面排查。

### 记住密码复用与紧凑布局

按用户选择“记住密码”的需求，插件仅在同源 iframe 中读取固定 `cli-proxy-auth` 和 `isLoggedIn`；使用官方管理中心 `953fb2444350c6c36052dda46cac0abce6b23ea6` 的 `enc::v2::` 编码和 Zustand version 0 格式。要求登录标记、rememberPassword、API base 与插件 origin 精确一致（仅兼容尾斜线）。不扫描其他键、不写存储、不把密钥放 URL。独立打开、跨源、旧格式或未知 schema 均回退手动输入。插件手动编辑优先，自动来源会在登出/切换记录时撤销；storage 事件使用接收窗口自己的 Storage 对象比较，避免父子 realm 对象不同导致遗漏登出。

这属于指定格式兼容，不是管理中心公开会话桥；无法复用未记住密码的纯内存登录。浏览器用合成官方格式记录验证自动连接、真实跨窗口 storage 登出事件、错误后端拒绝。布局覆盖 960×540 和 390×640 的 iframe，关键操作首屏可见，长日志内部滚动，其他内容可滚动到达。

## 系统路径与权限测试

需要 bubblewrap 和已授权的 root/非交互 sudo。测试使用私有文件系统/网络隔离；缺少隔离能力应报错，不允许退回宿主直接执行。

```bash
sudo env CPA_TEST_REAL_UID=1 python3 -B tests/test_worker.py
sudo env CPA_TEST_REAL_UID=1 python3 -B tests/test_backup_worker.py
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

## 插件热重载验收

[专用工作流](../.github/workflows/hot-reload-probe.yml) 使用固定校验和的官方 v8.0.56 amd64。低层探针 `tests/test_hot_reload.py` 区分同路径替换与不同版本路径加载；在收到首个下游 SSE chunk 后切换，断言完整 80 段内容顺序和结束标志、普通请求成功、PID/starttime 不变，并恢复原页面。模拟上游只在私有网络中提供测试数据，无付费 API。

`tests/test_hot_install_official.py` 在真实 UID/GID 1000 官方进程上执行原始 `install.sh --hot-reload`：旧页面换新、重复安装、配置与文件权限保留、无 systemctl 写操作。故障注入在真实 PUT 已保存且新页面生效后制造响应丢失/进程退出，再验证旧页面、配置、进程身份和持久事务恢复。systemctl 只读查询为测试替身，Worker 使用 protocol-1 idle fixture，不宣称真实 systemd 或真实用户模型验收。

```bash
python3 -B tests/test_private_json.py
python3 -B tests/test_hot_install.py
sudo python3 -B tests/test_hot_reload.py --binary test-output/cli-proxy-api --binary-sha256 0aa3798effa9a387feba232ef5306d159b0b7312a4a70abd794a7ba6e1e5c079 --output test-output/hot-reload
sudo python3 -B tests/test_hot_install_official.py --binary test-output/cli-proxy-api --output test-output/hot-install
```

输出目录需为空。低层探针 exit 0 代表可行，2 代表不支持，1 代表测试失败。早期可行性运行 [42400315903](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42400315903) 验证 320 次普通请求与 4 条流；完整发行应以同提交的最新工作流为准。

最终代码 `f9feb32` 的 [热更新及故障恢复验收](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42402108114) 和 [完整 CI](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42402111233) 均通过。期间发现并修复 legacy 无版本选择回滚仍选中新库的问题：事务先持久化再发布文件，失败时仅隔离本事务创建且哈希匹配的候选文件为非 `.so` 备份，再恢复原配置。旧库和隔离备份不删除。

热加载只针对当前 C 页面插件，不泛化为任意插件零中断。官方宿主在主进程内运行 native 插件、保留退休动态库，不是进程级故障隔离；反复更新有资源累积成本。不同宿主版本、arm64 实际热切换、真实 OAuth/provider 需另外验证。

## 成功后清理验收

以下是历史顺序执行测试，不覆盖最后一次文件身份检查与删除之间的并发替换窗口。安全复核复现该窗口后，当前修复暂停物理 prune，保留旧插件；不将旧测试通过解读为并发安全保证。

代码 `9ef47bc` 的 [GitHub 连续热更新验收](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42445721330) 与 [完整 CI](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42445723915) 通过。真实官方非 root 宿主依次安装四个构建并各重复一次：已登记的当前/上一版保留，legacy、未知同命名文件和隔离备份未删除；PID/start、配置、数据与队列保持不变。

`tests/test_hot_cleanup.py` 检查私有归属、文件摘要/链接、引用与活动事务保护及警告语义。`tests/test_update_command.py` 使用模拟下载/安装命令，但实际创建和删除临时目录，验证成功清理、失败保留、只恢复旧事务、健康失败、源码身份/标记篡改及清理失败返回成功。更新脚本不扫描旧目录；生产环境尚未通过此脚本操作。

隔离操作的预期 device/inode 在 rename 之前持久保存到 root 私有事务；重试仍使用同一身份。备份存在但无可信身份时停止人工处理，不能仅凭相同摘要采纳。移动后检测只能发现已发生的错误移动并保留证据，不是抵御同 UID 并发写入者的原子隔离。

源码清理通过已验证目录 fd 递归，不再对根路径调用 rmtree；根/父目录替换用例验证外来目录内容保留。同 UID 或 root 向已验证目录内部注入内容不属于此隔离保证，最终 rmdir 只可能移除空目录。

热安装成功后仍持有公共锁并维护 `hot-owned.json` 的 current/previous 信息，但旧插件物理删除已暂停。共同锁不能约束其他持有目录写权限的进程，摘要和 inode 检查之后的名称删除不是原子条件删除。安全优先保留文件；配置/OAuth、完整安装备份和主程序备份不动，也不卸载驻留库映像。

## CI、版本与发布

- [完整验证工作流](../.github/workflows/verify-core.yml) 供 main/PR 和手动运行复用，检出精确 commit。
- [双架构构建](../.github/workflows/build-native.yml) 在 Ubuntu 24.04 的 amd64/arm64 原生 runner 编译，并加载最终生产库做 ABI 冒烟；不等于两个架构都完成真实服务验收。
- README 标题也是机器检查的版本标记，保留 `# CPA Web Updater v版本号` 格式。升级用 `python3 -B scripts/bump_version.py 新版本号`（不带 v 的三段数字），同步 C、ABI 测试、官方宿主测试、README、Worker 和 runtime 六处标记；普通写入失败尝试还原，但不是断电原子事务。
- Actions 结果以精确 commit 的实际运行记录为准。源码测试、CI、源码推送均不等于线上部署，不能据此声称真实 OAuth/模型/反代验收通过。
- 当前只维护 GitHub 源码自安装；没有商店 ZIP、登记或自动 Release 流程。CI 构建产物不等于服务器部署；Push 和生产部署分开授权。
- `scripts/permission_preflight.py` 仅只读检查目录权限位，不能替代安装器的路径/权限保护或 Worker 的 `--preflight`；ACL、挂载与 systemd 沙箱需另查。
