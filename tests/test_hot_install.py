"""Hot install safety contracts (no service or privileged filesystem access)."""
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
import copy
import os
from contextlib import ExitStack
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('hot_installer', Path(__file__).parents[1] / 'install_helper.py')
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class HotInstallTests(unittest.TestCase):
    def test_hot_name_is_numeric_content_addressed(self):
        version, name = m.hot_name(b'library')
        self.assertRegex(version, r'^0\.0\.1(?:\.\d+){8}$')
        self.assertEqual(name, 'cpa-updater-v' + version + '.so')
        self.assertNotEqual(m.hot_name(b'other'), (version, name))

    def test_real_api_etag_header_and_payload(self):
        import io
        from types import SimpleNamespace
        api = m.API.__new__(m.API); api.key = 'test'
        response = io.BytesIO(b'{}'); response.headers = {'ETag': '"' + 'a' * 64 + '"'}
        from unittest.mock import Mock
        api.opener = SimpleNamespace(open=Mock(return_value=response))
        _, tag = api.conditional('/v8/management/config/plugins/configs/cpa-updater', {'enabled': True}, '"old"')
        request = api.opener.open.call_args.args[0]
        self.assertEqual(request.get_header('If-match'), '"old"')
        self.assertEqual(request.method, 'PUT')
        self.assertEqual(json.loads(request.data), {'enabled': True})
        self.assertEqual(tag, '"' + 'a' * 64 + '"')

    def test_quarantine_real_io_is_idempotent_and_refuses_changed_files(self):
        from types import SimpleNamespace
        user = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
        with tempfile.TemporaryDirectory() as directory, patch.object(m, 'plugin_directory'), \
                patch.object(m.pwd, 'getpwnam', return_value=user), \
                patch.object(m.os, 'getgrouplist', return_value=[]):
            target = Path(directory) / m.hot_name(b'new')[1]
            target.write_bytes(b'new')
            payload = json.dumps([target.name + '.' + 'a' * 24 + '.rollback-backup', m.hashlib.sha256(b'new').hexdigest()]).encode()
            m.plugin_io(target, 'quarantine', payload)
            backup = target.with_name(target.name + '.' + 'a' * 24 + '.rollback-backup')
            self.assertFalse(target.exists())
            self.assertEqual(backup.read_bytes(), b'new')
            m.plugin_io(target, 'quarantine', payload)
            target.write_bytes(b'concurrent')
            with self.assertRaises(RuntimeError): m.plugin_io(target, 'quarantine', payload)
            self.assertEqual(target.read_bytes(), b'concurrent')
            target.unlink()
            target.symlink_to(backup)
            with self.assertRaises(RuntimeError): m.plugin_io(target, 'quarantine', payload)
            self.assertEqual(backup.read_bytes(), b'new')

    def test_pending_is_compatible_deferred_work(self):
        m.hot_status({'protocol': 1, 'state': 'idle', 'pending': True})

    def exercise(self, fail=False, concurrent=False, lost=False, crash=False, selected=False, preexisting=False, publish_fail=False, quarantine_crash=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            app = root / 'app'; app.mkdir(); (app / 'plugins').mkdir()
            state = root / 'state'; state.mkdir(); (state / 'lock').touch(mode=0o600)
            public = root / 'public'; public.mkdir()
            (public / 'status.json').write_text(json.dumps({'protocol': 1, 'state': 'idle'}))
            run = root / 'run'; run.mkdir(); (run / 'inbox').mkdir()
            queued = run / 'inbox/request'; queued.write_bytes(b'keep request')
            old = app / 'plugins/cpa-updater.so'; old.write_bytes(b'old')
            before = {'enabled': True, 'configs': {'other': {'enabled': True},
                      'cpa-updater': {'enabled': True, 'priority': 17, 'store': {'repository': 'keep'}}}}
            if selected: before['configs']['cpa-updater']['store']['version'] = '7.0.0'
            target = app / 'plugins' / m.hot_name(b'new')[1]
            if preexisting: target.write_bytes(b'new')
            class Fake:
                def __init__(self):
                    self.config = copy.deepcopy(before); self.tag = 'original'; self.writes = []
                def conditional(self, path, value=None, etag=None):
                    if etag is None: return copy.deepcopy(self.config), self.tag
                    if etag != self.tag: raise RuntimeError('CAS conflict')
                    self.writes.append((copy.deepcopy(value), etag))
                    self.config['configs']['cpa-updater'] = copy.deepcopy(value)
                    self.tag = 'written' if len(self.writes) == 1 else 'restored'
                    if len(self.writes) == 1 and lost: raise RuntimeError('response lost')
                    return None, self.tag
                def request(self, path, **kwargs):
                    if path == '/v8/management/config': return {'plugins': copy.deepcopy(self.config), 'port': 9999 if concurrent == 'whole' and len(self.writes) else 8317}
                    if path.endswith('/status'): return {'protocol': 1, 'state': 'idle', 'pending': True}
                    return {'plugins_dir': str(app / 'plugins'), 'plugins': [
                        {'id': 'cpa-updater', 'path': str(old), 'registered': True, 'effective_enabled': True}]}
            api = Fake()
            for name, value in [('APP', app), ('STATE', state), ('PUBLIC', public), ('RUN', run)]:
                stack.enter_context(patch.object(m, name, value))
            for name in ['validate_service', 'safe_path']:
                stack.enter_context(patch.object(m, name))
            stack.enter_context(patch.object(m.os, 'geteuid', return_value=0))
            real_fstat = os.fstat
            def root_stat(fd):
                values = list(real_fstat(fd)); values[4] = 0
                return os.stat_result(values)
            stack.enter_context(patch.object(m.os, 'fstat', side_effect=root_stat))
            stack.enter_context(patch.object(m, 'API', return_value=api))
            stack.enter_context(patch.object(m, 'hot_identity', return_value=('10', '20')))
            stack.enter_context(patch.object(m, 'hot_panel', side_effect=lambda path: path.read_bytes()))
            def compile(*args): Path(args[-1]).write_bytes(b'new')
            stack.enter_context(patch.object(m, 'command', side_effect=compile))
            def io(path, action, data=None):
                if action == 'read': return path.read_bytes() if path.exists() else None
                if action == 'quarantine':
                    destination, digest = json.loads(data)
                    backup = path.with_name(destination)
                    if path.exists():
                        self.assertEqual(m.hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                        path.rename(backup)
                        if quarantine_crash: raise SystemExit('crash after quarantine')
                    return
                self.assertEqual(action, 'create')
                self.assertTrue((state / 'hot-transaction.json').exists(), 'candidate published before recovery record')
                if publish_fail: raise RuntimeError('publish failed')
                with path.open('xb') as stream: stream.write(data)
            stack.enter_context(patch.object(m, 'plugin_io', side_effect=io))
            def verify(api, path, panel, identity):
                self.assertEqual(queued.read_bytes(), b'keep request')
                if path == old and (fail or lost) and not concurrent and not selected and api.writes:
                    self.assertEqual(list((app / 'plugins').glob('cpa-updater-v*.so')), [],
                                     'legacy discovery still selects the new candidate')
                    self.assertEqual(len(list((app / 'plugins').glob('*.rollback-backup'))), 1)
                if path != old and fail:
                    if concurrent:
                        api.tag = 'concurrent'
                        if concurrent != 'whole': api.config['configs']['other']['priority'] = 99
                    raise RuntimeError('verification failed')
            stack.enter_context(patch.object(m, 'hot_verify', side_effect=verify))
            ctl = stack.enter_context(patch.object(m, 'ctl'))
            if preexisting or publish_fail or quarantine_crash:
                with self.assertRaises(RuntimeError): m.hot_install()
                if quarantine_crash:
                    self.assertTrue((state / 'hot-transaction.json').exists())
                    m.hot_install()
                self.assertEqual(api.config, before)
                self.assertFalse((state / 'hot-transaction.json').exists())
                self.assertEqual(old.read_bytes(), b'old')
                if preexisting:
                    self.assertEqual(target.read_bytes(), b'new')
                    self.assertEqual(api.writes, [])
                return
            if crash:
                with patch.object(m, 'hot_recover', side_effect=SystemExit('killed')):
                    with self.assertRaises(SystemExit): m.hot_install()
                self.assertTrue((state / 'hot-transaction.json').exists())
                with patch.object(m, 'command') as compiler:
                    m.hot_install()
                    compiler.assert_not_called()
                self.assertEqual(api.config, before)
                self.assertFalse((state / 'hot-transaction.json').exists())
                return
            if fail or lost:
                with self.assertRaises(RuntimeError): m.hot_install()
            else: m.hot_install()
            ctl.assert_not_called()
            self.assertEqual(queued.read_bytes(), b'keep request')
            self.assertEqual(old.read_bytes(), b'old')
            self.assertEqual(api.config['configs']['cpa-updater']['store']['repository'], 'keep')
            if (fail or lost) and not concurrent: self.assertEqual(api.config, before)
            if concurrent and concurrent != 'whole': self.assertEqual(api.config['configs']['other']['priority'], 99)
            self.assertEqual((state / 'hot-transaction.json').exists(), bool(concurrent))
            self.assertEqual(len(api.writes), 2 if (fail or lost) and not concurrent else 1)

    def test_existing_unowned_candidate_refuses_legacy_switch(self):
        self.exercise(preexisting=True)

    def test_publish_failure_recovers_without_candidate(self):
        self.exercise(publish_fail=True)

    def test_crash_after_quarantine_recovery_is_idempotent(self):
        self.exercise(lost=True, quarantine_crash=True)

    def test_version_selected_rollback_retains_candidate(self):
        self.exercise(lost=True, selected=True)

    def test_interrupted_transaction_recovers_on_next_invocation(self):
        self.exercise(lost=True, crash=True)

    def test_lost_put_response_restores_old_selection(self):
        self.exercise(lost=True)

    def test_hot_transaction_preserves_pending_and_defaults(self):
        self.exercise()

    def test_failure_restores_exact_revision_without_restart(self):
        self.exercise(fail=True)

    def test_whole_config_change_blocks_unknown_revision_rollback(self):
        self.exercise(fail=True, concurrent='whole')

    def test_concurrent_change_blocks_rollback(self):
        self.exercise(fail=True, concurrent=True)

    def test_pending_record_blocks_all_non_hot_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'hot-transaction.json').write_text('{}')
            for installing, worker in [(True, False), (True, True), (False, False)]:
                with patch.object(m, 'STATE', state), patch.object(m.os, 'geteuid', return_value=0):
                    with patch.object(m, 'validate_service') as validate:
                        with self.assertRaisesRegex(RuntimeError, 'hot-transaction'):
                            m.run(installing, worker_only=worker)
                        validate.assert_not_called()

    def test_private_record_rejects_symlink_and_public_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            path = state / 'hot-transaction.json'
            with patch.object(m, 'STATE', state), patch.object(m, 'safe_path'):
                path.write_text('最小记录')
                path.chmod(0o644)
                with self.assertRaises(RuntimeError): m.hot_record_read()
                path.unlink()
                path.symlink_to(state / 'missing')
                with self.assertRaises(OSError): m.hot_record_read()

    def test_hot_mode_cannot_uninstall_or_upgrade_worker(self):
        for installing, worker in [(False, False), (True, True)]:
            with self.subTest(installing=installing, worker=worker):
                with patch.object(m, 'validate_service') as validate:
                    with self.assertRaisesRegex(RuntimeError, 'hot-reload'):
                        m.run(installing, worker_only=worker, hot_reload=True)
                    validate.assert_not_called()

    def test_protocol_gate_rejects_busy_or_unknown_workers(self):
        for status in [{}, {'protocol': 2, 'state': 'idle'},
                       {'protocol': 1, 'state': 'updating'},
                       {'protocol': True, 'state': 'idle'}]:
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                m.hot_status(status)
        for state in ['idle', 'ready', 'current', 'success', 'needs_recheck', 'rolled_back']:
            m.hot_status({'protocol': 1, 'state': state, 'pending': False})


if __name__ == '__main__':
    unittest.main()
