# CPA Web Updater v0.3.0

为原生 systemd 部署的 [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) 提供：**检查正式版 → 确认版本 → 更新 → 失败恢复旧二进制**。

源码与反馈：[flying864/cliproxyapi-web-updater](https://github.com/flying864/cliproxyapi-web-updater)。第三方插件，未上架官方插件商店。

## 保持简单

- 一个 C 动态库、一个 Bash worker；无数据库、额外端口或常驻更新服务。
- Management Key 仅保留在页面内存，不写入浏览器存储。
- 每周只自动检查，不自动安装；更新必须手动确认指定版本。
- 文件队列提交固定任务，独立 systemd oneshot 执行更新。
- 自动回滚只恢复二进制，不覆盖配置、OAuth 或运行期间的新数据。

## 固定支持范围

本项目不是通用安装器，以下布局必须匹配：

- Linux amd64/aarch64、glibc、systemd；不支持 Docker、DSM 或 macOS。
- CLIProxyAPI 官方支持原生插件的版本，不是 `_no-plugin` 版本。
- 主服务 `cliproxyapi.service`，明确 `User=cliproxy`、`Group=cliproxy`，不能以 root 运行。
- ExecStart 精确为 `/opt/cliproxyapi/cli-proxy-api -config /opt/cliproxyapi/config.yaml`（不带其他参数）。
- 程序 `/opt/cliproxyapi/cli-proxy-api`；配置 `/opt/cliproxyapi/config.yaml`。
- 插件目录 `/opt/cliproxyapi/plugins`。
- OAuth 备份仅覆盖 `/opt/cliproxyapi/auths` 中的实际文件，不读取其他 `auth-dir`、不跟随外链；使用其他位置时必须自行备份，不应把本插件归档视为完整 OAuth 备份。
- 管理 API `http://127.0.0.1:8317`；密钥文件 `/root/cliproxyapi-admin-key`。
- 程序及插件目录链由 root 控制，不能允许非可信用户改写。
- `config.yaml` 是例外：官方管理 API 必须由 `cliproxy` 保存配置，接受 `cliproxy:cliproxy 0600` 或 `root:cliproxy 0660`；拒绝其他用户可读写、符号链接和多硬链接。安装器只检查，不自动修改现有配置权限。

路径不符时不要绕过预检。不要为了插件开放公网管理 API。

## 安装或升级插件

**安装会短暂重启 CLIProxyAPI，可能中断请求，请安排维护窗口。** 在符合上述布局的 Ubuntu 测试服务器执行：

```bash
git clone https://github.com/flying864/cliproxyapi-web-updater.git
cd cliproxyapi-web-updater
less install.sh
less cliproxy-updater-worker

# 临时目录隔离，不使用真实 /run，也不提交生产更新。
python3 test_plugin.py
sudo bash install.sh
```

依赖包括 gcc、Python 3、curl、Bash、systemd，以及常见 coreutils/util-linux 工具。缺少依赖会报错，不自动安装软件。不使用 `curl | bash`。

升级已安装插件时，从新的源码目录运行同一安装器。安装器核对服务身份、目录权限、插件 API，保留备份并验证注册、资源页和鉴权接口。全局插件开关关闭而其他插件配置为启用时，拒绝无声激活它们。

v8 配置 API 可能迁移旧配置布局；审查保留的安装备份。备份含敏感资料，不要上传 GitHub。不要与其他更新工具并发操作。

## 使用

通过现有可信入口打开：

```text
/v0/resource/plugins/cpa-updater/panel
```

浏览器在服务器本机时，地址为 `http://127.0.0.1:8317/v0/resource/plugins/cpa-updater/panel`；也可使用已有 SSH 转发。输入 **Management Key**，不是普通客户端 API Key。

1. 读取状态：当前/待升级版本和任务结果。
2. 检查版本：查询官方最新正式版，不安装。
3. 升级：确认弹窗版本；页面或 GitHub 版本变化时拒绝执行，要求重新检查确认。

匿名资源页是官方设计，管理接口仍强制鉴权。不要用升级按钮测试连通性。

## 恢复与诊断

```bash
systemctl status cliproxyapi.service cliproxy-updater.path --no-pager
systemctl list-timers '*cliproxy-updater*'
sudo journalctl -u cliproxy-updater.service -u cliproxy-updater-recover.service -n 100 --no-pager
sudo cat /run/cliproxy-updater/status.json
```

停服前持久保存恢复记录。正常失败进入恢复；异常终止后恢复单元处理遗留事务，**不重新尝试升级**。恢复失败显示 `rollback_failed` 并保留材料。

维护窗口内人工重试恢复：

```bash
sudo systemctl start cliproxy-updater-recover.service
sudo systemctl is-active cliproxyapi.service
sudo cat /run/cliproxy-updater/status.json
```

`/var/lib/cliproxy-updater/backups` 中的更新备份不自动删除：应用目录上限 512 MiB，累计备份加应用目录估算超过 1 GiB 会拒绝升级。仅在无遗留事务、确认不再需要后由管理员归档旧备份。安装快照另外保留在 `/var/lib/cliproxy-updater/install-*`。

磁盘只读、I/O 故障或旧程序无法启动时，先排除底层问题。不要删除事务标记“解锁”，不要把整份配置/OAuth 备份直接覆盖到运行中的数据目录。

## 卸载

```bash
sudo bash uninstall.sh
```

卸载也可能短暂重启主服务；仅处理本插件及更新任务，保留 CLIProxyAPI、账号数据和备份。有遗留事务或禁用/健康检查失败时停止处理，不默认强制删除。

## 开发与测试

不需要生产密钥。插件测试可普通用户运行；其余测试需要 Linux、gcc 和 bubblewrap。安装沙箱测试使用 `sudo -n bwrap`，需 root 或已授权的非交互 sudo；不满足时明确失败，不退回宿主安装。测试只能在开发/CI 机器运行。

```bash
python3 test_plugin.py
python3 tests/test_sanitizer.py
python3 tests/test_worker.py
python3 tests/test_install.py

mkdir -p test-output
python3 tests/fetch_official.py --output test-output/cli-proxy-api
python3 tests/test_official.py --binary test-output/cli-proxy-api --output test-output/official

for script in install.sh uninstall.sh cliproxy-updater-worker; do
    bash -n "$script" || exit
done
```

官方集成基准 **v8.0.56**，下载器核对固定 SHA256。结果及未覆盖范围见 [AUDIT.md](AUDIT.md)。OS 边界替身不能代替真实 systemd/生产升级验收。

## 安全边界

- 原生插件与主服务同进程，不是沙箱，只加载可信代码。
- worker 只接受 `check` 或 `update v数字.数字.数字`，不接受任意 URL/路径/命令。
- 同源 SHA256 不等于独立供应链签名。
- 基础健康检查不保证所有模型推理成功。
- 持久记录支持异常恢复，但不能保证损坏磁盘/系统必定可恢复。
- 二进制回滚不保证新版本从未改动数据；不可逆数据迁移应人工升级。
- aarch64 需在对应机器额外验收，amd64 结果不代表跨架构通过。
