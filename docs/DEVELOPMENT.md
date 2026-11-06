# 开发与测试

返回 [README](../README.md)。在源码根目录运行以下命令；这不是生产安装步骤。

## 基础验证

需要 Python 3、gcc；前端测试另需 Node.js。Node 不是生产运行依赖。

```bash
python3 -B scripts/check_release_version.py --tag v0.5.0
python3 -B scripts/validate_registry.py
python3 -B test_plugin.py
node tests/test_panel.js
python3 -B tests/test_sanitizer.py
python3 -B -m unittest discover -s tests -p 'test_store_*.py' -v
```

## 系统路径与权限测试

需要 bubblewrap 和已授权的 root/非交互 sudo。测试使用私有文件系统/网络隔离；缺少隔离能力应报错，不允许退回宿主直接执行。

```bash
sudo env CPA_TEST_REAL_UID=1 python3 -B tests/test_worker.py
sudo env CPA_TEST_REAL_UID=1 python3 -B tests/test_install.py
python3 -B tests/test_simple_install.py
sudo python3 -B tests/test_runtime.py
```

`CPA_TEST_REAL_UID=1` 要求真实非 root 归档测试。受 AppArmor 限制时，不带此变量只能运行明确的控制流替身，真实 UID 用例会跳过；跳过不等于完整验收。不要解除主机安全策略来绕过测试限制。

## 固定官方宿主集成

以下会下载固定基准官方二进制，但只在测试沙箱启动，不安装生产 systemd 单元、不读取真实密钥、不重启宿主主服务：

```bash
mkdir -p test-output
python3 -B tests/fetch_official.py --output test-output/cli-proxy-api
sudo python3 -B tests/test_official.py --binary test-output/cli-proxy-api --output test-output/official
```

固定基准为 amd64 CLIProxyAPI v8.0.56，涵盖真实插件注册、鉴权、版本确认、并发队列及测试子进程重启后的结果恢复。操作系统边界使用替身的用例与真实宿主集成不能混称；见 [AUDIT](../AUDIT.md)。

## CI、版本与发布

- [完整验证工作流](../.github/workflows/verify-core.yml) 供 main/PR 和 tag 复用，检出精确 commit。
- [双架构构建](../.github/workflows/build-store.yml) 在 Ubuntu 24.04 的 amd64/arm64 原生 runner 编译，并加载最终生产库做 ABI 冒烟；不等于两个架构都完成真实服务验收。
- README 标题也是机器检查的版本标记，保留 `# CPA Web Updater v版本号` 格式。升级用 `scripts/bump_version.py`，不要只改单处；用法和发布门禁见[发布指南](../STORE_PUBLISHING.md)。
- Actions 结果以精确 commit 的实际运行记录为准。源码测试、CI、源码推送均不等于线上部署，不能据此声称真实 OAuth/模型/反代验收通过。
- Push、tag、Release、官方商店 PR 和生产部署必须分别获得授权。
