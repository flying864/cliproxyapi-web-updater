"""Run unchanged entry points in disposable bwrap mounts; no host service calls."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parents[1]
_TEMP = tempfile.TemporaryDirectory(prefix='cpa-installer-tests-')
SCRATCH = Path(_TEMP.name)

SYSTEMCTL = '''#!/usr/bin/python3
import json,sys
from pathlib import Path
p=Path('/run/ctl.json'); s=json.loads(p.read_text()); a=sys.argv[1:]; verb=a[0]; u=a[-1]
s.setdefault(u, {'enabled':False,'active':u=='cliproxyapi.service'})
x=s[u]
if verb=='show':
 field=a[a.index('-p')+1]; u=a[1]; x=s.setdefault(u, {'enabled':False,'active':u=='cliproxyapi.service'})
 print({'User':s.get('identity','cliproxy'),'Group':'cliproxy','ExecStart':'{ path=/opt/cliproxyapi/cli-proxy-api ; argv[]=/opt/cliproxyapi/cli-proxy-api --config /opt/cliproxyapi/config.yaml --local-model ; ignore_errors=no ; }','WorkingDirectory':'/opt/cliproxyapi','LoadState':'loaded' if Path('/etc/systemd/system/'+u).exists() or u=='cliproxyapi.service' else 'not-found'}[field])
elif verb in ('is-active','is-enabled'):
 sys.exit(0 if x['active' if verb=='is-active' else 'enabled'] else 1)
elif verb in ('enable','disable','start','stop','restart'):
 if verb=='enable' and s.get('fail_trigger') and u.endswith('.path'):
  s['fail_trigger']=False; p.write_text(json.dumps(s)); sys.exit(1)
 if verb in ('enable','disable'): x['enabled']=verb=='enable'
 if verb in ('start','stop','restart') or '--now' in a: x['active']=verb not in ('stop','disable')
p.write_text(json.dumps(s))
'''
TMPFILES = '''#!/usr/bin/python3
import os,pwd,grp
from pathlib import Path
for line in Path('/etc/tmpfiles.d/cliproxy-updater.conf').read_text().splitlines():
 _,name,mode,user,group,*_=line.split(); p=Path(name); p.mkdir(exist_ok=True); os.chmod(p,int(mode,8)); os.chown(p,pwd.getpwnam(user).pw_uid,grp.getgrnam(group).gr_gid)
'''


def inside(scenario):
    assert os.geteuid() == 0 and Path('/run/sandbox-marker').exists()
    os.umask(0o022)
    for d in ['/opt/cliproxyapi', '/etc/systemd/system', '/etc/tmpfiles.d', '/usr/local/libexec', '/usr/local/bin', '/var/lib', '/var/tmp', '/tmp', '/root']:
        Path(d).mkdir(parents=True, exist_ok=True)
    # CI explicitly exercises real uid 1000. Restricted local tool sandboxes
    # use a labeled single-UID boundary fixture, not privilege-drop evidence.
    uid = 1000 if os.environ.get('CPA_TEST_REAL_UID') == '1' else 0
    Path('/etc/passwd').write_text(f'root:x:0:0:root:/root:/bin/bash\ncliproxy:x:{uid}:{uid}:fixture:/nonexistent:/usr/sbin/nologin\n')
    Path('/etc/group').write_text(f'root:x:0:\ncliproxy:x:{uid}:\n')
    for name, text in [('systemctl', SYSTEMCTL), ('systemd-tmpfiles', TMPFILES)]:
        p = Path('/usr/local/bin') / name; p.write_text(text); p.chmod(0o755)
    os.environ['PATH'] = '/usr/local/bin:/usr/bin:/usr/sbin:/bin'
    os.environ['TMPDIR'] = '/run'
    for name in ['cli-proxy-api', 'config.yaml']:
        p = Path('/opt/cliproxyapi') / name; p.write_text('fixture'); p.chmod(0o755 if name == 'cli-proxy-api' else 0o600)
    key = Path('/root/cliproxyapi-admin-key'); key.write_text('sandbox-only'); key.chmod(0o600)
    Path('/opt/cliproxyapi/auths').mkdir(mode=0o700)
    Path('/opt/cliproxyapi/plugins').mkdir(mode=0o700)
    if uid:
        for name in ['plugins', 'auths', 'config.yaml']:
            os.chown('/opt/cliproxyapi/' + name, uid, uid)
        os.chown('/opt/cliproxyapi', 0, uid)
        Path('/opt/cliproxyapi').chmod(0o750)
    ctl = Path('/run/ctl.json'); ctl.write_text(json.dumps({'identity':'root' if scenario == 'identity' else 'cliproxy'}))
    config = {'enabled': False, 'dir': '/opt/cliproxyapi/plugins', 'configs': {}}
    original = json.loads(json.dumps(config)); failed = False
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def handle_request(self):
            nonlocal failed
            path=self.path; code=200
            if path == '/v8/management/config/oauth/auth-dir': data='/opt/cliproxyapi/auths'
            elif path == '/v8/management/config/plugins': data=config
            elif path.startswith('/v8/management/config/plugins/'):
                field=path.removeprefix('/v8/management/config/plugins/')
                if self.command == 'DELETE': config['configs'].pop('cpa-updater',None)
                else:
                    value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if scenario == 'api' and not failed:
                        failed=True; code=500
                    elif field == 'enabled': config['enabled']=value
                    else: config['configs']['cpa-updater']=value
                data={}
            elif path == '/v8/management/plugins':
                enabled=config['enabled'] and config['configs'].get('cpa-updater',{}).get('enabled',False)
                data={'plugins_dir':'/opt/cliproxyapi/plugins','plugins':[{'id':'cpa-updater','registered':scenario!='registered','effective_enabled':enabled}]}
            elif path.endswith('/panel'): data='panel'
            else: data={'state':'idle'}
            self.send_response(code); self.end_headers(); self.wfile.write(json.dumps(data).encode())
        do_GET=do_PUT=do_DELETE=handle_request
    server=HTTPServer(('127.0.0.1',8317),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def invoke(name, success=True, extra=()):
        result=subprocess.run(['bash',str(ROOT/name),*extra],capture_output=True,text=True,timeout=90)
        print(name,result.returncode,result.stdout,result.stderr,flush=True)
        if result.returncode and success:
            probe=subprocess.run(['bash',str(ROOT/'cliproxy-updater-worker'),'--preflight'],capture_output=True,text=True); print('PREFLIGHT',probe.returncode,probe.stderr,flush=True)
        assert (result.returncode==0)==success, result.stderr
    if scenario == 'preflight-missing':
        for missing, mode in [('/run/cliproxy-updater', 0o750), ('/var/lib/cliproxy-updater', 0o700), ('/var/lib/cliproxy-updater/backups', 0o700), ('/var/lib/cliproxy-updater-status', 0o750)]:
            probe = subprocess.run(['bash', str(ROOT/'cliproxy-updater-worker'), '--preflight'], capture_output=True, text=True)
            assert probe.returncode != 0 and missing in probe.stderr, probe.stderr
            print('EXPECTED RED missing', missing, probe.stderr, flush=True)
            Path(missing).mkdir(mode=mode)
        return
    libexec = Path('/usr/local/libexec')
    if scenario in ('missing-libexec', 'uninstall-missing-libexec', 'symlink-libexec'):
        libexec.rmdir()
    if scenario == 'symlink-libexec':
        libexec.symlink_to('/opt/cliproxyapi', target_is_directory=True)
    if scenario == 'unsafe-libexec':
        libexec.chmod(0o777)
    if scenario == 'unsafe-libexec-parent':
        libexec.rmdir()
        libexec.parent.chmod(0o777)
    if scenario in ('unsafe-libexec', 'symlink-libexec', 'unsafe-libexec-parent'):
        invoke('install.sh', False)
        assert not Path('/usr/local/libexec/cliproxy-updater-worker').exists()
        assert not Path('/opt/cliproxyapi/plugins/cpa-updater.so').exists()
        return
    if scenario == 'uninstall-missing-libexec':
        invoke('uninstall.sh', False)
        assert not libexec.exists()
        return
    if scenario == 'lock':
        Path('/var/lib/cliproxy-updater').mkdir(mode=0o700)
        with open('/var/lib/cliproxy-updater/lock','w') as f:
            fcntl.flock(f,fcntl.LOCK_EX); invoke('install.sh',False)
        assert not Path('/run/cliproxy-updater').exists()
    elif scenario == 'worker-only':
        old=json.loads(json.dumps(config))
        invoke('install.sh',extra=('--worker-only',))
        assert config==old
        assert not Path('/opt/cliproxyapi/plugins/cpa-updater.so').exists()
        assert Path('/usr/local/libexec/cliproxy-updater-runtime.py').is_file()
        assert json.loads(Path('/var/lib/cliproxy-updater-status/status.json').read_text())['backups_protocol']==1
        assert len(json.loads(Path('/var/lib/cliproxy-updater/backup-registry.json').read_text()))==1
    elif scenario == 'identity': invoke('install.sh',False)
    elif scenario in ('api','registered'):
        invoke('install.sh',False)
        assert config==original, config
        assert not Path('/opt/cliproxyapi/plugins/cpa-updater.so').exists()
    else:
        invoke('install.sh')
        registry=json.loads(Path('/var/lib/cliproxy-updater/backup-registry.json').read_text())
        assert len(registry)==1 and next(iter(registry.values()))['kind']=='install'
        st = libexec.stat(); assert st.st_uid == 0 and st.st_mode & 0o022 == 0 and not libexec.is_symlink()
        assert Path('/opt/cliproxyapi/plugins').stat().st_mode&0o777==0o700
        for p,mode in [('/var/lib/cliproxy-updater',0o700),('/var/lib/cliproxy-updater/backups',0o700),('/run/cliproxy-updater',0o750),('/run/cliproxy-updater/inbox',0o730),('/var/lib/cliproxy-updater-status',0o750)]:
            st=Path(p).stat(); assert st.st_uid==0 and st.st_mode&0o777==mode,(p,oct(st.st_mode))
        subprocess.run(['bash',str(ROOT/'cliproxy-updater-worker'),'--preflight'],check=True,timeout=20)
        # Validate exact generated units against the private test filesystem.
        result = subprocess.run(['systemd-analyze', 'verify', '--man=no',
                                 *map(str, Path('/etc/systemd/system').glob('cliproxy-updater*'))],
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        if scenario=='trigger':
            states=json.loads(ctl.read_text()); states['cliproxy-updater-recover.service']['enabled']=False; states['fail_trigger']=True; ctl.write_text(json.dumps(states))
            invoke('install.sh',False)
            restored=json.loads(ctl.read_text())
            assert not restored['cliproxy-updater-recover.service']['enabled']
            assert restored['cliproxy-updater.path']['enabled'] and restored['cliproxy-updater.path']['active']
        else:
            invoke('install.sh'); invoke('uninstall.sh')
            assert not Path('/opt/cliproxyapi/plugins/cpa-updater.so').exists()
            assert Path('/var/lib/cliproxy-updater/backups').is_dir()
            assert config['configs']['cpa-updater']['enabled'] is False
    server.shutdown()
    print('PASS',scenario,flush=True)


def run(scenario):
    SCRATCH.mkdir(parents=True,exist_ok=True)
    ctlfile = SCRATCH / 'systemctl'; ctlfile.write_text(SYSTEMCTL); ctlfile.chmod(0o755)
    command=([] if os.geteuid() == 0 else ['sudo','-n']) + ['bwrap','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts','--cap-add','ALL','--tmpfs','/','--tmpfs','/usr','--ro-bind','/usr/bin','/usr/bin','--ro-bind','/usr/sbin','/usr/sbin','--ro-bind','/usr/lib','/usr/lib','--ro-bind','/usr/libexec','/usr/libexec','--ro-bind','/usr/lib64','/usr/lib64','--ro-bind','/usr/include','/usr/include','--ro-bind','/usr/share','/usr/share','--symlink','usr/bin','/bin','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--ro-bind',str(ROOT),str(ROOT),'--proc','/proc','--dev','/dev']
    for p in ['/run','/opt','/etc','/usr/local','/var','/root']:
        command+=['--tmpfs',p]
    command+=['--ro-bind','/etc/pam.d','/etc/pam.d','--ro-bind','/etc/login.defs','/etc/login.defs','--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache','--ro-bind','/etc/ssl','/etc/ssl','--ro-bind',str(ctlfile),'/usr/bin/systemctl','--dir','/run/sandbox-marker','--clearenv','--setenv','TMPDIR','/run','--setenv','HOME','/root','--setenv','PATH','/usr/local/bin:/usr/bin:/usr/sbin:/bin','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','CPA_TEST_REAL_UID',os.environ.get('CPA_TEST_REAL_UID','0'),'--chdir',str(ROOT),'--','/usr/bin/python3',str(Path(__file__).resolve()),'--inside',scenario]
    return subprocess.run(command,capture_output=True,text=True,timeout=180)

if __name__=='__main__':
    if sys.argv[1]=='--inside': inside(sys.argv[2])
    else:
        result=run(sys.argv[1]); print(result.stdout,result.stderr); sys.exit(result.returncode)
