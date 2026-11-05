#!/usr/bin/env python3
"""Pack and verify official CLIProxyAPI store assets using only the Python stdlib.

The release zip MUST contain one root-level cpa-updater.so and its name MUST
match cpa-updater_<version>_linux_<arch>.zip. Verify ELF architecture before
packing and again when checking release assets and checksums.
"""
import argparse
import hashlib
from pathlib import Path
import re
import stat
import struct
import zipfile

PLUGIN = 'cpa-updater'
ARCH_MACHINE = {'amd64': 62, 'arm64': 183}
ARCHS = tuple(ARCH_MACHINE)


def elf_arch(binary):
    data = binary[:64]
    if len(data) < 64 or data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1:
        raise ValueError('Library must be ELF64 little-endian')
    if struct.unpack_from('<H', data, 16)[0] != 3:
        raise ValueError('Library must have ELF ET_DYN type')
    machine = struct.unpack_from('<H', data, 18)[0]
    for arch, expect in ARCH_MACHINE.items():
        if machine == expect:
            return arch
    raise ValueError('Unsupported ELF e_machine: ' + str(machine))


def name(version, arch):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) or arch not in ARCHS:
        raise ValueError('Invalid version or architecture')
    return f'{PLUGIN}_{version}_linux_{arch}.zip'


def check_zip(path, version, arch):
    if Path(path).name != name(version, arch):
        raise ValueError('Release ZIP name mismatch')
    with zipfile.ZipFile(path) as z:
        items = z.infolist()
        if len(items) != 1 or items[0].filename != f'{PLUGIN}.so':
            raise ValueError('ZIP must contain only one root-level cpa-updater.so')
        item = items[0]
        kind = stat.S_IFMT(item.external_attr >> 16)
        if kind not in (0, stat.S_IFREG) or item.external_attr & 0x10:
            raise ValueError('ZIP library must be a regular file')
        if item.is_dir() or item.file_size > 20_000_000 or item.file_size < 512:
            raise ValueError('Suspicious library size')
        lib = z.read(item)
        if elf_arch(lib) != arch:
            raise ValueError('ELF architecture does not match ZIP')
        if z.testzip() is not None:
            raise ValueError('ZIP checksum failure')
    return True


def pack(args):
    binary = Path(args.binary).read_bytes()
    if elf_arch(binary) != args.arch:
        raise SystemExit('Native compiler output does not match requested architecture')
    target = Path(args.output) / name(args.version, args.arch)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        info = zipfile.ZipInfo(f'{PLUGIN}.so', date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o100755 << 16)
        z.writestr(info, binary, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    check_zip(target, args.version, args.arch)
    print(target)


def verify(args):
    folder = Path(args.directory)
    expected = {name(args.version, arch) for arch in ARCHS}
    found = {p.name for p in folder.iterdir() if p.suffix == '.zip'}
    if found != expected:
        raise ValueError(f'Expected exactly {sorted(expected)}, found {sorted(found)}')
    checks = {}
    for arch in ARCHS:
        archive = folder / name(args.version, arch)
        check_zip(archive, args.version, arch)
        checks[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
    digest_file = folder / 'checksums.txt'
    if args.create_checksums:
        digest_file.write_text(''.join(f'{digest}  {file}\n' for file, digest in sorted(checks.items())), encoding='ascii')
    if digest_file.exists():
        listed = {}
        for line in digest_file.read_text(encoding='ascii').splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
            if not match or match[2] in listed:
                raise ValueError('Bad or repeated checksum line')
            listed[match[2]] = match[1]
        if listed != checks:
            raise ValueError('checksums.txt does not match release assets')
    elif not args.create_checksums:
        raise ValueError('checksums.txt missing')
    print('Validated two official-style ZIP files and checksums.txt')


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('pack')
    b.add_argument('--binary', required=True)
    b.add_argument('--version', required=True)
    b.add_argument('--arch', choices=ARCHS, required=True)
    b.add_argument('--output', required=True)
    b.set_defaults(func=pack)
    v = sub.add_parser('verify')
    v.add_argument('--version', required=True)
    v.add_argument('--directory', required=True)
    v.add_argument('--create-checksums', action='store_true')
    v.set_defaults(func=verify)
    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
