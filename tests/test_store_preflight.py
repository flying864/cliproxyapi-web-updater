"""Read-only mode checks on temporary paths; no service or privilege changes."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import importlib
preflight = importlib.import_module("market_preflight")


class TestPreflight(unittest.TestCase):
    def run_check(self, mode=0o770, ancestor_mode=0o700, symlink=False,
                  missing_user=False, missing_worker=False, ancestor_symlink=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins = root / 'plugins'
            plugins.mkdir(mode=mode)
            plugins.chmod(mode)
            worker = root / 'worker'
            if not missing_worker:
                worker.touch()
            if symlink:
                link = root / 'link'
                link.symlink_to(plugins, target_is_directory=True)
                plugins = link
            if ancestor_symlink:
                link = root / 'ancestor-link'
                link.symlink_to(root, target_is_directory=True)
                plugins = link / 'plugins'
            owner = plugins.stat()
            user = SimpleNamespace(pw_name='cliproxy', pw_uid=owner.st_uid,
                                   pw_gid=owner.st_gid)
            output = io.StringIO()
            real_lstat = Path.lstat
            # The fixture starts at root; host /tmp (1777), ACLs and mount
            # layout outside it are not part of the mode-bit test subject.
            outside = set(root.parents)
            def fixture_lstat(path, *args, **kwargs):
                if path in outside:
                    return SimpleNamespace(st_mode=0o040755, st_uid=0, st_gid=0)
                return real_lstat(path, *args, **kwargs)
            with patch.object(Path, 'lstat', fixture_lstat), patch.object(preflight, 'PLUGIN_DIR', plugins), patch.object(
                    preflight, 'WORKER', worker), patch.object(
                    preflight.pwd, 'getpwnam', return_value=user,
                    side_effect=KeyError('cliproxy') if missing_user else None), patch.object(
                    preflight.os, 'getgrouplist', return_value=[owner.st_gid]), contextlib.redirect_stdout(output):
                root.chmod(ancestor_mode)
                try:
                    result = preflight.main()
                except SystemExit as exc:
                    result = 1
                    print(exc)
                finally:
                    root.chmod(0o700)
            return result, output.getvalue()

    def test_host_temp_ancestor_is_not_fixture_dependency(self):
        real_lstat = Path.lstat
        public_temp = Path(tempfile.gettempdir())
        def public_ancestor(path, *args, **kwargs):
            if path == public_temp:
                return SimpleNamespace(st_mode=0o041777, st_uid=0, st_gid=0)
            return real_lstat(path, *args, **kwargs)
        with patch.object(Path, 'lstat', public_ancestor):
            self.assertEqual(self.run_check()[0], 0)

    def test_owner_cannot_borrow_group_write(self):
        result, output = self.run_check(0o570)
        self.assertEqual(result, 1)
        self.assertNotIn('PASS', output)

    def test_missing_ancestor_search(self):
        self.assertEqual(self.run_check(ancestor_mode=0o600)[0], 1)

    def test_unsafe_ancestor(self):
        self.assertEqual(self.run_check(ancestor_mode=0o777)[0], 1)

    def test_symlink(self):
        self.assertEqual(self.run_check(symlink=True)[0], 1)

    def test_ancestor_symlink(self):
        self.assertEqual(self.run_check(ancestor_symlink=True)[0], 1)

    def test_missing_service_user(self):
        result, output = self.run_check(missing_user=True)
        self.assertEqual(result, 1)
        self.assertIn('service user does not exist', output)

    def test_mode_only_not_health(self):
        result, output = self.run_check()
        self.assertEqual(result, 0)
        for text in ('MODE CHECK ONLY', 'ACL', 'mount', 'service sandbox', 'unknown', 'exists'):
            self.assertIn(text, output)
        self.assertNotIn('PASS', output)

    def test_permission_classes_are_exclusive(self):
        st = SimpleNamespace(st_uid=1001, st_gid=2001, st_mode=0o057)
        self.assertFalse(preflight.mode_allows(st, 1001, [2001], 3))
        self.assertFalse(preflight.mode_allows(st, 1002, [2001], 3))
        self.assertTrue(preflight.mode_allows(st, 1002, [2002], 3))

    def test_missing_worker(self):
        self.assertEqual(self.run_check(missing_worker=True)[0], 1)


if __name__ == '__main__':
    unittest.main()
