# Changelog

## 0.3.0

- Fix official plugin registration metadata and full management routes; use the project GitHub repository.
- Bind the confirmed version end-to-end through `Query.version`, trusted status and the worker release check.
- Publish the single-file queue atomically without a transient second hard link.
- Replace substring JSON dispatch with bounded structured parsing; vendor the MIT-licensed jsmn header.
- Add isolated plugin, official-host, sanitizer, worker and installer regression tests. Tests do not use production paths or real credentials.
- Persist the binary recovery transaction before stopping the main service. Keep recovery material and explicit failure state when recovery fails.
- Add bounded probes/downloads/archives and offline interrupted-transaction recovery without reattempting an update.
- Share installer/uninstaller validation, locking and rollback code in a Python stdlib helper; no new daemon or package dependency.
- Require verified registration and endpoints before reporting installation success; protect plugin directory access and other-plugin configuration.
- Clarify that rollback restores the binary only, not configuration/OAuth data or irreversible data migrations.

## 0.2.0

Original uploaded implementation. See the v0.3.0 audit and regression coverage for verified compatibility and transaction defects.
