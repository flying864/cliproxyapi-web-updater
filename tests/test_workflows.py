"""Core CI contract tests; stdlib only, no workflow execution or publication."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowContract(unittest.TestCase):
    def text(self, name):
        return (ROOT / '.github/workflows' / name).read_text()

    def test_store_publication_is_removed(self):
        self.assertFalse((ROOT / '.github/workflows/release-plugin.yml').exists())
        for file in (ROOT / '.github/workflows').glob('*.yml'):
            self.assertNotIn('contents: write', file.read_text())
            self.assertNotIn('gh release create', file.read_text())

    def test_main_reuses_full_core_verification(self):
        verify = self.text('verify.yml')
        core = self.text('verify-core.yml')
        self.assertIn('uses: ./.github/workflows/verify-core.yml', verify)
        for command in ['test_plugin.py', 'test_sanitizer.py', 'test_worker.py',
                        'test_install.py', 'test_official.py', 'test_native.py', 'test_permissions.py', 'test_version.py', 'test_workflows.py',
                        'test_panel_browser.py', 'test_panel_auth.js', 'test_hot_install_official.py',
                        'test_runtime.py', 'test_simple_install.py', 'test_update_command.py']:
            self.assertIn(command, core)
        self.assertIn('ref: ${{ github.sha }}', core)

    def test_backup_manager_receives_private_ci_tmpdir(self):
        core=self.text('verify-core.yml')
        setup='export TMPDIR="$(mktemp -d "$RUNNER_TEMP/cpa-backup-tests.XXXXXXXX")"'
        self.assertIn(setup,core)
        self.assertLess(core.index(setup),core.index('python3 -B tests/test_backup_manager.py'))

    def test_shell_syntax_checks_reference_existing_scripts(self):
        core = self.text('verify-core.yml')
        match = re.search(r'for script in ([^;\n]+); do\s+bash -n "\$script"', core)
        self.assertIsNotNone(match)
        assert match is not None
        scripts = match[1].split()
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script):
                self.assertTrue((ROOT / script).is_file(), script)

    def test_both_native_builds_are_checked(self):
        build = self.text('build-native.yml')
        for text in ['ubuntu-24.04', 'ubuntu-24.04-arm', 'scripts/smoke_plugin.py',
                     'build/cpa-updater.so', 'readelf --version-info', 'timeout-minutes:']:
            self.assertIn(text, build)
        self.assertIn('uses: ./.github/workflows/build-native.yml', self.text('verify.yml'))
        self.assertIn('path: build/cpa-updater.so', build)
        self.assertNotIn('store_artifacts', build)

    def test_production_smoke_rejects_wrong_metadata_version(self):
        import platform
        arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}[platform.machine()]
        with tempfile.TemporaryDirectory(prefix='cpa-production-smoke-') as tmp:
            binary = Path(tmp) / 'cpa-updater.so'
            subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                            '-fPIC', '-shared', str(ROOT / 'cpa-updater.c'), '-o', str(binary)],
                           check=True, timeout=30)
            script = ROOT / 'scripts/smoke_plugin.py'
            result = subprocess.run([sys.executable, '-B', str(script), '--binary', str(binary),
                                     '--version', '999.999.999', '--arch', arch],
                                    text=True, capture_output=True, timeout=25)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('AssertionError', result.stderr)

    def test_actions_are_immutable_and_jobs_are_bounded(self):
        for file in (ROOT / '.github/workflows').glob('*.yml'):
            text = file.read_text()
            for uses in re.findall(r'uses:\s*([^\s#]+)', text):
                if not uses.startswith('./'):
                    self.assertRegex(uses, r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$')
        for name in ('verify-core.yml', 'build-native.yml'):
            self.assertIn('timeout-minutes:', self.text(name))


if __name__ == '__main__':
    unittest.main()
