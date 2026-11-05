# CPA Web Updater — 官方商店发布格式（v0.4.0）

仓库：<https://github.com/flying864/cliproxyapi-web-updater>

> **发布格式合规不等于店内一键安装。** ZIP 只包含动态库，不安装/升级 root worker、systemd units 或权限。当前安装器的 root-owned 插件目录不允许非 root 商店进程写入；本次不改变这个安全边界。不要 chmod 777、递归改属主或以 root 运行主程序。

## 代码与发布状态

- main/PR：运行完整验证和 Linux amd64/arm64 原生生产库构建，仅生成短期 Actions 测试产物，**不创建 Release**。
- tag `v数字.数字.数字`：复用同一套完整验证及双架构构建，均成功后才发布。
- registry 只有插件元数据，不手工维护版本；实际版本和下载来源是 GitHub 最新正式 Release。
- 将代码推到 main 既不代表已发布二进制，也不代表已获官方商店合并。

## 验证与版本维护

```bash
python3 -B scripts/check_release_version.py --tag v0.4.0
python3 -B scripts/validate_registry.py
python3 -B -m unittest discover -s tests -p 'test_store_*.py' -v
```

以后升级版本使用 `scripts/bump_version.py`；它同时检查 C metadata、ABI 单测、官方宿主单测、README 标题和 worker 注释五处，拒绝后缀、重复或不一致标记。不会自动更新历史 changelog 或发布说明，需人工审查。正常写入异常会尝试恢复原文件，不能把多文件更新称为断电原子事务。

完整验证定义在 `.github/workflows/verify-core.yml`：除了商店脚本回归，还执行原 ABI、sanitizer、worker、安装卸载和真实官方 v8.0.56 宿主集成。main 与 tag 复用该文件并 checkout 精确 `github.sha`，不会借用另一个 commit 的绿色状态。

`.github/workflows/build-store.yml` 在 `ubuntu-24.04` 与 `ubuntu-24.04-arm` 原生编译最终 `.so`，记录 readelf 符号版本并加载**这一份生产文件**验证 ABI、metadata 和路由注册；然后打包。此冒烟只调用注册方法，不触碰 `/run` 队列。

## 发布（需要单独授权）

推送 tag 会触发公开 Release，属于独立发布动作；普通源码修正不应顺手执行。确认审批、main 验证与变更后才进行：

```bash
python3 -B scripts/check_release_version.py --tag v0.4.0
git tag -a v0.4.0 -m 'CPA Web Updater v0.4.0'
git push origin v0.4.0
```

若 tag/Release 已存在，不覆盖、不强推，核对原状态或选择新版本。tag 工作流将生成：

```text
cpa-updater_0.4.0_linux_amd64.zip
cpa-updater_0.4.0_linux_arm64.zip
checksums.txt
```

两份 ZIP 都只包含根目录普通文件 `cpa-updater.so`。`checksums.txt` 是 ZIP 的 SHA256，不是 `.so` 的哈希。发布 job 仅在完整验证与整个双架构构建成功后获得 contents:write；它拒绝覆盖已有 Release，发布后回读 tag/资产状态并下载校验实际字节。

商店使用 Go 架构名 **arm64**，不同于 CLIProxyAPI 主程序 release 的 **aarch64** 包名，不能混用。

## 中断后的人工核对

若发布步骤失败：先查看精确 tag 的 Release 是否不存在、为 draft 或已经公开，以及资产是否齐全。响应丢失不等于发布没有发生。流程不会自动删除或覆盖已有 Release。

```bash
gh release view v0.4.0 --repo flying864/cliproxyapi-web-updater --json tagName,isDraft,isPrerelease,assets
```

保留日志，在确认原因和获得相应授权后才恢复/删除草稿或重新发布。不要无条件重跑并覆盖。GitHub CLI 普通资产上传使用 draft 再公开，但强杀或网络错误仍需人工判断。

## 商店源与官方登记

本仓库登记文件：

```text
https://raw.githubusercontent.com/flying864/cliproxyapi-web-updater/main/registry.json
```

该 URL 可读只代表元数据已推送；没有正式 Release 时不能完成资产安装。发布且回读验证成功后，才使用 [OFFICIAL_REGISTRY_PR.md](OFFICIAL_REGISTRY_PR.md) 向官方仓库提交单条记录。不能用本项目的单插件 registry 覆盖官方整个数组，未合并不得称“已上架官方商店”。

不要为测试源覆盖生产 config.yaml，也不要替换已有 plugins 配置块。

## 主机预检和权限限制

```bash
python3 -B scripts/market_preflight.py
```

脚本只读取账户、路径属性及权限位，不创建探测文件、不修改权限、不调用 systemctl。它按 owner/group/other 的互斥优先级检查目录和祖先；即使权限位通过，也**不验证 ACL、只读挂载、systemd 沙箱或实际写入**。worker 文件存在不代表它已正确部署或健康。

当前安装器要求 root-owned 插件目录，而官方商店以主服务用户写入 `plugins/<goos>/<goarch>/<id>-v<version>.so`。因此仍应使用源码安装器管理本插件和 worker；店内安装的权限模式需另行设计、审核、目标主机验收，不能在发布格式修复时放宽。

商店只更新动态库，不同步 worker。当前版本的 worker 仅更新版本注释，协议不变；未来不能以商店显示版本判断整套主机部署已升级。

## 平台与安全范围

- 主机运行条件沿用 README：Linux、glibc、systemd、非 root 主服务、固定目录。没有 Windows/macOS 或 Docker/DSM 支持。
- 发布二进制保守支持 Ubuntu 24.04 的 glibc 环境。CI 会记录实际 ELF 符号依赖；不承诺 Ubuntu 20.04、任意旧 glibc 或 musl 可加载。需要其他环境时应在对应环境源码构建和验收。
- 两个架构原生构建/ABI 验证不等于两架构完整生产部署；官方宿主完整集成固定在 amd64 v8.0.56。
- 同源 SHA256 不能独立抵御发布账号被攻陷。依赖 Actions 固定 commit SHA，后续更新应审核。
- 原生库与主服务同进程；API 更新会短暂中断。自动恢复只恢复主程序二进制，不覆盖配置/OAuth 数据。

## 旧源码补丁工具

已经 clone 本仓库当前 main 的用户**不需要运行** `apply_to_repo.sh`。工具仅用于把完整 v0.4.0 源码中的发布文件应用到仍停留在原 v0.3.0 的干净 checkout：

```bash
bash apply_to_repo.sh /path/to/clean-v0.3.0-checkout
```

它拒绝非 Git 根目录、dirty/冲突目标或不匹配基线；使用私有临时目录，正常异常回滚本次写入，不操作真实服务、不自动 commit/tag/push。只做本地转换/构建检查，不替代完整 CI。强杀/断电不保证自动恢复；不要将其当成通用代码合并工具。推荐直接使用仓库当前版本，避免维护重复补丁流程。
