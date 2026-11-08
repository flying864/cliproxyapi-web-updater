#!/usr/bin/env python3
"""Pinned, single-use hot updater. No cleanup of pre-existing directories."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
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
    """Clean through verified directory fds, never by resolving the root again.

    This prevents pathname replacement from redirecting recursive deletion. It
    is not a security boundary against root or a hostile process with our UID
    that can mutate the contents of the verified allocation itself.
    """
    if (str(root) != record['path'] or str(root.parent) != record['parent']
            or root.name in ('', '.', '..')):
        raise RuntimeError('source directory identity changed')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def same(a, b):
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)

    def empty(directory_fd):
        # Open every directory without following symlinks and check the device
        # before descending. Do not use rmtree(root) even with a parent dir_fd:
        # its initial stat would accept an entirely substituted root.
        for name in os.listdir(directory_fd):
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode):
                child_fd = os.open(name, flags, dir_fd=directory_fd)
                try:
                    child = os.fstat(child_fd)
                    if not same(before, child) or child.st_dev != record['device']:
                        raise RuntimeError('source child identity or device changed')
                    empty(child_fd)
                    if not same(child, os.stat(name, dir_fd=directory_fd, follow_symlinks=False)):
                        raise RuntimeError('source child identity changed')
                    os.rmdir(name, dir_fd=directory_fd)
                finally:
                    os.close(child_fd)
            else:
                # unlink never traverses a substituted symlink or directory.
                os.unlink(name, dir_fd=directory_fd)

    parent_fd = os.open(root.parent, flags)
    try:
        try:
            root_fd = os.open(root.name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise RuntimeError('source directory identity changed') from exc
        try:
            info = os.fstat(root_fd)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_ino != record['inode']
                    or info.st_dev != record['device'] or info.st_uid != record['uid']):
                raise RuntimeError('source directory identity changed')
            fd = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=root_fd)
            with os.fdopen(fd) as stream:
                mi = os.fstat(stream.fileno())
                if (not stat.S_ISREG(mi.st_mode) or mi.st_uid != os.getuid()
                        or mi.st_mode & 0o077 or json.load(stream) != record):
                    raise RuntimeError('ownership marker changed')
            empty(root_fd)
            if not same(info, os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)):
                raise RuntimeError('source directory identity changed')
            # A final concurrent swap can at worst remove an empty replacement;
            # rmdir cannot recursively delete replacement contents.
            os.rmdir(root.name, dir_fd=parent_fd)
        finally:
            os.close(root_fd)
    finally:
        os.close(parent_fd)


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
