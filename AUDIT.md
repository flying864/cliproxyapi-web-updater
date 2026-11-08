# 验证记录与边界

本文件保留验证摘要，不代表任何生产主机已经验收。当前结果以精确提交的 Actions 日志和测试输出为准，执行方法见 [开发与测试](docs/DEVELOPMENT.md)，安全要求见 [部署与安全边界](docs/SECURITY.md)。

## 核心证据

- 官方宿主基准：CLIProxyAPI v8.0.56，commit `585f97deac9aa57c700301221fb1a7085e1827cc`，Linux amd64 压缩包 SHA256 `6f313dfdfbb62154de97a446cfc47d5a3419723484ea9f3bc1fb0a3015d195e7`。下载工具固定校验，不追踪 latest。
- 插件：实际 gcc 构建/加载、ABI 注册、版本与路由、匿名管理请求拒绝、用户确认版本绑定、单请求队列、畸形输入 sanitizer。
- Worker：成功升级、下载/校验/空间/启动失败、恢复失败留证、信号与强杀中断、离线恢复、超时及降权归档。自动回滚只恢复二进制，不恢复配置/OAuth。
- 安装器：首次/重复安装、卸载、权限和锁、失败恢复；`--worker-only` 不替换页面、不重启主服务。
- 热更新：真实官方非 root 子进程，PID/start 不变、新页面/路径生效、ETag 并发保护；响应丢失与进程中断恢复；连续 API/SSE；多构建保留当前/上一版、未知文件不删除。
- 页面：实际嵌入 JS 的 Node 回归与 Chromium iframe 测试，覆盖记住密码复用/登出、手动密钥切换、重复点击、断线、窄屏及宿主工具栏遮挡。

## 测试与生产的区别

- Worker 和传统安装沙箱使用真实脚本，但 curl/systemctl/API 的部分边界为测试替身；真实宿主集成另行覆盖接口。热更新使用真实官方服务进程，systemctl 只读查询仍为替身，不是真实 systemd PID 1 验收。
- CI 的 `CPA_TEST_REAL_UID=1` 要求真实降权，不能用单 UID fixture 或 skipped 替代。受限本地环境不解除 AppArmor/namespace 安全策略，使用隔离 CI 验证。
- amd64/arm64 均做原生编译和最终库 ABI 冒烟；真实官方宿主、热更新/SSE 和恢复以 amd64 测试为基准，不泛称两种架构完整部署都通过。
- 不验证所有硬件断电/fsync 窗口、磁盘损坏、真实 OAuth 迁移及付费模型调用。同源 SHA256 是完整性检查，不是独立供应链签名。
- 普通安装快照与热更新/Worker 持久事务不同；恢复失败需保留材料。无任何测试授权删除生产备份或重启服务。

## 历史记录

v0.3.0–v0.5.0 的逐项历史记录可查 [精简前 AUDIT](https://github.com/flying864/cliproxyapi-web-updater/blob/65aab03b839c756f95c0f2037bd8ef35dd14d4af/AUDIT.md)，修复沿革保留在 [CHANGELOG](CHANGELOG.md)。历史发布配套验证不代表实际发布、上架或部署；当前项目只维护 GitHub 源码自安装。
