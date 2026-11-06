# 商店打包与发布

本指南面向维护者，普通用户从 [README](README.md) 开始。当前源码版本为 v0.5.0；文中的 Release 地址和资产名是发布目标，不代表已经发布或上架。

## 先分清三个环节

1. **源码验证**：main/PR 运行完整测试和 amd64/arm64 构建，只生成短期 Actions 产物，不创建 Release。
2. **发布资产**：推送正式 tag 后，精确 tag commit 的完整验证和双架构构建均成功，才创建 GitHub Release。
3. **官方登记**：Release 验证完成后，另向官方商店提交 PR；未合并不得称“已上架”。

商店 ZIP **只包含动态库**，不安装/升级 root Worker、systemd 单元或权限。主机初始化仍见 README 的 `--worker-only` 步骤。不要用商店显示的插件版本判断整套后台已升级。v0.5.0 的 Worker 版本注释有更新，协议仍为 1；未来升级仍须核对配套组件，不能默认兼容。

## 验证版本和元数据

在源码根目录运行：

```bash
python3 -B scripts/check_release_version.py --tag v0.5.0
python3 -B scripts/validate_registry.py
python3 -B -m unittest discover -s tests -p 'test_store_*.py' -v
```

以后升级版本时，用 `python3 -B scripts/bump_version.py 新版本号`，将“新版本号”替换为不带 v 的三段数字。它同步 C metadata、ABI 测试、官方宿主测试、README 标题、Worker 注释和 runtime 版本六处，拒绝重复、不一致或带后缀的标记。历史 changelog 和发布说明须人工更新；普通写入失败会尝试恢复，不能保证多文件断电原子性。

完整本地命令见[开发指南](docs/DEVELOPMENT.md)。工作流分别为：

- [verify-core.yml](.github/workflows/verify-core.yml)：完整隔离测试及固定官方 v8.0.56 宿主集成。
- [build-store.yml](.github/workflows/build-store.yml)：Ubuntu 24.04 amd64/arm64 原生构建，记录 ELF 符号依赖，加载最终生产 `.so` 验证 ABI、metadata 和注册，再打包；不触碰 `/run` 队列。
- [release-plugin.yml](.github/workflows/release-plugin.yml)：两项均成功才获得发布写权限；拒绝覆盖已有 Release，发布后回读状态并下载核对实际字节。

## 发布：必须单独授权

**推送 tag 会触发公开发布。** 以下不是普通测试命令，仅在确认授权、目标 commit、版本和验证结果后执行：

```bash
python3 -B scripts/check_release_version.py --tag v0.5.0
git tag -a v0.5.0 -m 'CPA Web Updater v0.5.0'
git push origin v0.5.0
```

tag/Release 已存在时不覆盖、不强推，应核对原状态或选新版本。预期资产：

```text
cpa-updater_0.5.0_linux_amd64.zip
cpa-updater_0.5.0_linux_arm64.zip
checksums.txt
```

每份 ZIP 只有根目录普通文件 `cpa-updater.so`。`checksums.txt` 是 **ZIP** 的 SHA256，不是 `.so` 的哈希。商店采用 Go 架构名 `arm64`，主程序 Release 包采用 `aarch64`，两者不能混用。

## 发布中断怎么办

响应丢失不等于未发布。先只读核对精确 tag，检查 Release 是否不存在、为 draft 或已公开，以及资产是否齐全：

```bash
gh release view v0.5.0 --repo flying864/cliproxyapi-web-updater --json tagName,isDraft,isPrerelease,assets
```

保留日志，确认原因并取得相应授权后再恢复/删除草稿或重新发布。流程不会自动删除或覆盖已有 Release；不要无条件重跑。强杀、网络中断和 GitHub CLI 上传/公开过程中的不确定状态都需人工核对。

## 商店源与官方登记

本仓库元数据源：

```text
https://raw.githubusercontent.com/flying864/cliproxyapi-web-updater/main/registry.json
```

registry 只维护插件元数据；版本和下载来源取自 GitHub 最新正式 Release。URL 可读不代表资产可安装。发布并回读成功后，按[官方登记 PR 模板](OFFICIAL_REGISTRY_PR.md) 提交单条记录；不能替换官方整个数组。不要为测试源覆盖生产 config.yaml 或已有 plugins 配置块。

## 主机权限与兼容性

可运行只读预检：

```bash
python3 -B scripts/market_preflight.py
```

它只读账户、路径和权限位，不创建探测文件、不改权限、不调用 systemctl。owner/group/other 按互斥优先级检查；不验证 ACL、只读挂载、systemd 沙箱或实际可写性，Worker 文件存在也不代表部署健康。

商店以主服务用户写入 `plugins/<goos>/<goarch>/<id>-v<version>.so`。安全的 `cliproxy:cliproxy 700` 插件目录可保留；旧 root-owned 不可写目录仍可能阻止商店安装，不自动放宽权限。禁止 `chmod 777`、递归改属主或用 root 运行主程序。

发布库面向 Ubuntu 24.04 glibc，不承诺旧 glibc、Ubuntu 20.04 或 musl 可加载。其他环境须自行源码构建并验收；双架构 ABI 冒烟不等于双架构完整服务验收。原生库与主服务同进程，更新会短暂中断，自动回滚只恢复主程序二进制。其他限制见[安全说明](docs/SECURITY.md)。

历史开发补丁叠加方式已移除；需要复现旧版时查阅固定版本的 Git 历史，不要混装新旧 UI/Worker。
