# CPA Web Updater v0.4.0 源码/旧版补丁说明

当前仓库已经整合商店发布格式，无需再次运行 apply_to_repo.sh。

如需为仍停留在原 v0.3.0 的干净 Git 根目录应用发布文件，可从此完整源码目录运行：

```bash
bash apply_to_repo.sh /path/to/clean-v0.3.0-checkout
```

脚本不会部署、发布或提交；正常异常尽力回滚，断电/强杀需人工复核。完整测试与发布流程见 STORE_PUBLISHING.md。

代码推送不等于 Release，不等于官方登记合并，也不等于解决 root worker 和商店目录权限限制。
