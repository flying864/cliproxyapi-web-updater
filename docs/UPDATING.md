# 更新插件

更新 **CPA Web Updater 插件页面**，不升级 CLIProxyAPI 主程序。

## 推荐：热更新，不重启主服务

适用于已通过本仓库安装并初始化的插件，且后台组件兼容 `protocol=1`。已在官方 CLIProxyAPI **v8.0.56 / Ubuntu 24.04 amd64** 上验证。热更新只替换页面插件，保留 Worker、配置和账号数据；不满足条件会停止，**不会自动改成重启安装**。

在原来的服务器终端用 Bash 执行：

```bash
(
  set -e
  workdir=$(mktemp -d "$HOME/cliproxy-updater-update.XXXXXX")
  git clone https://github.com/flying864/cliproxyapi-web-updater.git "$workdir"
  cd "$workdir"
  git checkout --detach f9feb32440ed85fbc3edc017a49ec99741a2de95
  python3 -B test_plugin.py
  sudo bash install.sh --hot-reload
  sudo systemctl is-active cliproxyapi.service
)
```

`detached HEAD` 是正常的版本锁定提示。热更新期间不要同时在页面点击升级主程序或修改插件配置。

## 检查是否成功

1. 终端出现 **“hot-reload 已验证”** 和 **“PID/start 未变化”**，服务显示 `active`。
2. 按 **Ctrl + Shift + R** 刷新管理中心，打开 **插件栏 → CPA 一键更新**。
3. 在管理中心勾选“记住密码”登录后，打开插件应自动填入密钥并连接；未复用时可重新登录管理中心，或手动输入管理密钥。
4. 检查原有 API 请求正常。不用点击“立即更新”来验收插件，那会升级主程序。

## 报错怎么办

- **后台正忙或有未完成任务**：先等待任务结束，不要删除队列、事务或旧插件文件。
- **提示“旧 hot 事务已恢复并验证”**：这次只恢复了旧插件；确认服务正常后，再运行同一目录中的 `sudo bash install.sh --hot-reload` 执行升级。
- **提示“hot 恢复未完成”或配置冲突**：停止重复操作，保留 `/var/lib/cliproxy-updater/hot-transaction.json`，按 [运维与恢复](OPERATIONS.md) 排查。不要改用普通安装、卸载或删除恢复记录。
- **其他错误**：保留终端报错，并查看以下日志；分享前遮住密钥和账号信息。

```bash
sudo systemctl is-active cliproxyapi.service
sudo journalctl -u cliproxyapi.service -n 80 --no-pager
```

## 哪些操作仍会重启？

- **第一次安装**：使用 `sudo bash install.sh`，会短暂重启主服务。
- **传统完整安装**：同时安装页面和 Worker，会重启；不适用于已有版本化插件选择的部署，安装器会提示停止。
- **仅更新后台组件**：管理员核对配套版本后使用 `sudo bash install.sh --worker-only`，不替换页面、不重启主服务。不要用它代替本次页面更新。
- **网页“立即更新”**：升级 CLIProxyAPI 主程序，仍会短暂中断服务。

热更新保留旧插件文件；官方宿主也会保留已加载的旧库映像。不要频繁反复切换或手工清理，维护时再安排正常重启。所有更新仍建议保留重要配置和 OAuth 数据备份。

热更新测试中的请求和流式响应保持正常，但不能保证所有环境、所有插件行为都零中断。商店安装、自定义目录或其他宿主版本请先核对兼容性。[技术验证与边界](DEVELOPMENT.md)。
