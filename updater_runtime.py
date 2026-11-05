#!/usr/bin/python3
"""Trusted stdlib-only updater boundary; never import application plugins."""
import json
import os
import pwd
import re
import shlex
import stat
import subprocess
import sys
import tarfile

APP = '/opt/cliproxyapi'
BIN = APP + '/cli-proxy-api'
CONFIG = APP + '/config.yaml'
STATE = '/var/lib/cliproxy-updater'
SERVICE = 'cliproxyapi.service'
MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 10000
WORKER_VERSION = '0.5.0'


def validate_exec(value):
    match = re.fullmatch(r'\{ path=([^;]+) ; argv\[\]=(.*?) ; ignore_errors=[^{}]*\}', value.strip())
    if not match or match[1].strip() != BIN:
        raise ValueError('Unsupported ExecStart (wrapper/multiple commands)')
    text = match[2]
    # systemd show escaping is not shell escaping; refuse ambiguous encodings.
    if any(c in text for c in ('\\', '\n', '\r', ';', '{', '}')):
        raise ValueError('Ambiguous ExecStart escaping')
    args = shlex.split(text)
    if not args or args[0] != BIN:
        raise ValueError('ExecStart must execute approved binary')
    configs = []
    i = 1
    while i < len(args):
        arg = args[i]
        if arg in ('-config', '--config'):
            i += 1
            if i >= len(args):
                raise ValueError('Missing config')
            configs.append(args[i])
        elif arg.startswith(('-config=', '--config=')):
            configs.append(arg.split('=', 1)[1])
        i += 1
    if configs != [CONFIG]:
        raise ValueError('Exactly one approved config required')
    return args


def check_service():
    def show(prop):
        return subprocess.check_output(['systemctl', 'show', SERVICE, '-p', prop, '--value'], text=True, timeout=10).strip()
    if show('User') != 'cliproxy' or show('Group') != 'cliproxy':
        raise ValueError('Service must run as cliproxy:cliproxy')
    return validate_exec(show('ExecStart'))


def open_path(path, directory=False):
    """Walk every component with dirfds; no symlink resolution, even ancestors."""
    if not os.path.isabs(path) or '..' in path.split('/'):
        raise ValueError('Absolute canonical source required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = [p for p in path.split('/') if p]
        for i, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if i < len(parts) - 1 or directory:
                flags |= os.O_DIRECTORY
            nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd); fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def archive_sources(archive, sources):
    count = total = 0
    def add(fd, name):
        nonlocal count, total
        before = os.fstat(fd)
        count += 1
        if count > MAX_FILES:
            raise ValueError('Snapshot file budget exceeded')
        info = tarfile.TarInfo(name)
        info.mode = stat.S_IMODE(before.st_mode) & 0o777
        info.mtime = before.st_mtime
        if stat.S_ISDIR(before.st_mode):
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
            for entry in sorted(os.listdir(fd)):
                child = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    add(child, name + '/' + entry)
                finally:
                    os.close(child)
        elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
            total += before.st_size
            if total > MAX_BYTES:
                raise ValueError('Snapshot byte budget exceeded')
            info.size = before.st_size
            with os.fdopen(os.dup(fd), 'rb') as stream:
                archive.addfile(info, stream)
        else:
            raise ValueError('Snapshot rejects links and special files')
        after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Snapshot source changed while reading')
    for name, path in sources:
        fd = open_path(path)
        try:
            add(fd, name)
        finally:
            os.close(fd)


def approved_auth():
    fd = open_path(STATE + '/deployment.json')
    with os.fdopen(fd) as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or st.st_mode & 0o077:
            raise ValueError('Unsafe deployment record')
        data = json.load(stream)
    auth = data.get('auth_dir')
    if data.get('protocol') != 1 or not isinstance(auth, str) or not os.path.isabs(auth) or os.path.normpath(auth) != auth or auth == '/':
        raise ValueError('Initialize approved auth-dir first')
    return auth


def current_auth():
    """Read only the single effective scalar via the existing local admin API."""
    import urllib.request
    fd = open_path('/root/cliproxyapi-admin-key')
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or st.st_mode & 0o077 or st.st_size > 4096:
            raise ValueError('Unsafe local management key file')
        key = stream.read(4097).decode().strip()
    if not key or '\n' in key or '\r' in key:
        raise ValueError('Invalid local management key')
    request = urllib.request.Request('http://127.0.0.1:8317/v8/management/config/oauth/auth-dir', headers={'Authorization':'Bearer '+key})
    # Fixed loopback, never proxy credentials, never follow redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Local API redirect refused')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=5) as response:
        raw = response.read(8193)
    if len(raw) > 8192:
        raise ValueError('Oversized auth-dir response')
    value = json.loads(raw)
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid effective auth-dir')
    account = pwd.getpwnam('cliproxy')
    if value == '~' or value.startswith('~/'):
        value = account.pw_dir + value[1:]
    if not os.path.isabs(value):
        working = subprocess.check_output(['systemctl','show',SERVICE,'-p','WorkingDirectory','--value'], text=True, timeout=10).strip()
        if not os.path.isabs(working):
            raise ValueError('Cannot resolve relative auth-dir')
        value = os.path.join(working, value)
    if '..' in value.split('/'):
        raise ValueError('Noncanonical effective auth-dir')
    return os.path.normpath(value)


def verify_auth():
    if current_auth() != approved_auth():
        raise ValueError('auth-dir changed; reinitialize the worker before updating')


def snapshot(output):
    if os.geteuid() != 0:
        raise ValueError('Snapshot requires root output custodian')
    def trusted_directory(path):
        fd = open_path(path, directory=True)
        try:
            st = os.fstat(fd)
            if st.st_uid != 0 or st.st_mode & 0o022:
                raise ValueError('Unsafe trusted directory: ' + path)
        finally:
            os.close(fd)
    for path in ('/var', '/var/lib', STATE, STATE + '/backups'):
        trusted_directory(path)
    auth = approved_auth()
    parent, name = os.path.split(output)
    if not re.fullmatch(r'/var/lib/cliproxy-updater/backups/[0-9-]+-[0-9.]+', parent) or name != 'runtime-config.tar.gz':
        raise ValueError('Unapproved snapshot output')
    directory = open_path(parent, directory=True)
    st = os.fstat(directory)
    if st.st_uid != 0 or st.st_mode & 0o077:
        os.close(directory)
        raise ValueError('Unsafe snapshot directory')
    dest = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read); os.close(dest); os.close(directory)
            account = pwd.getpwnam('cliproxy')
            if account.pw_uid == 0:
                raise ValueError('Refuse root cliproxy identity')
            os.setgroups([]); os.setgid(account.pw_gid); os.setuid(account.pw_uid)
            with os.fdopen(write, 'wb') as stream, tarfile.open(fileobj=stream, mode='w|gz') as archive:
                archive_sources(archive, [('config.yaml', CONFIG), ('auth-dir', auth), ('plugins', APP + '/plugins')])
            os._exit(0)
        except BaseException as exc:
            print('Snapshot: ' + str(exc), file=sys.stderr)
            os._exit(1)
    os.close(write)
    try:
        with os.fdopen(read, 'rb') as src, os.fdopen(dest, 'wb') as dst:
            # Also constrain compressed stream, including archive metadata overhead.
            total = 0
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES + 16 * 1024 * 1024:
                    raise ValueError('Snapshot stream budget exceeded')
                dst.write(chunk)
            dst.flush(); os.fsync(dst.fileno())
        _, status = os.waitpid(pid, 0)
        if status:
            raise ValueError('Unprivileged snapshot failed')
        os.fsync(directory)
    except BaseException:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        os.unlink(name, dir_fd=directory)
        raise
    finally:
        os.close(directory)


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['version']:
            print(WORKER_VERSION)
        elif sys.argv[1:] == ['preflight']:
            check_service()
        elif sys.argv[1:] == ['verify-auth']:
            verify_auth()
        elif len(sys.argv) == 3 and sys.argv[1] == 'snapshot':
            snapshot(sys.argv[2])
        else:
            raise ValueError('Usage: preflight | snapshot OUTPUT')
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
