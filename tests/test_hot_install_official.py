#!/usr/bin/env python3
"""Real v8.0.56 installer smoke test, confined to bubblewrap (run with sudo).

Usage: sudo python3 tests/test_hot_install_official.py --binary /verified/cli-proxy-api --output evidence
The caller supplies the verified official binary; nothing is downloaded. The
worker/runtime are real installed files, but NO worker process is run: protocol-1
idle status is an explicit fixture. This is not a worker or SSE continuity test.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

KEY = 'isolated-hot-install-not-a-real-secret'
TITLE = '<title>版本更新 · CLIProxyAPI</title>'
OLD_TITLE = '<title>old fixture</title>'
APP = Path('/opt/cliproxyapi')
STATE = Path('/var/lib/cliproxy-updater')
RUN = Path('/run/cliproxy-updater')
PUBLIC = Path('/var/lib/cliproxy-updater-status')


def inside():
    assert os.geteuid() == 0, 'isolated installer must run as root'
    Path('/tmp').chmod(0o1777)  # private mount must match real Linux temp semantics
    Path('/etc/passwd').write_text('root:x:0:0:root:/root:/bin/bash\ncliproxy:x:1000:1000:fixture:/opt/cliproxyapi:/usr/sbin/nologin\n')
    Path('/etc/group').write_text('root:x:0:\ncliproxy:x:1000:\n')
    for p in [APP, APP / 'plugins', APP / 'auths', STATE, STATE / 'backups', RUN,
              RUN / 'inbox', PUBLIC, Path('/root'), Path('/usr/local/libexec'),
              Path('/etc/systemd/system'), Path('/etc/tmpfiles.d'), Path('/shim')]:
        p.mkdir(parents=True, exist_ok=True)
        p.chmod(0o755)
    for p, mode, gid in [(STATE, 0o700, 0), (STATE / 'backups', 0o700, 0),
                         (RUN, 0o750, 1000), (RUN / 'inbox', 0o730, 1000),
                         (PUBLIC, 0o750, 1000), (Path('/root'), 0o700, 0)]:
        p.chmod(mode)
        os.chown(p, 0, gid)
    os.chown(APP / 'plugins', 1000, 1000)
    os.chown(APP / 'auths', 1000, 1000)
    shutil.copyfile('/official', APP / 'cli-proxy-api')
    (APP / 'cli-proxy-api').chmod(0o755)
    shutil.copyfile('/old.so', APP / 'plugins/cpa-updater.so')
    (APP / 'plugins/cpa-updater.so').chmod(0o755)
    for source, target, mode in [('/source/cliproxy-updater-worker', '/usr/local/libexec/cliproxy-updater-worker', 0o755),
                                 ('/source/updater_runtime.py', '/usr/local/libexec/cliproxy-updater-runtime.py', 0o644)]:
        shutil.copyfile(source, target)
        Path(target).chmod(mode)
    (STATE / 'deployment.json').write_text(json.dumps({'protocol': 1, 'auth_dir': str(APP / 'auths')}))
    (STATE / 'deployment.json').chmod(0o600)
    (STATE / 'lock').touch(mode=0o600)
    status = dict(protocol=1, worker_version='0.5.0', state='idle', current='8.0.56', latest='unknown',
                  detail='fixture only; worker process not running')
    (PUBLIC / 'status.json').write_text(json.dumps(status))
    (PUBLIC / 'status.json').chmod(0o640)
    os.chown(PUBLIC / 'status.json', 0, 1000)
    Path('/root/cliproxyapi-admin-key').write_text(KEY + '\n')
    Path('/root/cliproxyapi-admin-key').chmod(0o600)
    config = APP / 'config.yaml'
    config.write_text('''host: "127.0.0.1"
port: 8317
remote-management:
  allow-remote: false
  secret-key: "''' + KEY + '''"
  disable-control-panel: true
auth-dir: "/opt/cliproxyapi/auths"
api-keys:
  - "preserved-client-key"
plugins:
  enabled: true
  dir: "/opt/cliproxyapi/plugins"
  configs:
    cpa-updater:
      enabled: true
      priority: 1
    unrelated-fixture:
      enabled: false
      priority: 37
''')
    config.chmod(0o660)
    os.chown(config, 0, 1000)
    data = APP / 'auths/preserved.data'
    data.write_bytes(b'opaque user data must survive\x00\xff')
    os.chown(data, 1000, 1000)
    # Strict service boundary: every invocation is recorded, including denied ones.
    shim = Path('/shim/systemctl')
    shim.write_text('''#!/usr/bin/python3
import json,sys
from pathlib import Path
a=sys.argv[1:]
with Path('/output/systemctl.jsonl').open('a') as f: f.write(json.dumps(a)+'\\n')
if len(a)==5 and a[0]=='show' and a[1]=='cliproxyapi.service' and a[2]=='-p' and a[4]=='--value':
 values={'User':'cliproxy','Group':'cliproxy','ExecStart':'{ path=/opt/cliproxyapi/cli-proxy-api ; argv[]=/opt/cliproxyapi/cli-proxy-api --config /opt/cliproxyapi/config.yaml --local-model ; }','MainPID':Path('/run/main.pid').read_text().strip(),'ExecMainStartTimestampMonotonic':Path('/run/main.start').read_text().strip()}
 if a[3] in values: print(values[a[3]]);sys.exit(0)
if len(a)==3 and a[0]=='is-active' and a[1]=='--quiet':
 if a[2]=='cliproxyapi.service':
  try:
   import os
   os.kill(int(Path('/run/main.pid').read_text()),0);sys.exit(0)
  except ProcessLookupError: sys.exit(3)
 if a[2] in ['cliproxy-updater.service','cliproxy-updater-check.service','cliproxy-updater-recover.service']: sys.exit(3)
print('DENIED systemctl operation: '+repr(a),file=sys.stderr)
sys.exit(97)
''')
    shim.chmod(0o755)
    os.environ['PATH'] = '/shim:/usr/bin:/bin'
    records = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, method='GET', authenticated=True):
        req = urllib.request.Request('http://127.0.0.1:8317' + path, method=method,
                                     headers={'Authorization': 'Bearer ' + KEY} if authenticated else {})
        try:
            response = opener.open(req, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            records.append({'path': path, 'method': method, 'status': response.status,
                            'sha256': hashlib.sha256(raw).hexdigest()})
            assert response.status == 200, records[-1]
            return raw

    def snapshot(paths):
        return {str(p): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_uid, p.stat().st_gid)
                for p in paths}

    panel = '/v0/resource/plugins/cpa-updater/panel'
    with Path('/output/official-server.log').open('w') as log:
        proc = subprocess.Popen([str(APP / 'cli-proxy-api'), '--config', str(config), '--local-model'],
                                cwd=APP, user=1000, group=1000, extra_groups=[], stdout=log, stderr=subprocess.STDOUT)
        Path('/run/main.pid').write_text(str(proc.pid))
        Path('/run/main.start').write_text(Path(f'/proc/{proc.pid}/stat').read_text().split()[21])
        try:
            for _ in range(200):
                assert proc.poll() is None, 'official server exited; see official-server.log'
                try:
                    old = api(panel, authenticated=False).decode()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('official server startup timeout')
            assert OLD_TITLE in old and TITLE not in old, 'old plugin fixture was not loaded'
            assert 'Uid:\t1000\t1000\t1000\t1000' in Path(f'/proc/{proc.pid}/status').read_text()
            # Let the official host hash the management key before baseline capture.
            before_plugins = json.loads(api('/v8/management/config/plugins'))
            before_yaml = api('/v8/management/config.yaml')
            protected = [config, data, STATE / 'deployment.json', STATE / 'lock', PUBLIC / 'status.json',
                         Path('/usr/local/libexec/cliproxy-updater-worker'),
                         Path('/usr/local/libexec/cliproxy-updater-runtime.py')]
            protected.remove(config)  # Only the installer's own store.version selection may change.
            baseline = snapshot(protected)
            installed_yaml = before_yaml
            installed = None
            inode = None
            selected_path = None
            pid = proc.pid
            for iteration in (1, 2):
                result = subprocess.run(['/bin/bash', '/source/install.sh', '--hot-reload'],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
                Path(f'/output/install-{iteration}.log').write_text(result.stdout)
                assert result.returncode == 0, f'installer failed ({result.returncode}): {result.stdout}'
                assert proc.pid == pid and proc.poll() is None, 'main PID changed or exited'
                page = api(panel, authenticated=False).decode()
                assert TITLE in page and OLD_TITLE not in page, 'new page not effective'
                current_plugins = json.loads(api('/v8/management/config/plugins'))
                version = current_plugins['configs']['cpa-updater'].get('store', {}).get('version')
                assert isinstance(version, str) and version.startswith('0.0.1'), current_plugins
                comparable = json.loads(json.dumps(current_plugins))
                del comparable['configs']['cpa-updater']['store']
                assert comparable == before_plugins, 'unrelated plugin configuration changed'
                if iteration == 1:
                    installed_yaml = api('/v8/management/config.yaml')
                    def without_selection(raw):
                        return [line.strip() for line in raw.decode().splitlines()
                                if line.strip() and not line.strip().startswith(('store:', 'version:'))]
                    assert without_selection(installed_yaml) == without_selection(before_yaml), 'unrelated YAML changed'
                    assert stat.S_IMODE(config.stat().st_mode) == 0o660
                    assert (config.stat().st_uid, config.stat().st_gid) == (0, 1000)
                else:
                    assert api('/v8/management/config.yaml') == installed_yaml
                assert snapshot(protected) == baseline, 'config/data/worker/private state changed'
                listing = json.loads(api('/v8/management/plugins'))
                own = [p for p in listing['plugins'] if p['id'] == 'cpa-updater']
                assert len(own) == 1 and own[0]['registered'] and own[0]['effective_enabled'], listing
                assert json.loads(api('/v0/management/plugins/cpa-updater/status')) == dict(status, pending=False)
                assert not list((RUN / 'inbox').iterdir()), 'installer left a queued request'
                assert not (RUN / 'processing').exists()
                assert not (STATE / 'transaction.json').exists()
                calls = [json.loads(line) for line in Path('/output/systemctl.jsonl').read_text().splitlines()]
                assert all(c[0] in ('show', 'is-active') for c in calls), calls
                assert all(c[3] in ('User', 'Group', 'ExecStart', 'MainPID', 'ExecMainStartTimestampMonotonic') for c in calls if c[0] == 'show'), calls
                if iteration == 1:
                    selected_path = Path(own[0]['path'])
                    installed = snapshot([selected_path])
                    inode = selected_path.stat().st_ino
                else:
                    assert selected_path is not None
                    assert Path(own[0]['path']) == selected_path
                    assert snapshot([selected_path]) == installed
                    assert selected_path.stat().st_ino == inode, 'idempotent install replaced identical library'
            # The shared worker/installer lock is released, and remains private.
            with (STATE / 'lock').open('r+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            denied = subprocess.run(['/usr/bin/python3', '-c',
                "from pathlib import Path; Path('/var/lib/cliproxy-updater/lock').open('r+')"],
                user=1000, group=1000, extra_groups=[], capture_output=True)
            assert denied.returncode != 0 and b'PermissionError' in denied.stderr
            Path('/output/result.json').write_text(json.dumps(dict(passed=True, main_pid=pid,
                installs=2, worker_running=False, status_fixture=status, systemctl_calls=calls), indent=2))
            print('PASS: two real hot installs; new panel, stable nonroot PID, no service mutations; config/data preserved')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            Path('/output/api-probes.json').write_text(json.dumps(records, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        inside()
        return
    if args.binary is None or not args.binary.is_file():
        parser.error('--binary must name the verified official v8.0.56 executable')
    if os.geteuid() != 0:
        parser.error('run with sudo: real uid 1000 and root installer require root; no host fallback')
    for tool in ('bwrap', 'gcc'):
        if not shutil.which(tool):
            parser.error(tool + ' required; refusing host-system fallback')
    source = args.source.resolve()
    with tempfile.TemporaryDirectory(prefix='cpa-hot-install-') as tmp:
        temp = Path(tmp)
        output = args.output.resolve() if args.output else temp / 'output'
        output.mkdir(parents=True, exist_ok=True)
        text = (source / 'cpa-updater.c').read_text()
        assert text.count(TITLE) == 1, 'visible title fixture must match exactly once'
        old_source = temp / 'old.c'
        old_source.write_text(text.replace(TITLE, OLD_TITLE))
        library = temp / 'old.so'
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC', '-shared',
                        '-I', str(source), str(old_source), '-o', str(library)], check=True)
        cmd = ['bwrap', '--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts',
               '--die-with-parent', '--ro-bind', '/usr', '/usr',
               '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/sbin', '/sbin',
               '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/var',
               '--tmpfs', '/run', '--tmpfs', '/etc', '--tmpfs', '/opt', '--tmpfs', '/root',
               '--tmpfs', '/usr/local', '--ro-bind', str(source), '/source',
               '--ro-bind', str(args.binary.resolve()), '/official', '--ro-bind', str(library), '/old.so',
               '--ro-bind', str(Path(__file__).resolve()), '/test.py', '--bind', str(output), '/output',
               '--uid', '0', '--gid', '0', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
               '--setenv', 'HOME', '/root', '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
               '/usr/bin/python3', '/test.py', '--inside']
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        print(result.stdout, end='')
        print('Official binary SHA256:', hashlib.sha256(args.binary.read_bytes()).hexdigest())
        if args.output:
            print('Evidence:', output)
        if result.returncode:
            log = output / 'official-server.log'
            if log.exists():
                print(log.read_text())
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
