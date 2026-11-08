import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import importlib
check = importlib.import_module("check_release_version")
bump = importlib.import_module("bump_version")

class VersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in [*check.PATTERNS, 'tests/test_official.py']:
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dest)

    def test_official_is_checked(self):
        self.assertIn('tests/test_official.py', check.source_versions(self.root))

    def test_suffix_and_unicode_rejected(self):
        for value in ['0.4.0-beta', '0.4.0.1', '０.4.0']:
            with self.subTest(value=value):
                path = self.root / 'README.md'
                original = (ROOT / 'README.md').read_text()
                current = check.source_versions(ROOT)['README.md']
                path.write_text(original.replace('# CPA Web Updater v' + current, '# CPA Web Updater v' + value, 1))
                with self.assertRaises(ValueError):
                    check.source_versions(self.root)

    def test_duplicate_rejected(self):
        path = self.root / 'README.md'
        path.write_text(path.read_text() + '\n' + path.read_text().splitlines()[0] + '\n')
        with self.assertRaises(ValueError):
            check.source_versions(self.root)

    def test_bump_rollback_and_mode(self):
        before = {n: (self.root / n).read_bytes() for n in check.PATTERNS}
        real = bump.os.replace
        calls = []
        def fail_once(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError('injected second replacement failure')
            return real(src, dst)
        with patch.object(bump.os, 'replace', side_effect=fail_once):
            with self.assertRaises(OSError):
                bump.bump('0.5.0', self.root)
        self.assertEqual(before, {n: (self.root / n).read_bytes() for n in check.PATTERNS})
        worker = self.root / 'cliproxy-updater-worker'
        worker.chmod(0o751)
        bump.bump('0.5.0', self.root)
        self.assertEqual(worker.stat().st_mode & 0o777, 0o751)
        self.assertEqual(set(check.source_versions(self.root).values()), {'0.5.0'})

    def test_inconsistent_versions_rejected(self):
        path = self.root / 'tests/test_official.py'
        text = path.read_text()
        current = check.source_versions(self.root)['tests/test_official.py']
        path.write_text(text.replace("== '" + current + "'", "== '9.8.7'"))
        with self.assertRaises(ValueError):
            check.source_versions(self.root)
        with self.assertRaises(ValueError):
            bump.bump('0.5.0', self.root)

    def test_invalid_requested_versions_rejected(self):
        for version in ['0.4.0-beta', '0.4.0.1', '０.4.0', 'v0.4.0', '0.4.0\n']:
            with self.subTest(version=version), self.assertRaises(ValueError):
                bump.bump(version, self.root)

    def test_symlink_rejected(self):
        path = self.root / 'README.md'
        path.unlink()
        path.symlink_to(ROOT / 'README.md')
        with self.assertRaises(ValueError):
            check.source_versions(self.root)

if __name__ == '__main__':
    unittest.main()
