"""Conservative hot ownership retention; real files, no production access."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('cleanup_installer', Path(__file__).parents[1] / 'install_helper.py')
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CleanupTests(unittest.TestCase):
    def test_owned_manifest_is_private_and_unknown_files_are_not_adopted(self):
        with tempfile.TemporaryDirectory() as root, patch.object(m, 'safe_path'):
            with patch.object(m, 'STATE', Path(root)):
                self.assertEqual(m.hot_owned_read(), {'protocol': 1, 'owned': {}, 'current': None, 'previous': None})
                m.hot_owned_write(m.hot_owned_read())
                path = Path(root) / 'hot-owned.json'
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                path.chmod(0o644)
                with self.assertRaises(RuntimeError): m.hot_owned_read()

    def exercise_cleanup(self, block=None, same=False, write_fail=False, changed=False):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            root = Path(root); app = root / 'app'; app.mkdir(); plugins = app / 'plugins'; plugins.mkdir()
            state = root / 'state'; state.mkdir(); run = root / 'run'; run.mkdir()
            paths = []
            for data in (b'oldest', b'previous', b'current', b'unknown'):
                path = plugins / m.hot_name(data)[1]; path.write_bytes(data); paths.append(path)
            oldest, previous, current, unknown = paths
            value = {'protocol': 1, 'owned': {p.name: m.hashlib.sha256(p.read_bytes()).hexdigest() for p in paths[:3]}, 'current': str(current), 'previous': str(previous)}
            config = {'enabled': True, 'configs': {'cpa-updater': {'enabled': True, 'store': {'version': m.hot_name(b'current')[0]}}}}
            if block == 'reference': config['configs']['cpa-updater']['store']['version'] = m.hot_name(b'oldest')[0]
            if block == 'unknown': config['configs']['cpa-updater']['mystery'] = 'keep'
            class API:
                def conditional(self, path): return config, 'tag'
                def request(self, path, **kw):
                    if path == '/v8/management/config': return {'plugins': config}
                    return {'plugins_dir': str(plugins), 'plugins': [{'id': 'cpa-updater', 'path': str(current), 'registered': True, 'effective_enabled': True}]}
            for name, replacement in [('APP', app), ('STATE', state), ('RUN', run), ('safe_path', lambda *args: None), ('plugin_directory', lambda *args: None), ('hot_identity', lambda: ('changed' if block == 'identity' else 'pid', 'start'))]:
                stack.enter_context(patch.object(m, name, replacement))
            user = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
            stack.enter_context(patch.object(m.pwd, 'getpwnam', return_value=user))
            stack.enter_context(patch.object(m.os, 'getgrouplist', return_value=[]))
            real_fstat = os.fstat
            def root_stat(fd):
                fields = list(real_fstat(fd)); fields[4] = 0
                return os.stat_result(fields)
            stack.enter_context(patch.object(m.os, 'fstat', side_effect=root_stat))
            m.hot_owned_write(value)
            if changed: oldest.write_bytes(b'replaced')
            if block in ('transaction.json', 'hot-transaction.json'): (state / block).write_text('{}')
            if write_fail: stack.enter_context(patch.object(m, 'hot_owned_write', side_effect=OSError('disk full')))
            api = API()
            m.hot_cleanup(api, current, current if same else previous, ('pid', 'start'), config, 'tag', m.hot_scope(api))
            self.assertTrue(current.exists()); self.assertTrue(previous.exists()); self.assertTrue(unknown.exists())
            self.assertEqual(oldest.exists(), bool(block or changed or write_fail))
            if not write_fail:
                self.assertEqual(m.hot_owned_read()['previous'], str(previous))

    def test_retains_current_previous_and_unknown(self): self.exercise_cleanup()
    def test_same_target_preserves_previous(self): self.exercise_cleanup(same=True)
    def test_active_transactions_skip_all_deletion(self):
        for block in ('transaction.json', 'hot-transaction.json'):
            with self.subTest(block=block): self.exercise_cleanup(block=block)
    def test_identity_change_skips_cleanup(self): self.exercise_cleanup(block='identity')
    def test_config_reference_protects_oldest(self): self.exercise_cleanup(block='reference')
    def test_unknown_config_skips_cleanup(self): self.exercise_cleanup(block='unknown')
    def test_write_failure_warns_without_deletion(self): self.exercise_cleanup(write_fail=True)
    def test_replaced_owned_file_is_not_deleted(self): self.exercise_cleanup(changed=True)

    def test_checked_unlink_real_files_rejects_changed_and_linked_candidates(self):
        user = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
        with tempfile.TemporaryDirectory() as root, patch.object(m, 'plugin_directory'), patch.object(m.pwd, 'getpwnam', return_value=user), patch.object(m.os, 'getgrouplist', return_value=[]):
            target = Path(root) / m.hot_name(b'owned')[1]
            target.write_bytes(b'changed')
            digest = m.hashlib.sha256(b'owned').hexdigest().encode()
            with self.assertRaises(RuntimeError): m.plugin_io(target, 'prune', digest)
            target.write_bytes(b'owned')
            link = target.with_name('keep'); os.link(target, link)
            with self.assertRaises(RuntimeError): m.plugin_io(target, 'prune', digest)
            link.unlink()
            m.plugin_io(target, 'prune', digest)
            self.assertFalse(target.exists())


if __name__ == '__main__': unittest.main()
