# 官方商店登记 PR 模板

面向维护者。先完成[发布及资产回读](STORE_PUBLISHING.md)，再向 [CLIProxyAPI-Plugins-Store](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store) 提交 PR。提交或合并 PR 不会替你安装主机 Worker。

## 修改内容

在官方 `registry.json` 的 `plugins` 数组增加**一条**记录，保留其他插件。不能用本仓库的单插件 registry 替换官方整个文件：

```json
{
  "id": "cpa-updater",
  "name": "CPA Web Updater",
  "description": "Web UI to check and explicitly approve CLIProxyAPI binary updates; requires a separately installed, privileged systemd worker. Linux only.",
  "author": "flying864",
  "repository": "https://github.com/flying864/cliproxyapi-web-updater",
  "homepage": "https://github.com/flying864/cliproxyapi-web-updater",
  "tags": ["management", "utility", "linux"]
}
```

## PR 描述参考

发布后先核对版本和资产，再使用以下内容；目标地址未必已经存在：

- 仓库：`https://github.com/flying864/cliproxyapi-web-updater`
- Release：`https://github.com/flying864/cliproxyapi-web-updater/releases/tag/v0.5.0`
- 资产：`cpa-updater_0.5.0_linux_amd64.zip`、`cpa-updater_0.5.0_linux_arm64.zip`、`checksums.txt`
- 功能：需要管理密钥的页面，只执行用户明确确认的二进制更新；特权 Worker 必须在 Linux systemd 主机单独初始化。
- 限制：商店只安装动态库，不部署 Worker 或改变权限；旧 root-owned 不可写插件目录可能阻止安装，已有安全服务用户目录保持不变。

不要手动插到官方插件列表第一位，遵守维护者按 PR 合并顺序排序第三方插件的规则。PR 未合并前不要宣称“已上架”。
