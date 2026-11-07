#!/usr/bin/env python3
"""Old -> new installer rehearsal in the existing disposable bwrap sandbox.

Service control, tmpfiles and management HTTP are fixtures, NOT real systemd/API.
Both installers and their source trees are mounted read-only and run unchanged.
Run with CPA_TEST_REAL_UID=1 on a host permitting privileged bubblewrap.
"""
import argparse
import ast
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

# Each probe runs in a NEW interpreter: no cached dlopen handle after replacement.
ABI_PROBE = r'''
import base64, ctypes as c, hashlib, json, sys
from pathlib import Path
class Buf(c.Structure):
    _fields_ = [('ptr', c.c_void_p), ('len', c.c_size_t)]
CALL = c.CFUNCTYPE(c.c_int, c.c_char_p, c.c_void_p, c.c_size_t, c.POINTER(Buf))
FREE = c.CFUNCTYPE(None, c.c_void_p, c.c_size_t)
SHUT = c.CFUNCTYPE(None)
class Plugin(c.Structure):
    _fields_ = [('abi_version', c.c_uint32), ('call', CALL), ('free_buffer', FREE), ('shutdown', SHUT)]
lib = c.CDLL(sys.argv[1]); p = Plugin()
lib.cliproxy_plugin_init.argtypes = [c.c_void_p, c.POINTER(Plugin)]
assert lib.cliproxy_plugin_init(None, c.byref(p)) == 0
assert p.abi_version == 1
request = json.dumps({'Method':'GET', 'Path':'/v0/resource/plugins/cpa-updater/panel'}).encode()
out = Buf()
assert p.call(b'management.handle', request, len(request), c.byref(out)) == 0
try:
    response = json.loads(c.string_at(out.ptr, out.len))['result']
finally:
    p.free_buffer(out.ptr, out.len)
assert response['StatusCode'] == 200
body = base64.b64decode(response['Body'], validate=True)
assert b'<html' in body.lower() and b'encodeURIComponent(v)' in body
Path(sys.argv[2]).write_bytes(body)
p.shutdown()
print('ABI panel sha256', hashlib.sha256(body).hexdigest(), flush=True)
'''

REHEARSAL = r'''
    # This block replaces only the harness scenarios, never installer code.
    old_source = Path('/rehearsal-old')
    new_source = Path('/rehearsal-new')
    plugin = Path('/opt/cliproxyapi/plugins/cpa-updater.so')
    config_file = Path('/opt/cliproxyapi/config.yaml')
    config_file.write_bytes(b'# rehearsal non-secret fixture\nport: 8317\n')
    oauth = Path('/opt/cliproxyapi/auths/oauth-fixture.json')
    oauth.write_text('{"provider":"fixture","token":"not-a-real-token"}\n')
    oauth.chmod(0o600)
    os.chown(oauth, uid, uid)
    def snapshot(path):
        st = path.stat()
        return path.read_bytes(), st.st_uid, st.st_gid, st.st_mode & 0o777
    preserved = {p: snapshot(p) for p in [config_file, oauth]}
    def check_preserved():
        for path, expected in preserved.items():
            assert snapshot(path) == expected, ('fixture changed', str(path))
    def panel(label):
        target = Path('/run') / (label + '.html')
        subprocess.run(['/usr/bin/python3', '-I', '-c', ABI_PROBE, str(plugin), str(target)], check=True, timeout=20)
        return target.read_bytes()
    def backups():
        return set(Path('/var/lib/cliproxy-updater').glob('install-*'))
    config['configs']['unrelated-fixture'] = {'enabled': False, 'priority': 73, 'opaque': 'preserve-me'}
    ROOT = old_source
    invoke('install.sh')
    old_bytes = plugin.read_bytes()
    old_panel = panel('old')
    check_preserved()
    assert old_bytes.startswith(b'\x7fELF')
    # Independently build the unchanged new source with installer flags.
    expected = Path('/run/expected-new.so')
    subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC', '-shared',
                    str(new_source / 'cpa-updater.c'), '-o', str(expected)], check=True, timeout=90)
    new_bytes = expected.read_bytes()
    assert new_bytes != old_bytes, 'sources do not produce different plugin bytes'
    if scenario == 'rollback':
        # Force an API config change so restoration is not a no-op.
        config['configs']['cpa-updater']['enabled'] = False
        states = json.loads(ctl.read_text())
        states['fail_trigger'] = True
        ctl.write_text(json.dumps(states))
    before_config = json.loads(json.dumps(config))
    before_backups = backups()
    before_states = json.loads(ctl.read_text())
    ROOT = new_source
    invoke('install.sh', scenario != 'rollback')
    added = backups() - before_backups
    assert len(added) == 1, added
    backup = added.pop()
    manifest = json.loads((backup / 'manifest.json').read_text())
    assert (backup / str(manifest[str(plugin)])).read_bytes() == old_bytes
    assert (backup / 'config.yaml').read_bytes() == preserved[config_file][0]
    check_preserved()
    if scenario == 'rollback':
        # Failure fixture captures bytes at trigger activation AFTER plugin swap.
        assert Path('/run/attempt.so').read_bytes() == new_bytes
        assert not json.loads(ctl.read_text())['fail_trigger'], 'failure was not injected'
        assert plugin.read_bytes() == old_bytes, 'old plugin not restored'
        assert panel('restored') == old_panel
        assert config == before_config, 'API config not restored'
        restored = json.loads(ctl.read_text())
        for unit in ['cliproxy-updater.path', 'cliproxy-updater-check.timer', 'cliproxy-updater-recover.service']:
            assert restored[unit] == before_states[unit], unit
    else:
        assert plugin.read_bytes() == new_bytes
        assert panel('new') != old_panel, 'new panel not actually installed'
        assert config == before_config, 'unrelated API configuration changed'
    print('plugin sha256 old/new', hashlib.sha256(old_bytes).hexdigest(), hashlib.sha256(new_bytes).hexdigest(), flush=True)
'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('harness interface drift: ' + repr(old[:100]))
    return text.replace(old, new, 1)


def derived_harness(old_source, new_source):
    """Extend the checked-in fixture with fail-closed unique source anchors."""
    text = (ROOT / 'tests/install_sandbox.py').read_text()
    text = replace_once(text, 'import fcntl\n', 'import fcntl\nimport hashlib\nABI_PROBE = ' + repr(ABI_PROBE) + '\n')
    text = replace_once(text, 'def inside(scenario):\n', 'def inside(scenario):\n    global ROOT\n')
    start = '    libexec = Path(\'/usr/local/libexec\')\n'
    end = '    server.shutdown()\n'
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError('harness scenario anchors drifted')
    a, b = text.index(start), text.index(end)
    if a >= b:
        raise RuntimeError('harness anchors out of order')
    text = text[:a] + REHEARSAL + text[b:]
    text = replace_once(text,
        "  s['fail_trigger']=False; p.write_text(json.dumps(s)); sys.exit(1)",
        "  Path('/run/attempt.so').write_bytes(Path('/opt/cliproxyapi/plugins/cpa-updater.so').read_bytes())\n  s['fail_trigger']=False; p.write_text(json.dumps(s)); sys.exit(1)")
    text = replace_once(text, '    return subprocess.run(command,capture_output=True,text=True,timeout=180)',
        "    boundary = command.index('--')\n"
        "    command[boundary:boundary] = ['--ro-bind', " + repr(str(old_source)) + ", '/rehearsal-old', '--ro-bind', " + repr(str(new_source)) + ", '/rehearsal-new']\n"
        "    return subprocess.run(command,capture_output=True,text=True,timeout=360)")
    # Derived file lives directly in a temporary child directory of project root.
    ast.parse(text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-source', type=Path, required=True)
    parser.add_argument('--new-source', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true', help='validate harness without invoking bwrap or installers')
    args = parser.parse_args()
    old, new = args.old_source.resolve(), args.new_source.resolve()
    for source in [old, new]:
        for name in ['install.sh', 'install_helper.py', 'cpa-updater.c', 'updater_runtime.py', 'cliproxy-updater-worker']:
            if not (source / name).is_file():
                parser.error('missing source file: ' + str(source / name))
    if old == new:
        parser.error('old and new source directories must differ')
    text = derived_harness(old, new)
    compile(ABI_PROBE, '<abi-probe>', 'exec')
    if args.check_only:
        print('PASS harness syntax, source prerequisites and unique extension anchors; no installer executed')
        return 0
    # Keeping this under ROOT makes the derived harness visible through the
    # original read-only ROOT bind. No host production paths are ever written.
    with tempfile.TemporaryDirectory(prefix='.upgrade-rehearsal-', dir=ROOT) as directory:
        # sudo/bwrap may map root without host DAC override capabilities.
        Path(directory).chmod(0o755)
        harness = Path(directory) / 'install_sandbox.py'
        harness.write_text(text)
        harness.chmod(0o644)
        for scenario in ['upgrade', 'rollback']:
            result = subprocess.run([sys.executable, str(harness), scenario], text=True, capture_output=True, timeout=390)
            print(result.stdout, end='', flush=True)
            print(result.stderr, end='', file=sys.stderr, flush=True)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
