#!/usr/bin/env python3
"""Real official-host integration in a private network/filesystem namespace.

Usage: python3 tests/test_official.py --binary /path/to/verified/cli-proxy-api
Requires Linux, gcc and bubblewrap; does not download anything or use real keys.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

KEY = 'isolated-integration-test-not-a-real-key'
REPO = 'https://github.com/flying864/cliproxyapi-web-updater'


def inside():
    app = Path('/app')
    (app / 'plugins').mkdir(parents=True)
    (app / 'auths').mkdir()
    shutil.copyfile('/library.so', app / 'plugins/cpa-updater.so')
    run = Path('/run/cliproxy-updater')
    (run / 'inbox').mkdir(parents=True)
    (app / 'config.yaml').write_text('''host: "127.0.0.1"
port: 8317
remote-management:
  allow-remote: false
  secret-key: "isolated-integration-test-not-a-real-key"
  disable-control-panel: true
auth-dir: "/app/auths"
api-keys:
  - "isolated-client-test-key"
plugins:
  enabled: true
  dir: "/app/plugins"
  configs:
    cpa-updater:
      enabled: true
      priority: 1
''')
    records = []

    def request(path, method='GET', auth=True):
        headers = {'Authorization': 'Bearer ' + KEY} if auth else {}
        req = urllib.request.Request('http://127.0.0.1:8317' + path,
                                     method=method, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read().decode()
            try:
                body = json.loads(raw)
            except ValueError:
                body = {'html': '<html' in raw.lower(), 'length': len(raw)}
            result = {'method': method, 'path': path, 'authenticated': auth,
                      'status': response.status, 'body': body}
            records.append(result)
            return result

    log_path = Path('/output/official-server.log')
    with log_path.open('w') as log:
        proc = subprocess.Popen(['/official', '--config', '/app/config.yaml', '--local-model'],
                                cwd='/app', stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(120):
                if proc.poll() is not None:
                    raise AssertionError('Official server exited during startup; inspect log')
                try:
                    request('/v1/models', auth=False)
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('Official server startup timeout')
            config = request('/v8/management/config/plugins')
            assert config['status'] == 200 and config['body']['enabled'] is True, config
            assert config['body']['configs']['cpa-updater']['enabled'] is True, config
            listing = request('/v8/management/plugins')
            assert listing['status'] == 200, listing
            plugins = [p for p in listing['body']['plugins'] if p['id'] == 'cpa-updater']
            assert len(plugins) == 1, listing
            plugin = plugins[0]
            assert plugin['registered'] is True and plugin['effective_enabled'] is True, plugin
            assert plugin['metadata']['github_repository'] == REPO, plugin
            assert plugin['metadata']['version'] == '0.3.0', plugin
            panel = request('/v0/resource/plugins/cpa-updater/panel', auth=False)
            assert panel['status'] == 200 and panel['body']['html'], panel
            api = '/v0/management/plugins/cpa-updater'
            for endpoint, method in [('status', 'GET'), ('check', 'POST'), ('update', 'POST')]:
                result = request(api + '/' + endpoint, method, auth=False)
                assert result['status'] == 401, result
            result = request(api + '/status')
            assert result['status'] == 200, result
            result = request(api + '/check', 'POST')
            assert result['status'] == 202, result
            assert (run / 'inbox/request').read_text() == 'check'
            assert (run / 'inbox/request').stat().st_nlink == 1
            (run / 'inbox/request').unlink()
            (run / 'status.json').write_text(json.dumps({
                'state': 'ready', 'current': '8.0.55', 'latest': 'v8.0.56'}))
            for query in ['', '?version=v8.0.55', '?version=v8.0.56&version=v8.0.57']:
                result = request(api + '/update' + query, 'POST')
                assert result['status'] in (400, 409), result
                assert not (run / 'inbox/request').exists(), result
            result = request(api + '/update?version=v8.0.56', 'POST')
            assert result['status'] == 202, result
            assert (run / 'inbox/request').read_text() == 'update v8.0.56'
            assert (run / 'inbox/request').stat().st_nlink == 1
            (run / 'inbox/request').unlink()
            with ThreadPoolExecutor(max_workers=8) as pool:
                concurrent = list(pool.map(lambda _: request(api + '/check', 'POST'), range(8)))
            assert sum(r['status'] == 202 for r in concurrent) == 1, concurrent
            assert all(r['status'] in (202, 409) for r in concurrent), concurrent
            assert (run / 'inbox/request').read_text() == 'check'
            assert (run / 'inbox/request').stat().st_nlink == 1
            print('PASS: official registration, repository/version metadata, panel, auth, full routes, '
                  'confirmed version and concurrent single-link queue')
        finally:
            # This is the isolated test child, never a host system service.
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            Path('/output/official-probes.json').write_text(
                json.dumps(records, ensure_ascii=False, indent=2))


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
        parser.error('--binary must name a previously verified official CLIProxyAPI executable')
    for tool in ['bwrap', 'gcc']:
        if not shutil.which(tool):
            parser.error(tool + ' is required for isolation; refusing a host-system fallback')
    with tempfile.TemporaryDirectory(prefix='cpa-official-test-') as tmp:
        temp = Path(tmp)
        output = args.output.resolve() if args.output else temp / 'output'
        output.mkdir(parents=True, exist_ok=True)
        library = temp / 'cpa-updater.so'
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC',
                        '-shared', str(args.source.resolve() / 'cpa-updater.c'),
                        '-o', str(library)], check=True)
        isolation = ['--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts'] if os.geteuid() == 0 else ['--unshare-all']
        cmd = ['bwrap', *isolation, '--die-with-parent', '--ro-bind', '/usr', '/usr',
               '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/sbin', '/sbin',
               '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/var',
               '--tmpfs', '/run', '--tmpfs', '/etc', '--tmpfs', '/app',
               '--ro-bind', str(args.binary.resolve()), '/official',
               '--ro-bind', str(library), '/library.so',
               '--ro-bind', str(Path(__file__).resolve()), '/test.py',
               '--bind', str(output), '/output', '--uid', '0', '--gid', '0',
               '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/app',
               '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', '/usr/bin/python3', '/test.py', '--inside']
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=90)
        print(result.stdout, end='')
        if result.returncode:
            log = output / 'official-server.log'
            if log.exists():
                print(log.read_text())
            raise SystemExit(result.returncode)
        print('Official binary SHA256:', hashlib.sha256(args.binary.read_bytes()).hexdigest())
        if args.output:
            print('Evidence:', output)


if __name__ == '__main__':
    main()
