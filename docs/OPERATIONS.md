# 运维与恢复

返回 [README](../README.md)。以下操作面向主机管理员，恢复/重装请安排维护窗口。

## 文件在哪里

| 路径 | 用途 |
| --- | --- |
| `/var/lib/cliproxy-updater-status/status.json` | 最近状态；root 控制，服务组只读，重启后保留 |
| `/var/lib/cliproxy-updater` | root 私有备份、批准记录、锁和恢复事务 |
| `/run/cliproxy-updater/inbox` | 临时请求；只允许固定检查/更新命令，不是 shell 入口 |
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

达到磁盘或备份预算会拒绝更新，不自动清理失败证据。管理员确认没有遗留事务且相关材料不再用于恢复后，再自行归档旧备份和安装快照。不要批量删除整个私有状态目录；备份中可能有密钥和账号数据，应按敏感文件保存。

详细信任边界见[安全说明](SECURITY.md)。真实 OAuth、聊天、图片和反代验收需另行授权；不要把源码测试通过当成线上验收。
