"""Installer compatibility and privilege boundaries; local fixtures only."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('simple_installer', ROOT / 'install_helper.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SimpleInstallTests(unittest.TestCase):
    def test_existing_service_owned_plugins_mode_preserved(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plugins'
            path.mkdir(mode=0o700)
            before = path.stat()
            with patch.object(m, 'safe_path'), patch.object(m.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=before.st_uid,pw_gid=before.st_gid)), patch.object(m.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=before.st_gid)):
                m.plugin_directory(path)
            after = path.stat()
            self.assertEqual((after.st_uid,after.st_gid,stat.S_IMODE(after.st_mode)),
                             (before.st_uid,before.st_gid,0o700))

    def test_double_dash_and_extra_args_do_not_rewrite_service(self):
        m = load()
        text = '{ path=/opt/cliproxyapi/cli-proxy-api ; argv[]=/opt/cliproxyapi/cli-proxy-api --config /opt/cliproxyapi/config.yaml --local-model ; ignore_errors=no ; }'
        calls=[]
        def ctl(*args):
            calls.append(args)
            return {'User':'cliproxy','Group':'cliproxy','ExecStart':text}[args[3]]
        with patch.object(m, 'ctl', ctl), patch.object(m, 'query', return_value=True), patch.object(m, 'safe_path'), patch.object(m, 'validate_config_permissions'), patch.object(m, 'readable_by_service'):
            m.validate_service()
        self.assertTrue(all(c[0]=='show' for c in calls))

    def test_units_include_persistent_status_without_mount_or_daemon(self):
        m = load()
        data=m.units()
        self.assertTrue(all(not name.endswith('.mount') for name in data))
        for name in ['cliproxy-updater.service','cliproxy-updater-check.service','cliproxy-updater-recover.service']:
            self.assertIn('/var/lib/cliproxy-updater-status',data[name])
            self.assertIn('Type=oneshot',data[name])
            self.assertNotIn('MemoryMax=768M',data[name])


if __name__=='__main__':unittest.main()
