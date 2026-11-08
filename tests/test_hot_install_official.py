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
    cpa-key-billing:
      enabled: false
      priority: 37
      allow_unpriced_models: true
      codex_fast_mode_billing: false
      debug: false
      state_file: "/opt/cliproxyapi/plugins/cpa-key-billing-state-v1.db"
      store:
        author: "fixture author"
        description: "synthetic billing-store metadata, not real billing plugin"
        homepage: "https://example.invalid"
        id: "cpa-key-billing"
        install:
          type: "github-release"
        license: "MIT"
        name: "store fixture"
        release-tag: "v1.2.3"
        repository: "https://example.invalid/fixture"
        source-id: "test-source"
        source-name: "test store"
        source-url: "https://example.invalid/registry.json"
        tags:
          - "billing"
        version: "1.2.3"
''')
    config.chmod(0o660)
    os.chown(config, 0, 1000)
    data = APP / 'auths/preserved.data'
    data.write_bytes(b'opaque user data must survive\x00\xff')
    os.chown(data, 1000, 1000)
    billing_files = []
    for suffix in ['', '-wal', '-shm']:
        path = APP / ('plugins/cpa-key-billing-state-v1.db' + suffix)
        path.write_bytes(b'synthetic billing data; must not be touched')
        os.chown(path, 1000, 1000)
        billing_files.append(path)
    # Strict service boundary: every invocation is recorded, including denied ones.
    shim = Path('/shim/systemctl')
    shim.write_text('''#!/usr/bin/python3
import json,sys
from pathlib import Path
a=sys.argv[1:]
with Path('/output/systemctl.jsonl').open('a') as f: f.write(json.dumps(a)+'\\n')
if len(a)==5 and a[0]=='show' and a[1]=='cliproxyapi.service' and a[2]=='-p' and a[4]=='--value':
 values={'User':'cliproxy','Group':'cliproxy','ExecStart':'{ path=/opt/cliproxyapi/cli-proxy-api ; argv[]=/opt/cliproxyapi/cli-proxy-api --config /opt/cliproxyapi/config.yaml --local-model ; ignore_errors=no ; }','MainPID':Path('/run/main.pid').read_text().strip(),'ExecMainStartTimestampMonotonic':Path('/run/main.start').read_text().strip()}
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
            protected.extend(billing_files)
            baseline = snapshot(protected)
            installed_yaml = before_yaml
            installed = None
            inode = None
            selected_path = None
            pid = proc.pid
            start = Path(f'/proc/{pid}/stat').read_text().split()[21]
            old_path = next(p['path'] for p in json.loads(api('/v8/management/plugins'))['plugins']
                            if p['id'] == 'cpa-updater')
            original_library = snapshot([Path(old_path)])

            def service_read_only():
                assert not list(Path('/etc/systemd/system').iterdir()), 'installer wrote service files'
                assert not list(Path('/etc/tmpfiles.d').iterdir()), 'installer wrote tmpfiles policy'
                calls = [json.loads(line) for line in Path('/output/systemctl.jsonl').read_text().splitlines()]
                assert all(c[0] in ('show', 'is-active') for c in calls), calls
                assert all(c[3] in ('User', 'Group', 'ExecStart', 'MainPID', 'ExecMainStartTimestampMonotonic')
                           for c in calls if c[0] == 'show'), calls

            def restored_baseline():
                assert proc.poll() is None and proc.pid == pid, 'main PID changed or exited'
                assert Path(f'/proc/{pid}/stat').read_text().split()[21] == start
                assert api(panel, authenticated=False).decode() == old, 'old page not restored'
                assert json.loads(api('/v8/management/config/plugins')) == before_plugins, 'old selection not restored'
                restored_yaml = api('/v8/management/config.yaml')
                if restored_yaml != before_yaml:
                    import difflib
                    raise AssertionError('old YAML not restored (synthetic fixture only):\n' + ''.join(
                        difflib.unified_diff(before_yaml.decode().splitlines(True), restored_yaml.decode().splitlines(True))))
                listing = json.loads(api('/v8/management/plugins'))
                own = [p for p in listing['plugins'] if p['id'] == 'cpa-updater']
                assert len(own) == 1 and own[0]['path'] == old_path
                assert own[0]['registered'] and own[0]['effective_enabled']
                assert snapshot([Path(old_path)]) == original_library, 'old library changed'
                assert snapshot(protected) == baseline, 'protected state changed'
                assert stat.S_IMODE(config.stat().st_mode) == 0o660
                assert (config.stat().st_uid, config.stat().st_gid) == (0, 1000)
                assert not list((RUN / 'inbox').iterdir()) and not (RUN / 'processing').exists()
                assert not (STATE / 'transaction.json').exists()
                assert not (STATE / 'hot-transaction.json').exists(), 'hot recovery record not cleared'
                assert json.loads(api('/v0/management/plugins/cpa-updater/status')) == dict(status, pending=False)
                with (STATE / 'lock').open('r+') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                service_read_only()

            # Fault injection is exclusively at the client return boundary: the
            # real official server handles the PUT and serves the new panel first.
            # Neither API responses nor installer transaction logic are mocked.
            fault_code = r'''
import json,os,sys,time
from pathlib import Path
sys.path.insert(0, '/source')
import install_helper as installer
mode = sys.argv[1]
original = installer.API.conditional
fired = False
def conditional(self, path, value=None, etag=None):
    global fired
    result = original(self, path, value, etag)
    if etag is not None and not fired and path.endswith('/configs/cpa-updater'):
        fired = True
        deadline = time.monotonic() + 15
        while True:
            listing = self.request('/v8/management/plugins')
            own = next(p for p in listing['plugins'] if p['id'] == 'cpa-updater')
            page = self.request('/v0/resource/plugins/cpa-updater/panel', raw=True)
            if own['path'] != '/opt/cliproxyapi/plugins/cpa-updater.so' and b'<title>\xe7\x89\x88\xe6\x9c\xac\xe6\x9b\xb4\xe6\x96\xb0' in page:
                assert page == installer.hot_panel(Path(own['path']))
                assert self.config()['configs']['cpa-updater'] == value
                Path('/output/' + mode + '-applied.json').write_text(json.dumps({
                    'actual_put_applied': True, 'new_page_served': True,
                    'selected_path': own['path'], 'mode': mode}))
                break
            assert time.monotonic() < deadline, 'actual new selection never became effective'
            time.sleep(.1)
        if mode == 'interrupted':
            os._exit(86)  # no exception handling/finally: durable recovery required
        raise TimeoutError('injected lost response after actual official-server PUT')
    return result
installer.API.conditional = conditional
installer.hot_install()
raise AssertionError('fault injection did not fire')
'''
            def without_selection(raw):
                return [line.strip() for line in raw.decode().splitlines()
                        if line.strip() and not line.strip().startswith(('store:', 'version:'))]

            failure_scenarios = []
            for mode in ('lost-response', 'interrupted'):
                result = subprocess.run(['/usr/bin/python3', '-c', fault_code, mode],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
                fault_log = Path('/output/' + mode + '.log')
                fault_log.write_text(result.stdout)
                fault_log.chmod(0o644)
                assert result.returncode != 0, 'injected failure unexpectedly succeeded'
                marker = Path('/output/' + mode + '-applied.json')
                assert marker.exists(), 'fault was not injected after a verified real PUT'
                marker.chmod(0o644)
                assert json.loads(marker.read_text())['actual_put_applied']
                if mode == 'lost-response':
                    assert 'injected lost response' in result.stdout, result.stdout
                else:
                    assert result.returncode == 86, result.stdout
                    pending = STATE / 'hot-transaction.json'
                    assert pending.is_file(), 'crashed installer left no durable recovery record'
                    assert stat.S_IMODE(pending.stat().st_mode) == 0o600 and pending.stat().st_uid == 0
                    assert TITLE in api(panel, authenticated=False).decode(), 'crash did not leave new page active'
                    recovery = subprocess.run(['/bin/bash', '/source/install.sh', '--hot-reload'],
                                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
                    recovery_log = Path('/output/interrupted-recovery.log')
                    recovery_log.write_text(recovery.stdout)
                    recovery_log.chmod(0o644)
                    assert recovery.returncode == 0, recovery.stdout
                restored_baseline()
                failure_scenarios.append(dict(mode=mode, actual_put_applied=True, old_page_restored=True,
                                              old_config_restored=True, pid_preserved=True, service_writes=False))
            for iteration in (1, 2):
                result = subprocess.run(['/bin/bash', '/source/install.sh', '--hot-reload'],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
                log_path = Path(f'/output/install-{iteration}.log')
                log_path.write_text(result.stdout)
                log_path.chmod(0o644)  # test evidence, contains no production credentials
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
                assert not (STATE / 'hot-transaction.json').exists()
                assert Path(f'/proc/{pid}/stat').read_text().split()[21] == start
                service_read_only()
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
            # Unregistered files are not installer-owned, even if their names
            # match its content-addressed namespace. Never prune by glob alone.
            unknown = APP / ('plugins/cpa-updater-v0.0.1.' + '.'.join(['4294967295'] * 8) + '.so')
            shutil.copyfile('/old.so', unknown)
            unknown.chmod(0o755)
            rollback_backup = selected_path.with_name(selected_path.name + '.' + 'a' * 24 + '.rollback-backup')
            shutil.copyfile(selected_path, rollback_backup)
            preserved_libraries = snapshot([Path(old_path), unknown, rollback_backup])
            owned_paths = [selected_path]
            owned_hashes = {str(selected_path): hashlib.sha256(selected_path.read_bytes()).hexdigest()}
            upgrades = []
            for label in ('B', 'C', 'D'):
                variant = Path('/run/variant-' + label)
                shutil.copytree('/source', variant, ignore=shutil.ignore_patterns('.git', '__pycache__'))
                variant_title = TITLE.replace('</title>', ' ' + label + '</title>')
                source_file = variant / 'cpa-updater.c'
                source_text = source_file.read_text()
                assert source_text.count(TITLE) == 1
                source_file.write_text(source_text.replace(TITLE, variant_title))
                assert (variant / 'install_helper.py').read_bytes() == Path('/source/install_helper.py').read_bytes()
                for repeat in (False, True):
                    before_repeat = snapshot(list((APP / 'plugins').iterdir())) if repeat else None
                    before_inodes = {str(p): p.stat().st_ino for p in (APP / 'plugins').iterdir()} if repeat else None
                    before_repeat_yaml = api('/v8/management/config.yaml') if repeat else None
                    result = subprocess.run(['/bin/bash', str(variant / 'install.sh'), '--hot-reload'],
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
                    log_path = Path('/output/install-' + label + ('-repeat' if repeat else '') + '.log')
                    log_path.write_text(result.stdout)
                    log_path.chmod(0o644)
                    assert result.returncode == 0, result.stdout
                    assert variant_title in api(panel, authenticated=False).decode(), 'new build not served'
                    listing = json.loads(api('/v8/management/plugins'))
                    own = [p for p in listing['plugins'] if p['id'] == 'cpa-updater']
                    assert len(own) == 1 and own[0]['registered'] and own[0]['effective_enabled'], listing
                    live_path = Path(own[0]['path'])
                    live_hash = hashlib.sha256(live_path.read_bytes()).hexdigest()
                    if not repeat:
                        assert live_path not in owned_paths and live_hash not in owned_hashes.values()
                        owned_paths.append(live_path)
                        owned_hashes[str(live_path)] = live_hash
                    else:
                        assert live_path == owned_paths[-1]
                        assert snapshot(list((APP / 'plugins').iterdir())) == before_repeat, 'repeat changed library files'
                        assert {str(p): p.stat().st_ino for p in (APP / 'plugins').iterdir()} == before_inodes
                        assert api('/v8/management/config.yaml') == before_repeat_yaml
                    # Count only positively observed successful installs; unknown
                    # and legacy files deliberately make total file counts larger.
                    survivors = [p for p in owned_paths if p.exists()]
                    assert survivors == owned_paths[-2:], 'owned cleanup must retain current and previous only'
                    for p in survivors:
                        assert hashlib.sha256(p.read_bytes()).hexdigest() == owned_hashes[str(p)]
                    assert snapshot([Path(old_path), unknown, rollback_backup]) == preserved_libraries
                    current_plugins = json.loads(api('/v8/management/config/plugins'))
                    assert current_plugins['configs']['cpa-updater']['store']['version'] == live_path.name[len('cpa-updater-v'):-3]
                    comparable = json.loads(json.dumps(current_plugins))
                    del comparable['configs']['cpa-updater']['store']
                    assert comparable == before_plugins, 'unrelated plugin configuration changed'
                    assert without_selection(api('/v8/management/config.yaml')) == without_selection(before_yaml)
                    assert stat.S_IMODE(config.stat().st_mode) == 0o660
                    assert (config.stat().st_uid, config.stat().st_gid) == (0, 1000)
                    assert snapshot(protected) == baseline, 'data/worker/private state changed'
                    assert not list((RUN / 'inbox').iterdir()) and not (RUN / 'processing').exists()
                    assert not (STATE / 'transaction.json').exists()
                    assert not (STATE / 'hot-transaction.json').exists()
                    assert json.loads(api('/v0/management/plugins/cpa-updater/status')) == dict(status, pending=False)
                    # Check identity after all readbacks, not merely installer exit.
                    assert proc.poll() is None and proc.pid == pid
                    assert Path(f'/proc/{pid}/stat').read_text().split()[21] == start
                    service_read_only()
                    upgrades.append(dict(build=label, repeat=repeat, selected_path=str(live_path),
                                         sha256=live_hash, retained_owned=[str(p) for p in survivors],
                                         owned_hashes=dict(owned_hashes)))
            calls = [json.loads(line) for line in Path('/output/systemctl.jsonl').read_text().splitlines()]
            # The shared worker/installer lock is released, and remains private.
            with (STATE / 'lock').open('r+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            denied = subprocess.run(['/usr/bin/python3', '-c',
                "from pathlib import Path; Path('/var/lib/cliproxy-updater/lock').open('r+')"],
                user=1000, group=1000, extra_groups=[], capture_output=True)
            assert denied.returncode != 0 and b'PermissionError' in denied.stderr
            Path('/output/result.json').write_text(json.dumps(dict(passed=True, main_pid=pid,
                installs=2 + len(upgrades), upgrades=upgrades,
                preserved_libraries=[str(p) for p in (Path(old_path), unknown, rollback_backup)],
                failure_scenarios=failure_scenarios, worker_running=False,
                status_fixture=status, systemctl_calls=calls), indent=2))
            print('PASS: real rollback/recovery; four distinct builds with repeat installs; current+previous owned cleanup; unknown/legacy/backups preserved; stable nonroot PID, no service mutations; config/data preserved')
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
