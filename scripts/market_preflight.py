#!/usr/bin/env python3
"""Read-only mode-bit preflight, not an effective-access or worker health test."""
import os
import pwd
from pathlib import Path
import stat

PLUGIN_DIR = Path('/opt/cliproxyapi/plugins')
WORKER = Path('/usr/local/libexec/cliproxy-updater-worker')


def mode_allows(st, uid, groups, required):
    # POSIX permission classes are mutually exclusive, even for an owner whose
    # group permissions are more permissive. Do not use the checker's os.access.
    shift = 6 if st.st_uid == uid else 3 if st.st_gid in groups else 0
    return (st.st_mode >> shift) & required == required


def main():
    print('MODE CHECK ONLY: ACL, mount restrictions, service sandbox unknown.')
    print('No effective-access test or worker health check is performed.')
    try:
        user = pwd.getpwnam('cliproxy')
    except KeyError:
        print('FAIL: cliproxy service user does not exist')
        return 1
    groups = os.getgrouplist(user.pw_name, user.pw_gid)
    # Inspect from root down without resolving symlinks. Every ancestor needs
    # search permission; only the final directory needs write as well.
    directory = Path(os.path.abspath(PLUGIN_DIR))
    for path in (*reversed(directory.parents), directory):
        try:
            st = path.lstat()
        except OSError as exc:
            print(f'BLOCKED: cannot inspect {path}: {exc}')
            return 1
        if not stat.S_ISDIR(st.st_mode):
            print(f'BLOCKED: directory missing, symlink or non-directory: {path}')
            return 1
        if st.st_mode & stat.S_IWOTH:
            print(f'BLOCKED: world-writable directory (unsafe): {path}')
            return 1
        required = 0o3 if path == directory else 0o1
        if not mode_allows(st, user.pw_uid, groups, required):
            print(f'BLOCKED: cliproxy lacks mode-bit write/search permission: {path}')
            print('Do NOT chown without reviewing installer safeguards.')
            return 1
    print('Directory mode bits permit write/search; actual access remains unknown.')
    exists = WORKER.exists()
    print('Independent root worker exists (health unknown):', exists)
    return int(not exists)


if __name__ == '__main__':
    raise SystemExit(main())
