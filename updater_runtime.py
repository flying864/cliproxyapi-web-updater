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
import hashlib
import secrets
import time
from datetime import datetime, timezone

PUBLIC = '/var/lib/cliproxy-updater-status'
BACKUP_OWNER_UID = 0  # Fixed in production; only isolated tests patch this constant.


def _backup_time():
    return datetime.now(timezone.utc).isoformat()


def _backup_dir(path, private=True):
    # Validate every ancestor as well as binding the final object to a dirfd.
    # Test fixtures patch owner only; production accepts root-owned ancestors.
    current = '/'
    private_barrier = False
    for part in [p for p in path.split('/') if p]:
        current = os.path.join(current, part)
        ancestor = open_path(current, directory=True)
        try:
            st = os.fstat(ancestor)
            if st.st_uid not in (0, BACKUP_OWNER_UID) or (st.st_mode & 0o022 and not private_barrier):
                raise ValueError('Unsafe backup directory ancestor')
            if st.st_uid == BACKUP_OWNER_UID and not st.st_mode & 0o077:
                private_barrier = True
        finally:
            os.close(ancestor)
    fd = open_path(path, directory=True)
    st = os.fstat(fd)
    if st.st_uid != BACKUP_OWNER_UID or st.st_mode & (0o077 if private else 0o022):
        os.close(fd)
        raise ValueError('Unsafe backup directory')
    return fd


def _backup_require_owner():
    if os.geteuid() != BACKUP_OWNER_UID:
        raise ValueError('Backup management requires root')


def _backup_write(fd, name, value, mode=0o600, gid=None):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()
    if len(raw)>16*1024*1024: raise ValueError('Backup metadata byte budget exceeded')
    temp = '.backup-' + secrets.token_hex(16)
    out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
    try:
        with os.fdopen(out, 'wb') as stream:
            if gid is not None: os.fchown(stream.fileno(),BACKUP_OWNER_UID,gid)
            os.fchmod(stream.fileno(),mode)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temp, dir_fd=fd)
        except FileNotFoundError:
            pass


def _backup_publish(result):
    fd = _backup_dir(PUBLIC, private=False)
    try:
        # Preserve the directory's service group without looking up test identities.
        raw = json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode()
        if len(raw) > 65536:
            raise ValueError('Backup public result exceeds byte budget')
        _backup_write(fd, 'backups.json', result, 0o640, gid=os.fstat(fd).st_gid)
    finally:
        os.close(fd)
    return result


def _backup_name(kind, name):
    if not isinstance(name, str) or len(name) > 100:
        raise ValueError('Invalid backup name')
    expression = r'[0-9]{8}-[0-9]{6}-[0-9]+\.[0-9]+\.[0-9]+' if kind == 'runtime' else r'install-[A-Za-z0-9_-]+'
    if kind not in ('runtime', 'install') or not re.fullmatch(expression, name):
        raise ValueError('Invalid backup kind/name')


def _backup_candidates():
    result = []
    for kind, root in [('runtime', STATE + '/backups'), ('install', STATE)]:
        fd = _backup_dir(root)
        try:
            for name in sorted(os.listdir(fd)):
                try:
                    _backup_name(kind, name)
                except ValueError:
                    continue
                result.append((kind, name))
        finally:
            os.close(fd)
    return result


def _backup_read(fd, name, default=None):
    try:
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return default
    with os.fdopen(source, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != BACKUP_OWNER_UID or st.st_nlink != 1 or st.st_mode & 0o077 or st.st_size > 16 * 1024 * 1024:
            raise ValueError('Unsafe private backup record')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value: raise ValueError('Duplicate backup metadata field')
                value[key]=item
            return value
        raw=stream.read(16*1024*1024+1)
        if len(raw)>16*1024*1024: raise ValueError('Backup metadata byte budget exceeded')
        value=json.loads(raw,object_pairs_hook=unique)
        if not isinstance(value,dict): raise ValueError('Invalid backup metadata object')
        return value


def _backup_identity(st):
    return [st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid,
            st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def _backup_open_group(kind, name):
    _backup_name(kind, name)
    parent = _backup_dir(STATE + '/backups' if kind == 'runtime' else STATE)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        st = os.fstat(fd)
        if st.st_uid != BACKUP_OWNER_UID or st.st_mode & 0o077:
            os.close(fd)
            raise ValueError('Unsafe backup group')
        return parent, fd
    except BaseException:
        os.close(parent)
        raise


def _backup_inventory(fd, kind):
    """Flat opaque files only: never interpret archives/manifests or visit plugins."""
    before = _backup_identity(os.fstat(fd))
    names = sorted(os.listdir(fd))
    if len(names) > 100:
        raise ValueError('Backup file budget exceeded')
    if kind == 'runtime':
        if names != ['cli-proxy-api', 'runtime-config.tar.gz']:
            raise ValueError('Incomplete runtime backup')
    elif 'manifest.json' not in names or 'config.yaml' not in names or any(not re.fullmatch(r'(?:[0-9]+|config\.yaml|manifest\.json)', n) for n in names):
        raise ValueError('Incomplete install backup')
    files = {}
    for name in names:
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            st = os.fstat(source)
            # Root-owned snapshots are mandatory. A legacy service-owned config
            # remains protected: a private parent alone cannot revoke old open FDs.
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != BACKUP_OWNER_UID or st.st_mode & 0o022:
                raise ValueError('Unsafe backup file')
            digest = hashlib.sha256()
            while True:
                chunk = os.read(source, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            if (_backup_identity(st) != _backup_identity(os.fstat(source)) or
                    _backup_identity(st) != _backup_identity(os.stat(name, dir_fd=fd, follow_symlinks=False))):
                raise ValueError('Backup changed while reading')
            files[name] = dict(identity=_backup_identity(st), sha256=digest.hexdigest())
        finally:
            os.close(source)
    if before != _backup_identity(os.fstat(fd)) or names != sorted(os.listdir(fd)):
        raise ValueError('Backup file set changed')
    return dict(directory=before, files=files)


def _backup_active(fd):
    return any(_backup_exists(fd, name) for name in ('transaction.json', 'hot-transaction.json'))


def _backup_exists(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def backup_register(kind, name):
    """Caller holds the common lock and invokes only after verified success.

    Does not bootstrap trust from public metadata, names, or archive contents.
    Existing registration is immutable; failed/recovery groups must not call this.
    """
    _backup_require_owner()
    _backup_name(kind, name)
    state = _backup_dir(STATE)
    try:
        if _backup_active(state):
            raise ValueError('Active transaction; register after completion')
        registry = _backup_read(state, 'backup-registry.json', {})
        _backup_validate_registry(registry)
        key = kind + '/' + name
        if key in registry:
            raise ValueError('Backup already registered')
        parent, group = _backup_open_group(kind, name)
        try:
            inventory = _backup_inventory(group, kind)
        finally:
            os.close(group)
            os.close(parent)
        record = dict(id=secrets.token_hex(16), kind=kind, name=name,
                      created_at=_backup_time(), registered_ns=time.time_ns(), inventory=inventory)
        registry[key] = record
        _backup_write(state, 'backup-registry.json', registry)
        return record['id']
    finally:
        os.close(state)


def _backup_validate_registry(registry):
    if not isinstance(registry,dict) or len(registry)>10000: raise ValueError('Invalid backup registry')
    seen=set()
    for key,record in registry.items():
        if not isinstance(record,dict): raise ValueError('Invalid backup record')
        required={'id','kind','name','created_at','registered_ns','inventory'}
        if set(record)!=required: raise ValueError('Invalid backup record fields')
        _backup_name(record['kind'],record['name'])
        if key!=record['kind']+'/'+record['name'] or not isinstance(record['id'],str) or not re.fullmatch(r'[0-9a-f]{32}',record['id']) or record['id'] in seen: raise ValueError('Invalid backup identity')
        seen.add(record['id'])
        if type(record['registered_ns']) is not int or record['registered_ns']<0 or not isinstance(record['created_at'],str): raise ValueError('Invalid backup timestamp')
        inv=record['inventory']
        if not isinstance(inv,dict) or set(inv)!={'directory','files'} or not isinstance(inv['files'],dict): raise ValueError('Invalid backup inventory')
        if not isinstance(inv['directory'],list) or len(inv['directory'])!=9: raise ValueError('Invalid backup directory identity')
        # File keys are used for unlink: constrain them independently of hashes.
        names=sorted(inv['files'])
        if record['kind']=='runtime':
            valid=names==['cli-proxy-api','runtime-config.tar.gz']
        else: valid='config.yaml' in names and 'manifest.json' in names and len(names)<=100 and all(re.fullmatch(r'(?:[0-9]+|config\.yaml|manifest\.json)',n) for n in names)
        if not valid: raise ValueError('Invalid backup inventory names')
        for entry in inv['files'].values():
            if not isinstance(entry,dict) or set(entry)!={'identity','sha256'} or not isinstance(entry['identity'],list) or len(entry['identity'])!=9 or not isinstance(entry['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',entry['sha256']): raise ValueError('Invalid backup file identity')


def _backup_latest(registry):
    _backup_validate_registry(registry)
    existing = set(_backup_candidates())
    latest={kind:None for kind in ('runtime','install')}
    # Keep the newest *intact* group, not a corrupted replacement bearing its name.
    for kind in latest:
        ordered=sorted((r for r in registry.values() if r['kind']==kind and (kind,r['name']) in existing),key=lambda r:(r['registered_ns'],r['id']),reverse=True)
        for record in ordered:
            try:
                parent,fd=_backup_open_group(kind,record['name'])
                try: intact=_backup_inventory(fd,kind)==record['inventory']
                finally: os.close(fd);os.close(parent)
                if intact:
                    latest[kind]=record['id'];break
            except (ValueError,OSError): continue
    return latest


def backup_preview(page=0):
    """Read-only group preview. size_bytes counts logical regular-file bytes."""
    _backup_require_owner()
    state = _backup_dir(STATE)
    try:
        registry = _backup_read(state, 'backup-registry.json', {})
        active = _backup_active(state)
    finally:
        os.close(state)
    latest = _backup_latest(registry)
    allowed = {}
    items = []
    candidates = _backup_candidates()
    if type(page) is not int or not 0<=page<=999: raise ValueError('Invalid preview page')
    page_count=max(1,(len(candidates)+99)//100)
    page=min(page,page_count-1)
    for kind, name in candidates[page*100:(page+1)*100]:
        size = 0
        root = STATE + '/backups' if kind == 'runtime' else STATE
        try:
            fd = _backup_dir(root + '/' + name)
            try:
                for entry in os.listdir(fd):
                    st = os.stat(entry, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISREG(st.st_mode):
                        size += st.st_size
            finally:
                os.close(fd)
        except (ValueError, OSError):
            pass
        record = registry.get(kind + '/' + name)
        reason = 'unregistered or unsafe backup'
        identity = hashlib.sha256((kind + '/' + name).encode()).hexdigest()[:32]
        if record:
            identity = record['id']
            reason = ''
            try:
                parent, fd = _backup_open_group(kind, name)
                try:
                    if _backup_inventory(fd, kind) != record['inventory']:
                        reason = 'backup identity or content changed'
                finally:
                    os.close(fd)
                    os.close(parent)
            except (OSError, ValueError):
                reason = 'unsafe backup'
            if identity == latest[kind]:
                reason = 'latest successful backup'
            if active:
                reason = 'active transaction'
            if not reason:
                allowed[identity] = record
        items.append(dict(id=identity, name=name, kind=kind,
                          created_at=record['created_at'] if record else '', size_bytes=size,
                          deletable=not reason, reason=reason))
    token = secrets.token_hex(16)
    state = _backup_dir(STATE)
    try:
        _backup_write(state, 'backup-preview.json', dict(token=token, generated=time.time(), allowed=allowed))
    finally:
        os.close(state)
    return _backup_publish(dict(protocol=1, state='ready', token=token, generated_at=_backup_time(),
                                detail='文件逻辑字节统计；受保护备份不可删除', items=items,
                                page=page,page_count=page_count,total_count=len(candidates), truncated=len(candidates) > 100))


class BackupCleanupRejected(ValueError):
    """Rejection with an already-published exact operation result."""
    def __init__(self, result):
        super().__init__(result['detail'])
        self.result = result


def backup_cleanup(token, ids):
    """Caller holds common lock. Preflight entire batch; consume before deletion.

    No atomicity claim: disk errors can leave a partially removed group. The token
    is consumed even on rejection; retry requires a new explicit scan/selection.
    Private root-only parents exclude service races, not a malicious root actor.
    """
    _backup_require_owner()
    if isinstance(ids, str):
        ids = ids.split(',')
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token) or not isinstance(ids, (list, tuple)) or not 1 <= len(ids) <= 20 or any(not isinstance(i, str) or not re.fullmatch(r'[0-9a-f]{32}', i) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Invalid cleanup token/selection')
    state = _backup_dir(STATE)
    opened = []
    result = dict(protocol=1, state='error', token='', generated_at=_backup_time(),
                  detail='清理被拒绝，请重新扫描', items=[], total_count=0, truncated=False)
    try:
        preview = _backup_read(state, 'backup-preview.json')
        if not preview or preview.get('token') != token:
            raise ValueError('Unknown or consumed preview token')
        os.unlink('backup-preview.json', dir_fd=state)
        os.fsync(state)
        age = time.time() - preview['generated']
        if not 0 <= age <= 600:
            raise ValueError('Expired preview token')
        if _backup_active(state):
            raise ValueError('Active transaction')
        registry = _backup_read(state, 'backup-registry.json', {})
        latest = _backup_latest(registry)
        for identity in ids:
            record = preview['allowed'].get(identity)
            if not record or registry.get(record['kind'] + '/' + record['name']) != record or latest[record['kind']] == identity:
                raise ValueError('Selection no longer eligible')
            parent, fd = _backup_open_group(record['kind'], record['name'])
            opened.append((record, parent, fd))
            if _backup_inventory(fd, record['kind']) != record['inventory']:
                raise ValueError('Backup changed since preview')
        deleted = []
        failed = []
        for record, parent, fd in opened:
            try:
                if _backup_active(state):
                    raise ValueError('Active transaction')
                if _backup_identity(os.stat(record['name'], dir_fd=parent, follow_symlinks=False)) != record['inventory']['directory']:
                    raise ValueError('Backup directory replaced')
                if _backup_inventory(fd, record['kind']) != record['inventory']:
                    raise ValueError('Backup changed before deletion')
                for name, expected in record['inventory']['files'].items():
                    if _backup_identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != expected['identity']:
                        raise ValueError('Backup file replaced')
                    os.unlink(name, dir_fd=fd)
                os.rmdir(record['name'], dir_fd=parent)
                os.fsync(parent)
                deleted.append(record['id'])
            except (ValueError, OSError):
                failed.append(record['id'])
        result.update(state='error' if failed else 'success',
                      detail='已删除 %d 组；失败 %d 组。请重新扫描核对；失败组可能部分删除。' % (len(deleted), len(failed)),
                      deleted_ids=deleted, failed_ids=failed)
        return _backup_publish(result)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result['detail'] = '清理未完成；请重新扫描核对，勿重复提交：' + str(exc)
        _backup_publish(result)
        raise BackupCleanupRejected(result) from exc
    finally:
        for _, parent, fd in opened:
            os.close(fd)
            os.close(parent)
        os.close(state)


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
        elif len(sys.argv) == 4 and sys.argv[1] == 'backups-register':
            print(backup_register(sys.argv[2], sys.argv[3]))
        elif len(sys.argv) in (2,3) and sys.argv[1] == 'backups-preview':
            if len(sys.argv)==3 and not re.fullmatch(r'[0-9]{1,3}',sys.argv[2]): raise ValueError('Invalid page')
            print(json.dumps(backup_preview(int(sys.argv[2]) if len(sys.argv)==3 else 0)))
        elif len(sys.argv) == 4 and sys.argv[1] == 'backups-clean':
            try:
                print(json.dumps(backup_cleanup(sys.argv[2], sys.argv[3])))
            except BackupCleanupRejected as exc:
                # Published operational rejection is not a transport failure.
                print(json.dumps(exc.result))
        elif len(sys.argv) == 3 and sys.argv[1] == 'snapshot':
            snapshot(sys.argv[2])
        else:
            raise ValueError('Usage: preflight | snapshot OUTPUT')
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
