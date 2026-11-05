#!/usr/bin/env python3
"""Isolated stdlib C ABI regressions. No root, service, or production /run access."""
import base64
import concurrent.futures
import ctypes as c
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
PREFIX = '/v0/management/plugins/cpa-updater/'

class Buf(c.Structure):
    _fields_ = [('ptr', c.c_void_p), ('len', c.c_size_t)]
CALL = c.CFUNCTYPE(c.c_int, c.c_char_p, c.c_void_p, c.c_size_t, c.POINTER(Buf))
FREE = c.CFUNCTYPE(None, c.c_void_p, c.c_size_t)
SHUT = c.CFUNCTYPE(None)
class Plugin(c.Structure):
    _fields_ = [('abi_version', c.c_uint32), ('call', CALL), ('free_buffer', FREE), ('shutdown', SHUT)]

class Regression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='cpa-plugin-test-')
        cls.sandbox = Path(cls.tmp.name)
        (cls.sandbox / 'inbox').mkdir()
        so = cls.sandbox / 'plugin.so'
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC', '-shared',
                        '-DCPA_TEST', '-DCPA_RUN="' + str(cls.sandbox) + '"',
                        '-DCPA_STATUS_UID=' + str(os.getuid()), str(ROOT / 'cpa-updater.c'), '-o', str(so)], check=True)
        cls.lib = c.CDLL(str(so))
        cls.p = Plugin()
        cls.lib.cliproxy_plugin_init.argtypes = [c.c_void_p, c.POINTER(Plugin)]
        assert cls.lib.cliproxy_plugin_init(None, c.byref(cls.p)) == 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        for path in self.sandbox.iterdir():
            if path.name not in ('inbox', 'plugin.so'):
                path.unlink()
        for path in (self.sandbox / 'inbox').iterdir():
            path.unlink()

    def invoke(self, method, req=None, raw=None, length=None):
        data = raw if raw is not None else json.dumps(req or {}).encode()
        out = Buf()
        self.assertEqual(self.p.call(method.encode(), data, len(data) if length is None else length, c.byref(out)), 0)
        try:
            return json.loads(c.string_at(out.ptr, out.len))
        finally:
            self.p.free_buffer(out.ptr, out.len)

    def http(self, route='status', verb='GET', query=None, **extra):
        r = self.invoke('management.handle', dict(Method=verb, Path=PREFIX + route, Query=query or {}, **extra))['result']
        return r['StatusCode'], base64.b64decode(r['Body'])

    def ready(self, raw=None):
        p = self.sandbox / 'status.json'
        p.write_text(raw or '{"state":"ready","latest":"v8.0.56"}')
        p.chmod(0o644)

    def test_metadata(self):
        m = self.invoke('plugin.register')['result']['metadata']
        self.assertEqual(m['GitHubRepository'], 'https://github.com/flying864/cliproxyapi-web-updater')
        self.assertEqual(m['Version'], '0.4.0')
        self.assertEqual(self.p.abi_version, 1)

    def test_full_routes(self):
        self.assertEqual(self.http()[0], 200)
        self.assertEqual(self.http('check', 'POST')[0], 202)
        self.assertEqual((self.sandbox / 'inbox/request').read_text(), 'check')
        self.assertEqual(self.http('check', 'GET')[0], 404)

    def test_version_binding(self):
        self.ready()
        for q in ({}, {'version': []}, {'version': ['v8.0.56','v8.0.56']}, {'version': 'v8.0.56'}, {'version': ['v8.0.55']}, {'version': ['v..']}, {'version': ['v8.0.56;id']}):
            self.assertEqual(self.http('update', 'POST', q, Body='eyJ2ZXJzaW9uIjoidjguMC41NiJ9')[0], 409)
        self.assertEqual(self.http('update', 'POST', {'version':['v8.0.56']})[0], 202)
        self.assertEqual((self.sandbox / 'inbox/request').read_text(), 'update v8.0.56')
        self.assertEqual(self.http('update', 'POST', {'version':['v8.0.56']})[0], 409)

    def test_top_level_and_length(self):
        for raw in (b'{"nested":{"Method":"GET","Path":"'+PREFIX.encode()+b'status"}}', b'{"Method":"GET","Method":"POST","Path":"'+PREFIX.encode()+b'status"}', b'{"Method":"GET"} trailing', b'{"Method":"GET",}', b'{"Method":"GET"}\x00{}'):
            self.assertIn(self.invoke('management.handle', raw=raw)['result']['StatusCode'], (400,404))
        raw = b'{"Method":"GET","Path":"'+PREFIX.encode()+b'status"}'
        self.assertEqual(self.invoke('management.handle', raw=raw+b'junk', length=len(raw))['result']['StatusCode'],200)
        self.assertEqual(self.invoke('management.handle', raw=raw, length=len(raw)-1)['result']['StatusCode'],400)

    def test_status_properties(self):
        self.ready()
        p = self.sandbox / 'status.json'
        p.chmod(0o666)
        self.assertEqual(self.http()[0],503)
        p.unlink()
        p.symlink_to(self.sandbox / 'missing')
        self.assertEqual(self.http()[0],503)
        p.unlink()
        self.ready('{"nested":{"state":"ready","latest":"v8.0.56"}}')
        self.assertEqual(self.http('update','POST',{'version':['v8.0.56']})[0],409)
        self.ready('{"state":"ready","latest":"v8.0.56","latest":"v8.0.57"}')
        self.assertEqual(self.http('update','POST',{'version':['v8.0.56']})[0],503)

    def test_concurrent_single_link(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            codes = list(pool.map(lambda _: self.http('check','POST')[0], range(48)))
        self.assertEqual(codes.count(202),1)
        self.assertEqual(codes.count(409),47)
        st = (self.sandbox / 'inbox/request').stat()
        self.assertEqual(st.st_nlink,1)
        self.assertEqual(st.st_mode & 0o777,0o600)
        self.assertEqual(st.st_uid,os.getuid())
        self.assertEqual(len(list((self.sandbox / 'inbox').iterdir())),1)

    def test_processing_and_status_bounds(self):
        (self.sandbox / 'processing').write_text('check')
        self.assertEqual(self.http('check', 'POST')[0],409)
        (self.sandbox / 'processing').unlink()
        for raw in ('{} trailing', '{"state":"ready",}', '{"state":"ready" "latest":"v8.0.56"}', 'x' * 8193, ''):
            p = self.sandbox / 'status.json'
            p.write_text(raw)
            p.chmod(0o644)
            self.assertEqual(self.http()[0],503)
        self.ready()
        os.link(self.sandbox / 'status.json',self.sandbox / 'other')
        self.assertEqual(self.http()[0],503)

    def test_nested_fields_are_not_dispatch(self):
        raw = {'nested': {'Method':'POST','Path':PREFIX+'check'}, 'Method':'GET','Path':PREFIX+'status'}
        self.assertEqual(self.invoke('management.handle', raw)['result']['StatusCode'],200)
        self.assertFalse((self.sandbox / 'inbox/request').exists())
        self.ready()
        for query in ({'nested':{'version':['v8.0.56']}}, {'version':[{'value':'v8.0.56'}]}):
            self.assertEqual(self.http('update','POST',query)[0],409)
        for v in ('v.0.56','v8..56','v8.0.','v8.0.56.1','v8.0.56\n','v'+'1'*40+'.0.1'):
            self.ready(json.dumps({'state':'ready','latest':v}))
            self.assertEqual(self.http('update','POST',{'version':[v]})[0],409)

    def test_panel(self):
        r = self.invoke('management.handle', {'Method':'GET','Path':'/v0/resource/plugins/cpa-updater/panel'})['result']
        self.assertEqual(r['StatusCode'],200)
        body = base64.b64decode(r['Body'])
        self.assertIn(b'encodeURIComponent(v)',body)
        self.assertNotIn(b'localStorage',body)

if __name__ == '__main__':
    unittest.main(verbosity=2)
