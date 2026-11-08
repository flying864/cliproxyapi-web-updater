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

    def exercise_cleanup(self, block=None, same=False, write_fail=False, changed=False, billing=None, billing_config=None, state_case=None):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            root = Path(root); app = root / 'app'; app.mkdir(); plugins = app / 'plugins'; plugins.mkdir()
            state = root / 'state'; state.mkdir(); run = root / 'run'; run.mkdir()
            paths = []
            for data in (b'oldest', b'previous', b'current', b'unknown'):
                path = plugins / m.hot_name(data)[1]; path.write_bytes(data); paths.append(path)
            oldest, previous, current, unknown = paths
            value = {'protocol': 1, 'owned': {p.name: m.hashlib.sha256(p.read_bytes()).hexdigest() for p in paths[:3]}, 'current': str(current), 'previous': str(previous)}
            config = {'enabled': True, 'dir': str(plugins), 'configs': {'cpa-updater': {'enabled': True, 'store': {'version': m.hot_name(b'current')[0]}}}}
            if block == 'reference': config['configs']['cpa-updater']['store']['version'] = m.hot_name(b'oldest')[0]
            if block == 'unknown': config['configs']['cpa-updater']['mystery'] = 'keep'
            if block == 'opaque': config['configs']['cpa-updater']['config'] = {'path': str(oldest)}
            if block in ('version', 'release-tag'):
                store = config['configs']['cpa-updater']['store']
                store['release-tag'] = ' V' + m.hot_name(b'previous')[0] + ' '
                store[block] = ' v' + m.hot_name(b'oldest')[0] + ' '
            billing_path = plugins / 'cpa-key-billing-v1.2.3.so'
            billing_path.write_bytes(b'billing unchanged')
            if billing is not None:
                config['configs']['cpa-key-billing'] = {'enabled': False, 'store': billing}
            if billing_config is not None:
                config['configs']['cpa-key-billing'] = billing_config.copy()
            if state_case:
                mode, suffix = state_case
                reference = oldest
                if suffix:
                    reference = plugins / 'billing.db'
                    Path(str(reference) + suffix).symlink_to(oldest)
                if mode == 'absolute': raw = str(reference)
                elif mode == 'app': raw = str(reference.relative_to(app))
                elif mode == 'plugins': raw = reference.name
                else:
                    alias = app / 'billing-alias'
                    alias.symlink_to(plugins, target_is_directory=True)
                    raw = str(alias / reference.name)
                config['configs']['cpa-key-billing'] = {'enabled': False, 'state_file': raw}
            config_before = json.dumps(config, sort_keys=True)
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
            self.assertEqual(json.dumps(config, sort_keys=True), config_before)
            self.assertEqual(billing_path.read_bytes(), b'billing unchanged')
            self.assertTrue(current.exists()); self.assertTrue(previous.exists()); self.assertTrue(unknown.exists())
            self.assertTrue(oldest.exists())
            if not write_fail:
                self.assertIn(oldest.name, m.hot_owned_read()['owned'])
            if not write_fail:
                self.assertEqual(m.hot_owned_read()['previous'], str(previous))

    def test_billing_top_level_shape_allows_cleanup(self):
        self.exercise_cleanup(billing_config={
            'allow_unpriced_models': True, 'codex_fast_mode_billing': False,
            'debug': False, 'enabled': True, 'priority': 10,
            'state_file': '/var/lib/billing/state.db', 'store': {'version': '1.2.3'},
        })

    def test_billing_state_references_and_sidecar_aliases_preserve_oldest(self):
        for mode in ('absolute', 'app', 'plugins', 'alias'):
            for suffix in ('', '-wal', '-shm'):
                with self.subTest(mode=mode, suffix=suffix):
                    self.exercise_cleanup(block='state', state_case=(mode, suffix))

    def test_invalid_billing_top_level_types_skip_cleanup(self):
        cases = [('allow_unpriced_models', 1), ('codex_fast_mode_billing', 'false'),
                 ('debug', 0), ('enabled', 1), ('priority', True), ('priority', '1'),
                 ('state_file', None), ('store', []), ('unknown', 'secret-value'),
                 ('state_file', '../billing.db'), ('state_file', '/tmp/../billing.db'),
                 ('state_file', '/tmp//billing.db'), ('state_file', ''),
                 ('state_file', ' /tmp/billing.db '),
                 ('state_file', '/tmp/secret\x00.db')]
        import io
        for key, value in cases:
            with self.subTest(key=key, value=value), patch.object(m.sys, 'stderr', new_callable=io.StringIO) as errors:
                self.exercise_cleanup(block='invalid', billing_config={key: value})
                self.assertIn('cpa-key-billing.' + key, errors.getvalue())
                self.assertNotIn('secret-value', errors.getvalue())

    def test_complete_billing_metadata_does_not_block_updater_cleanup(self):
        self.exercise_cleanup(billing={
            'author': 'billing', 'description': 'billing plugin', 'homepage': 'https://example.org',
            'id': 'cpa-updater',  # Metadata cannot redirect the config-key selector.
            'install': {'type': 'github-release'}, 'license': 'MIT', 'name': 'Billing',
            'release-tag': m.hot_name(b'oldest')[0], 'repository': 'owner/repo',
            'source-id': 'official', 'source-name': 'Official', 'source-url': 'https://example.org/store',
            'tags': ['billing'], 'version': '1.2.3',
        })

    def test_both_selectors_protect_normalized_references(self):
        for selector in ('version', 'release-tag'):
            with self.subTest(selector=selector): self.exercise_cleanup(block=selector)

    def test_invalid_or_unknown_metadata_preserves_owned_files(self):
        cases = [
            {'install': []}, {'install': {'unknown': 'keep'}},
            {'install': {'type': False}}, {'install': {'artifacts': {}}},
            {'install': {'artifacts': [{'url': 123}]}},
            {'install': {'artifacts': [{'size': True}]}},
            {'install': {'artifacts': [{'path': '/do/not/delete'}]}},
            {'tags': ['valid', 42]}, {'author': {}}, {'schema-version': True},
            {'locales': {'en': {'unknown': 'keep'}}}, {'future-field': 'keep'},
            {'version': None}, {'release-tag': '../unsafe'},
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                self.exercise_cleanup(block='metadata', billing=metadata)

    def test_extended_official_manifest_types_are_read_only(self):
        self.exercise_cleanup(billing={
            'schema-version': 2, 'logo': 'https://example.org/logo',
            'locales': {'en': {'name': 'Billing', 'tags': ['billing']}},
            'install': {'type': 'direct', 'artifacts': [{'goos': 'linux', 'goarch': 'amd64',
                'url': 'https://example.org/billing.so', 'sha256': 'a' * 64, 'size': 123}]},
        })

    def test_opaque_config_still_skips_cleanup(self): self.exercise_cleanup(block='opaque')
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

    def test_prune_final_stat_race_never_deletes_replacement(self):
        import subprocess
        user = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
        with tempfile.TemporaryDirectory() as root, patch.object(m, 'plugin_directory'), patch.object(m.pwd, 'getpwnam', return_value=user), patch.object(m.os, 'getgrouplist', return_value=[]):
            target = Path(root) / m.hot_name(b'owned')[1]
            target.write_bytes(b'owned')
            replacement = target.with_name('billing-state'); replacement.write_bytes(b'billing-critical')
            real_run = subprocess.run
            hook = """import os
original_stat=os.stat
def race_stat(path,*args,**kwargs):
 result=original_stat(path,*args,**kwargs)
 if path==TARGET and kwargs.get('dir_fd') is not None:
  os.replace(REPLACEMENT,TARGET,src_dir_fd=kwargs['dir_fd'],dst_dir_fd=kwargs['dir_fd'])
 return result
os.stat=race_stat
""".replace('TARGET', repr(target.name)).replace('REPLACEMENT', repr(replacement.name))
            def run(args, **kwargs):
                args=list(args); args[3]=hook+args[3]
                return real_run(args, **kwargs)
            with patch.object(m.subprocess, 'run', side_effect=run):
                with self.assertRaises(RuntimeError):
                    m.plugin_io(target, 'prune', m.hashlib.sha256(b'owned').hexdigest().encode())
            self.assertTrue(target.exists())
            self.assertIn(b'billing-critical', [p.read_bytes() for p in Path(root).iterdir()])

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
            with self.assertRaises(RuntimeError): m.plugin_io(target, 'prune', digest)
            self.assertEqual(target.read_bytes(), b'owned')


if __name__ == '__main__': unittest.main()
