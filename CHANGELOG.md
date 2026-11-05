# Changelog

## 0.5.0

- Keep a two-action Web UI: check, confirm update, and automatic reconnect to the last result.
- Preserve existing `--config`/`-config` service arguments and safe service-owned plugin directory permissions.
- Add worker-only initialization without replacing the plugin or restarting the main service.
- Persist public status separately from root-private backups and reject missing/incompatible worker protocol.
- Approve the actual OAuth directory once and read runtime backup data without root privileges.
- Strengthen readiness with the running host version and a stable service observation window.
- No task center, history UI, notification service, database, automatic upgrade or runtime framework.

## 0.4.0

- Add official-store schema v1 registry and native amd64/arm64 ZIP packaging.
- Require full verification of the exact tag commit before publishing; reuse main CI and pin Actions commits.
- Validate the final production library ABI before packaging and read back published asset bytes.
- Include the official-host test in complete version checks; reject numeric-prefix/suffix mismatches.
- Correct read-only permission-bit checks and reject nonregular ZIP entries.
- Guard legacy overlay application against conflicts and ordinary partial-write failures.
- Preserve root worker and host permission boundaries; store publication is not a one-click host installer.

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
