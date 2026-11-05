# v0.3.0 验证与边界

## 目的

本版本修复 v0.2.0 的注册、接口路径、版本确认、队列发布、更新恢复和安装事务问题，不增加业务功能。运行时仍是 C 插件、Bash worker；安装/卸载共用一次性的 Python 标准库 helper，不是新服务。

## 真实官方集成

固定基准 CLIProxyAPI v8.0.56，commit `585f97deac9aa57c700301221fb1a7085e1827cc`，Linux amd64 官方压缩包 SHA256：

`6f313dfdfbb62154de97a446cfc47d5a3419723484ea9f3bc1fb0a3015d195e7`

真实二进制在隔离网络/文件系统中验证：

- 插件注册、effective_enabled、v0.3.0 版本和本仓库元数据。
- 匿名资源页 200；匿名管理请求 401。
- 带测试密钥 status 200、check 202。
- 缺失、多值、过期的确认版本被拒绝且不入队；正确版本准确入队。
- 并发入队仅一个请求成功，request 链接数始终为 1。
- v8 config/plugins 返回直接配置对象，与安装 helper 使用结构一致。

## 本地回归

- 严格 C 编译：`-std=c11 -Wall -Wextra -Werror -O2 -fPIC -shared`。
- `test_plugin.py`：9 项回归，独立临时目录和编译期状态属主注入，不接触生产 /run。
- `tests/test_sanitizer.py`：12,000 次有界畸形 ABI 请求，ASan/UBSan 未报告错误；不是完备形式证明。
- `tests/test_worker.py`：6 项 unittest，包含成功、替换失败、启动失败、恢复失败及重试、TERM/INT/HUP、强杀后离线恢复、低磁盘、版本不匹配、checksum 错误、错误身份、暂存符号链接、归档成员超限、只读 preflight、真实版本探测 timeout 等子场景。
- `tests/test_install.py`：13 项 unittest，包含首次安装、重复安装、成功卸载、API 拒绝、未注册拒绝、触发器失败恢复、锁竞争、目录缺失与权限、恢复 unit、命令时限及健康等待等子场景。
- 所有 Shell 文件逐一 bash -n；Python AST 语法校验。
- 生成的原始 systemd unit 在私有文件系统中以 systemd-analyze verify 检查，不将 ExecStart 改成 true 来掩盖文件缺失。

部分 regression 先在原实现观察到失败后修复；其余是后补覆盖，不宣称每项断言都单独完成严格 TDD。

## 隔离与替身

worker 测试运行未改写生产脚本，但 curl/systemctl/runuser 等 OS 边界用明确测试替身。安装沙箱执行实际入口和 worker preflight，但管理 API、systemctl/tmpfiles 是替身；其 API 数据结构另外由真实官方集成验证。

本地 namespace 的 cliproxy 账户使用单 UID fixture，因此不能据此宣称真实降权已验收；安装器静态校验真实部署服务账户与文件权限，仍需目标主机验收。测试没有读取真实管理密钥、安装真实 systemd unit 或重启宿主服务。

## 明确未覆盖及保留的限制

- 未在生产环境或真实 systemd PID 1 上安装/升级；没有改变用户线上服务。
- 未运行 aarch64 二进制，不宣称跨架构验收通过。
- 未模拟所有 fsync/硬件断电窗口、磁盘损坏、每一个归档字节预算边界或真实 OAuth 数据迁移。
- 更新回滚只恢复二进制。配置、OAuth 和不可逆迁移不能自动安全回滚。
- 安装器普通异常/信号提供有限恢复；SIGKILL/断电留下的安装快照需人工处理，不宣称安装事务也有全自动崩溃恢复。
- JSON 解析保证有界结构/分隔符/数字/重复字段/顶层字段校验，不是通用 Unicode JSON 验证器；官方宿主及可信 worker 正常序列化是信任边界。
- 同源 SHA256 只能发现损坏，不能独立证明发布者身份。
- 备份不自动清理失败证据；达到预算则拒绝升级，由管理员审查归档。安装快照也需人工保留管理。

## 发布与部署状态

源码交付、Git 推送、CI 和生产部署是不同状态。本文件只记录已经执行的本地验证范围；Actions 是否通过以具体运行记录为准。没有发布 GitHub Release，也没有自动部署。
