#!/usr/bin/env python3
"""Load the exact trusted native production build; only registration calls.

Never accepts a download URL or calls management.handle, so no queue/state path is
accessed. The loader runs in a bounded child because native code can crash Python.
"""
import argparse
import ctypes as c
import json
from pathlib import Path
import subprocess
import sys
from native_artifacts import elf_arch

REPOSITORY = 'https://github.com/flying864/cliproxyapi-web-updater'


class Buffer(c.Structure):
    _fields_ = [('ptr', c.c_void_p), ('len', c.c_size_t)]


CALL = c.CFUNCTYPE(c.c_int, c.c_char_p, c.c_void_p, c.c_size_t, c.POINTER(Buffer))
FREE = c.CFUNCTYPE(None, c.c_void_p, c.c_size_t)
SHUTDOWN = c.CFUNCTYPE(None)


class Plugin(c.Structure):
    _fields_ = [('abi_version', c.c_uint32), ('call', CALL),
                ('free_buffer', FREE), ('shutdown', SHUTDOWN)]


def load(binary, version, arch):
    if elf_arch(binary.read_bytes()) != arch:
        raise ValueError('ELF architecture mismatch')
    library = c.CDLL(str(binary.resolve()))
    library.cliproxy_plugin_init.argtypes = [c.c_void_p, c.POINTER(Plugin)]
    library.cliproxy_plugin_init.restype = c.c_int
    plugin = Plugin()
    assert library.cliproxy_plugin_init(None, c.byref(plugin)) == 0
    assert plugin.abi_version == 1

    def call(method):
        output = Buffer()
        assert plugin.call(method.encode(), b'{}', 2, c.byref(output)) == 0
        try:
            assert output.ptr and 0 < output.len < 100_000
            result = json.loads(c.string_at(output.ptr, output.len))
        finally:
            plugin.free_buffer(output.ptr, output.len)
        assert result['ok'] is True, result
        return result['result']

    metadata = call('plugin.register')['metadata']
    assert metadata['Version'] == version, metadata
    assert metadata['GitHubRepository'] == REPOSITORY, metadata
    routes = call('management.register')
    assert routes['routes'] and routes['resources'], routes
    if plugin.shutdown:
        plugin.shutdown()
    print('PASS: exact production library loads, ABI v1, metadata and routes:', arch, version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--arch', choices=['amd64', 'arm64'], required=True)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        load(args.binary, args.version, args.arch)
    else:
        subprocess.run([sys.executable, '-B', __file__, '--binary', str(args.binary.resolve()),
                        '--version', args.version, '--arch', args.arch, '--child'],
                       check=True, timeout=20)


if __name__ == '__main__':
    main()
