# 向官方 CLIProxyAPI-Plugins-Store 提交 PR

官方仓库：<https://github.com/router-for-me/CLIProxyAPI-Plugins-Store>

在其 `registry.json` 的 `plugins` 数组增加以下一条（不能用你的单插件 registry 替换官方整个数组）：

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

PR 描述可写：

- Repository: `https://github.com/flying864/cliproxyapi-web-updater`
- Release: `https://github.com/flying864/cliproxyapi-web-updater/releases/tag/v0.5.0` **（发布完成后才会存在）**
- Assets: `cpa-updater_0.5.0_linux_amd64.zip`, `cpa-updater_0.5.0_linux_arm64.zip`, `checksums.txt`
- Capability: authenticated management page for explicit user-approved binary updates; privileged worker separately provisioned on Linux systemd hosts.
- Disclaimer: market only deploys shared library. It does not deploy host systemd worker, and existing root-owned plugin directories may still prevent marketplace installation; service-owned secure plugin directories are preserved.

不要手动将 PR 插入官方插件列表第一位；官方维护者按 PR 合并顺序排序第三方插件。
