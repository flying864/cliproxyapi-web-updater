# 运维与恢复

返回 [README](../README.md)。以下操作面向主机管理员，恢复/重装请安排维护窗口。

## 文件在哪里

| 路径 | 用途 |
| --- | --- |
| `/var/lib/cliproxy-updater-status/status.json` | 最近状态；root 控制，服务组只读，重启后保留 |
| `/var/lib/cliproxy-updater` | root 私有备份、批准记录、锁和恢复事务 |
| `/run/cliproxy-updater/inbox` | 临时请求；只允许固定检查/更新/备份扫描/选择清理命令，不是 shell 入口 |
| `/usr/local/libexec/cliproxy-updater-worker` | 按需运行的后台脚本 |
| `/usr/local/libexec/cliproxy-updater-runtime.py` | 可信路径与降权归档辅助代码 |

## 先看状态，再处理

```bash
sudo cat /var/lib/cliproxy-updater-status/status.json
sudo journalctl -u cliproxy-updater.service -u cliproxy-updater-recover.service -n 100 --no-pager
sudo systemctl status cliproxyapi.service --no-pager
```

- **只是页面断线**：主服务重启时正常，先等重连；不要仅凭 HTTP 错误认定升级失败。
- **要求重新检查**：用户确认后官方版本变化，重新检查并确认目标版本。
- **未初始化或协议不兼容**：使用配套源码执行 README 的 Worker 初始化步骤，不能用商店 UI 版本推断后台版本。
- **OAuth 路径不符**：确认实际目录和权限，无遗留事务后重新初始化；不要直接编辑批准记录。
- **恢复失败**：保留日志、事务和备份，先排除磁盘/配置/权限等底层问题。不要删除事务或队列“解锁”。

## 重试二进制恢复

确认问题已处理，并接受主服务可能停启后，在维护窗口执行：

```bash
sudo systemctl start cliproxy-updater-recover.service
sudo cat /var/lib/cliproxy-updater-status/status.json
sudo journalctl -u cliproxy-updater-recover.service -n 100 --no-pager
```

启动命令成功不等于业务恢复成功，仍需核对状态与主服务。恢复失败会保留材料供再次处理；自动恢复只恢复二进制，不覆盖配置/OAuth。没有网页手动切换旧版功能。

## 备份容量与保留

达到磁盘或备份预算会拒绝更新，**不会自动删除备份**。在插件页面展开“备份管理”，点击扫描/刷新：先查看备份组时间、类型、大小和保护原因，再勾选可以删除的旧组，核对选中数量和占用后确认永久删除。默认不选中任何项目，每次最多 20 组。删除的是整组旧程序与数据快照，不是只删除其中的压缩包；不可撤销。

- 只处理 `/var/lib/cliproxy-updater/backups/` 下的主程序备份组、私有状态目录的 `install-*` 安装快照；不扫描或删除运行中的配置、OAuth 目录、billing 数据、旧 `.so`、失败隔离库、源码目录和其他插件。
- 新版在更新/安装验证成功后登记备份归属；**既有未登记历史备份只显示、不可选中**，不会仅凭名称把旧文件认领成可删文件。失败或登记不完整的备份保持保护；需要管理员另行审查后处理。
- 每类最近一份成功备份保留；有主程序或热更新恢复事务时禁止删除。清理和更新共用锁，扫描/清理不会停启服务，也不会触发二进制恢复。失败钩子仅对 root 保护的中断主程序更新请求执行恢复；备份请求失败不会沿 systemd OnFailure 自动恢复主程序，开机恢复仍保留。
- 选择绑定一次预览，10 分钟过期。文件身份/内容、事务或保护状态变化后拒绝原选择，需要重新扫描。预检失败不开始删除；执行过程中 I/O 失败可能仅删除部分，页面结果不是“全成或全败”的原子事务。
- 提交成功只是排队，等待结果才知道实际是否删除。断线时不自动重发删除；重新连接、扫描核对。清理结果独立保存，不抹掉最近主程序升级结果。
- 清单每页最多 100 组，支持上一页/下一页；翻页会刷新 token 并清空选择。显示逻辑文件大小（不是实际磁盘块），只统计组内普通文件。备份含密钥和账号数据，不提供网页下载或内容浏览，公共清单只暴露元数据。

此功能需要新页面和配套后台：仅 `--hot-reload` 不更新 Worker。后台缺少 `backups_protocol:1` 时禁用清理，不影响原版本检查/更新。安排维护并确认授权后，用同一份已验证源码执行 `sudo bash install.sh --worker-only` 更新后台，再按 [更新插件](UPDATING.md) 热更新页面。

不要批量删除整个私有状态目录，不要删事务来“解锁”。备份应按敏感文件保存。

详细信任边界见[安全说明](SECURITY.md)。真实 OAuth、聊天、图片和反代验收需另行授权；不要把源码测试通过当成线上验收。
