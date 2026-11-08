"""Offline updater tests: real directories, mocked privileged/network commands."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / 'scripts/update_plugin.py'


class UpdateCommandTests(unittest.TestCase):
    def setUp(self):
        self.cwd = Path.cwd()
        self.addCleanup(os.chdir, self.cwd)

    def load(self):
        self.assertTrue(MODULE.exists(), 'update command has not been implemented')
        spec = importlib.util.spec_from_file_location('update_command', MODULE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_success_removes_only_created_directory(self):
        m = self.load()
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as home:
            unrelated = Path(home) / 'cliproxy-updater-update.keep'
            unrelated.mkdir()
            calls = []
            def run(argv, **kw):
                calls.append((argv, kw))
                out = 'hot-reload 已验证：target' if 'bash' in argv else ''
                if argv[:3] == ['git', 'rev-parse', 'HEAD']:
                    out = 'a' * 40
                return subprocess.CompletedProcess(argv, 0, out, '')
            with mock.patch.object(m.Path, 'home', return_value=Path(home)), mock.patch.object(m.subprocess, 'run', side_effect=run), mock.patch.object(m.os, 'geteuid', return_value=0):
                self.assertEqual(m.main(['--commit', 'a' * 40]), 0)
            self.assertEqual(list(Path(home).iterdir()), [unrelated])
            self.assertTrue(any(c[0] == ['bash', 'install.sh', '--hot-reload'] for c in calls))
            self.assertTrue(all(0 < c[1]['timeout'] <= 900 for c in calls))

    def exercise(self, mode='success', nonroot=False):
        m = self.load()
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as home:
            calls = []
            def run(argv, **kwargs):
                calls.append(argv)
                if mode == 'interrupt':
                    raise KeyboardInterrupt()
                if mode == 'timeout':
                    raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
                output = ''
                if argv[:3] == ['git', 'rev-parse', 'HEAD']:
                    output = ('b' if mode == 'mismatch' else 'a') * 40
                if 'bash' in argv:
                    output = '旧 hot 事务已恢复并验证' if mode == 'recovery' else 'hot-reload 已验证：target'
                rc = 1 if mode == 'failure' or (mode == 'health' and 'systemctl' in argv) else 0
                return subprocess.CompletedProcess(argv, rc, output, '')
            stderr = io.StringIO()
            with mock.patch.object(m.Path, 'home', return_value=Path(home)), mock.patch.object(m.subprocess, 'run', side_effect=run), mock.patch.object(m.os, 'geteuid', return_value=1000 if nonroot else 0), contextlib.redirect_stderr(stderr):
                if mode == 'cleanup':
                    with mock.patch.object(m, 'cleanup_source', side_effect=OSError('denied')):
                        rc = m.main(['--commit', 'a' * 40])
                else:
                    rc = m.main(['--commit', 'a' * 40])
            entries = list(Path(home).iterdir())
            return rc, entries, calls, stderr.getvalue()

    def test_interrupt_retains_source(self):
        rc, entries, _, _ = self.exercise('interrupt')
        self.assertEqual(rc, 1)
        self.assertEqual(len(entries), 1)

    def test_failures_retain_source(self):
        for mode in ('failure', 'timeout', 'mismatch', 'recovery', 'health'):
            with self.subTest(mode=mode):
                rc, entries, calls, _ = self.exercise(mode)
                self.assertEqual(rc, 1)
                self.assertEqual(len(entries), 1)
                if mode == 'mismatch':
                    self.assertFalse(any('bash' in argv for argv in calls))

    def test_cleanup_warning_preserves_success(self):
        rc, entries, _, stderr = self.exercise('cleanup')
        self.assertEqual(rc, 0)
        self.assertEqual(len(entries), 1)
        self.assertIn('WARNING', stderr)

    def test_nonroot_install_and_health_use_sudo(self):
        rc, entries, calls, _ = self.exercise(nonroot=True)
        self.assertEqual(rc, 0)
        self.assertEqual(entries, [])
        self.assertIn(['sudo', '--', 'bash', 'install.sh', '--hot-reload'], calls)
        self.assertIn(['sudo', '--', 'systemctl', 'is-active', '--quiet', 'cliproxyapi.service'], calls)

    def test_invalid_commit_never_creates_source(self):
        m = self.load()
        for commit in ('main', 'a' * 39, 'a' * 41, 'g' * 40, ' ' + 'a' * 40):
            with mock.patch.object(m, 'create_source') as create, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    m.main(['--commit', commit])
                self.assertEqual(exc.exception.code, 2)
                create.assert_not_called()

    def test_cleanup_refuses_tampered_marker_and_symlink(self):
        m = self.load()
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as home, mock.patch.object(m.Path, 'home', return_value=Path(home)):
            root, record = m.create_source()
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            (root / m.MARKER).write_text('{}')
            with self.assertRaises(RuntimeError):
                m.cleanup_source(root, record)
            original = root.with_name(root.name + '.original')
            root.rename(original)
            root.symlink_to(original, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                m.cleanup_source(root, record)
            self.assertTrue(original.is_dir())


if __name__ == '__main__':
    unittest.main()
