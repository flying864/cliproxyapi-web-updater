#!/usr/bin/env python3
"""Pinned, single-use hot updater. No cleanup of pre-existing directories."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile

REPOSITORY = 'https://github.com/flying864/cliproxyapi-web-updater.git'
MARKER = '.update-command-owner.json'


def command(argv, cwd, timeout=300):
    result = subprocess.run(argv, cwd=str(cwd), timeout=timeout,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, check=False)
    if result.stdout:
        print(result.stdout, end='' if result.stdout.endswith('\n') else '\n')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='' if result.stderr.endswith('\n') else '\n')
    if result.returncode:
        raise RuntimeError('command failed: ' + ' '.join(argv))
    return result.stdout


def create_source():
    parent = Path.home().resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix='cliproxy-updater-update.', dir=str(parent)))
    os.chmod(root, 0o700)
    info = root.lstat()
    record = {'path': str(root), 'parent': str(parent), 'device': info.st_dev,
              'inode': info.st_ino, 'uid': info.st_uid, 'nonce': secrets.token_hex(32)}
    marker = root / MARKER
    with marker.open('x') as stream:
        os.chmod(marker, 0o600)
        json.dump(record, stream)
    return root, record


def cleanup_source(root, record):
    """Delete only this invocation's private allocation; refuse substituted paths."""
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_ino != record['inode']
            or info.st_dev != record['device'] or info.st_uid != record['uid']
            or str(root.resolve(strict=True)) != record['path']
            or str(root.parent.resolve(strict=True)) != record['parent']):
        raise RuntimeError('source directory identity changed')
    marker = root / MARKER
    fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        mi = os.fstat(stream.fileno())
        if (not stat.S_ISREG(mi.st_mode) or mi.st_uid != os.getuid()
                or mi.st_mode & 0o077 or json.load(stream) != record):
            raise RuntimeError('ownership marker changed')
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError('safe recursive deletion unavailable')
    os.chdir(root.parent)
    shutil.rmtree(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True, help='exact trusted 40-hex Git commit')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9a-fA-F]{40}', args.commit):
        parser.error('--commit must be exactly 40 hexadecimal characters')
    root = None
    try:
        root, record = create_source()
        print('Source retained on failure: ' + str(root), flush=True)
        source = root / 'source'
        command(['git', 'clone', '--no-checkout', '--', REPOSITORY, str(source)], root)
        command(['git', 'checkout', '--detach', args.commit], source)
        actual = command(['git', 'rev-parse', 'HEAD'], source).strip()
        if actual.lower() != args.commit.lower():
            raise RuntimeError('checked out commit does not match requested commit')
        command([sys.executable, 'test_plugin.py'], source, 900)
        privileged = [] if os.geteuid() == 0 else ['sudo', '--']
        output = command(privileged + ['bash', 'install.sh', '--hot-reload'], source, 900)
        if not any(line.startswith('hot-reload 已验证：') for line in output.splitlines()):
            raise RuntimeError('no new hot-reload verification marker (recovery-only is not an upgrade)')
        # Use the same privilege boundary as installation; do not confuse denied queries with health.
        command(privileged + ['systemctl', 'is-active', '--quiet', 'cliproxyapi.service'], source, 30)
    except (OSError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        print('Update failed; source retained' + (': ' + str(root) if root else '') + ': ' + str(exc), file=sys.stderr)
        return 1
    print('Upgrade verified.')
    try:
        cleanup_source(root, record)
    except Exception as exc:
        print('WARNING: upgrade succeeded but source cleanup failed: ' + str(root) + ': ' + str(exc), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
