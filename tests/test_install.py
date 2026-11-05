"""Installer tests: local fixtures only; never invoke host installation."""
import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock
import contextlib
import io
import fcntl
import os

ROOT = pathlib.Path(__file__).resolve().parents[1]

def load():
    spec = importlib.util.spec_from_file_location('installer', ROOT / 'install_helper.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class InstallTests(unittest.TestCase):
    def test_isolated_entrypoints(self):
        from install_sandbox import run
        for scenario in ['preflight-missing', 'success', 'api', 'registered', 'trigger', 'identity', 'lock', 'worker-only']:
            with self.subTest(scenario=scenario):
                result = run(scenario)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_health_retries_transient_failure(self):
        m = load()
        api = mock.Mock()
        api.request.side_effect = [ConnectionError(), {'plugins': []}]
        with mock.patch.object(m, 'query', return_value=True), mock.patch.object(m.time, 'sleep'):
            m.health(api, None, budget=1)
        self.assertEqual(api.request.call_count, 2)

    def test_command_has_timeout(self):
        m = load()
        with mock.patch.object(m.subprocess, 'run') as run:
            m.command('test')
            self.assertEqual(run.call_args.kwargs['timeout'], 45)

    def test_config_permission_boundary(self):
        import stat
        from types import SimpleNamespace
        m = load()
        with mock.patch.object(m, 'safe_path'), mock.patch.object(m.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)), mock.patch.object(m.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=1000)):
            for uid, gid, mode, allowed in [(1000,1000,0o600,True),(0,1000,0o660,True),(0,0,0o600,False),(0,1000,0o640,False),(1000,1000,0o666,False),(1000,2000,0o660,False)]:
                with self.subTest(uid=uid,gid=gid,mode=oct(mode)):
                    path=mock.Mock()
                    path.parent=pathlib.Path('/trusted')
                    path.lstat.return_value=SimpleNamespace(st_mode=stat.S_IFREG|mode,st_nlink=1,st_uid=uid,st_gid=gid)
                    if allowed: m.validate_config_permissions(path)
                    else:
                        with self.assertRaises(RuntimeError): m.validate_config_permissions(path)

    def test_plugins_directory_traversable(self):
        m = load()
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'plugins'
            p.mkdir(mode=0o700)
            user=mock.Mock(pw_uid=p.stat().st_uid)
            with mock.patch.object(m, 'safe_path'), mock.patch.object(m.pwd, 'getpwnam', return_value=user), mock.patch.object(m.grp, 'getgrnam', return_value=mock.Mock(gr_gid=p.stat().st_gid)):
                m.plugin_directory(p)
            self.assertEqual(p.stat().st_mode & 0o777, 0o700)

    def test_unregistered_rejected(self):
        m = load()
        for plugins in [[], [{'id': 'cpa-updater', 'registered': False, 'effective_enabled': True}]]:
            with self.assertRaises(RuntimeError):
                m.validate_registered({'plugins': plugins})

    def test_other_plugins_not_silently_activated(self):
        m = load()
        with self.assertRaises(RuntimeError):
            m.plan_config({'enabled': False, 'configs': {'other': {'enabled': True}}}, True)
        original = {'enabled': True, 'configs': {'other': {'enabled': True}, 'cpa-updater': {'priority': 9, 'custom': 'kept'}}}
        target = m.plan_config(original, True)
        self.assertEqual(target['configs']['other'], original['configs']['other'])
        self.assertEqual(target['configs']['cpa-updater']['custom'], 'kept')
        self.assertNotIn('enabled', original['configs']['cpa-updater'])

    def test_transactions_and_processing_refused_without_deletion(self):
        m = load()
        with tempfile.TemporaryDirectory() as d:
            m.STATE = m.RUN = pathlib.Path(d)
            for name in ['transaction.json', 'processing']:
                p = pathlib.Path(d) / name
                p.write_text('preserve')
                with mock.patch.object(m, 'query', return_value=False), self.assertRaises(RuntimeError):
                    m.idle()
                self.assertEqual(p.read_text(), 'preserve')
                p.unlink()

    def test_units_recovery_not_recursive(self):
        data = load().units()
        self.assertIn('OnFailure=cliproxy-updater-recover.service', data['cliproxy-updater.service'])
        recover = data['cliproxy-updater-recover.service']
        self.assertIn('--recover', recover)
        self.assertIn('WantedBy=multi-user.target', recover)
        self.assertNotIn('OnFailure=', recover)

    def scenario(self, failure):
        m = load()
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            m.APP = root / 'app'; m.APP.mkdir()
            (m.APP / 'config.yaml').write_text('fixture-config')
            m.STATE = root / 'state'; m.STATE.mkdir(mode=0o700)
            m.RUN = root / 'run'; m.RUN.mkdir()
            m.SYSTEM = root / 'system'; m.SYSTEM.mkdir()
            m.WORKER = root / 'worker'
            m.RUNTIME = root / 'runtime.py'
            m.PUBLIC = root / 'public'; m.PUBLIC.mkdir()
            m.TMPFILE = root / 'tmpfiles.conf'
            original = {'enabled': True, 'configs': {'cpa-updater': {'enabled': True, 'priority': 4}}}
            class FixtureAPI:
                def __init__(self): self.value = m.copy.deepcopy(original)
                def config(self):
                    if failure == 'restart' and calls.count(('restart', 'cliproxyapi.service')) == 1:
                        raise RuntimeError('fixture API offline after failed restart')
                    return m.copy.deepcopy(self.value)
                def request(self, path, **kwargs):
                    return {'plugins_dir': str(m.APP / 'plugins'), 'plugins': []}
                def put(self, field, value):
                    if failure == 'config' and value.get('enabled') is False if isinstance(value, dict) else False:
                        raise RuntimeError('fixture config failure')
                    if field == 'enabled': self.value['enabled'] = value
                    else: self.value['configs']['cpa-updater'] = value
            api = FixtureAPI()
            calls = []
            def ctl(*args):
                calls.append(args)
                if failure == 'restart' and args == ('restart', 'cliproxyapi.service') and calls.count(args) == 1:
                    raise RuntimeError('fixture first restart failure')
                return ''
            lock = None
            if failure == 'lock':
                lock = open(m.STATE / 'lock', 'w')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def health(api, installed):
                if failure == 'health' and installed is False:
                    raise RuntimeError('fixture health failure')
            with contextlib.ExitStack() as stack:
                for name, value in [('plugin_directory', lambda *a: None), ('plugin_io', lambda *a: None), ('ensure_directory', lambda *a: None), ('validate_service', lambda: None), ('safe_path', lambda *a: None), ('API', lambda: api), ('ctl', ctl), ('query', lambda *a: False), ('health', health)]:
                    stack.enter_context(mock.patch.object(m, name, value))
                real_fstat = os.fstat
                def fixture_stat(fd):
                    st = real_fstat(fd)
                    values = list(st)
                    values[4] = 0
                    return os.stat_result(values)
                stack.enter_context(mock.patch.object(m.os, 'fstat', fixture_stat))
                stack.enter_context(mock.patch.object(m.os, 'geteuid', return_value=0))
                stack.enter_context(mock.patch.object(m.os, 'chown'))
                stack.enter_context(mock.patch.object(m.grp, 'getgrnam', return_value=mock.Mock(gr_gid=os.getgid())))
                stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                with self.assertRaises((RuntimeError, BlockingIOError)):
                    m.run(False)
            if lock: lock.close()
            self.assertEqual(api.value, original)
            self.assertEqual((m.APP / 'config.yaml').read_text(), 'fixture-config')
            if failure == 'lock':
                self.assertEqual(calls, [])
            else:
                self.assertIn(('disable', m.TRIGGERS[0]), calls)
            return calls

    def test_config_failure_aborts_restores(self):
        self.scenario('config')

    def test_health_failure_aborts_restores(self):
        self.scenario('health')

    def test_restart_failure_recovers_when_api_offline(self):
        calls = self.scenario('restart')
        self.assertGreaterEqual(calls.count(('restart', 'cliproxyapi.service')), 2)
        self.assertGreaterEqual(calls.count(('daemon-reload',)), 2)

    def test_shared_flock_race_aborts_before_config(self):
        calls = self.scenario('lock')
        self.assertNotIn(('restart', 'cliproxyapi.service'), calls)

if __name__ == '__main__': unittest.main()
