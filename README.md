# CPA Web Updater v0.5.0

给现有 CLIProxyAPI 增加一个更新页面：**检查更新 → 确认版本 → 立即更新**。后台按需下载、校验、备份和重启，失败时尝试恢复旧二进制；没有常驻更新进程，也不会自动安装新版本。

这是[第三方项目](https://github.com/flying864/cliproxyapi-web-updater)，不是 CLIProxyAPI 官方安装器。源码、Release、官方商店登记和主机部署是四件不同的事，不能相互替代。

> **已安装用户更新提示：** [更新命令、重启提醒与验收步骤](docs/UPDATING.md)。本次修复按钮闪烁并优化 UI；旧版 → 新版隔离演练已通过，完整安装仍会短暂重启服务。首次打开需再次点击的问题尚未确认解决。

## 快速使用

已经安装并初始化？在你信任的管理入口域名后打开：

```text
/v0/resource/plugins/cpa-updater/panel
```

1. 输入 **Management Key（管理密钥）**，不是客户端 API Key。
2. 点击“检查更新”，查看当前版本、最新正式版和官方更新日志。
3. 确认目标版本及短暂中断提醒，再点击“立即更新”。不要在有关键请求运行时更新。
4. 等页面重新连接，查看最终结果。服务重启导致的断线本身不代表升级失败。

密钥只保存在页面内存，刷新后需要重输。页面只显示最近结果，没有任务中心、历史列表、多服务器管理或手动降级功能。

## 安装

### 先确认是否适用

本项目**不安装 CLIProxyAPI 主程序**，只支持符合以下布局的已有主机：

| 项目 | 要求 |
| --- | --- |
| 系统 | Ubuntu 24.04 原生 Linux、glibc、systemd；amd64 或 arm64 |
| 主服务 | 正常运行的 `cliproxyapi.service`，明确设置 `User=cliproxy`、`Group=cliproxy` |
| 程序与配置 | `/opt/cliproxyapi/cli-proxy-api`、`/opt/cliproxyapi/config.yaml` |
| 启动参数 | 恰好一个 `-config` 或 `--config` 指向上述配置；保留可明确解析的其他参数 |
| 管理 API | 本机 `127.0.0.1:8317` 可用 |
| 本机管理密钥 | 已存在于 `/root/cliproxyapi-admin-key`，由 root 控制且仅 root 可读 |

不支持 Docker、DSM、macOS、Windows，也不迁移部署或改 Nginx、SOCKS5/Xray、模型设置。wrapper、多条 ExecStart、重复或含糊的配置参数会被拒绝，不会尝试重写主服务。

目录和配置权限也有要求，安装前请核对[部署与安全边界](docs/SECURITY.md)。**不要为了通过检查而使用 `chmod 777`、递归改属主或让主服务以 root 运行。**

### 首次完整安装

先备份重要数据、审阅源码，再在维护窗口执行。最后一条命令会安装插件和后台组件，并短暂重启主服务：

```bash
git clone https://github.com/flying864/cliproxyapi-web-updater.git
cd cliproxyapi-web-updater
python3 -B test_plugin.py
sudo bash install.sh
```

需要 Git（获取源码）、gcc、Python 3 标准库、curl、Bash、systemd 及常见 coreutils/util-linux 命令。缺少依赖会报错，不会自动安装软件。不需要 pip/npm 包、数据库或额外 Web 服务。

### 已经从商店安装了页面

在**同版本源码目录**中初始化后台组件（Worker）：

```bash
sudo bash install.sh --worker-only
```

该模式不覆盖插件、不改插件配置、不重启主服务；只安装后台脚本、辅助代码、systemd 单元及状态目录。商店只分发动态库，不会安装或同步 root Worker。页面提示未初始化或协议不兼容时，不能直接更新；请管理员核对配套版本。

### 卸载

在源码目录执行：

```bash
sudo bash uninstall.sh
```

完整卸载可能重启主服务。保留用户配置、账号和备份，不修改插件目录权限；商店安装的版本化 `.so` 仍由商店管理，不会被通配符删除。

## 常见问题

### 会自动更新吗？

不会。默认开机后安排一次检查，之后约每七天检查，带随机延迟；安装必须手动确认。管理员可关闭或恢复定时检查，网页手动检查不受影响：

```bash
# 关闭
sudo systemctl disable --now cliproxy-updater-check.timer
# 恢复
sudo systemctl enable --now cliproxy-updater-check.timer
```

### 更新会改动账号或配置吗？

更新器不主动改 API Key、OAuth、代理和主服务启动参数。但新版本主程序可能迁移数据。**自动回滚只恢复二进制，不恢复配置/OAuth，也不能撤销不可逆迁移。** 备份并不等于无损回滚保证。

### 页面断线、报错或恢复失败怎么办？

先等主服务重连，查看最近状态和日志：

```bash
sudo cat /var/lib/cliproxy-updater-status/status.json
sudo journalctl -u cliproxy-updater.service -u cliproxy-updater-recover.service -n 100 --no-pager
```

不要反复点击、删除事务或队列来“解锁”。恢复失败、磁盘不足和备份容量问题的处理见[运维与恢复](docs/OPERATIONS.md)。

### 改过 OAuth 目录后为什么无法更新？

初始化会通过本机管理 API 确认实际 `auth-dir`，保存到 root 私有批准记录。每次升级前重新核对；路径变化会中止。管理员确认新路径合法且没有遗留事务后，用同版本源码重新运行 `sudo bash install.sh --worker-only`。不要手工伪造批准记录。

### 商店无法安装，或页面有了却不能更新？

商店需要主服务用户能写入插件目录，旧的 root-owned 只读布局可能不满足；即使页面安装成功，也仍需单独初始化 Worker。详见[商店打包与发布](STORE_PUBLISHING.md)，不要以放宽整个应用目录权限解决问题。

## 更多说明

- [部署与安全边界](docs/SECURITY.md)：目录权限、更新流程、信任边界。
- [运维与恢复](docs/OPERATIONS.md)：状态位置、故障处理、备份管理。
- [开发与测试](docs/DEVELOPMENT.md)：本地命令、隔离要求、CI 范围。
- [验证记录](AUDIT.md)：历史验证及未覆盖内容，不是当前机器的验收报告。
- [商店打包与发布](STORE_PUBLISHING.md) · [官方登记 PR 模板](OFFICIAL_REGISTRY_PR.md)。
- [版本历史](CHANGELOG.md) · [第三方组件及许可](THIRD_PARTY.md)。
