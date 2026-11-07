# 更新插件

这份指南更新 **CPA Web Updater 页面和后台组件**，不升级 CLIProxyAPI 主程序。

本次包含：密钥自动填入后的自动连接、按钮闪烁修复，以及更清晰的手机/桌面界面。

## 1. 更新前

- 在**原来安装插件的 Ubuntu 24.04 服务器**操作，适用于通过本仓库 `install.sh` 安装的用户。
- 如果只从商店安装，先看 [商店说明](../STORE_PUBLISHING.md)，不要直接套用本命令。
- 备份重要配置和 OAuth 数据，避开使用高峰。**安装会短暂重启 CLIProxyAPI，影响正在进行的请求。**
- 保持 [原安装要求](../README.md#第一次安装) 和依赖；不要为通过检查随意改目录权限。

## 2. 复制执行

在服务器终端用 Bash 执行。命令会新建源码目录，不覆盖旧源码，并锁定本次修复提交。

```bash
(
  set -e

  workdir=$(mktemp -d "$HOME/cliproxy-updater-update.XXXXXX")
  git clone https://github.com/flying864/cliproxyapi-web-updater.git "$workdir"
  cd "$workdir"

  git checkout --detach 09c3581d92fa5b91059fbcd579c93d35c2746635
  python3 -B test_plugin.py

  sudo bash install.sh
  sudo systemctl is-active cliproxyapi.service
)
```

`detached HEAD` 是正常的版本锁定提示。不要加 `--worker-only`，否则不会更新页面。

## 3. 检查是否成功

1. 终端依次出现测试 `OK`、“安装已验证完成”和服务 `active`。**保留安装打印的备份路径。**
2. 按 **Ctrl + Shift + R** 刷新管理中心，打开 **插件栏 → CPA 一键更新**。
3. 输入管理密钥，等待版本状态显示；如果密钥已自动填入但仍不连接，手动重新粘贴一次。
4. 确认“检查版本”按钮不再反复闪烁，并检查原有 API 请求正常。

不用点击“立即更新”来验收插件，它会触发主程序升级。

## 出错怎么办

**停止重复安装，不要卸载或删除备份。** 保留安装报错和备份路径，然后查看：

```bash
sudo systemctl is-active cliproxyapi.service
sudo journalctl -u cliproxyapi.service -n 80 --no-pager
```

安装器会尝试恢复旧插件；出现“有限恢复检查通过”表示已执行恢复检查，不是升级成功。需要协助时附上报错，先遮住密钥和账号信息。详细处理见 [运维与恢复](OPERATIONS.md)。

## 技术信息

本次源码修复为 [`09c3581`](https://github.com/flying864/cliproxyapi-web-updater/commit/09c3581d92fa5b91059fbcd579c93d35c2746635)，插件版本号仍为 `0.5.0`。测试范围、浏览器限制和历史升级演练见 [开发与测试](DEVELOPMENT.md)。
