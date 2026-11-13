"""Non-root tests of installer backup registration/capability using private paths."""
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest import TestCase,main,mock
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]

def load():
    spec=importlib.util.spec_from_file_location('backup_installer', ROOT/'install_helper.py')
    assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

class BackupInstallTests(TestCase):
    def test_existing_status_gains_capability_without_erasing_result(self):
        m=load()
        with tempfile.TemporaryDirectory() as tmp:
            setattr(m,'PUBLIC',Path(tmp))
            target=m.PUBLIC/'status.json'
            original=dict(protocol=1,state='success',detail='preserved',latest='v8.0.56',updated_at='kept')
            target.write_text(json.dumps(original))
            target.chmod(0o640)
            real_lstat=Path.lstat
            def owner(path):
                st=real_lstat(path)
                return SimpleNamespace(st_uid=0,st_nlink=st.st_nlink,st_mode=st.st_mode)
            with mock.patch.object(Path,'lstat',owner), mock.patch.object(m.os,'chown'), mock.patch.object(m.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=0)), mock.patch.object(m,'runtime_module',return_value=SimpleNamespace(WORKER_VERSION='0.5.0')):
                m.initialize_status()
            value=json.loads(target.read_text())
            self.assertEqual(value['backups_protocol'],1)
            for key,val in original.items(): self.assertEqual(value[key],val)

    def test_registration_failure_does_not_fail_verified_install(self):
        m=load()
        with mock.patch.object(m,'command',side_effect=RuntimeError('fixture registration failure')) as command, mock.patch('sys.stderr'):
            m.register_backup(Path('/var/lib/cliproxy-updater/install-example'))
        self.assertEqual(command.call_args.args,('python3',str(m.RUNTIME),'backups-register','install','install-example'))

if __name__=='__main__': main()
