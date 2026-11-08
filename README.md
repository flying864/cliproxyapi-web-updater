# CPA Web Updater v0.5.0

面向自用 Ubuntu/systemd 部署，从本 GitHub 仓库直接安装，不提供插件商店发布流程。

给 CLIProxyAPI 管理中心增加一个 **「CPA 一键更新」** 插件：查看版本、检查更新，确认后升级主程序。

**不会自动安装更新。** 网页升级主程序会短暂中断服务，请避开使用高峰；更新插件页面可使用不重启主服务的热更新。这是第三方插件，不是 CLIProxyAPI 官方安装器。

> 已经安装过？直接看 [更新插件](docs/UPDATING.md)。支持 `--hot-reload` 热更新页面；包含按钮闪烁修复、自动填充连接和手机/桌面布局优化。

## 怎么使用

1. 登录 **CLIProxyAPI 管理中心**。
2. 在侧边栏的**插件栏**点击 **「CPA 一键更新」**。
3. 登录时勾选了 **“记住密码”**？同源管理中心内会自动填入密钥并连接；未复用时再输入 **管理密钥（Management Key）**，不是客户端 API Key。
4. 点击 **“检查版本”**，查看最新正式版和更新日志。
5. 需要升级时，点击 **“立即更新”**，核对版本并确认。
6. 等待服务重连，在右侧查看结果；短暂断线不代表更新失败。

插件只复用管理中心已保存、且对应当前服务的登录记录，不额外保存密钥。登出管理中心后自动复用的密钥会清除；手动输入始终优先。独立打开插件页面时仍需手动输入。

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

### 只维护后台组件

已安装插件、只需初始化或更新配套 Worker 时，在**匹配版本的源码目录**执行：

```bash
sudo bash install.sh --worker-only
```

此命令不替换页面、不重启主服务。更新页面请看 [更新插件](docs/UPDATING.md)，不要只运行 `--worker-only`。请核对后台协议和配套版本，不要将页面更新等同于 Worker 更新。

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

卸载不批量删除版本化插件文件或备份，避免破坏恢复材料和其他插件。

## 更多说明

- [更新插件](docs/UPDATING.md)：更新命令和成功检查。
- [部署要求](docs/SECURITY.md) · [运维与恢复](docs/OPERATIONS.md)。
- [开发与测试](docs/DEVELOPMENT.md) · [验证记录](AUDIT.md)。
- [版本历史](CHANGELOG.md) · [第三方组件及许可](THIRD_PARTY.md)。

仓库更新不会自动更新你的服务器；请按安装或更新步骤操作。
