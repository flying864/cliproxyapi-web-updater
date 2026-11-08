#!/usr/bin/env python3
"""Shared, one-shot installer transaction. No daemon or third-party modules."""
import copy
import hashlib
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import pwd
import grp
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

APP = Path('/opt/cliproxyapi')
STATE = Path('/var/lib/cliproxy-updater')
RUN = Path('/run/cliproxy-updater')
SYSTEM = Path('/etc/systemd/system')
WORKER = Path('/usr/local/libexec/cliproxy-updater-worker')
RUNTIME = Path('/usr/local/libexec/cliproxy-updater-runtime.py')
PUBLIC = Path('/var/lib/cliproxy-updater-status')
TMPFILE = Path('/etc/tmpfiles.d/cliproxy-updater.conf')
TRIGGERS = ['cliproxy-updater.path', 'cliproxy-updater-check.timer']
SERVICES = ['cliproxy-updater.service', 'cliproxy-updater-check.service', 'cliproxy-updater-recover.service']
BASE = 'http://127.0.0.1:8317'


def command(*args, timeout=45):
    try:
        return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout).stdout.strip()
    except FileNotFoundError:
        raise RuntimeError('缺少命令或不在 PATH 中: ' + args[0] + '；请先安装对应依赖（gcc 需要 C 编译器）') from None


def ctl(*args):
    return command('systemctl', *args)


def query(verb, unit):
    return subprocess.run(['systemctl', verb, '--quiet', unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0


def safe_path(p, directory=False):
    p = Path(p)
    for item in [*reversed(p.parents), p]:
        st = item.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise RuntimeError('不安全的属主、权限或符号链接: ' + str(item))
    if directory and not p.is_dir():
        raise RuntimeError('不是目录: ' + str(p))


def ensure_directory(path, mode, gid=0):
    safe_path(path.parent, True)
    if not path.exists():
        path.mkdir(mode=mode)
        os.chown(path, 0, gid, follow_symlinks=False)
        path.chmod(mode)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode:
        raise RuntimeError('目录属主/权限不匹配: ' + str(path))


def plugin_directory(p):
    safe_path(p.parent, True)
    user = pwd.getpwnam('cliproxy')
    gid = grp.getgrnam('cliproxy').gr_gid
    if not os.path.lexists(p):
        p.mkdir(mode=0o700)
        os.chown(p, user.pw_uid, gid, follow_symlinks=False)
    st = p.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid not in (0, user.pw_uid) or
            st.st_mode & 0o022 or (st.st_uid != 0 and st.st_gid != gid)):
        raise RuntimeError('插件目录必须由 root 或 cliproxy 控制，且不能组/其他可写')
    # Existing permissions and owner are deliberately not changed.


def runtime_module():
    spec = importlib.util.spec_from_file_location('trusted_runtime', Path(__file__).resolve().with_name('updater_runtime.py'))
    if spec is None or spec.loader is None:
        raise RuntimeError('缺少配套 updater_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plugin_io(path, action, data=None):
    """Untrusted plugin directory operations never execute with root privileges."""
    directory = path.parent
    plugin_directory(directory)
    owner = directory.lstat().st_uid
    user = pwd.getpwnam('cliproxy')
    uid = 0 if owner == 0 else user.pw_uid
    gid = 0 if owner == 0 else user.pw_gid
    groups = [] if owner == 0 else os.getgrouplist('cliproxy', user.pw_gid)
    code = r'''import os,sys,stat,tempfile,json,re,hashlib
from pathlib import Path
p=Path(sys.argv[1]); action=sys.argv[2]
fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
 if action=='read':
  try: f=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
  except FileNotFoundError: sys.exit(44)
  with os.fdopen(f,'rb') as stream:
   st=os.fstat(stream.fileno())
   if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>20000000: raise ValueError('unsafe plugin file')
   sys.stdout.buffer.write(stream.read(20000001))
 elif action in ('write','create'):
  data=sys.stdin.buffer.read(20000001)
  if len(data)>20000000: raise ValueError('oversized plugin')
  name='.cpa-updater-'+os.urandom(12).hex()
  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o755,dir_fd=fd)
  try:
   with os.fdopen(f,'wb') as out: out.write(data);out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),0o755)
   if action=='create':
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.renameat2(fd,os.fsencode(name),fd,os.fsencode(p.name),1)!=0:
     error=ctypes.get_errno();raise OSError(error,os.strerror(error))
   else: os.replace(name,p.name,src_dir_fd=fd,dst_dir_fd=fd)
   os.fsync(fd)
  finally:
   try:os.unlink(name,dir_fd=fd)
   except FileNotFoundError:pass
 elif action=='quarantine':
  destination,digest=json.loads(sys.stdin.buffer.read(4096))
  if not re.fullmatch(r'cpa-updater-v0\.0\.1(?:\.\d+){8}\.so',p.name): raise ValueError('unsafe candidate')
  if not re.fullmatch(re.escape(p.name)+r'\.[0-9a-f]{24}\.rollback-backup',destination) or not re.fullmatch(r'[0-9a-f]{64}',digest): raise ValueError('unsafe backup')
  def checked(name):
   try:f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
   except FileNotFoundError:return None
   with os.fdopen(f,'rb') as stream:
    st=os.fstat(stream.fileno())
    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>20000000: raise ValueError('unsafe candidate')
    if hashlib.sha256(stream.read(20000001)).hexdigest()!=digest: raise ValueError('changed candidate')
    return st
  source=checked(p.name); backup=checked(destination)
  if source is not None:
   if backup is not None: raise ValueError('backup already exists')
   now=os.stat(p.name,dir_fd=fd,follow_symlinks=False)
   if (now.st_ino,now.st_dev)!=(source.st_ino,source.st_dev): raise ValueError('changed candidate')
   # RENAME_NOREPLACE prevents a concurrent backup from being overwritten.
   import ctypes
   libc=ctypes.CDLL(None,use_errno=True)
   if libc.renameat2(fd,os.fsencode(p.name),fd,os.fsencode(destination),1)!=0:
    error=ctypes.get_errno();raise OSError(error,os.strerror(error))
   os.fsync(fd)
 elif action=='prune':
  digest=sys.stdin.buffer.read(65).decode()
  if not re.fullmatch(r'cpa-updater-v0\.0\.1(?:\.\d+){8}\.so',p.name) or not re.fullmatch(r'[0-9a-f]{64}',digest): raise ValueError('unsafe owned candidate')
  try:f=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
  except FileNotFoundError:sys.exit(0)
  with os.fdopen(f,'rb') as stream:
   st=os.fstat(stream.fileno())
   if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>20000000: raise ValueError('unsafe owned candidate')
   if hashlib.sha256(stream.read(20000001)).hexdigest()!=digest: raise ValueError('changed owned candidate')
   now=os.stat(p.name,dir_fd=fd,follow_symlinks=False)
   if (now.st_dev,now.st_ino,now.st_nlink)!=(st.st_dev,st.st_ino,1): raise ValueError('replaced owned candidate')
   os.unlink(p.name,dir_fd=fd);os.fsync(fd)
 elif action=='delete':
  try:os.unlink(p.name,dir_fd=fd);os.fsync(fd)
  except FileNotFoundError:pass
 else:raise ValueError('unknown action')
finally:os.close(fd)
'''
    result = subprocess.run([sys.executable, '-I', '-c', code, str(path), action],
                            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=20, user=None if uid == os.geteuid() else uid,
                            group=None if gid == os.getegid() else gid,
                            extra_groups=None if uid == os.geteuid() and gid == os.getegid() else groups)
    if result.returncode == 44 and action == 'read':
        return None
    if result.returncode:
        raise RuntimeError('插件文件操作失败（未以 root 进入服务用户可写目录）')
    return result.stdout



def readable_by_service(path):
    user = pwd.getpwnam('cliproxy')
    groups = os.getgrouplist('cliproxy', user.pw_gid)
    for p in [*reversed(path.parents), path]:
        st = p.stat()
        shift = 6 if st.st_uid == user.pw_uid else 3 if st.st_gid in groups else 0
        required = 1 if stat.S_ISDIR(st.st_mode) else 4
        if not ((st.st_mode >> shift) & required):
            raise RuntimeError('主服务用户无法读取/遍历: ' + str(p))


def validate_config_permissions(path):
    """The management API must write config, unlike executable/plugin paths."""
    safe_path(path.parent, True)
    st = path.lstat()
    user = pwd.getpwnam('cliproxy')
    gid = grp.getgrnam('cliproxy').gr_gid
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
            st.st_uid not in (0, user.pw_uid) or st.st_mode & 0o007 or
            (st.st_mode & 0o020 and st.st_gid != gid)):
        raise RuntimeError('配置必须为安全普通文件，仅 root/cliproxy 可读写')
    shift = 6 if st.st_uid == user.pw_uid else 3 if st.st_gid == gid else 0
    if ((st.st_mode >> shift) & 0o6) != 0o6:
        raise RuntimeError('cliproxy 必须可读写 config.yaml，管理 API 才能保存配置')


def validate_service():
    if ctl('show', 'cliproxyapi.service', '-p', 'User', '--value') != 'cliproxy' or ctl('show', 'cliproxyapi.service', '-p', 'Group', '--value') != 'cliproxy':
        raise RuntimeError('主服务必须明确 User=cliproxy Group=cliproxy')
    value = ctl('show', 'cliproxyapi.service', '-p', 'ExecStart', '--value')
    runtime_module().validate_exec(value)
    for p in [APP, APP / 'cli-proxy-api', Path('/usr/local/libexec'), SYSTEM, Path('/etc/tmpfiles.d')]:
        safe_path(p)
    validate_config_permissions(APP / 'config.yaml')
    if (APP / 'plugins').exists() or (APP / 'plugins').is_symlink():
        plugin_directory(APP / 'plugins')
    for p in [APP, APP / 'config.yaml', APP / 'cli-proxy-api']:
        readable_by_service(p)
    if not query('is-active', 'cliproxyapi.service'):
        raise RuntimeError('主服务未启动')


class API:
    def __init__(self):
        p = Path('/root/cliproxyapi-admin-key')
        safe_path(p)
        if p.stat().st_mode & 0o077:
            raise RuntimeError('管理密钥必须仅 root 可读')
        self.key = p.read_text().strip()
        if not self.key:
            raise RuntimeError('管理密钥为空')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, value=None, method='GET', raw=False, timeout=15):
        req = urllib.request.Request(BASE + path, method=method,
            data=None if value is None else json.dumps(value).encode(),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        with self.opener.open(req, timeout=timeout) as response:
            data = response.read(2 * 1024 * 1024)
            return data if raw else json.loads(data)

    def conditional(self, path, value=None, etag=None):
        headers = {'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'}
        if etag is not None:
            headers['If-Match'] = etag
        req = urllib.request.Request(BASE + path, method='GET' if etag is None else 'PUT',
            data=None if etag is None else json.dumps(value).encode(), headers=headers)
        with self.opener.open(req, timeout=15) as response:
            data = response.read(2 * 1024 * 1024)
            tag = response.headers.get('ETag', '')
            if not re.fullmatch(r'"[0-9a-f]{64}"', tag):
                raise RuntimeError('管理 API 未提供强配置 ETag')
            return json.loads(data) if etag is None else None, tag

    def config(self):
        return self.request('/v8/management/config/plugins')

    def put(self, field, value):
        self.request('/v8/management/config/plugins/' + field, value, 'PUT', raw=True)


def plan_config(config, installing):
    target = copy.deepcopy(config)
    configs = target.setdefault('configs', {})
    if installing and not target.get('enabled', False):
        if any(k != 'cpa-updater' and v.get('enabled', False) for k, v in configs.items()):
            raise RuntimeError('全局插件关闭且其他插件 enabled；拒绝默认激活，请管理员先处理')
        target['enabled'] = True
    own = configs.setdefault('cpa-updater', {})
    own['enabled'] = installing
    if installing:
        own.setdefault('priority', 1)
    return target


def validate_registered(data):
    found = [p for p in data.get('plugins', []) if p.get('id') == 'cpa-updater']
    if len(found) != 1 or found[0].get('registered') is not True or found[0].get('effective_enabled') is not True:
        raise RuntimeError('插件未真实注册/启用')


def health(api, installed, budget=30):
    deadline = time.monotonic() + budget
    last = None
    while time.monotonic() < deadline:
        try:
            if not query('is-active', 'cliproxyapi.service'):
                raise RuntimeError('主服务未健康')
            data = api.request('/v8/management/plugins', timeout=min(3, max(.1, deadline-time.monotonic())))
            if installed:
                validate_registered(data)
                if not api.request('/v0/resource/plugins/cpa-updater/panel', raw=True, timeout=3):
                    raise RuntimeError('插件页面为空')
                status = api.request('/v0/management/plugins/cpa-updater/status', timeout=3)
                if not isinstance(status, dict) or 'state' not in status:
                    raise RuntimeError('带密钥 status 无效')
            elif installed is False and any(p.get('id') == 'cpa-updater' and p.get('effective_enabled') for p in data.get('plugins', [])):
                raise RuntimeError('卸载后插件仍启用')
            return
        except Exception as exc:
            last = exc
            time.sleep(min(.5, max(0, deadline-time.monotonic())))
    raise RuntimeError('主服务/插件健康等待超时') from last


def units():
    result = {}
    for suffix, mode, timeout in [('service', '--consume', 900), ('check.service', '--check', 900), ('recover.service', '--recover', 300)]:
        recover = mode == '--recover'
        head = '[Unit]\nDescription=CLIProxyAPI updater ' + mode + '\nAfter=cliproxyapi.service network-online.target\n'
        if not recover:
            head += 'OnFailure=cliproxy-updater-recover.service\n'
        body = '[Service]\nType=oneshot\nUser=root\nGroup=root\nExecStart=/usr/local/libexec/cliproxy-updater-worker ' + mode + '\n'
        body += f'TimeoutStartSec={timeout}\nTimeoutStopSec=180\nMemoryMax=384M\nTasksMax=64\nLimitNOFILE=256\n'
        body += 'AmbientCapabilities=CAP_SETUID\nPrivateTmp=true\nNoNewPrivileges=true\nProtectSystem=strict\nReadWritePaths=/opt/cliproxyapi /var/lib/cliproxy-updater /var/lib/cliproxy-updater-status /run/cliproxy-updater\nProtectHome=read-only\nRestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX\n'
        if recover:
            body += '[Install]\nWantedBy=multi-user.target\n'
        result['cliproxy-updater.' + suffix if suffix == 'service' else 'cliproxy-updater-' + suffix] = head + body
    result['cliproxy-updater.path'] = '[Unit]\nDescription=Watch authenticated updater queue\n[Path]\nPathExists=/run/cliproxy-updater/inbox/request\nUnit=cliproxy-updater.service\n[Install]\nWantedBy=multi-user.target\n'
    result['cliproxy-updater-check.timer'] = '[Unit]\nDescription=Weekly version check\n[Timer]\nOnBootSec=4min\nOnUnitActiveSec=7d\nRandomizedDelaySec=10min\nPersistent=true\nUnit=cliproxy-updater-check.service\n[Install]\nWantedBy=timers.target\n'
    return result


def idle():
    if os.path.lexists(STATE / 'hot-transaction.json'):
        raise RuntimeError('存在 hot-transaction.json；先运行 --hot-reload 恢复，禁止安装/卸载')
    if (STATE / 'transaction.json').exists():
        raise RuntimeError('存在 transaction.json；先执行 systemctl start cliproxy-updater-recover.service 恢复，禁止安装/卸载')
    if (RUN / 'processing').exists() or any(query('is-active', u) for u in SERVICES):
        raise RuntimeError('活动任务或 processing 残留；先运行 worker --recover，不删除队列')


def atomic_write(path, data, mode):
    fd, name = tempfile.mkstemp(prefix='.updater-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def restore_triggers(states):
    for u, (enabled, active) in states.items():
        if ctl('show', u, '-p', 'LoadState', '--value') == 'not-found':
            if enabled or active:
                raise RuntimeError('原有触发器丢失: ' + u)
            continue
        ctl('enable' if enabled else 'disable', u)
        ctl('start' if active else 'stop', u)
        if query('is-enabled', u) != enabled or query('is-active', u) != active:
            raise RuntimeError('触发器恢复验证失败: ' + u)


def deployment_config(api):
    value = api.request('/v8/management/config/oauth/auth-dir')
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError('无法取得实际 auth-dir；拒绝猜测备份路径')
    user = pwd.getpwnam('cliproxy')
    if value == '~' or value.startswith('~/'):
        value = user.pw_dir + value[1:]
    path = Path(value)
    if not path.is_absolute():
        working = ctl('show', 'cliproxyapi.service', '-p', 'WorkingDirectory', '--value')
        if not working or not Path(working).is_absolute():
            raise RuntimeError('相对 auth-dir 需要明确 WorkingDirectory')
        path = Path(working) / path
    if '..' in path.parts or path == Path('/'):
        raise RuntimeError('auth-dir 路径不安全')
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise RuntimeError('auth-dir 或祖先不得为符号链接')
    if not path.is_dir():
        raise RuntimeError('auth-dir 目录不存在')
    readable_by_service(path)
    return {'protocol': 1, 'auth_dir': str(path)}


def initialize_status():
    target = PUBLIC / 'status.json'
    if target.exists():
        st = target.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or st.st_mode & 0o022:
            raise RuntimeError('不安全的持久状态文件')
        value = json.loads(target.read_text())
        if value.get('protocol') == 1:
            return
    data = json.dumps(dict(protocol=1, worker_version=runtime_module().WORKER_VERSION, state='idle',
        detail='更新服务已初始化，点击检查更新', current='unknown', latest='unknown'), ensure_ascii=False).encode()
    atomic_write(target, data, 0o640)
    os.chown(target, 0, grp.getgrnam('cliproxy').gr_gid, follow_symlinks=False)


def hot_name(data):
    # Reserved namespace: 0.0.1.<eight decimal uint32 SHA256 words>.
    # Each numeric component fits the official host's signed-int64 comparator.
    digest = hashlib.sha256(data).digest()
    version = '0.0.1.' + '.'.join(str(int.from_bytes(digest[i:i+4], 'big')) for i in range(0, 32, 4))
    return version, 'cpa-updater-v' + version + '.so'


def hot_identity():
    pid = ctl('show', 'cliproxyapi.service', '-p', 'MainPID', '--value')
    start = ctl('show', 'cliproxyapi.service', '-p', 'ExecMainStartTimestampMonotonic', '--value')
    if not pid.isdecimal() or int(pid) <= 0 or not start.isdecimal() or int(start) <= 0:
        raise RuntimeError('无法验证主服务 PID/start')
    return pid, start


def hot_panel(path):
    # Isolated interpreter avoids dlopen caching. Only the read-only panel route
    # is dispatched; no status/queue/config routes are invoked by native code.
    code = r'''
import base64,ctypes as c,json,sys
class B(c.Structure): _fields_=[('ptr',c.c_void_p),('len',c.c_size_t)]
CALL=c.CFUNCTYPE(c.c_int,c.c_char_p,c.c_void_p,c.c_size_t,c.POINTER(B))
FREE=c.CFUNCTYPE(None,c.c_void_p,c.c_size_t)
SHUT=c.CFUNCTYPE(None)
class P(c.Structure): _fields_=[('abi',c.c_uint32),('call',CALL),('free',FREE),('shutdown',SHUT)]
lib=c.CDLL(sys.argv[1]);p=P()
lib.cliproxy_plugin_init.argtypes=[c.c_void_p,c.POINTER(P)]
assert lib.cliproxy_plugin_init(None,c.byref(p))==0 and p.abi==1
req=json.dumps({'Method':'GET','Path':'/v0/resource/plugins/cpa-updater/panel'}).encode(); out=B()
assert p.call(b'management.handle',req,len(req),c.byref(out))==0
try: result=json.loads(c.string_at(out.ptr,out.len))['result']
finally: p.free(out.ptr,out.len)
assert result['StatusCode']==200
sys.stdout.buffer.write(base64.b64decode(result['Body'],validate=True))
p.shutdown()
'''
    user = pwd.getpwnam('cliproxy')
    result = subprocess.run([sys.executable, '-I', '-c', code, str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=20,
        user=user.pw_uid, group=user.pw_gid, extra_groups=[])
    if not result.stdout:
        raise RuntimeError('原生插件 panel 为空')
    return result.stdout


def hot_verify(api, path, panel, identity, budget=30):
    deadline = time.monotonic() + budget
    while True:
        if hot_identity() != identity:
            raise RuntimeError('hot-reload 主服务 PID/start 发生变化；禁止重启回退')
        try:
            data = api.request('/v8/management/plugins')
            validate_registered(data)
            own = next(p for p in data['plugins'] if p['id'] == 'cpa-updater')
            if own.get('path') != str(path):
                raise RuntimeError('实际插件路径不匹配')
            if api.request('/v0/resource/plugins/cpa-updater/panel', raw=True) != panel:
                raise RuntimeError('实际 panel 内容不匹配')
            hot_status(api.request('/v0/management/plugins/cpa-updater/status'))
            if hot_identity() != identity:
                raise RuntimeError('主服务身份变化')
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)


def hot_record_read():
    path = STATE / 'hot-transaction.json'
    if not os.path.lexists(path):
        return None
    safe_path(STATE, True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or
                stat.S_IMODE(st.st_mode) != 0o600 or st.st_size > 2 * 1024 * 1024):
            raise RuntimeError('不安全的 hot 恢复记录')
        record = json.load(stream)
    if record.get('protocol') != 1:
        raise RuntimeError('未知 hot 恢复记录版本')
    return record


def hot_sync():
    fd = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def hot_record_write(record):
    safe_path(STATE, True)
    atomic_write(STATE / 'hot-transaction.json', json.dumps(record).encode(), 0o600)
    hot_sync()


def hot_record_clear():
    (STATE / 'hot-transaction.json').unlink()
    hot_sync()


def hot_scope(api):
    # Hash only: never persist management keys or full deployment config.
    value = api.request('/v8/management/config', raw=False)
    if not isinstance(value, dict) or 'plugins' not in value:
        raise RuntimeError('无法取得完整配置以证明恢复范围')
    value = copy.deepcopy(value)
    value.pop('plugins')
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def hot_recover(api, record):
    try:
        identity = tuple(record['identity'])
        if hot_identity() != identity:
            raise RuntimeError('主服务身份变化，拒绝自动恢复')
        old = Path(record['path'])
        if old.parent != APP / 'plugins' or old.name in ('', '.', '..'):
            raise RuntimeError('恢复插件路径不安全')
        if plugin_io(old, 'read') is None:
            raise RuntimeError('原插件文件丢失')
        panel = hot_panel(old)
        current, tag = api.conditional('/v8/management/config/plugins')
        if current not in (record['before'], record['expected']):
            raise RuntimeError('插件配置发生并发变化，拒绝恢复')
        if tag not in (record.get('written'), record.get('tag')) and hot_scope(api) != record['scope']:
            raise RuntimeError('完整配置发生并发变化，拒绝恢复')
        # Without an explicit selector the official host discovers versioned
        # libraries before the legacy path. Hide only this transaction's new
        # candidate, before restoring/reloading the original configuration.
        candidate = record.get('candidate')
        legacy = not record['before']['configs']['cpa-updater'].get('store', {}).get('version')
        if legacy and candidate and record.get('created'):
            target = Path(candidate)
            if (target.parent != old.parent or target == old or
                    not re.fullmatch(r'cpa-updater-v0\.0\.1(?:\.\d+){8}\.so', target.name)):
                raise RuntimeError('恢复候选路径不安全')
            plugin_io(target, 'quarantine', json.dumps([record['quarantine'], record['digest']]).encode())
        if current == record['expected'] or (legacy and candidate and record.get('created')):
            if hot_identity() != identity:
                raise RuntimeError('主服务身份变化，拒绝恢复写入')
            # Re-read ETag is the CAS fence even when a PUT response was lost.
            api.conditional('/v8/management/config/plugins/configs/cpa-updater',
                            record['before']['configs']['cpa-updater'], tag)
            restored, _ = api.conditional('/v8/management/config/plugins')
            if restored != record['before']:
                raise RuntimeError('恢复配置回读不匹配')
        hot_verify(api, old, panel, identity)
        if 'owned_before' in record:
            hot_owned_write(record['owned_before'])
        hot_record_clear()
    except BaseException as exc:
        raise RuntimeError('hot 恢复未完成；保留 hot-transaction.json，禁止安装/卸载，请修复后重新运行 --hot-reload') from exc


def hot_owned_read() -> dict:
    path = STATE / 'hot-owned.json'
    if not os.path.lexists(path):
        return dict(protocol=1, owned={}, current=None, previous=None)
    safe_path(STATE, True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or
                stat.S_IMODE(st.st_mode) != 0o600 or st.st_size > 2 * 1024 * 1024):
            raise RuntimeError('不安全的 hot 归属清单')
        value = json.load(stream)
    if (not isinstance(value, dict) or value.get('protocol') != 1 or
            not isinstance(value.get('owned'), dict) or
            not {'current', 'previous'} <= value.keys()):
        raise RuntimeError('未知 hot 归属清单')
    for name, digest in value['owned'].items():
        if (not re.fullmatch(r'cpa-updater-v0\.0\.1(?:\.\d+){8}\.so', name) or
                not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise RuntimeError('无效 hot 归属记录')
    for key in ('current', 'previous'):
        if value[key] is not None and (not isinstance(value[key], str) or Path(value[key]).parent != APP / 'plugins'):
            raise RuntimeError('无效 hot 保留路径')
    return value


def hot_owned_write(value):
    safe_path(STATE, True)
    atomic_write(STATE / 'hot-owned.json', json.dumps(value).encode(), 0o600)
    hot_sync()


def hot_cleanup(api, target, old, identity, expected, tag, scope):
    """Caller holds the common lock; only reached after successful verification."""
    try:
        value = hot_owned_read()
        if target != old:
            value['previous'] = str(old)
        value['current'] = str(target)
        # Persist retention before any deletion. A failed write must not prune.
        hot_owned_write(value)
        keep = {value['current'], value['previous']}
        def fence():
            if any(os.path.lexists(p) for p in (STATE / 'transaction.json', STATE / 'hot-transaction.json', RUN / 'processing')):
                raise RuntimeError('存在活动事务，跳过清理')
            if hot_identity() != identity:
                raise RuntimeError('主服务身份变化，跳过清理')
            current, current_tag = api.conditional('/v8/management/config/plugins')
            if current != expected or current_tag != tag or hot_scope(api) != scope:
                raise RuntimeError('配置变化，跳过清理')
            discovered = api.request('/v8/management/plugins')
            validate_registered(discovered)
            if (discovered.get('plugins_dir') != str(APP / 'plugins') or
                    next(p['path'] for p in discovered['plugins'] if p['id'] == 'cpa-updater') != str(target)):
                raise RuntimeError('加载路径变化，跳过清理')
            for plugin in discovered['plugins']:
                if not isinstance(plugin.get('path'), str):
                    raise RuntimeError('未知插件路径，跳过清理')
                keep.add(plugin['path'])
        fence()
        # Protect every configuration, including disabled plugin selectors.
        if (not isinstance(expected.get('configs'), dict) or
                set(expected) - {'enabled', 'configs', 'dir', 'store-sources', 'store-auth', 'auth-revision'} or
                expected.get('dir', str(APP / 'plugins')) != str(APP / 'plugins')):
            raise RuntimeError('未知插件配置，跳过清理')
        for plugin_id, config in expected['configs'].items():
            if not isinstance(config, dict) or not re.fullmatch(r'[A-Za-z0-9_-]+', plugin_id):
                raise RuntimeError('未知插件配置，跳过清理')
            store = config.get('store', {})
            if not isinstance(store, dict) or set(store) - {'version'}:
                raise RuntimeError('未知 store 配置，跳过清理')
            version = store.get('version')
            if version is not None:
                if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9.+_-]+', version):
                    raise RuntimeError('未知版本引用，跳过清理')
                keep.add(str(APP / 'plugins' / (plugin_id + '-v' + version + '.so')))
            for key in config:
                if key not in ('enabled', 'priority', 'config', 'store'):
                    raise RuntimeError('未知插件配置字段，跳过清理')
            # Opaque plugin-specific configuration may contain path references.
            if config.get('config'):
                raise RuntimeError('存在不透明插件配置，跳过清理')
        for name, digest in list(value['owned'].items()):
            path = APP / 'plugins' / name
            if str(path) in keep:
                continue
            fence()
            # Forget durably first: crashes/write failures can leak, never expand ownership.
            reduced = copy.deepcopy(value)
            del reduced['owned'][name]
            hot_owned_write(reduced)
            value = reduced
            plugin_io(path, 'prune', digest.encode())
    except Exception as exc:
        print('警告：hot 插件清理跳过/未完成：' + str(exc), file=sys.stderr)


def hot_install():
    if os.geteuid() != 0:
        raise RuntimeError('必须 root 执行')
    os.umask(0o077)
    validate_service()
    safe_path(STATE, True)
    safe_path(STATE / 'lock')
    api = API()
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='cpa-hot-') as build:
        compiled = Path(build) / 'cpa-updater.so'
        fd = os.open(STATE / 'lock', os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r+') as locked:
            st = os.fstat(locked.fileno())
            if st.st_uid != 0 or st.st_nlink != 1 or not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
                raise RuntimeError('不安全的共同锁')
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (STATE / 'transaction.json').exists() or (RUN / 'processing').exists():
                raise RuntimeError('未恢复的 worker 事务')
            pending = hot_record_read()
            if pending is not None:
                hot_recover(api, pending)
                print('旧 hot 事务已恢复并验证；请重新运行 --hot-reload 执行新升级')
                return
            command('gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC', '-shared',
                    str(here / 'cpa-updater.c'), '-o', str(compiled))
            data = compiled.read_bytes()
            version, name = hot_name(data)
            target = APP / 'plugins' / name
            hot_status(api.request('/v0/management/plugins/cpa-updater/status'))
            persistent = json.loads((PUBLIC / 'status.json').read_text())
            hot_status(persistent)
            before, tag = api.conditional('/v8/management/config/plugins')
            if not isinstance(before, dict):
                raise RuntimeError('插件配置不是对象')
            if before.get('enabled') is not True or before.get('configs', {}).get('cpa-updater', {}).get('enabled') is not True:
                raise RuntimeError('hot-reload 仅升级已启用插件')
            discovered = api.request('/v8/management/plugins')
            validate_registered(discovered)
            if discovered.get('plugins_dir') != str(APP / 'plugins'):
                raise RuntimeError('插件目录不匹配')
            old = Path(next(p['path'] for p in discovered['plugins'] if p['id'] == 'cpa-updater'))
            if old.parent != target.parent or plugin_io(old, 'read') is None:
                raise RuntimeError('当前插件路径不安全')
            identity = hot_identity()
            old_panel = hot_panel(old)
            hot_verify(api, old, old_panel, identity)
            existing = plugin_io(target, 'read')
            if existing is not None and existing != data:
                raise RuntimeError('不可变 hot 插件内容冲突')
            if (existing is not None and target != old and
                    not before['configs']['cpa-updater'].get('store', {}).get('version')):
                raise RuntimeError('legacy 无版本选择器且候选已存在；无法证明创建归属，拒绝切换')
            own = copy.deepcopy(before['configs']['cpa-updater'])
            own.setdefault('store', {})['version'] = version
            # A queued request is compatible deferred work: no queue/state/worker
            # writes, no trigger changes, shared lock excludes worker execution.
            hot_status(api.request('/v0/management/plugins/cpa-updater/status'))
            expected = copy.deepcopy(before)
            expected['configs']['cpa-updater'] = own
            record = dict(protocol=1, before=before, expected=expected, path=str(old),
                          identity=list(identity), tag=tag, scope=hot_scope(api),
                          candidate=str(target), created=existing is None,
                          quarantine=name + '.' + os.urandom(12).hex() + '.rollback-backup',
                          digest=hashlib.sha256(data).hexdigest())
            owned = None
            try:
                owned = hot_owned_read()
                record['owned_before'] = copy.deepcopy(owned)
            except Exception as exc:
                print('警告：归属清单不可用，保留所有旧插件：' + str(exc), file=sys.stderr)
            hot_record_write(record)
            try:
                if existing is None and owned is not None:
                    owned['owned'][name] = record['digest']
                    try:
                        hot_owned_write(owned)
                    except Exception as exc:
                        owned = None
                        print('警告：无法登记插件归属，跳过清理：' + str(exc), file=sys.stderr)
                if existing is None:
                    plugin_io(target, 'create', data)
                panel = hot_panel(target)
                _, written = api.conditional('/v8/management/config/plugins/configs/cpa-updater', own, tag)
                record['written'] = written
                hot_record_write(record)
                current, current_tag = api.conditional('/v8/management/config/plugins')
                expected = copy.deepcopy(before)
                expected['configs']['cpa-updater'] = own
                if current != expected or current_tag != written:
                    raise RuntimeError('配置发生并发变化')
                hot_verify(api, target, panel, identity)
            except BaseException:
                hot_recover(api, record)
                raise
            hot_record_clear()
            if owned is not None:
                hot_cleanup(api, target, old, identity, expected, written, record['scope'])
            print('hot-reload 已验证：' + str(target) + '；PID/start 未变化；worker/队列保持原样')


def hot_status(value):
    if (not isinstance(value, dict) or type(value.get('protocol')) is not int or
            value['protocol'] != 1 or
            value.get('state') not in ('idle', 'ready', 'current', 'success', 'up_to_date', 'error', 'rolled_back', 'needs_recheck')):
        raise RuntimeError('hot-reload 需要兼容 protocol=1 的空闲 worker')


def run(installing, worker_only=False, hot_reload=False):
    if hot_reload:
        if not installing or worker_only:
            raise RuntimeError('hot-reload 仅支持现有插件的独立安装')
        return hot_install()
    if os.geteuid() != 0:
        raise RuntimeError('必须 root 执行')
    os.umask(0o077)
    if os.path.lexists(STATE / 'hot-transaction.json'):
        raise RuntimeError('存在 hot-transaction.json；先运行 --hot-reload 恢复，禁止安装/卸载')
    if installing:
        libexec = WORKER.parent
        safe_path(libexec.parent, True)
        if not os.path.lexists(libexec):
            ensure_directory(libexec, 0o755)
        safe_path(libexec, True)
    validate_service()
    api = API()
    discovered = api.request('/v8/management/plugins')
    if discovered.get('plugins_dir') != str(APP / 'plugins'):
        raise RuntimeError('插件目录不匹配')
    if installing and not worker_only:
        own = api.config().get('configs', {}).get('cpa-updater', {})
        if own.get('store', {}).get('version') or own.get('store', {}).get('release-tag'):
            raise RuntimeError('存在 store/hot 版本选择；默认 install 拒绝覆盖未被选择的 legacy 插件，请使用 --hot-reload')
    here = Path(__file__).resolve().parent
    approved_deployment = deployment_config(api) if installing else None
    with tempfile.TemporaryDirectory(prefix='cpa-installer-') as build:
        compiled = Path(build) / 'cpa-updater.so'
        if installing and not worker_only:
            command('gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC', '-shared', str(here / 'cpa-updater.c'), '-o', str(compiled))
        ensure_directory(STATE, 0o700)
        lock = STATE / 'lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as locked:
            if os.fstat(locked.fileno()).st_uid != 0 or os.fstat(locked.fileno()).st_nlink != 1:
                raise RuntimeError('不安全的共同锁')
            # Acquire before touching trigger state, so concurrent installers cannot
            # restore each other's triggers. Recheck after stopping under the same lock.
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if os.path.lexists(STATE / 'hot-transaction.json'):
                raise RuntimeError('存在 hot-transaction.json；禁止安装/卸载')
            states = {u: (query('is-enabled', u), query('is-active', u)) for u in TRIGGERS + ['cliproxy-updater-recover.service']}
            snapshots = {}
            changed = False
            before = after = None
            try:
                for u in TRIGGERS:
                    if ctl('show', u, '-p', 'LoadState', '--value') == 'not-found':
                        continue
                    ctl('disable', '--now', u)
                    if query('is-active', u):
                        raise RuntimeError('触发器停止失败')
                # Nonblocking: never wait while holding stopped triggers for an active update.
                fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
                idle()
                validate_service()
                if installing:
                    ensure_directory(STATE / 'backups', 0o700)
                    ensure_directory(RUN, 0o750, grp.getgrnam('cliproxy').gr_gid)
                    ensure_directory(RUN / 'inbox', 0o730, grp.getgrnam('cliproxy').gr_gid)
                    ensure_directory(PUBLIC, 0o750, grp.getgrnam('cliproxy').gr_gid)
                before = api.config()
                after = before if worker_only else plan_config(before, installing)
                plugin_path = APP / 'plugins/cpa-updater.so'
                if not worker_only:
                    plugin_directory(plugin_path.parent)
                paths = [WORKER, RUNTIME, TMPFILE, STATE / 'deployment.json', PUBLIC / 'status.json'] + [SYSTEM / u for u in units()]
                if not worker_only:
                    paths.insert(0, plugin_path)
                for p in paths:
                    if not worker_only and p == plugin_path:
                        data = plugin_io(p, 'read')
                        snapshots[p] = None if data is None else (data, 0o755)
                    elif p.exists() or p.is_symlink():
                        safe_path(p)
                        snapshots[p] = (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
                    else:
                        snapshots[p] = None
                backup = Path(tempfile.mkdtemp(prefix='install-', dir=STATE))
                for i, (p, old) in enumerate(snapshots.items()):
                    if old:
                        (backup / str(i)).write_bytes(old[0])
                (backup / 'manifest.json').write_text(json.dumps({str(p): i for i, p in enumerate(snapshots)}))
                shutil.copy2(APP / 'config.yaml', backup / 'config.yaml')
                changed = True
                if installing:
                    if not worker_only:
                        plugin_io(plugin_path, 'write', compiled.read_bytes())
                    atomic_write(RUNTIME, (here / 'updater_runtime.py').read_bytes(), 0o644)
                    atomic_write(STATE / 'deployment.json', json.dumps(approved_deployment).encode(), 0o600)
                    atomic_write(WORKER, (here / 'cliproxy-updater-worker').read_bytes(), 0o755)
                    command(str(WORKER), '--preflight')
                    initialize_status()
                    for name, text in units().items():
                        atomic_write(SYSTEM / name, text.encode(), 0o644)
                    atomic_write(TMPFILE, b'd /var/lib/cliproxy-updater 0700 root root - -\nd /var/lib/cliproxy-updater/backups 0700 root root - -\nd /var/lib/cliproxy-updater-status 0750 root cliproxy - -\nd /run/cliproxy-updater 0750 root cliproxy - -\nd /run/cliproxy-updater/inbox 0730 root cliproxy - -\n', 0o644)
                    command('systemd-tmpfiles', '--create', '/etc/tmpfiles.d/cliproxy-updater.conf')
                    if not worker_only:
                        readable_by_service(plugin_path)
                # Write the private entry first, global last. Never overwrite unrelated config.
                if not worker_only:
                    api.put('configs/cpa-updater', after['configs']['cpa-updater'])
                if not worker_only and before.get('enabled') != after.get('enabled'):
                    api.put('enabled', after['enabled'])
                if api.config() != after:
                    raise RuntimeError('配置写入未实际生效或发生并发修改')
                if not installing:
                    for u in SERVICES:
                        if ctl('show', u, '-p', 'LoadState', '--value') != 'not-found':
                            ctl('stop', u)
                    if ctl('show', 'cliproxy-updater-recover.service', '-p', 'LoadState', '--value') != 'not-found':
                        ctl('disable', 'cliproxy-updater-recover.service')
                    for p in paths:
                        if p == plugin_path:
                            plugin_io(p, 'delete')
                        elif p in (STATE / 'deployment.json', PUBLIC / 'status.json'):
                            continue
                        else:
                            p.unlink(missing_ok=True)
                    if PUBLIC.exists():
                        atomic_write(PUBLIC / 'status.json', json.dumps(dict(protocol=0, state='setup_required', detail='更新服务已卸载')).encode(), 0o640)
                        os.chown(PUBLIC / 'status.json', 0, grp.getgrnam('cliproxy').gr_gid)
                ctl('daemon-reload')
                if not worker_only:
                    ctl('restart', 'cliproxyapi.service')
                health(api, None if worker_only else installing)
                if installing:
                    ctl('enable', 'cliproxy-updater-recover.service')
                    for u in TRIGGERS:
                        ctl('enable', '--now', u)
                        if not query('is-active', u) or not query('is-enabled', u):
                            raise RuntimeError('触发器启用未生效')
                print(('安装' if installing else '卸载') + '已验证完成；用户数据及备份保留于 ' + str(backup))
            except BaseException:
                failures = []
                if changed:
                    assert before is not None and after is not None
                    for p, old in snapshots.items():
                        try:
                            if p == plugin_path:
                                plugin_io(p, 'delete' if old is None else 'write', None if old is None else old[0])
                            elif old is None:
                                p.unlink(missing_ok=True)
                            else:
                                atomic_write(p, *old)
                                if p == PUBLIC / 'status.json':
                                    os.chown(p, 0, grp.getgrnam('cliproxy').gr_gid)
                        except Exception:
                            failures.append('文件恢复失败: ' + str(p))
                    # Restore service independently: a dead API must not prevent
                    # restarting the old executable/plugin files we just restored.
                    try:
                        ctl('daemon-reload')
                    except Exception:
                        failures.append('恢复旧 unit 后 daemon-reload 失败')
                    try:
                        if not worker_only:
                            ctl('restart', 'cliproxyapi.service')
                        health(api, None)
                    except Exception:
                        failures.append('旧服务启动/健康恢复未通过')
                    try:
                        # Only restore fields still equal to our intended value or original.
                        current = api.config()
                        for field in ([] if worker_only else ['configs', 'enabled']):
                            if field == 'configs':
                                own = current.get('configs', {}).get('cpa-updater')
                                original = before.get('configs', {}).get('cpa-updater')
                                expected = after.get('configs', {}).get('cpa-updater')
                                if own not in (original, expected):
                                    raise RuntimeError('本插件配置并发变化')
                                if original is None:
                                    api.request('/v8/management/config/plugins/configs/cpa-updater', method='DELETE', raw=True)
                                else:
                                    api.put('configs/cpa-updater', original)
                            elif current.get(field) in (before.get(field), after.get(field)):
                                api.put(field, before.get(field, False))
                            else:
                                raise RuntimeError('全局开关并发变化')
                        if api.config() != before:
                            raise RuntimeError('配置不等于快照；保留并发变化，需人工复核')
                        health(api, None)
                    except Exception:
                        failures.append('配置/健康恢复未通过；保留快照，请人工检查')
                try:
                    restore_triggers(states)
                except Exception:
                    failures.append('触发器状态恢复失败')
                print('操作失败；' + ('；'.join(failures) if failures else '有限恢复检查通过'), file=sys.stderr)
                raise


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise RuntimeError('收到终止信号，操作中止')
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        if len(sys.argv) not in (2, 3) or sys.argv[1] not in ('install', 'uninstall') or (len(sys.argv) == 3 and (sys.argv[1] != 'install' or sys.argv[2] not in ('--worker-only', '--hot-reload'))):
            raise RuntimeError('用法: install.sh [--worker-only | --hot-reload] 或 uninstall.sh')
        run(sys.argv[1] == 'install', worker_only='--worker-only' in sys.argv[2:], hot_reload='--hot-reload' in sys.argv[2:])
    except BaseException as exc:
        # Never print HTTP payloads, headers, credentials, or subprocess output.
        print('安装/卸载中止: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
