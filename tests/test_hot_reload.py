#!/usr/bin/env python3
"""Official v8.0.56 hot-reload experiment (Linux/gcc/bwrap, no paid API).

python3 tests/test_hot_reload.py --binary ./cli-proxy-api --binary-sha256 SHA256 --output ./evidence
Exit 0 = feasible with uninterrupted traffic AND restored A; 2 = measured unsupported;
1 = broken baseline, isolation, traffic, rollback or other test failure. Never SKIP/PASS
unsupported. Binary digest must come from an independently verified official archive.
--self-test validates fixture builds and local SSE, NOT official host feasibility.
Fixtures differ ONLY in an HTML marker, not a complete release upgrade.
API/source contract: router-for-me/CLIProxyAPI tag v8.0.56 (585f97deac9aa57c700301221fb1a7085e1827cc),
internal/api/server_management_v8.go, handlers/management/config_v8.go,
internal/pluginhost/config.go, shadow.go and loader_unix.go. No explicit reload
route exists. Versioned files are selected by configs.<id>.store.version; no path field.
"""
import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

KEY = 'isolated-hot-reload-management'
CLIENT = 'isolated-hot-reload-client'
MODEL = 'hot-reload-fixture'
ROOT = '/v8/management/config/plugins'
PANEL = '/v0/resource/plugins/cpa-updater/panel'
MARKERS = {x: 'CPA_HOT_RELOAD_FIXTURE_' + x for x in 'AB'}


def require(value, message):
    if not value:
        raise AssertionError(message)


def identity(pid):
    # comm may contain spaces or parentheses; field 22 starts after final ')'.
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'starttime': fields[19]}


def build(source, dest):
    text = (source / 'cpa-updater.c').read_text()
    needle = '<title>版本更新 · CLIProxyAPI</title>'
    require(text.count(needle) == 1, 'fixture title must be unique')
    for letter, marker in MARKERS.items():
        fixture = dest / (letter + '.c')
        fixture.write_text(text.replace(needle, '<title>' + marker + '</title>'))
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                        '-fPIC', '-shared', '-I', str(source), str(fixture),
                        '-o', str(dest / (letter + '.so'))], check=True, timeout=60)
    require((dest / 'A.so').read_bytes() != (dest / 'B.so').read_bytes(), 'identical fixtures')


class Provider(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            require(self.path == '/v1/chat/completions', 'unexpected provider path')
            require(body.get('stream') is True, 'provider requires streaming')
            self.server.requests += 1
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            # 8 seconds: switching waits for downstream first chunk, not just request creation.
            for i in range(80):
                chunk = {'id': 'fixture', 'object': 'chat.completion.chunk',
                         'created': 1, 'model': MODEL,
                         'choices': [{'index': 0, 'delta': {'content': f'chunk-{i};'},
                                      'finish_reason': None}]}
                self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                self.wfile.flush()
                time.sleep(.1)
            final = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1,
                     'model': MODEL, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
            self.wfile.write(('data: ' + json.dumps(final) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.close_connection = True


def provider():
    server = ThreadingHTTPServer(('127.0.0.1', 18318), Provider)
    server.daemon_threads = True
    server.requests = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def inside():
    output = Path('/output')
    evidence = {'schema': 1, 'status': 'failed', 'feasible': False,
                'fixture_scope': 'same plugin id; HTML-marker-only A/B, not full upgrade',
                'explicit_reload': 'not present in official v8.0.56 routes',
                'requests': [], 'stages': [], 'traffic': {'models': 0, 'streams': 0, 'errors': []}}
    proc = None
    server = None
    stop = threading.Event()
    workers = []
    phase = 'baseline'

    def request(path, method='GET', body=None):
        raw_body = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request('http://127.0.0.1:8317' + path, data=raw_body,
                                     method=method, headers={'Authorization': 'Bearer ' +
                                     (CLIENT if path.startswith('/v1/') else KEY),
                                     'Content-Type': 'application/json'})
        try:
            resp = urllib.request.urlopen(req, timeout=4)
        except urllib.error.HTTPError as error:
            resp = error
        with resp:
            raw = resp.read().decode()
            try:
                data = json.loads(raw)
            except ValueError:
                data = raw
            evidence['requests'].append({'time': time.monotonic(), 'phase': phase,
                                         'method': method, 'path': path, 'status': resp.status,
                                         'body': data, 'etag': resp.headers.get('ETag')})
            return resp.status, data

    def patch(value):
        status, _ = request(ROOT, 'PUT', value)  # raw JSON object, never {value: ...}
        require(status == 200, 'official plugins PUT failed')
        status, actual = request(ROOT)
        require(status == 200 and actual == value, 'configuration readback mismatch')

    def page(expected, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, html = request(PANEL)
            if status == 200 and isinstance(html, str) and MARKERS[expected] in html:
                return True
            time.sleep(.15)
        return False

    def stable():
        require(proc.poll() is None and identity(proc.pid) == evidence['identity_before'],
                'official main PID/starttime changed')

    def snapshot(name):
        stable()
        status, listing = request('/v8/management/plugins')
        require(status == 200, 'plugin listing failed')
        maps = Path(f'/proc/{proc.pid}/maps').read_text()
        evidence['stages'].append({'name': name, 'identity': identity(proc.pid),
                                   'plugins': listing, 'mapped_libraries':
                                   [line for line in maps.splitlines() if '.so' in line and
                                    ('plugin' in line or 'shadow' in line)],
                                   'models_completed': evidence['traffic']['models'],
                                   'streams_completed': evidence['traffic']['streams']})

    def models():
        while not stop.is_set():
            try:
                status, data = request('/v1/models')
                require(status == 200 and MODEL in json.dumps(data), 'models missing fixture')
                evidence['traffic']['models'] += 1
            except Exception as exc:
                evidence['traffic']['errors'].append({'phase': phase, 'kind': 'models', 'error': str(exc)})
            stop.wait(.1)

    def stream(started, finished):
        record = {'phase_started': phase, 'started_at': time.monotonic(), 'chunks': 0}
        try:
            req = urllib.request.Request('http://127.0.0.1:8317/v1/chat/completions',
                data=json.dumps({'model': MODEL, 'messages': [{'role': 'user', 'content': 'probe'}],
                                 'stream': True}).encode(), headers={
                    'Authorization': 'Bearer ' + CLIENT, 'Content-Type': 'application/json'})
            done = False
            pieces = []
            with urllib.request.urlopen(req, timeout=12) as response:
                require(response.status == 200, 'stream status')
                for line in response:
                    if line.startswith(b'data: '):
                        if line.strip() == b'data: [DONE]':
                            done = True
                        else:
                            obj = json.loads(line[6:])
                            if obj.get('choices', [{}])[0].get('delta', {}).get('content'):
                                pieces.append(obj['choices'][0]['delta']['content'])
                                record['chunks'] += 1
                                started.set()
            require(done and ''.join(pieces) == ''.join(f'chunk-{i};' for i in range(80)),
                    'missing, duplicated, reordered or truncated downstream SSE content')
            evidence['traffic']['streams'] += 1
        except Exception as exc:
            evidence['traffic']['errors'].append({'phase': phase, 'kind': 'stream', 'error': str(exc)})
        finally:
            record['finished_at'] = time.monotonic()
            evidence.setdefault('streams', []).append(record)
            finished.set()

    def across(action):
        started, finished = threading.Event(), threading.Event()
        thread = threading.Thread(target=stream, args=(started, finished), daemon=True)
        workers.append(thread)
        thread.start()
        require(started.wait(5), 'real official downstream SSE never began')
        require(not finished.is_set(), 'SSE ended before switching')
        begin = time.monotonic()
        result = action()
        require(not finished.is_set(), 'SSE did not remain open across switching')
        require(finished.wait(12), 'SSE completion timeout')
        require(not evidence['traffic']['errors'], 'traffic errors during switching')
        stable()
        evidence.setdefault('switch_windows', []).append({'phase': phase, 'begin': begin,
                                                         'end': time.monotonic()})
        return result

    try:
        for path in ['/app/plugins', '/app/auths', '/run/cliproxy-updater/inbox',
                     '/var/lib/cliproxy-updater-status']:
            Path(path).mkdir(parents=True)
        target = Path('/app/plugins/cpa-updater-v1.0.1.so')
        shutil.copyfile('/A.so', target)
        server = provider()
        # Legacy input is supported by official v8 migration; API reads/writes use v8 raw JSON.
        Path('/app/config.yaml').write_text('''host: "127.0.0.1"
port: 8317
remote-management:
  allow-remote: false
  secret-key: "isolated-hot-reload-management"
  disable-control-panel: true
auth-dir: "/app/auths"
api-keys: ["isolated-hot-reload-client"]
openai-compatibility:
  - name: "isolated-provider"
    base-url: "http://127.0.0.1:18318/v1"
    api-key-entries:
      - api-key: "dummy-not-paid"
    models:
      - name: "hot-reload-fixture"
        alias: "hot-reload-fixture"
plugins:
  enabled: true
  dir: "/app/plugins"
  configs:
    cpa-updater:
      enabled: true
      priority: 1
      store:
        version: "1.0.1"
''')
        with (output / 'official-server.log').open('w') as log:
            proc = subprocess.Popen(['/official', '--config', '/app/config.yaml', '--local-model'],
                                    cwd='/app', stdout=log, stderr=subprocess.STDOUT)
        evidence['identity_before'] = identity(proc.pid)
        for _ in range(120):
            require(proc.poll() is None, 'official process exited at startup')
            try:
                if request(ROOT)[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(.1)
        else:
            raise AssertionError('official startup timeout')
        require(page('A'), 'baseline A page missing')
        status, original = request(ROOT)
        require(status == 200 and original['configs']['cpa-updater']['enabled'], 'baseline config')
        snapshot('baseline-A')
        workers.append(threading.Thread(target=models, daemon=True))
        workers[-1].start()
        # Establish complete real proxy stream before interpreting unsupported results.
        across(lambda: time.sleep(.2))
        phase = 'same-path-atomic-swap'
        def samepath():
            shutil.copyfile('/B.so', target.with_suffix('.new'))
            os.replace(target.with_suffix('.new'), target)
            patch(copy.deepcopy(original))
            return page('B', 2)
        same = across(samepath)
        evidence['same_path_new_marker'] = same
        snapshot(phase)
        phase = 'unique-version-path'
        changed = copy.deepcopy(original)
        changed['configs']['cpa-updater']['store']['version'] = '1.0.2'
        shutil.copyfile('/B.so', '/app/plugins/cpa-updater-v1.0.2.so')
        unique = across(lambda: (patch(changed), page('B', 3))[1])
        evidence['unique_path_new_marker'] = unique
        snapshot(phase)
        if unique:
            loaded = json.dumps(evidence['stages'][-1]['plugins'])
            require('cpa-updater-v1.0.2.so' in loaded, 'new library path not reported loaded')
        # Bad new library: probe rejection, then explicitly restore config AND old inode.
        phase = 'bad-version-and-recovery'
        bad = copy.deepcopy(original)
        bad['configs']['cpa-updater']['store']['version'] = '1.0.3'
        Path('/app/plugins/cpa-updater-v1.0.3.so').write_bytes(b'not-an-ELF-fixture\n')
        def recover():
            patch(bad)
            time.sleep(.4)
            snapshot('bad-library-observation')
            shutil.copyfile('/A.so', target.with_suffix('.new'))
            os.replace(target.with_suffix('.new'), target)
            patch(original)
            return page('A', 3)
        restored = across(recover)
        require(restored, 'A page not restored after bad library/config rollback')
        require(request(ROOT)[1] == original, 'rollback config differs')
        snapshot('restored-A')
        require(evidence['traffic']['models'] >= 10 and server.requests >= 4,
                'insufficient real traffic/provider requests')
        evidence['provider_requests'] = server.requests
        evidence['identity_after'] = identity(proc.pid)
        evidence['restored_A'] = True
        evidence['feasible'] = bool(unique or same)
        evidence['status'] = 'feasible' if evidence['feasible'] else 'unsupported'
        return 0 if evidence['feasible'] else 2
    except Exception as exc:
        evidence['error'] = str(exc)
        return 1
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=1)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if server is not None:
            server.shutdown()
            server.server_close()
        (output / 'hot-reload.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        print(json.dumps({'status': evidence['status'], 'feasible': evidence['feasible'],
                          'traffic': evidence['traffic'], 'error': evidence.get('error')}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--binary-sha256')
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.inside:
        return inside()
    if not args.self_test:
        require(args.binary and args.binary.is_file(), '--binary required')
        require(args.binary_sha256 and len(args.binary_sha256) == 64 and
                all(c in '0123456789abcdef' for c in args.binary_sha256), 'lowercase SHA256 required')
        require(hashlib.sha256(args.binary.read_bytes()).hexdigest() == args.binary_sha256,
                'official binary SHA256 mismatch')
        require(args.output is not None, '--output required to retain evidence')
        require(shutil.which('bwrap'), 'bwrap required; refusing host fallback')
    require(shutil.which('gcc'), 'gcc required')
    with tempfile.TemporaryDirectory(prefix='cpa-hot-reload-') as tmp:
        temp = Path(tmp)
        build(args.source.resolve(), temp)
        if args.self_test:
            server = provider()
            try:
                req = urllib.request.Request('http://127.0.0.1:18318/v1/chat/completions',
                    data=b'{"stream":true}', headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=12) as response:
                    data = response.read()
                require(data.count(b'"chat.completion.chunk"') == 81 and b'data: [DONE]' in data,
                        'provider SSE fixture failed')
                require(identity(os.getpid())['pid'] == os.getpid(), 'PID parser failed')
                print('SELF-TEST: two distinct ELF fixtures built; local provider 80 SSE chunks + DONE; PID parser OK. Not official feasibility evidence.')
                return 0
            finally:
                server.shutdown()
                server.server_close()
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        require(not (output / 'hot-reload.json').exists(),
                'output already contains evidence; use a fresh directory to avoid stale results')
        isolation = ['--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts'] if os.geteuid() == 0 else ['--unshare-all']
        cmd = ['bwrap', *isolation, '--die-with-parent', '--ro-bind', '/usr', '/usr',
               '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/sbin', '/sbin',
               '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/var',
               '--tmpfs', '/run', '--tmpfs', '/etc', '--tmpfs', '/app',
               '--ro-bind', str(args.binary.resolve()), '/official',
               '--ro-bind', str(temp / 'A.so'), '/A.so', '--ro-bind', str(temp / 'B.so'), '/B.so',
               '--ro-bind', str(Path(__file__).resolve()), '/test.py', '--bind', str(output), '/output',
               '--uid', '0', '--gid', '0', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
               '--setenv', 'HOME', '/app', '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
               '/usr/bin/python3', '/test.py', '--inside']
        (output / 'binary.json').write_text(json.dumps({'sha256': args.binary_sha256,
            'official_tag': 'v8.0.56', 'fixture_sha256': {
                x: hashlib.sha256((temp / (x + '.so')).read_bytes()).hexdigest() for x in 'AB'}}, indent=2))
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=110)
            print(result.stdout, end='')
            code = result.returncode
        except subprocess.TimeoutExpired as exc:
            (output / 'isolation.log').write_text(str(exc))
            code = 1
        else:
            (output / 'isolation.log').write_text(result.stdout)
        if not (output / 'hot-reload.json').exists():
            (output / 'hot-reload.json').write_text(json.dumps({'schema': 1, 'status': 'failed',
                'feasible': False, 'error': 'isolation failed or timed out; see isolation.log'}))
            code = 1
        print('Evidence:', output)
        return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('FAIL:', error, file=sys.stderr)
        sys.exit(1)
