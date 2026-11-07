# CPA Web Updater v0.5.0

给 CLIProxyAPI 管理中心增加一个 **「CPA 一键更新」** 插件：查看版本、检查更新，确认后升级主程序。

**不会自动安装更新。** 升级会短暂中断服务，请避开使用高峰。这是第三方插件，不是 CLIProxyAPI 官方安装器。

> 已经安装过？直接看 [更新插件](docs/UPDATING.md)。最新版修复按钮闪烁、改善密钥自动填充后的连接，并优化手机和桌面布局。

## 怎么使用

1. 登录 **CLIProxyAPI 管理中心**。
2. 在侧边栏的**插件栏**点击 **「CPA 一键更新」**。
3. 输入 **管理密钥（Management Key）**，页面会自动连接并读取状态。它不是客户端 API Key。
4. 点击 **“检查版本”**，查看最新正式版和更新日志。
5. 需要升级时，点击 **“立即更新”**，核对版本并确认。
6. 等待服务重连，在右侧查看结果；短暂断线不代表更新失败。

插件不保存密钥，也不读取管理中心保存的密钥。刷新后需要重新输入；浏览器若已自动填入可读取的密钥，页面会自动连接。

## 第一次安装

### 先确认服务器符合要求

本插件用于**已有且正常运行的 CLIProxyAPI**，不会帮你安装主程序。

- Ubuntu 24.04 原生 Linux、systemd，amd64 或 arm64；**不支持 Docker、群晖 DSM、Windows 和 macOS**。
- 服务名为 `cliproxyapi.service`，以 `cliproxy` 用户和组运行。
- 程序：`/opt/cliproxyapi/cli-proxy-api`；配置：`/opt/cliproxyapi/config.yaml`。
- 启动参数中只有一个 `-config` 或 `--config` 指向上述配置，不使用启动包装脚本。
- 本机管理 API：`127.0.0.1:8317`；管理密钥文件：`/root/cliproxyapi-admin-key`，仅 root 可读。
- 已安装 Git、gcc、Python 3、curl、Bash 及常见系统工具。脚本不会自动安装缺失依赖。

不确定目录和权限是否符合要求？先看 [部署要求](docs/SECURITY.md)，不要用 `chmod 777` 或把主服务改为 root 来绕过检查。

### 执行安装

先备份重要配置和 OAuth 数据。在服务器终端用 Bash 执行以下命令，**安装会短暂重启主服务**：

```bash
(
  set -e
  git clone https://github.com/flying864/cliproxyapi-web-updater.git
  cd cliproxyapi-web-updater
  python3 -B test_plugin.py
  sudo bash install.sh
  sudo systemctl is-active cliproxyapi.service
)
```

看到测试 `OK`、安装提示“安装已验证完成”和服务 `active` 后，刷新管理中心，从插件栏打开。保留安装输出的备份路径。

### 已经从商店安装了页面？

商店只安装页面插件，还需要初始化后台组件（Worker）。在**与插件配套的同版本源码目录**中执行：

```bash
sudo bash install.sh --worker-only
```

此命令不替换页面、不重启主服务。更新页面请看 [更新插件](docs/UPDATING.md)，不要只运行 `--worker-only`。商店安装细节见 [商店说明](STORE_PUBLISHING.md)。

## 常见问题

**插件栏没有「CPA 一键更新」？**

刷新管理中心，检查插件是否已启用、成功加载，以及管理中心是否支持插件菜单。需要单独打开页面排查时，可在可信的管理服务地址后加：

```text
/v0/resource/plugins/cpa-updater/panel
```

**密钥框有圆点，但一直显示“等待连接”？**

先等几秒；仍不连接时，手动重新粘贴管理密钥。部分浏览器需要用户确认后才会把自动填充的密码交给页面。

**会自动升级吗？**

不会。后台默认开机后检查一次，之后约每七天检查；安装新版本始终需要手动确认。

**失败会恢复所有数据吗？**

不会。主程序升级失败时会尝试恢复旧二进制，**不恢复配置或 OAuth 数据**。升级前请备份，尤其注意新版本可能带来的数据迁移。

**报错或更新后服务没恢复？**

不要反复点击更新、删除备份或队列。保留错误信息，按 [运维与恢复](docs/OPERATIONS.md) 检查日志；分享日志前遮住密钥和账号信息。

## 卸载

在源码目录执行；卸载可能短暂重启服务，保留用户配置、账号和备份：

```bash
sudo bash uninstall.sh
```

商店安装的版本化插件文件仍由商店管理。

## 更多说明

- [更新插件](docs/UPDATING.md)：更新命令和成功检查。
- [部署要求](docs/SECURITY.md) · [运维与恢复](docs/OPERATIONS.md)。
- [开发与测试](docs/DEVELOPMENT.md) · [验证记录](AUDIT.md)。
- [商店打包与发布](STORE_PUBLISHING.md) · [官方登记 PR 模板](OFFICIAL_REGISTRY_PR.md)。
- [版本历史](CHANGELOG.md) · [第三方组件及许可](THIRD_PARTY.md)。

仓库更新不会自动更新你的服务器或商店插件；请按安装或更新步骤操作。
