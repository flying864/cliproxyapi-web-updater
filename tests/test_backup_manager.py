"""Isolated backup tests: only this fixture patches paths and trusted owner.

No production path, ownership change, service, archive extraction or cross-UID probe.
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('backup_runtime', Path(__file__).resolve().parents[1] / 'updater_runtime.py')
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class BackupTests(unittest.TestCase):
    def setUp(self):
        base = os.environ.get('TMPDIR')
        self.assertTrue(base, 'tests require current-user private TMPDIR')
        self.temp = tempfile.TemporaryDirectory(prefix='backup-manager-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / 'state'
        self.public = self.base / 'public'
        self.state.mkdir(mode=0o700)
        (self.state / 'backups').mkdir(mode=0o700)
        self.public.mkdir(mode=0o750)
        for key, value in [('STATE', str(self.state)), ('PUBLIC', str(self.public)), ('BACKUP_OWNER_UID', os.geteuid())]:
            p = patch.object(runtime, key, value, create=True)
            p.start()
            self.addCleanup(p.stop)

    def group(self, number, kind='runtime'):
        name = f'20261113-1200{number:02d}-1.2.3' if kind == 'runtime' else f'install-test{number}'
        path = (self.state / 'backups' if kind == 'runtime' else self.state) / name
        path.mkdir(mode=0o700)
        files = {'cli-proxy-api': b'binary', 'runtime-config.tar.gz': b'not an archive; never extract'} if kind == 'runtime' else {'manifest.json': b'{}', 'config.yaml': b'secret', '0': b'old'}
        for name, data in files.items():
            (path / name).write_bytes(data)
        return path

    def test_pagination_reaches_install_groups_after_legacy_runtime(self):
        for i in range(100):self.group(i)
        groups,_,ids=self.eligible(count=2,kind='install')
        second=runtime.backup_preview(1)
        self.assertEqual(second['page'],1)
        self.assertEqual(second['total_count'],102)
        self.assertTrue(any(i['deletable'] and i['kind']=='install' for i in second['items']))
        self.assertEqual(second['page_count'],2)
        with self.assertRaises(ValueError):runtime.backup_preview(-1)

    def test_public_snapshot_readable_with_worker_private_umask(self):
        old=os.umask(0o077)
        try:runtime.backup_preview()
        finally:os.umask(old)
        self.assertEqual((self.public/'backups.json').stat().st_mode&0o777,0o640)

    def test_malformed_private_metadata_fails_closed(self):
        for raw in ('[]','{"unexpected":1}','{"runtime/x":{"id":"bad"}}','{"x":1,"x":2}'):
            with self.subTest(raw=raw):
                path=self.state/'backup-registry.json';path.write_text(raw);path.chmod(0o600)
                with self.assertRaises(ValueError):runtime.backup_preview()

    def test_latest_corrupt_group_does_not_release_last_good_backup(self):
        groups,preview,ids=self.eligible()
        (groups[-1]/'cli-proxy-api').write_bytes(b'corrupted')
        latest_preview=runtime.backup_preview()
        item=next(i for i in latest_preview['items'] if i['name']==groups[-2].name)
        self.assertFalse(item['deletable'])

    def test_preview_protects_unknown_without_reading_archive_or_deleting(self):
        group = self.group(1)
        result = runtime.backup_preview()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['total_count'], 1)
        self.assertFalse(result['items'][0]['deletable'])
        self.assertIn('unregistered', result['items'][0]['reason'])
        self.assertEqual(result['items'][0]['size_bytes'], sum(p.stat().st_size for p in group.iterdir()))
        self.assertTrue(group.exists())
        self.assertEqual(json.loads((self.public / 'backups.json').read_text()), result)

    def test_registered_selection_deletes_only_old_success_and_consumes_token(self):
        old, latest = self.group(1), self.group(2)
        runtime.backup_register('runtime', old.name)
        runtime.backup_register('runtime', latest.name)
        preview = runtime.backup_preview()
        chosen = next(x for x in preview['items'] if x['name'] == old.name)
        self.assertTrue(chosen['deletable'])
        self.assertFalse(next(x for x in preview['items'] if x['name'] == latest.name)['deletable'])
        result = runtime.backup_cleanup(preview['token'], [chosen['id']])
        self.assertEqual(result['state'], 'success')
        self.assertFalse(old.exists())
        self.assertTrue(latest.exists())
        with self.assertRaises(ValueError):
            runtime.backup_cleanup(preview['token'], [chosen['id']])
    def eligible(self, count=3, kind='runtime'):
        groups = [self.group(i, kind) for i in range(count)]
        for g in groups:
            runtime.backup_register(kind, g.name)
        preview = runtime.backup_preview()
        return groups, preview, [i['id'] for i in preview['items'] if i['deletable']]

    def test_expired_or_refreshed_token_rejected(self):
        groups, preview, ids = self.eligible()
        with patch.object(runtime.time, 'time', return_value=runtime.time.time() + 601):
            with self.assertRaises(ValueError):
                runtime.backup_cleanup(preview['token'], ids)
        fresh = runtime.backup_preview()
        runtime.backup_preview()
        with self.assertRaises(ValueError):
            runtime.backup_cleanup(fresh['token'], ids)
        self.assertTrue(all(g.exists() for g in groups))

    def test_batch_preflight_tamper_rejects_every_group(self):
        for attack in ('content', 'extra', 'symlink', 'hardlink', 'directory', 'mode'):
            with self.subTest(attack=attack):
                # A separate private fixture per attack avoids re-registering names.
                folder = self.state / 'backups'
                for g in folder.iterdir():
                    import shutil
                    shutil.rmtree(g)
                (self.state / 'backup-registry.json').unlink(missing_ok=True)
                groups, preview, ids = self.eligible()
                target = groups[1] / 'cli-proxy-api'
                if attack == 'content':
                    target.write_bytes(b'changed')
                elif attack == 'extra':
                    (groups[1] / 'unexpected').write_text('extra')
                elif attack == 'mode':
                    target.chmod(0o666)
                elif attack == 'directory':
                    groups[1].rename(str(groups[1]) + '-saved')
                    groups[1].mkdir(mode=0o700)
                else:
                    target.unlink()
                    if attack == 'symlink':
                        target.symlink_to(groups[2] / 'cli-proxy-api')
                    else:
                        os.link(groups[2] / 'cli-proxy-api', target)
                with self.assertRaises(ValueError):
                    runtime.backup_cleanup(preview['token'], ids)
                self.assertTrue(groups[0].exists())
                self.assertTrue(groups[2].exists())

    def test_transactions_even_broken_symlink_protect_and_recheck(self):
        groups, preview, ids = self.eligible()
        for name in ('transaction.json', 'hot-transaction.json'):
            transaction = self.state / name
            transaction.symlink_to(self.base / 'absent')
            self.assertTrue(all(not i['deletable'] for i in runtime.backup_preview()['items']))
            transaction.unlink()
        preview = runtime.backup_preview()
        (self.state / 'transaction.json').write_text('corrupt')
        with self.assertRaises(ValueError):
            runtime.backup_cleanup(preview['token'], ids)
        self.assertTrue(all(g.exists() for g in groups))

    def test_install_and_runtime_have_independent_latest_protection(self):
        self.eligible(kind='runtime')
        groups, preview, ids = self.eligible(kind='install')
        self.assertEqual(sum(not x['deletable'] for x in preview['items']), 2)
        runtime.backup_cleanup(preview['token'], ids)
        self.assertTrue(groups[-1].exists())

    def test_invalid_selections_and_unknown_ids_leave_groups_intact(self):
        groups, preview, ids = self.eligible()
        for chosen in ([], ids * 11, [ids[0], ids[0]], ['../x'], ['a' * 32], ids + ['b' * 32]):
            with self.subTest(chosen=chosen):
                preview = runtime.backup_preview()
                with self.assertRaises(ValueError):
                    runtime.backup_cleanup(preview['token'], chosen)
        self.assertTrue(all(g.exists() for g in groups))

    def test_register_rejects_unknown_layout_links_paths_and_re_registration(self):
        group = self.group(1)
        for kind, name in [('runtime', '../x'), ('install', '/x'), ('other', group.name)]:
            with self.assertRaises(ValueError):
                runtime.backup_register(kind, name)
        (group / 'extra').mkdir()
        with self.assertRaises(ValueError):
            runtime.backup_register('runtime', group.name)
        (group / 'extra').rmdir()
        runtime.backup_register('runtime', group.name)
        with self.assertRaises(ValueError):
            runtime.backup_register('runtime', group.name)

    def test_partial_failure_honest_and_not_replayed(self):
        groups, preview, ids = self.eligible()
        unlink = os.unlink
        def fail(name, *args, **kwargs):
            if name == 'runtime-config.tar.gz':
                raise OSError('injected disk error')
            return unlink(name, *args, **kwargs)
        with patch.object(runtime.os, 'unlink', side_effect=fail):
            result = runtime.backup_cleanup(preview['token'], ids)
        self.assertEqual(result['state'], 'error')
        self.assertEqual(set(result['failed_ids']), set(ids))
        self.assertEqual(result['deleted_ids'], [])
        self.assertFalse((groups[0] / 'cli-proxy-api').exists())
        with self.assertRaises(ValueError):
            runtime.backup_cleanup(preview['token'], ids)

    def test_truncation_is_explicit_and_public_contains_no_secret(self):
        for i in range(105):
            self.group(i, kind='install')
        preview = runtime.backup_preview()
        self.assertEqual(preview['total_count'], 105)
        self.assertEqual(len(preview['items']), 100)
        self.assertTrue(preview['truncated'])
        raw = (self.public / 'backups.json').read_bytes()
        self.assertLessEqual(len(raw), 65536)
        self.assertNotIn(b'secret', raw)
        self.assertNotIn(b'sha256', raw)

    def test_private_state_and_root_only_boundary(self):
        with patch.object(runtime.os, 'geteuid', return_value=runtime.BACKUP_OWNER_UID + 1):
            with self.assertRaises(ValueError):
                runtime.backup_preview()
        self.state.chmod(0o750)
        with self.assertRaises(ValueError):
            runtime.backup_preview()

    def test_non_target_content_and_update_status_unchanged(self):
        import hashlib
        groups, preview, ids = self.eligible()
        unrelated = self.base / 'plugins'
        unrelated.mkdir()
        targets = [unrelated / 'unrelated.so', self.public / 'status.json', self.state / 'deployment.json']
        for target in targets:
            target.write_bytes(b'not cleanup scope')
        before = [hashlib.sha256(t.read_bytes()).hexdigest() for t in targets]
        runtime.backup_cleanup(preview['token'], ids[:1])
        self.assertEqual(before, [hashlib.sha256(t.read_bytes()).hexdigest() for t in targets])
        self.assertTrue(groups[1].exists())

    def test_exact_twenty_selection_supported(self):
        groups, preview, ids = self.eligible(count=21, kind='install')
        self.assertEqual(len(ids), 20)
        result = runtime.backup_cleanup(preview['token'], ','.join(ids))
        self.assertEqual(len(result['deleted_ids']), 20)
        self.assertTrue(groups[-1].exists())

    def test_new_latest_registration_and_deleted_latest_fail_closed(self):
        groups, preview, ids = self.eligible()
        # Protect the newest remaining registered group if latest was externally lost.
        import shutil
        shutil.rmtree(groups[-1])
        refreshed = runtime.backup_preview()
        self.assertEqual(sum(not i['deletable'] for i in refreshed['items']), 1)
        # New success does not extend validity of old preview token after a scan.
        with self.assertRaises(ValueError):
            runtime.backup_cleanup(preview['token'], ids)

    def test_registration_refuses_links_and_service_writable_files(self):
        group = self.group(1)
        target = group / 'cli-proxy-api'
        target.chmod(0o666)
        with self.assertRaises(ValueError):
            runtime.backup_register('runtime', group.name)
        target.chmod(0o644)
        other = self.base / 'outside'
        os.link(target, other)
        with self.assertRaises(ValueError):
            runtime.backup_register('runtime', group.name)
        other.unlink()
        target.unlink()
        target.symlink_to(self.base / 'missing')
        with self.assertRaises(OSError):
            runtime.backup_register('runtime', group.name)
        self.assertFalse((self.state / 'backup-registry.json').exists())

    def test_cli_operational_rejection_preserves_published_result_and_returns_normally(self):
        import contextlib
        import io
        import sys
        groups, preview, ids = self.eligible()
        (self.state / 'transaction.json').write_text('broken transaction')
        assert runtime.__file__
        source = Path(runtime.__file__).read_text()
        entrypoint = source[source.index("if __name__ == '__main__':"):]
        scope = dict(vars(runtime), __name__='__main__')
        output = io.StringIO()
        with patch.object(sys, 'argv', ['updater_runtime.py', 'backups-clean', preview['token'], ','.join(ids)]), contextlib.redirect_stdout(output):
            exec(compile(entrypoint, runtime.__file__, 'exec'), scope)
        result = json.loads(output.getvalue())
        self.assertEqual(result['state'], 'error')
        self.assertIn('Active transaction', result['detail'])
        self.assertEqual(json.loads((self.public / 'backups.json').read_text()), result)
        self.assertTrue(all(g.exists() for g in groups))

    def test_cli_has_fixed_backup_commands_no_environment_paths(self):
        assert runtime.__file__
        source = Path(runtime.__file__).read_text()
        self.assertIn("sys.argv[1] == 'backups-register'", source)
        self.assertIn("sys.argv[1] == 'backups-preview'", source)
        self.assertIn("sys.argv[1] == 'backups-clean'", source)
        self.assertNotIn('os.environ', source)


if __name__ == '__main__':
    unittest.main()
