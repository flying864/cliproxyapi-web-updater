# 更新已安装的 CPA Web Updater

返回 [README](../README.md)。本文更新的是**插件页面及配套后台组件**，不是升级 CLIProxyAPI 主程序；网页里的“立即更新”则用于更新主程序，两者不要混淆。

## 本次更新内容

目标源码提交：[`31c08eddf0eddb21c4e1f841dc940085c4f1707c`](https://github.com/flying864/cliproxyapi-web-updater/commit/31c08eddf0eddb21c4e1f841dc940085c4f1707c)。版本元数据仍为 `0.5.0`，请用提交号区分此次源码修订，不要仅凭版本号判断页面是否更新。

- 修复后台轮询使“检查版本”按钮反复禁用、恢复而闪烁的问题。
- 轮询期间的操作串行排队，避免重复提交；提交前复核状态，失效操作明确提示未提交。
- 优化密钥区、版本信息和最近状态布局，适配桌面、手机与系统浅色/深色。
- **“首次打开插件需要再点页面中间才显示”尚未在本地复现，不宣称已解决。**

仓库源码更新不等于创建 Release、更新官方商店或部署服务器。本文命令锁定已演练的源码，不自动追踪后续 `main`。

## 适用范围与风险

- 适用于原先通过本仓库 `install.sh` 安装、且仍符合 [README 安装要求](../README.md#安装) 的 Ubuntu 24.04 原生 systemd 主机。不适用于 Docker、DSM 等部署。
- 如果只通过商店安装、使用版本化 `.so` 或自定义目录，先核对 [商店说明](../STORE_PUBLISHING.md) 和当前插件配置，不直接套用本步骤。
- 先备份重要配置和实际 OAuth 目录，再选择维护窗口。**完整安装会短暂重启 `cliproxyapi.service`，中断 API 请求。**
- 需要 Git、gcc、Python 3、curl、Bash、systemd 等原安装依赖及 sudo 权限。脚本不会自动安装缺失依赖。
- 不要为了通过权限检查使用 `chmod 777`、递归改属主或把主服务改成 root。

## 更新命令

在原来安装插件的服务器上，用 Bash 执行。新建源码目录，不覆盖旧源码；任何步骤失败都会停止后续执行。

```bash
(
  set -e

  workdir=$(mktemp -d "$HOME/cliproxy-updater-update.XXXXXX")
  git clone https://github.com/flying864/cliproxyapi-web-updater.git "$workdir"
  cd "$workdir"

  git checkout --detach 31c08eddf0eddb21c4e1f841dc940085c4f1707c
  python3 -B test_plugin.py

  sudo bash install.sh
  sudo systemctl is-active cliproxyapi.service
)
```

`detached HEAD` 是锁定提交后的正常 Git 提示，不是错误。**不要加 `--worker-only`**：该选项不会替换页面插件，不能用于本次 UI 更新。

## 成功验收

1. 插件测试输出 `OK`。
2. 安装输出“安装已验证完成”，并打印 `/var/lib/cliproxy-updater/install-...` 备份位置。**保存这个实际路径，不要删除备份。**
3. 最后一条命令输出 `active`。服务 active 不代表页面与业务都已验收。
4. 浏览器按 **Ctrl + Shift + R** 强制刷新管理中心，重新进入插件、输入管理密钥。
5. 确认新版布局出现，状态连接正常，“检查版本”按钮空闲时不再闪烁；可手动检查版本，但不要为了验收 UI 而点击“立即更新”升级主程序。
6. 检查原有 API 的正常业务请求。此项需要你自己的环境和合法凭据，不要将密钥贴到 Issue 或日志中。

## 出错后怎么办

出现“安装/卸载中止”“恢复失败”或服务不 active 时，**停止重复安装**，不要删除事务、队列或备份，也不要先卸载插件。

保留终端错误及安装打印的备份路径，查看：

```bash
sudo systemctl is-active cliproxyapi.service
sudo journalctl -u cliproxyapi.service -n 80 --no-pager
```

安装器会在可恢复的失败中尝试还原旧插件、配套文件、相关配置与触发器状态；“有限恢复检查通过”不代表本次升级成功。恢复也可能失败，需结合保留的快照检查，**不要盲目复制备份覆盖整个配置或执行通用降级命令**。更多说明见 [运维与恢复](OPERATIONS.md)。分享日志前遮住密码、Token、Cookie、管理密钥及私人账号信息。

## 旧版升级演练证据与边界

[GitHub Actions 演练记录](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42395864349)：

- 旧源码：`9d85507225ac7dd26604de8abfdf28b67b0868d6`。
- 新源码：`31c08eddf0eddb21c4e1f841dc940085c4f1707c`。
- 测试脚本所在提交：`2a1cf810f436e68917c98009c910ccf68024a56b`；[常规 CI](https://github.com/flying864/cliproxyapi-web-updater/actions/runs/42395864406) 也通过。
- 真实调用两个提交各自未修改的 `install.sh`；验证新插件字节匹配新版构建、独立进程能读取新页面 ABI、旧插件备份存在、配置与 OAuth 测试文件内容和权限保留。
- 在新插件写入后注入触发器启用失败，验证旧插件字节、旧页面、API 配置及触发器状态恢复。
- 结果为 `PASS upgrade`、`PASS rollback`。失败场景中的安装退出码 1 是预期故障注入，不是被忽略的测试失败。

演练位于 GitHub Ubuntu 24.04 amd64 的 bubblewrap 私有文件系统和网络中，使用真实编译、文件和权限操作，但 **systemctl、tmpfiles 与管理 API 是测试替身**，不是完整真实 systemd 部署。它既不是同版本重复安装，也不是升级 CLIProxyAPI 主程序；不覆盖任意历史安装、生产主机差异、真实 OAuth 数据或浏览器宿主的所有行为。**测试通过不等于生产零风险。**
