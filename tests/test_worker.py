"""Production worker in bwrap; only OS/service/network boundaries are simulated."""
import hashlib, json, os, subprocess, tarfile, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# Keep fixtures alive for the entire module; tempfile honors the caller's TMPDIR.
_TEMP=tempfile.TemporaryDirectory(prefix='cpa-worker-')
BASE=Path(_TEMP.name)
SCRATCH=BASE
SCRATCH.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT
MOCKS={
'systemctl':r'''#!/bin/bash
printf '%s\n' "$*" >> /sim/systemctl.log
case "$1" in
 show)
  case "$4" in User|Group) [[ $CASE != wrong_identity ]] && printf 'cliproxy\n' || printf 'root\n';; *) printf '{ path=/opt/cliproxyapi/cli-proxy-api ; argv[]=/opt/cliproxyapi/cli-proxy-api -config /opt/cliproxyapi/config.yaml ; ignore_errors=no ; }\n';; esac;;
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

# Rootless bwrap maps one uid only; runuser cannot switch to an unmapped uid.
'runuser':r'''#!/bin/bash
shift 3
exec "$@"
''',
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
    return f,m

def sandbox_args(f,m):
    # Root CI already has mount privileges; avoid a one-UID user namespace
    # losing access to runner-owned parent directories. Filesystem/network stay isolated.
    isolation = ['--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts'] if os.geteuid() == 0 else ['--unshare-all']
    cmd=['bwrap',*isolation,'--die-with-parent','--ro-bind','/usr','/usr',
         '--symlink','usr/bin','/bin','--symlink','usr/sbin','/sbin',
         '--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
         '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--tmpfs','/var',
         '--tmpfs','/run','--tmpfs','/opt','--tmpfs','/etc','--dir','/etc/alternatives',
         '--ro-bind','/usr/bin/mawk','/etc/alternatives/awk','--dir','/real',
         '--ro-bind','/usr/bin/mv','/real/mv','--ro-bind','/usr/bin/cp','/real/cp','--ro-bind','/usr/bin/df','/real/df',
         '--ro-bind',str(SOURCE),'/source','--ro-bind',str(BASE),'/review',
         '--ro-bind',str(f),'/fixtures','--uid','0','--gid','0','--clearenv',
         '--setenv','PATH','/usr/sbin:/usr/bin:/sbin:/bin','--setenv','LC_ALL','C']
    for n in MOCKS:
        p=Path('/usr/bin')/n
        if not p.exists(): p=Path('/usr/sbin')/n
        cmd+=['--ro-bind',str(m/n),str(p)]
    return cmd

SETUP=r'''
printf 'root:x:0:0::/:/bin/bash\ncliproxy:x:0:0::/:/bin/bash\n' > /etc/passwd
printf 'root:x:0:\ncliproxy:x:0:\n' > /etc/group
mkdir -p /opt/cliproxyapi/auths /opt/cliproxyapi/plugins /run/cliproxy-updater/inbox /var/lib/cliproxy-updater/backups /var/tmp
printf '#!/bin/sh\nprintf "CLIProxyAPI Version: 8.0.55, Commit: mock\\n"\n' > /opt/cliproxyapi/cli-proxy-api
chmod 0755 /opt/cliproxyapi/cli-proxy-api
printf 'mock: true\n' > /opt/cliproxyapi/config.yaml
chmod 0600 /opt/cliproxyapi/config.yaml
printf 'update v8.0.56' > /run/cliproxy-updater/inbox/request
printf active > /sim/service-state
[[ $CASE != mismatch ]] || printf 'update v8.0.54' > /run/cliproxy-updater/inbox/request
[[ $CASE != stale ]] || touch /run/cliproxy-updater/processing
chown cliproxy:cliproxy /run/cliproxy-updater/inbox/request
if [[ $CASE == unsafe_new ]]; then ln -s /opt/cliproxyapi/config.yaml /opt/cliproxyapi/.cli-proxy-api.new; fi
bash /source/cliproxy-updater-worker --consume > /sim/worker.log 2>&1
rc=$?
printf '%s' "$rc" > /sim/exit-code
if [[ $CASE == killed ]]; then CASE=offline bash /source/cliproxy-updater-worker --recover >> /sim/worker.log 2>&1; fi
[[ ! -e /var/lib/cliproxy-updater/transaction.json ]] || touch /sim/transaction-left
[[ ! -e /opt/cliproxyapi/.cli-proxy-api.rollback ]] || touch /sim/rollback-left
cp /run/cliproxy-updater/status.json /sim/status.json
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
  for case,state,service in [('low_space','error','active'),('success','success','active'),('rollback_success','rolled_back','active'),('rollback_copy_failure','rollback_failed','stopped'),('term','rolled_back','active'),('int','rolled_back','active'),('hup','rolled_back','active'),('delayed_recovery','rolled_back','active'),('killed','rolled_back','active'),('stale','success','active'),('mismatch','needs_recheck','active'),('checksum','error','active'),('wrong_identity',None,'active'),('unsafe_new',None,'active')]:
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
     if state=='success': self.assertEqual(status['current'],'8.0.56')
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
 def test_version_timeout(self):
  f,m=build_fixtures()
  script=SETUP.split('bash /source/cliproxy-updater-worker --consume')[0]+r'''
printf '#!/bin/sh\nsleep 60\n' > /opt/cliproxyapi/cli-proxy-api
bash /source/cliproxy-updater-worker --check > /sim/worker.log 2>&1
rc=$?
[[ $rc != 0 && ! -e /sim/curl.log ]]
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
if __name__=='__main__': unittest.main()
