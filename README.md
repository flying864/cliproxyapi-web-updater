# CPA Web Updater v0.5.0

**打开页面 → 检查更新 → 点击立即更新。** 后台一个按需运行的脚本负责下载、校验、备份、替换、重启和失败恢复；平时没有常驻更新进程。

仓库：[flying864/cliproxyapi-web-updater](https://github.com/flying864/cliproxyapi-web-updater)。第三方项目，不是官方安装器，也未自动上架官方商店。

## 页面只有两项操作

- **检查更新**：当前版本、最新正式版、官方更新日志链接。
- **立即更新**：确认具体版本及短暂中断提醒，提交后台任务。

页面自动读取最近一次结果。CLIProxyAPI 重启时暂时断开，只显示重新连接，不把 HTTP 断线判为升级失败；恢复后自动显示成功、错误或回滚结果。没有任务中心、历史列表、通知、多服务器或无人值守升级。

## 现有主机保持不变

支持 Ubuntu 24.04 原生 systemd、glibc、amd64/arm64：

- 主服务 `cliproxyapi.service`，`User=cliproxy`、`Group=cliproxy`。
- 主程序 `/opt/cliproxyapi/cli-proxy-api`，配置 `/opt/cliproxyapi/config.yaml`。
- `-config` 和 `--config` 均可，准确指向上述配置；保留无歧义附加参数，不重写主 service。无法可靠解析的 wrapper/多条 ExecStart/重复 config 会拒绝，不尝试改写。
- `/opt/cliproxyapi` 保持 root 控制，例如 `root:cliproxy 750`。
- `/opt/cliproxyapi/plugins` 可保持 `cliproxy:cliproxy 700`，或已有安全 root-owned 布局。安装器不递归 chmod/chown，不强制改变已有目录权限。服务可写目录的动态库操作以服务账户执行，root 不执行其中的代码。
- 管理 API `127.0.0.1:8317`；首次初始化及升级前核对 OAuth 目录时读取 `/root/cliproxyapi-admin-key`。密钥只用于固定本机管理 API，不写入日志或 UI。
- 配置文件须可由服务保存：例如 `cliproxy:cliproxy 600` 或 `root:cliproxy 660`，不得其他用户可读写或使用不安全链接。

不支持 Docker/DSM/macOS/Windows，不迁移部署、不改 Nginx、SOCKS5/Xray 或业务模型设置。

## 首次安装

先阅读代码，在维护窗口执行。完整安装会短暂重启主服务以加载插件，但不修改其启动参数：

```bash
git clone https://github.com/flying864/cliproxyapi-web-updater.git
cd cliproxyapi-web-updater
python3 -B test_plugin.py
sudo bash install.sh
```

依赖 gcc、Python 3 标准库、curl、Bash、systemd 和常见 coreutils/util-linux；不需要数据库、pip/npm 包或额外 Web 服务。缺少依赖会报错，不自动安装软件。

如果 UI 已经由插件商店安装，仅初始化更新脚本：

```bash
sudo bash install.sh --worker-only
```

此模式不覆盖插件、不改 plugins 配置、不重启主服务。只有受 root 控制的 Worker、辅助代码、systemd 更新单元和状态目录会被安装。未初始化或协议不兼容时，页面禁用操作并提示，不显示虚假的可用状态。

初始化通过官方管理 API 读取实际 `auth-dir`，将获准路径固定到 root 私有 `deployment.json`；每次升级前重新查询实际目录并与批准记录比较；更改 auth-dir 后会中止升级并要求重新初始化，不会让可写配置指挥 root 备份任意目录。

## 日常使用

在可信管理入口打开：

```text
/v0/resource/plugins/cpa-updater/panel
```

输入 Management Key（不是普通客户端 API Key），点击检查更新，再确认立即更新。Key 仅在页面内存保存；刷新页面后需重新输入，断线自动重试不会把 Key 写入浏览器持久存储。

每七天仅自动检查，不自动安装。暂时关闭/恢复定期检查：

```bash
sudo systemctl disable --now cliproxy-updater-check.timer
sudo systemctl enable --now cliproxy-updater-check.timer
```

这是管理员可选操作；网页手动检查不依赖定时器。

## 后台做什么

1. 核对服务身份、路径和确认的正式版本。
2. 下载固定官方仓库的程序包、校验 SHA256 和 ELF 架构。
3. 在 root 私有目录备份旧二进制及配置、已批准的实际 OAuth 目录和插件数据；读取不可信运行数据时降权，不跟随链接或特殊文件。
4. 持久保存恢复记录后停止主服务，原子替换二进制并启动原服务。
5. 检查实际运行版本、API 就绪及短暂稳定窗口；失败尝试恢复旧二进制。

不更改现有 API Key、OAuth、代理、Nginx 或主服务参数。新版本自身可能迁移数据，不能承诺无损自动迁移；自动恢复只恢复二进制，不覆盖 OAuth/config。真实模型调用或图片生成可能收费，不作为默认健康检查。

## 状态与恢复

- 最近状态：`/var/lib/cliproxy-updater-status/status.json`，root 控制，服务组只读，重启后保留。
- 私有备份/事务：`/var/lib/cliproxy-updater`，仅 root 可读。
- 临时请求：`/run/cliproxy-updater/inbox`，只允许固定检查/更新命令。

```bash
sudo journalctl -u cliproxy-updater.service -u cliproxy-updater-recover.service -n 100 --no-pager
sudo cat /var/lib/cliproxy-updater-status/status.json
```

若恢复失败，保留记录和备份，并明确显示失败。解决磁盘/配置等底层问题后可在维护窗口重试：

```bash
sudo systemctl start cliproxy-updater-recover.service
```

不要直接删除事务来“解锁”。备份达到容量预算会拒绝更新，不自动清理失败材料；无遗留事务且确认不再需要后由管理员归档。没有 Web 手动切换旧版本功能。

## 卸载

```bash
sudo bash uninstall.sh
```

完整卸载可能重启主服务；保留用户配置、账号和备份，不改插件目录权限。商店自行安装的版本化 `.so` 仍由商店管理，初始化脚本不以通配符删除它们。

## 开发与验证

```bash
python3 -B test_plugin.py
node tests/test_panel.js
python3 -B tests/test_sanitizer.py
sudo env CPA_TEST_REAL_UID=1 python3 -B tests/test_worker.py
python3 -B tests/test_install.py
python3 -B tests/test_simple_install.py
sudo python3 -B tests/test_runtime.py
python3 -B -m unittest discover -s tests -p 'test_store_*.py'
```

Node 仅用于前端行为测试，不是生产运行依赖。系统路径测试必须使用 bubblewrap，安装测试需要已授权的非交互 sudo/root，缺隔离能力就报错，不退回宿主执行。`CPA_TEST_REAL_UID=1` 强制真实非 root 归档路径测试；受 AppArmor 限制的本机可不带该变量运行控制流替身，但真实 UID 用例会明确跳过，不能当作完整验收。不要解除主机安全策略来绕过限制。真实官方宿主集成方法见 `tests/test_official.py`；包含测试子进程重启后的结果恢复，不接触线上主服务。

CI 同时验证 Linux amd64/arm64 的生产库；amd64 做官方 v8.0.56 完整插件集成。真实 VPS 更新、真实 OAuth/聊天/图片/反代验收需单独授权，源码测试与 CI 不代表已部署。

商店打包与发布见 [STORE_PUBLISHING.md](STORE_PUBLISHING.md)。main 推送只验证构建；tag 发布、Release 和官方商店登记是独立操作，不自动执行。
