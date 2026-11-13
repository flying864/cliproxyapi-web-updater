"""Production worker request dispatch in a private filesystem/network namespace.
The helper/service boundary is explicit; real backup engine tests live separately.
Never run worker or deletion against production paths outside bwrap.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_worker import build_fixtures, sandbox_args, SETUP, SCRATCH

HELPER = r'''
import json,pathlib,sys
p=pathlib.Path('/sim/helper-calls')
with p.open('a') as f: f.write(json.dumps(sys.argv[1:])+'\n')
if sys.argv[1]=='version': print('0.5.0')
elif sys.argv[1].startswith('backups-'):
 pathlib.Path('/var/lib/cliproxy-updater-status/backups.json').write_text(json.dumps(dict(protocol=1,state='ready',token='a'*32,items=[])))
else: raise SystemExit('Backup requests must not run service/auth preflight')
'''

class BackupWorkerTests(unittest.TestCase):
    def run_case(self, request, transaction=False, helper_fails=False):
        fixtures, mocks = build_fixtures()
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            sim = Path(d)
            (sim/'helper.py').write_text(HELPER if not helper_fails else 'raise SystemExit(7)\n')
            (sim/'input').write_bytes(request)
            script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
cp /sim/helper.py /usr/local/libexec/cliproxy-updater-runtime.py
chmod 0644 /usr/local/libexec/cliproxy-updater-runtime.py
cp /sim/input /run/cliproxy-updater/inbox/request
chown cliproxy:cliproxy /run/cliproxy-updater/inbox/request
printf '{"protocol":1,"state":"success","detail":"previous update preserved"}' > /var/lib/cliproxy-updater-status/status.json
cp /var/lib/cliproxy-updater-status/status.json /sim/before.json
'''
            if transaction:
                script += "printf broken > /var/lib/cliproxy-updater/transaction.json\nchmod 0600 /var/lib/cliproxy-updater/transaction.json\n"
            script+=r'''
bash /source/cliproxy-updater-worker --consume > /sim/worker.log 2>&1
printf '%s' "$?" > /sim/rc
cp /var/lib/cliproxy-updater-status/status.json /sim/after.json
if [[ -e /var/lib/cliproxy-updater-status/backups.json ]]; then cp /var/lib/cliproxy-updater-status/backups.json /sim/backups.json; fi
[[ ! -e /run/cliproxy-updater/processing ]] || touch /sim/processing-left
[[ ! -e /run/cliproxy-updater/inbox/request ]] || touch /sim/request-left
'''
            result=subprocess.run(sandbox_args(fixtures,mocks)+['--bind',str(sim),'/sim','--setenv','CASE','backup','/bin/bash','-c',script],capture_output=True,text=True,timeout=25)
            self.assertEqual(result.returncode,0,result.stderr)
            files={p.name:p.read_text() for p in sim.iterdir() if p.is_file() and p.name!='input'}
            self.assertNotIn('processing-left',files)
            self.assertNotIn('request-left',files)
            return files

    def test_scan_uses_only_backup_helper_and_preserves_upgrade_status(self):
        files=self.run_case(b'backups')
        self.assertEqual(files['rc'],'0',files['worker.log'])
        self.assertEqual(files['before.json'],files['after.json'])
        self.assertEqual(json.loads(files['helper-calls'].splitlines()[0]),['backups-preview'])
        self.assertNotIn('curl.log',files)
        self.assertNotIn('systemctl.log',files)

    def test_preview_page_is_numeric_only(self):
        files=self.run_case(b'backups 1')
        self.assertEqual(files['rc'],'0',files['worker.log'])
        self.assertEqual(json.loads(files['helper-calls'].splitlines()[0]),['backups-preview','1'])
        for raw in [b'backups -1',b'backups 1000',b'backups ../x']:
            self.assertNotEqual(self.run_case(raw)['rc'],'0')

    def test_cleanup_uses_bound_token_and_ids(self):
        token='a'*32; ids='b'*32+','+'c'*32
        files=self.run_case(('cleanup '+token+' '+ids).encode())
        self.assertEqual(files['rc'],'0',files['worker.log'])
        self.assertEqual(json.loads(files['helper-calls'].splitlines()[0]),['backups-clean',token,ids])
        self.assertEqual(files['before.json'],files['after.json'])
        self.assertNotIn('systemctl.log',files)

    def test_scan_does_not_trigger_recovery(self):
        files=self.run_case(b'backups',transaction=True)
        self.assertEqual(files['rc'],'0',files['worker.log'])
        self.assertEqual(files['before.json'],files['after.json'])
        self.assertNotIn('systemctl.log',files)

    def test_backup_failure_preserves_upgrade_result(self):
        files=self.run_case(b'backups',helper_fails=True)
        self.assertNotEqual(files['rc'],'0')
        self.assertEqual(files['before.json'],files['after.json'])
        self.assertEqual(json.loads(files['backups.json'])['state'],'error')

    def test_real_engine_register_preview_and_selected_delete(self):
        fixtures,mocks=build_fixtures()
        with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
            sim=Path(d)
            script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
set -e
rm /run/cliproxy-updater/inbox/request
cp /source/updater_runtime.py /usr/local/libexec/cliproxy-updater-runtime.py
chmod 0644 /usr/local/libexec/cliproxy-updater-runtime.py
chmod 0700 /var/lib/cliproxy-updater /var/lib/cliproxy-updater/backups
python3 - <<'PYFIXTURE'
from pathlib import Path
import subprocess,json,hashlib
state=Path('/var/lib/cliproxy-updater')
Path('/var/lib/cliproxy-updater-status/status.json').write_text('{"protocol":1,"state":"success","detail":"preserved fixture"}')
for i in range(3):
 p=state/'backups'/f'20261113-12000{i}-1.2.3';p.mkdir(mode=0o700)
 (p/'cli-proxy-api').write_bytes(b'isolated binary')
 (p/'runtime-config.tar.gz').write_bytes(b'isolated opaque archive')
 subprocess.run(['python3','/usr/local/libexec/cliproxy-updater-runtime.py','backups-register','runtime',p.name],check=True)
Path('/sim/upgrade-before').write_bytes(Path('/var/lib/cliproxy-updater-status/status.json').read_bytes())
PYFIXTURE
printf backups > /run/cliproxy-updater/inbox/request
chown cliproxy:cliproxy /run/cliproxy-updater/inbox/request
bash /source/cliproxy-updater-worker --consume
cp /var/lib/cliproxy-updater-status/backups.json /sim/preview.json
python3 - <<'PYSELECT'
import json,os,pwd
from pathlib import Path
p=json.loads(Path('/sim/preview.json').read_text());i=next(i for i in p['items'] if i['deletable'])
Path('/sim/selected').write_text(i['name'])
f=Path('/run/cliproxy-updater/inbox/request');f.write_text('cleanup '+p['token']+' '+i['id']);os.chown(f,pwd.getpwnam('cliproxy').pw_uid,pwd.getpwnam('cliproxy').pw_gid)
PYSELECT
bash /source/cliproxy-updater-worker --consume
cp /var/lib/cliproxy-updater-status/backups.json /sim/result.json
cp /var/lib/cliproxy-updater-status/status.json /sim/upgrade-after
python3 - <<'PYVERIFY'
from pathlib import Path
import json
Path('/sim/remaining.json').write_text(json.dumps(sorted(p.name for p in Path('/var/lib/cliproxy-updater/backups').iterdir())))
PYVERIFY
'''
            result=subprocess.run(sandbox_args(fixtures,mocks)+['--bind',str(sim),'/sim','--setenv','CASE','backup','/bin/bash','-c',script],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            preview=json.loads((sim/'preview.json').read_text()); self.assertEqual(preview['total_count'],3)
            result=json.loads((sim/'result.json').read_text());self.assertEqual(result['state'],'success',result)
            self.assertEqual(len(result['deleted_ids']),1)
            remaining=json.loads((sim/'remaining.json').read_text());self.assertEqual(len(remaining),2)
            self.assertNotIn((sim/'selected').read_text(),remaining)
            self.assertEqual((sim/'upgrade-before').read_bytes(),(sim/'upgrade-after').read_bytes())
            self.assertFalse((sim/'systemctl.log').exists())
            self.assertFalse((sim/'curl.log').exists())

    def test_failure_hook_ignores_backups_and_preserves_update_recovery(self):
        fixtures,mocks=build_fixtures()
        for request,expected in [('backups',0),('cleanup '+'a'*32+' '+'b'*32,0),('update v8.0.56',1)]:
            with self.subTest(request=request),tempfile.TemporaryDirectory(dir=SCRATCH) as d:
                sim=Path(d);(sim/'input').write_text(request)
                script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
rm /run/cliproxy-updater/inbox/request
cp /sim/input /run/cliproxy-updater/processing
chmod 0400 /run/cliproxy-updater/processing
printf broken > /var/lib/cliproxy-updater/transaction.json
chmod 0600 /var/lib/cliproxy-updater/transaction.json
bash /source/cliproxy-updater-worker --recover-update-failure > /sim/hook.log 2>&1
printf '%s' "$?" > /sim/rc
'''
                result=subprocess.run(sandbox_args(fixtures,mocks)+['--bind',str(sim),'/sim','--setenv','CASE','backup','/bin/bash','-c',script],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(int((sim/'rc').read_text()),expected,(sim/'hook.log').read_text())
                self.assertFalse((sim/'systemctl.log').exists())

    def test_invalid_cleanup_requests_never_reach_helper(self):
        for request in [b'cleanup ../x y',('cleanup '+'a'*32+' '+'b'*32+','+'b'*32).encode(),('cleanup '+'a'*32+' '+','.join(f'{i:032x}' for i in range(21))).encode(),b'backups\x00',b'backups\n']:
            with self.subTest(request=request):
                files=self.run_case(request)
                self.assertNotEqual(files['rc'],'0',files['worker.log'])
                self.assertNotIn('helper-calls',files)
                self.assertNotIn('systemctl.log',files)

if __name__=='__main__': unittest.main()
