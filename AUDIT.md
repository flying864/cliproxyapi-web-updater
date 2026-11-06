# 验证记录与未覆盖范围

**这是历史验证记录，不是当前工作树或生产主机的验收结论。** 测试数量、版本和已执行结果仅对应当时记录；当前结果应以精确 commit 的测试输出/Actions 记录为准。源码交付、Push、CI、Release 和生产部署不能混为一谈。

当前测试方法见[开发指南](docs/DEVELOPMENT.md)，操作风险见[安全说明](docs/SECURITY.md)。本文件不授权发布或部署。

## v0.5.0：两项操作与初始化

- UI 只保留检查与确认更新，最近状态持久化，并有协议初始化提示和断线重连；未新增任务中心、数据库或常驻服务。
- 本地曾执行固定官方 v8.0.56 测试子进程真实退出/重启，验证持久结果恢复。Node vm 执行真实嵌入脚本，模拟 POST 未送达、重连及重复点击；这不是生产升级。
- 本机 AppArmor 限制跨 UID，Worker 控制流使用明确的 snapshot 边界替身；真实降权归档用例显式 skipped，没有解除 AppArmor。CI 设置 `CPA_TEST_REAL_UID=1`，要求真实非 root 子进程读取配置/OAuth/plugins、root 控制输出并拒绝链接；是否通过仍以具体 CI 记录为准。
- 支持 `-config`/`--config` 和无歧义附加参数，不重写主 service。保留安全插件目录权限，Worker-only 安装不修改插件、不重启主服务。
- 初始化时通过 API 批准实际 auth-dir，升级前固定 loopback API 再核对；变化即中止并要求重新初始化。辅助代码在固定 root libexec 路径，自动回滚仍只恢复二进制。

## v0.4.0：商店格式与发布门禁

- 保留 v0.3.0 的业务权限和更新协议边界，增加版本、权限、ZIP、旧补丁应用回归及工作流依赖检查。
- main 与 tag 复用完整验证；双架构 job 加载最终生产库。源码 Push 不授权 tag/Release，Actions 状态需核对精确 commit。
- 修复/补测官方集成测试版本遗漏、稳定版本前缀误接受、发布未依赖完整验证、owner 借用 group 权限、非普通 ZIP 条目，以及当时旧补丁工具的冲突和普通失败恢复。
- 部分代码是后补回归，不宣称所有内容从零严格 TDD。旧补丁工具现已移除，历史行为可在 Git 中查阅。
- 当时未执行生产商店安装、权限迁移、Release 或注册表 PR。root-owned 不可写目录仍可能阻止店内安装；arm64 构建/ABI 冒烟不等于完整服务验收。

## v0.3.0：历史兼容性与事务修复

该版修复 v0.2.0 的注册、接口路径、版本确认、队列发布、更新恢复及安装事务，不增加业务功能。运行组件仍为 C 插件和 Bash Worker；Python 标准库 helper 是一次性辅助程序，不是新服务。

### 固定官方宿主

- CLIProxyAPI v8.0.56，commit `585f97deac9aa57c700301221fb1a7085e1827cc`。
- Linux amd64 官方压缩包 SHA256：`6f313dfdfbb62154de97a446cfc47d5a3419723484ea9f3bc1fb0a3015d195e7`。

在隔离网络和文件系统中使用真实二进制验证：

- 插件注册、effective_enabled、当时 v0.3.0 版本及本仓库元数据。
- 匿名资源页 200，匿名管理请求 401；测试密钥 status 200、check 202。
- 缺失、多值、过期确认版本被拒绝且不入队，正确版本准确入队。
- 并发仅一个请求成功，request 链接数始终为 1。
- v8 config/plugins 返回直接配置对象，与安装 helper 的数据结构一致。

### 当时本地回归

| 项目 | 记录的验证范围 |
| --- | --- |
| C 编译 | `-std=c11 -Wall -Wextra -Werror -O2 -fPIC -shared` |
| `test_plugin.py` | 9 项回归，独立临时目录及编译期状态属主注入，不碰生产 `/run` |
| `tests/test_sanitizer.py` | 12,000 次有界畸形 ABI 请求，ASan/UBSan 未报错，不是形式证明 |
| `tests/test_worker.py` | 6 项 unittest；成功、替换/启动失败、恢复失败及重试、TERM/INT/HUP、强杀后离线恢复、低磁盘、版本/checksum 错误、错误身份、暂存链接、归档超限、只读 preflight、版本探测超时等子场景 |
| `tests/test_install.py` | 13 项 unittest；首次/重复安装、卸载、API/注册/触发器失败恢复、锁竞争、目录与权限、恢复 unit、命令时限、健康等待等子场景 |
| 语法与 unit | Shell 逐一 `bash -n`、Python AST 校验；在私有文件系统对原始 unit 执行 `systemd-analyze verify`，未改 ExecStart 为 true 掩盖缺文件 |

部分回归先观察到原实现失败再修复，其余是后补覆盖，不能宣称每条断言都独立完成严格 TDD。

### 替身和隔离边界

Worker 测试使用原生产脚本，但 curl/systemctl/runuser 等 OS 边界使用明确替身。安装沙箱执行实际入口及 Worker preflight，但管理 API、systemctl/tmpfiles 为替身；API 结构另由真实官方集成验证。

当时本地 namespace 的 cliproxy 是单 UID fixture，不能证明真实降权已验收；目标主机仍需身份/权限验收。没有读取真实管理密钥、安装宿主 unit 或重启宿主主服务。

## 所有历史结果都不覆盖的保证

- 没有据此验证生产环境或真实 systemd PID 1 上的安装/升级，没有改变线上服务。
- v0.3.0 本地记录未运行 aarch64；后续双架构构建/ABI 验证不应反写为当时已完整验收。
- 未模拟全部 fsync/硬件断电窗口、磁盘损坏、每个归档预算边界或真实 OAuth 迁移。
- 自动回滚仅恢复二进制，配置/OAuth 及不可逆迁移不能自动安全回滚。
- 安装器普通异常/信号仅有限恢复；SIGKILL/断电快照需人工处理。
- JSON 解析不是通用 Unicode JSON 验证器，同源 SHA256 不能独立证明发布者身份。
- 备份不自动清理失败证据，超预算拒绝升级；安装快照也须人工保留管理。

本记录不声称已发布 GitHub Release、上架商店或完成生产部署；这些状态须单独回读核实。
