"""Offline fixtures: no historical Git object or network is required."""
import importlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
OLD_VERIFY = 'name: verify\n\non:\n  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n\npermissions:\n  contents: read\n\nconcurrency:\n  group: verify-${{ github.ref }}\n  cancel-in-progress: true\n\njobs:\n  linux-amd64:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 20\n    steps:\n      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4\n      - name: Install test-only dependencies\n        run: |\n          sudo apt-get update\n          sudo apt-get install -y --no-install-recommends gcc python3 curl bubblewrap\n      - name: Syntax and isolated plugin tests\n        run: |\n          for script in install.sh uninstall.sh cliproxy-updater-worker; do\n            bash -n "$script" || exit\n          done\n          python3 test_plugin.py\n          python3 tests/test_sanitizer.py\n      - name: Isolated worker and installer regression tests\n        run: |\n          # Root is only used on an ephemeral runner so user-namespace policy\n          # cannot silently skip tests. The tests themselves require bwrap.\n          sudo python3 tests/test_worker.py\n          sudo python3 tests/test_install.py\n      - name: Pinned official CLIProxyAPI integration\n        run: |\n          mkdir -p test-output\n          python3 tests/fetch_official.py --output test-output/cli-proxy-api\n          sudo python3 tests/test_official.py --binary test-output/cli-proxy-api --output test-output/official\n'


class ApplyTests(unittest.TestCase):
    def target(self, parent):
        overlay = importlib.import_module('apply_overlay')
        bump = importlib.import_module('bump_version')
        root = Path(parent) / 'target'
        root.mkdir()
        for name in overlay.PATTERNS:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        bump.bump('0.3.0', root)
        workflow = root / overlay.VERIFY
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(OLD_VERIFY)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(root), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid',
                        'commit', '-qm', 'isolated v0.3.0 fixture'], check=True)
        return root

    def test_missing_manifest_member_fails_before_writes(self):
        overlay = importlib.import_module('apply_overlay')
        for name in ['.github/workflows/verify-core.yml', '.github/workflows/build-store.yml',
                     'scripts/smoke_plugin.py', 'tests/test_store_workflows.py']:
            self.assertIn(name, overlay.NEW_FILES)
        with tempfile.TemporaryDirectory() as tmp:
            root = self.target(tmp)
            source = Path(tmp) / 'source'
            source.mkdir()
            for name in overlay.PATTERNS:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, path)
            with self.assertRaises((ValueError, FileNotFoundError)):
                overlay.apply(root, source)
            self.assertEqual(b'', subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain']))

    def test_failed_validation_restores_clean_checkout(self):
        overlay = importlib.import_module('apply_overlay')
        with tempfile.TemporaryDirectory() as tmp:
            root = self.target(tmp)
            before = {name: (root / name).read_bytes() for name in (*overlay.PATTERNS, overlay.VERIFY)}
            # Inject only the post-write child command boundary. Real filesystem
            # writes/rollback and Git root/clean checks still run unmodified.
            versions = overlay.source_versions
            def historical_source(root):
                values = versions(root)
                return dict.fromkeys(values, '0.4.0') if Path(root) == ROOT else values
            with patch.object(overlay, 'source_versions', side_effect=historical_source), patch.object(overlay.subprocess, 'run', side_effect=RuntimeError('injected validation failure')):
                with self.assertRaisesRegex(RuntimeError, 'injected validation failure'):
                    overlay.apply(root, ROOT)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in before})
            self.assertEqual(b'', subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain']))

    def test_new_runtime_versions_do_not_run_legacy_overlay(self):
        overlay = importlib.import_module('apply_overlay')
        versions = overlay.source_versions
        with tempfile.TemporaryDirectory() as tmp:
            root = self.target(tmp)
            def new_source(path):
                values = versions(path)
                return dict.fromkeys(values, '0.5.0') if Path(path) == ROOT else values
            with patch.object(overlay, 'source_versions', side_effect=new_source), self.assertRaisesRegex(ValueError, 'v0.4.0'):
                overlay.apply(root, ROOT)
            self.assertEqual(b'', subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain']))

    def test_ignored_overlay_target_is_not_overwritten(self):
        overlay = importlib.import_module('apply_overlay')
        with tempfile.TemporaryDirectory() as tmp:
            root = self.target(tmp)
            (root / '.git/info/exclude').write_text('registry.json\n')
            target = root / 'registry.json'
            target.write_text('preserve ignored fixture')
            versions = overlay.source_versions
            def historical_source(path):
                values = versions(path)
                return dict.fromkeys(values, '0.4.0') if Path(path) == ROOT else values
            with patch.object(overlay, 'source_versions', side_effect=historical_source), self.assertRaisesRegex(ValueError, 'existing overlay target'):
                overlay.apply(root, ROOT)
            self.assertEqual(target.read_text(), 'preserve ignored fixture')

    def test_rejects_nested_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            child = root / 'child'
            child.mkdir()
            result = subprocess.run(['bash', str(ROOT / 'apply_to_repo.sh'), str(child)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Git top-level', result.stderr)


if __name__ == '__main__':
    unittest.main()
