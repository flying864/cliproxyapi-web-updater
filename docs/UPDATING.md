# 更新插件

更新 **CPA Web Updater 插件及配套后台**，不升级 CLIProxyAPI 主程序。以下命令固定到已通过 GitHub 验收的源码提交 `543b2c96cf061e9fe9bfd8900c987c19c244f552`。

## 本次备份管理更新：后台 + 页面

**需要“备份管理”的用户用这一节。** 只更新页面不会给旧 Worker 增加清理能力。适用于已经初始化、符合本仓库布局的部署；先备份重要配置与账号数据，并确保没有进行中的主程序升级或恢复任务。

在原服务器终端复制执行。它只更新后台组件并热更新页面，**不重启 CLIProxyAPI 主服务**；会短暂停用并恢复插件自身的更新触发器。失败时停止，不自动改成重启安装；源码目录保留供核查，不批量删除历史目录。

```bash
(
  set -euo pipefail
  SOURCE="$(mktemp -d "$HOME/cliproxy-updater-backups.XXXXXXXX")"
  printf '源码与失败排查目录：%s\n' "$SOURCE"
  git clone --no-checkout https://github.com/flying864/cliproxyapi-web-updater.git "$SOURCE/source"
  cd "$SOURCE/source"
  git checkout --detach 543b2c96cf061e9fe9bfd8900c987c19c244f552
  test "$(git rev-parse HEAD)" = 543b2c96cf061e9fe9bfd8900c987c19c244f552
  python3 -B test_plugin.py
  sudo bash install.sh --worker-only
  sudo bash install.sh --hot-reload
  sudo systemctl is-active cliproxyapi.service
)
```

成功后刷新管理中心 → 插件栏 → **CPA 一键更新**，展开 **备份管理** 并主动扫描。检查可显示列表和保护原因；不要为了验收而删除备份。只有勾选并确认后才执行删除。

- 最近完整成功备份、恢复事务使用的材料和未登记历史备份不能删除。
- 若提示“备份后台需要更新”，确认上面的 `--worker-only` 成功，不要只反复刷新页面。
- 若提示“旧 hot 事务已恢复并验证”，这次仅恢复旧插件；在终端保留的源码目录重跑 `sudo bash install.sh --hot-reload`，看到“hot-reload 已验证”后才算页面更新完成。
- 本功能不自动清理、不删除旧 `.so`、配置、OAuth 或其他插件；完整规则见 [备份容量与保留](OPERATIONS.md#备份容量与保留)。

验收证据：[真实权限/安装器/双架构](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/43351812281) · [官方宿主热安装/恢复](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/43351817539)。服务管理部分为隔离测试边界，不代表生产 systemd 全程验收。

## 仅更新页面：热更新，不重启主服务

适用于已通过本仓库安装并初始化的插件，且后台组件兼容 `protocol=1`。已在官方 CLIProxyAPI **v8.0.56 / Ubuntu 24.04 amd64** 上验证。热更新只替换页面插件，保留 Worker、配置和账号数据；不满足条件会停止，**不会自动改成重启安装**。

在原来的服务器终端复制执行。命令先校验固定版本的更新脚本，再自动下载源码、测试、热更新和验证；成功后删除本次源码目录，无需先卸载。

```bash
python3 -c '
import hashlib, sys, urllib.request
commit = "543b2c96cf061e9fe9bfd8900c987c19c244f552"
url = "https://raw.githubusercontent.com/flying864/cliproxyapi-web-updater/" + commit + "/scripts/update_plugin.py"
with urllib.request.urlopen(url, timeout=30) as response:
    code = response.read(65537)
if hashlib.sha256(code).hexdigest() != "d75f2f04cefb96d8ef72b23312eacb8b44fc970a7c5f3d9d7b94beb1f383bd9e":
    sys.exit("更新脚本校验失败，已停止")
sys.argv = ["update_plugin.py", "--commit", commit]
exec(compile(code, url, "exec"), {"__name__": "__main__"})
'
```

`detached HEAD` 是正常的版本锁定提示。热更新期间不要同时在页面点击升级主程序或修改插件配置。

## 检查是否成功

1. 终端出现 **“hot-reload 已验证”**、**“PID/start 未变化”** 和 **`Upgrade verified.`**；脚本已检查服务 active，成功后自动清理本次源码。
2. 按 **Ctrl + Shift + R** 刷新管理中心，打开 **插件栏 → CPA 一键更新**。
3. 在管理中心勾选“记住密码”登录后，打开插件应自动填入密钥并连接；未复用时可重新登录管理中心，或手动输入管理密钥。
4. 检查原有 API 请求正常。不用点击“立即更新”来验收插件，那会升级主程序。

## 成功后的自动清理

- 只删除本次命令创建的源码目录；旧的 `/root/cliproxy-updater-update.*` 目录不会被批量删除。
- 为规避共享插件目录中的文件替换竞态，**暂停自动删除旧插件文件**。仍记录当前/上一版本，旧文件保留，不影响热更新。
- 历史来源不明的插件、商店文件、恢复备份、配置和 OAuth 数据不删。因此目录里可能仍超过两个文件。
- 清理失败只显示警告，不影响已经验证成功的更新；失败、中断或仅恢复旧事务时保留源码。

## 报错怎么办

- **后台正忙或有未完成任务**：先等待任务结束，不要删除队列、事务或旧插件文件。
- **提示“旧 hot 事务已恢复并验证”**：这次只恢复了旧插件；确认服务正常后，按终端打印的保留目录进入其 `source` 子目录，再运行 `sudo bash install.sh --hot-reload` 执行升级；手动执行不会自动删除源码。
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

清理只释放磁盘文件；官方宿主仍会保留已加载的旧库映像。不要频繁反复切换或手工清理，维护时再安排正常重启。所有更新仍建议保留重要配置和 OAuth 数据备份。

热更新测试中的请求和流式响应保持正常，但不能保证所有环境、所有插件行为都零中断。非本仓库安装布局、自定义目录或其他宿主版本请先核对兼容性。[技术验证与边界](DEVELOPMENT.md)。
