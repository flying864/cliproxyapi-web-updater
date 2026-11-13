"""Production worker in bwrap; only OS/service/network boundaries are simulated."""
import hashlib, json, os, subprocess, tarfile, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# Multi-UID DAC needs privileged bwrap; tests never change host confinement.
_TEMP=tempfile.TemporaryDirectory(prefix='cpa-worker-')
BASE=Path(_TEMP.name)
SCRATCH=BASE
SCRATCH.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT
REAL_UID = os.environ.get('CPA_TEST_REAL_UID') == '1'
MOCKS={
'runuser':r'''#!/usr/bin/python3
import os,pwd,sys
u=pwd.getpwnam(sys.argv[2])
if u.pw_uid != os.geteuid(): os.setgroups([]); os.setgid(u.pw_gid); os.setuid(u.pw_uid)
os.execvp(sys.argv[4],sys.argv[4:])
''',

'sleep': '#!/bin/sh\nexit 0\n',
'systemctl':r'''#!/bin/bash
printf '%s\n' "$*" >> /sim/systemctl.log
case "$1" in
 show)
  case "$4" in NRestarts) if [[ $CASE == crashrestart && ! -f /sim/start-failed ]] && [[ $(stat -c %s /opt/cliproxyapi/cli-proxy-api) -gt 1000 ]]; then printf '1\n'; else printf '0\n'; fi;; MainPID) printf '101\n';; User|Group) [[ $CASE != wrong_identity ]] && printf 'cliproxy\n' || printf 'root\n';; *) printf '{ path=/opt/cliproxyapi/cli-proxy-api ; argv[]=/opt/cliproxyapi/cli-proxy-api -config /opt/cliproxyapi/config.yaml ; ignore_errors=no ; }\n';; esac;;
 is-active) [[ $(cat /sim/service-state) == active ]];;
 stop) printf stopped > /sim/service-state;;
 start)
  if [[ $CASE == rollback_copy_failure || $CASE == rollback_success ]]; then
   if [[ ! -f /sim/start-failed ]]; then touch /sim/start-failed; exit 1; fi
  fi
  if [[ $CASE == term && ! -e /sim/signaled ]]; then touch /sim/signaled; kill -TERM "$PPID"; exit 1; fi
  if [[ $CASE == killed && ! -e /sim/signaled ]]; then touch /sim/signaled; kill -KILL "$PPID"; exit 1; fi
  if [[ $CASE == int || $CASE == hup ]]; then
   if [[ ! -e /sim/signaled ]]; then touch /sim/signaled; kill -${CASE^^} "$PPID"; exit 1; fi
  fi
  if [[ $CASE == delayed_recovery && ! -e /sim/start-failed ]]; then touch /sim/start-failed; exit 1; fi
  printf active > /sim/service-state;;
 *) exit 2;;
esac
''',

# runuser mock uses real setgroups/setgid/setuid; avoids host PAM dependencies.

'curl':r'''#!/bin/bash
out=''
while (($#)); do
 case "$1" in -o) out=$2; shift 2;; *) url=$1; shift;; esac
done
printf '%s\n' "$url" >> /sim/curl.log
case "$url" in
 */releases/latest) [[ $CASE != offline ]] || exit 1; printf '{"tag_name":"v8.0.56"}\n';;
 */checksums.txt) if [[ $CASE == checksum ]]; then printf 'bad checksum' > "$out"; else /usr/bin/cp /fixtures/checksums.txt "$out"; fi;;
 */CLIProxyAPI_8.0.56_linux_amd64.tar.gz) /usr/bin/cp /fixtures/CLIProxyAPI_8.0.56_linux_amd64.tar.gz "$out";;
 */v8/management/config/oauth/auth-dir) printf '"/srv/actual-auth"';;
 */v8/management/config)
  version=8.0.55
  if [[ -e /opt/cliproxyapi/.cli-proxy-api.rollback ]] && [[ $(stat -c %s /opt/cliproxyapi/cli-proxy-api) -gt 1000 ]]; then version=8.0.56; fi
  [[ $CASE != running_mismatch ]] || version=8.0.55
  printf 'HTTP/1.1 401 Unauthorized\r\nX-CPA-VERSION: %s\r\n\r\n' "$version";;
 */v1/models)
  if [[ $CASE == delayed_recovery && ! -e /sim/health-delayed ]]; then touch /sim/health-delayed; printf '000'; exit 7; fi
  printf '200';;
 *) printf 'Unexpected URL mock: %s\n' "$url" >&2; exit 2;;
esac
''',
'mv':r'''#!/bin/bash
if [[ $CASE == rename_failure && $* == *'/opt/cliproxyapi/.cli-proxy-api.new'* ]]; then
 printf 'Injected rename failure\n' >&2; exit 1
fi
exec /real/mv "$@"
''',
'df':r'''#!/bin/bash
if [[ $CASE == low_space ]]; then
 printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture 100 99 1 99%% /\n'
else exec /real/df "$@"; fi
''',
'cp':r'''#!/bin/bash
if [[ $CASE == rollback_copy_failure && $* == *'.cli-proxy-api.restore'* ]]; then
 printf 'Injected rollback copy failure\n' >&2; exit 1
fi
exec /real/cp "$@"
''',
}

def build_fixtures():
    f=BASE/'fixtures'; f.mkdir(exist_ok=True)
    code=f/'mock-binary.c'
    code.write_text('#include <stdio.h>\nint main(void){puts("CLIProxyAPI Version: 8.0.56, Commit: review-mock");return 0;}\n')
    subprocess.run(['gcc',str(code),'-o',str(f/'cli-proxy-api')],check=True)
    with (f/'cli-proxy-api').open('ab') as out: out.truncate(1_000_000)
    asset=f/'CLIProxyAPI_8.0.56_linux_amd64.tar.gz'
    with tarfile.open(asset,'w:gz') as t: t.add(f/'cli-proxy-api',arcname='cli-proxy-api')
    (f/'checksums.txt').write_text(hashlib.sha256(asset.read_bytes()).hexdigest()+'  '+asset.name+'\n')
    m=BASE/'mocks'; m.mkdir(exist_ok=True)
    for n,s in MOCKS.items():
        p=m/n; p.write_text(s); p.chmod(0o755)
    (f/'local_snapshot_boundary.py').write_text("""import importlib.util,sys,tarfile,os
spec=importlib.util.spec_from_file_location('actual_runtime','/source/updater_runtime.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
if sys.argv[1:]==['version']:print(m.WORKER_VERSION)
elif sys.argv[1:]==['preflight']:m.check_service()
elif sys.argv[1]=='backups-register':m.backup_register(sys.argv[2],sys.argv[3])
elif sys.argv[1:]==['verify-auth']:
 if os.environ.get('CASE')=='changed_auth':raise ValueError('auth-dir changed')
elif sys.argv[1]=='snapshot':
 with tarfile.open(sys.argv[2],'w:gz') as out:m.archive_sources(out,[('config.yaml',m.CONFIG),('auth-dir',m.approved_auth()),('plugins',m.APP+'/plugins')])
else:raise SystemExit(2)
""")
    return f,m

def sandbox_args(f,m):
    # Root CI already has mount privileges; avoid a one-UID user namespace
    # losing access to runner-owned parent directories. Filesystem/network stay isolated.
    isolation = ['--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts'] if os.geteuid() == 0 else ['--unshare-all']
    if os.geteuid() != 0:
        raise RuntimeError('Run worker namespace tests with sudo; no host fallback or implicit escalation')
    isolation = ['--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
    cmd=['bwrap',*isolation,'--cap-add','ALL','--die-with-parent','--ro-bind','/usr','/usr',
         '--symlink','usr/bin','/bin','--symlink','usr/sbin','/sbin',
         '--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
         '--tmpfs','/usr/local','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--tmpfs','/var',
         '--tmpfs','/run','--tmpfs','/opt','--tmpfs','/etc','--dir','/etc/alternatives',
         '--ro-bind','/usr/bin/mawk','/etc/alternatives/awk','--dir','/real',
         '--ro-bind','/usr/bin/mv','/real/mv','--ro-bind','/usr/bin/cp','/real/cp','--ro-bind','/usr/bin/df','/real/df',
         '--ro-bind',str(SOURCE),'/source','--ro-bind',str(BASE),'/review',
         '--ro-bind',str(f),'/fixtures','--uid','0','--gid','0','--cap-add','ALL','--clearenv',
         '--setenv','PATH','/usr/sbin:/usr/bin:/sbin:/bin','--setenv','LC_ALL','C',
         '--setenv','CPA_TEST_REAL_UID','1' if REAL_UID else '0']
    for n in MOCKS:
        p=Path('/usr/bin')/n
        if not p.exists(): p=Path('/usr/sbin')/n
        cmd+=['--ro-bind',str(m/n),str(p)]
    return cmd

SETUP=r'''
umask 022
uid=0; [[ $CPA_TEST_REAL_UID != 1 ]] || uid=1234
printf 'root:x:0:0::/:/bin/bash\ncliproxy:x:%s:%s::/home/cliproxy:/bin/bash\n' "$uid" "$uid" > /etc/passwd
printf 'root:x:0:\ncliproxy:x:%s:\n' "$uid" > /etc/group
mkdir -p /opt/cliproxyapi/auths /opt/cliproxyapi/plugins /run/cliproxy-updater/inbox /var/lib/cliproxy-updater/backups /var/tmp /var/lib/cliproxy-updater-status /usr/local/libexec /srv/actual-auth /root
cp /source/updater_runtime.py /usr/local/libexec/cliproxy-updater-runtime.py
if [[ $CPA_TEST_REAL_UID != 1 ]]; then
 # Local single-UID worker control-flow only. CI explicitly runs the real helper.
 cp /fixtures/local_snapshot_boundary.py /usr/local/libexec/cliproxy-updater-runtime.py
fi
chmod 0700 /var/lib/cliproxy-updater /var/lib/cliproxy-updater/backups
chmod 0730 /run/cliproxy-updater/inbox
printf fixture-only > /root/cliproxyapi-admin-key
chmod 0600 /root/cliproxyapi-admin-key
if [[ $CPA_TEST_REAL_UID == 1 ]]; then
 python3 /source/tests/auth_api_fixture.py &
 python3 -c 'import time,pathlib; p=pathlib.Path("/run/auth-fixture-ready"); end=time.monotonic()+5
while not p.exists() and time.monotonic()<end: time.sleep(.01)
assert p.exists()'
fi
printf '{"protocol":1,"auth_dir":"/srv/actual-auth"}\n' > /var/lib/cliproxy-updater/deployment.json
chmod 0600 /var/lib/cliproxy-updater/deployment.json
printf '#!/bin/sh\nprintf "CLIProxyAPI Version: 8.0.55, Commit: mock\\n"\n' > /opt/cliproxyapi/cli-proxy-api
chmod 0755 /opt/cliproxyapi/cli-proxy-api
printf 'mock: true\n' > /opt/cliproxyapi/config.yaml
chmod 0600 /opt/cliproxyapi/config.yaml
chown cliproxy:cliproxy /opt/cliproxyapi/config.yaml /srv/actual-auth /opt/cliproxyapi/plugins
printf 'update v8.0.56' > /run/cliproxy-updater/inbox/request
printf active > /sim/service-state
[[ $CASE != mismatch ]] || printf 'update v8.0.54' > /run/cliproxy-updater/inbox/request
[[ $CASE != stale ]] || touch /run/cliproxy-updater/processing
chown cliproxy:cliproxy /run/cliproxy-updater/inbox/request
if [[ $CASE == unsafe_new ]]; then ln -s /opt/cliproxyapi/config.yaml /opt/cliproxyapi/.cli-proxy-api.new; fi
bash /source/cliproxy-updater-worker --consume > /sim/worker.log 2>&1
rc=$?
printf '%s' "$rc" > /sim/exit-code
if [[ $CASE == killed ]]; then CASE=offline bash /source/cliproxy-updater-worker --recover-update-failure >> /sim/worker.log 2>&1; fi
[[ ! -e /var/lib/cliproxy-updater/transaction.json ]] || touch /sim/transaction-left
[[ ! -e /opt/cliproxyapi/.cli-proxy-api.rollback ]] || touch /sim/rollback-left
cp /var/lib/cliproxy-updater-status/status.json /sim/status.json
[[ ! -e /var/lib/cliproxy-updater/backup-registry.json ]] || cp /var/lib/cliproxy-updater/backup-registry.json /sim/backup-registry.json
[[ ! -e /run/cliproxy-updater/processing ]] || touch /sim/processing-left
/opt/cliproxyapi/cli-proxy-api --version > /sim/installed-version
'''


class WorkerTests(unittest.TestCase):
 def test_rename_failure_restores_service(self):
  f,m=build_fixtures()
  with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
   sim=Path(d)
   p=subprocess.run(sandbox_args(f,m)+['--bind',str(sim),'/sim','--setenv','CASE','rename_failure','/bin/bash','-c',SETUP],capture_output=True,text=True,timeout=60)
   self.assertEqual(p.returncode,0,p.stderr)
   self.assertEqual((sim/'service-state').read_text(),'active',(sim/'worker.log').read_text())
   self.assertEqual(json.loads((sim/'status.json').read_text())['state'],'rolled_back')
 def test_scenarios(self):
  f,m=build_fixtures()
  for case,state,service in [('low_space','error','active'),('success','success','active'),('offline','error','active'),('changed_auth','error','active'),('running_mismatch','rolled_back','active'),('crashrestart','rolled_back','active'),('rollback_success','rolled_back','active'),('rollback_copy_failure','rollback_failed','stopped'),('term','rolled_back','active'),('int','rolled_back','active'),('hup','rolled_back','active'),('delayed_recovery','rolled_back','active'),('killed','rolled_back','active'),('stale','success','active'),('mismatch','needs_recheck','active'),('checksum','error','active'),('wrong_identity','error','active'),('unsafe_new',None,'active')]:
   with self.subTest(case=case), tempfile.TemporaryDirectory(dir=SCRATCH) as d:
    sim=Path(d)
    p=subprocess.run(sandbox_args(f,m)+['--bind',str(sim),'/sim','--setenv','CASE',case,'/bin/bash','-c',SETUP],capture_output=True,text=True,timeout=60)
    self.assertEqual(p.returncode,0,p.stderr)
    log=(sim/'worker.log').read_text()
    self.assertEqual((sim/'service-state').read_text(),service,log)
    if case=='low_space':
     self.assertIn('Insufficient free space',log)
     self.assertNotIn('stop cliproxyapi.service',(sim/'systemctl.log').read_text())
    if state:
     status=json.loads((sim/'status.json').read_text()); self.assertEqual(status['state'],state,log)
     if state=='success':
      self.assertEqual(status['current'],'8.0.56')
      self.assertTrue((sim/'backup-registry.json').exists(),log)
      self.assertEqual(len(json.loads((sim/'backup-registry.json').read_text())),1)
     else: self.assertFalse((sim/'backup-registry.json').exists(),log)
    self.assertFalse((sim/'processing-left').exists(),log)
    if case=='unsafe_new': self.assertNotEqual((sim/'exit-code').read_text(),'0',log)
    self.assertEqual((sim/'transaction-left').exists(),case=='rollback_copy_failure',log)
    if case in ('term','killed'): self.assertNotEqual((sim/'exit-code').read_text(),'0')
 def test_archive_budget(self):
  f,m=build_fixtures()
  asset=f/'CLIProxyAPI_8.0.56_linux_amd64.tar.gz'
  with tarfile.open(asset,'w:gz') as archive:
   for i in range(129):
    archive.addfile(tarfile.TarInfo('padding-'+str(i)))
  (f/'checksums.txt').write_text(hashlib.sha256(asset.read_bytes()).hexdigest()+'  '+asset.name+'\n')
  with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
   p=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','--setenv','CASE','archive_budget','/bin/bash','-c',SETUP],capture_output=True,text=True,timeout=30)
   sim=Path(d)
   self.assertEqual(p.returncode,0,p.stderr)
   self.assertIn('Archive budget exceeded',(sim/'worker.log').read_text())
   self.assertNotIn('stop cliproxyapi.service',(sim/'systemctl.log').read_text())
   self.assertFalse((sim/'transaction-left').exists())
 def test_preflight_read_only(self):
  f,m=build_fixtures()
  script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
find /opt /run /var -printf '%p %m %s %T@\n' | sort > /sim/before
bash /source/cliproxy-updater-worker --preflight
rc=$?
find /opt /run /var -printf '%p %m %s %T@\n' | sort > /sim/after
cmp /sim/before /sim/after || exit 10
exit "$rc"
'''
  with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
   p=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','--setenv','CASE','preflight','/bin/bash','-c',script],capture_output=True,text=True,timeout=20)
   self.assertEqual(p.returncode,0,p.stderr)
   self.assertFalse((Path(d)/'curl.log').exists())
 def test_disk_version_probe_classification(self):
  f,m=build_fixtures()
  for output,code,message in [('ignored',1,'Unable to probe on-disk version'),('CLIProxyAPI Version: 8.0.54, Commit: fixture',0,'Running and on-disk versions differ')]:
   script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]
   script += "printf '#!/bin/sh\necho \"%s\"\nexit %s\n' > /opt/cliproxyapi/cli-proxy-api\n" % (output,code)
   script += 'bash /source/cliproxy-updater-worker --check > /sim/worker.log 2>&1; [[ $? != 0 ]]'
   with self.subTest(code=code), tempfile.TemporaryDirectory(dir=SCRATCH) as d:
    p=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','--setenv','CASE','probe','/bin/bash','-c',script],capture_output=True,text=True,timeout=20)
    self.assertEqual(p.returncode,0,p.stderr)
    log=(Path(d)/'worker.log').read_text()
    self.assertIn(message,log)
    if code: self.assertNotIn('Running and on-disk versions differ',log)
    self.assertNotIn('stop cliproxyapi.service',(Path(d)/'systemctl.log').read_text())
 def test_version_timeout(self):
  f,m=build_fixtures()
  script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
printf '#!/bin/sh\nwhile :; do :; done\n' > /opt/cliproxyapi/cli-proxy-api
bash /source/cliproxy-updater-worker --check > /sim/worker.log 2>&1
rc=$?
[[ $rc != 0 ]] || exit 10
python3 -c 'from pathlib import Path; assert "releases/latest" not in Path("/sim/curl.log").read_text()'
'''
  with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
   p=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','--setenv','CASE','timeout','/bin/bash','-c',script],capture_output=True,text=True,timeout=15)
   self.assertEqual(p.returncode,0,p.stderr)
 def test_recovery_returns_without_release_query(self):
  f,m=build_fixtures()
  for argument in ('--check','--recover'):
   with self.subTest(argument=argument), tempfile.TemporaryDirectory(dir=SCRATCH) as d:
    script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
bash /source/cliproxy-updater-worker --consume > /sim/worker.log 2>&1
[[ -f /var/lib/cliproxy-updater/transaction.json ]] || exit 10
: > /sim/curl.log
export CASE=offline
bash /source/cliproxy-updater-worker ARG >> /sim/worker.log 2>&1 || exit 11
[[ ! -e /var/lib/cliproxy-updater/transaction.json ]] || exit 12
! /usr/bin/grep -q releases /sim/curl.log
'''
    p=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','--setenv','CASE','rollback_copy_failure','/bin/bash','-c',script.replace(' ARG ',' '+argument+' ')],capture_output=True,text=True,timeout=30)
    self.assertEqual(p.returncode,0,p.stderr+(Path(d)/'worker.log').read_text())
class RecoveryTests(unittest.TestCase):
 def test_snapshot_cli_security(self):
  if not REAL_UID:
   self.skipTest('Real UID snapshot requires CPA_TEST_REAL_UID=1 on privileged isolated CI; local AppArmor forbids UID changes')
  f,m=build_fixtures()
  script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
set -e
chmod 0750 /var/lib/cliproxy-updater-status
mkdir -m 0700 /var/lib/cliproxy-updater/backups/20261105-1.0.0
printf actual-secret > /srv/actual-auth/token
chown cliproxy:cliproxy /srv/actual-auth/token
printf fake > /opt/cliproxyapi/auths/fake
python3 /usr/local/libexec/cliproxy-updater-runtime.py snapshot /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz
tar tzf /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz > /sim/archive
stat -c '%u %a' /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz > /sim/mode
rm /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz
ln -s /etc/passwd /srv/actual-auth/link
if python3 /usr/local/libexec/cliproxy-updater-runtime.py snapshot /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz; then exit 10; fi
test ! -e /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz
rm /srv/actual-auth/link
ln -s /etc/passwd /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz
if python3 /usr/local/libexec/cliproxy-updater-runtime.py snapshot /var/lib/cliproxy-updater/backups/20261105-1.0.0/runtime-config.tar.gz; then exit 11; fi
'''
  with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
   result=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','/bin/bash','-c',script],capture_output=True,text=True,timeout=20)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertIn('auth-dir/token',(Path(d)/'archive').read_text())
   self.assertNotIn('fake',(Path(d)/'archive').read_text())
   self.assertEqual((Path(d)/'mode').read_text().strip(),'0 600')

 def test_preflight_failure_retires_request_and_recovery_ignores_helper(self):
  f,m=build_fixtures()
  script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
rm /usr/local/libexec/cliproxy-updater-runtime.py
bash /source/cliproxy-updater-worker --consume > /sim/worker.log 2>&1
[[ $? != 0 && ! -e /run/cliproxy-updater/inbox/request ]] || exit 21
python3 -c 'import json; assert json.load(open("/var/lib/cliproxy-updater-status/status.json"))["state"]=="error"' || exit 22
printf '{"protocol":1,"state":"success","detail":"kept"}' > /var/lib/cliproxy-updater-status/status.json
bash /source/cliproxy-updater-worker --recover || exit 23
python3 -c 'import json; assert json.load(open("/var/lib/cliproxy-updater-status/status.json"))["state"]=="success"'
'''
  with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
   result=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','--setenv','CASE','helperfail','/bin/bash','-c',script],capture_output=True,text=True,timeout=20)
   self.assertEqual(result.returncode,0,result.stderr)

 def test_reboot(self):
  f,m=build_fixtures()
  script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
rm /run/cliproxy-updater/inbox/request
printf '{"protocol":1,"worker_version":"0.5.0","state":"success","detail":"kept"}' > /var/lib/cliproxy-updater-status/status.json
cp /var/lib/cliproxy-updater-status/status.json /sim/before
bash /source/cliproxy-updater-worker --recover || exit 11
cmp /sim/before /var/lib/cliproxy-updater-status/status.json || exit 12
printf '{"state":"installing"}' > /var/lib/cliproxy-updater-status/status.json
bash /source/cliproxy-updater-worker --recover || exit 13
cp /var/lib/cliproxy-updater-status/status.json /sim/status.json
'''
  with tempfile.TemporaryDirectory(dir=SCRATCH) as d:
   result=subprocess.run(sandbox_args(f,m)+['--bind',d,'/sim','--setenv','CASE','reboot','/bin/bash','-c',script],capture_output=True,text=True,timeout=20)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertEqual(json.loads((Path(d)/'status.json').read_text())['state'],'interrupted')

if __name__=='__main__' : unittest.main()
