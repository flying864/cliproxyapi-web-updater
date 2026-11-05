# 历史 v0.4.0 开发补丁

v0.5.0 已包含运行组件更新，不再使用旧发布文件叠加方式。直接 clone 当前仓库，并按 README 安装或执行一次 `install.sh --worker-only`。

`apply_to_repo.sh` 仍保留为历史工具，但从 v0.5.0 源码调用会在写文件前拒绝；不要绕过版本门禁把新旧 Worker/UI 混装。需要复现旧版补丁时使用固定 v0.4.0 commit。
