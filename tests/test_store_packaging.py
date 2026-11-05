import json
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from store_artifacts import elf_arch, name, check_zip, pack, verify
from validate_registry import validate


def synthetic_elf(arch):
    b = bytearray(1024)
    b[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', b, 16, 3)
    struct.pack_into('<H', b, 18, {'amd64': 62, 'arm64': 183}[arch])
    return bytes(b)


class TestOfficialStore(unittest.TestCase):
    def test_registry(self):
        self.assertTrue(validate())

    def test_bad_name(self):
        with self.assertRaises(ValueError):
            name('v0.4.0', 'amd64')
        with self.assertRaises(ValueError):
            name('0.4.0', 'aarch64')

    def test_two_platforms_and_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            for arch in ['amd64', 'arm64']:
                b = p / (arch + '.so')
                b.write_bytes(synthetic_elf(arch))
                pack(type('Args', (), dict(binary=b, arch=arch, version='0.4.0', output=p)))
            verify(type('Args', (), dict(version='0.4.0', directory=p, create_checksums=True)))
            verify(type('Args', (), dict(version='0.4.0', directory=p, create_checksums=False)))
            with (p / name('0.4.0', 'amd64')).open('ab') as f:
                f.write(b'changed')
            with self.assertRaises(ValueError):
                verify(type('Args', (), dict(version='0.4.0', directory=p, create_checksums=False)))

    def test_reject_nested_library(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / name('0.4.0', 'amd64')
            with zipfile.ZipFile(bad, 'w') as z:
                z.writestr('nested/cpa-updater.so', synthetic_elf('amd64'))
            with self.assertRaises(ValueError):
                check_zip(bad, '0.4.0', 'amd64')

    def test_zip_entry_types(self):
        # Synthetic headers exercise package format only, not loadable libraries.
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / name('0.4.0', 'amd64')
            for kind in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK,
                         stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFDIR,
                         stat.S_IFREG, 0):
                with self.subTest(kind=kind):
                    item = zipfile.ZipInfo('cpa-updater.so')
                    item.create_system = 3
                    item.external_attr = (kind | 0o755) << 16
                    with zipfile.ZipFile(archive, 'w') as z:
                        z.writestr(item, synthetic_elf('amd64'))
                    if kind in (stat.S_IFREG, 0):
                        self.assertTrue(check_zip(archive, '0.4.0', 'amd64'))
                    else:
                        with self.assertRaises(ValueError):
                            check_zip(archive, '0.4.0', 'amd64')

    def test_reject_duplicate_extra_and_mixed_arch(self):
        import warnings
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / name('0.4.0', 'amd64')
            for entries in (
                [('cpa-updater.so', 'amd64'), ('cpa-updater.so', 'amd64')],
                [('cpa-updater.so', 'amd64'), ('extra', 'amd64')],
                [('cpa-updater.so', 'arm64')],
            ):
                with self.subTest(entries=entries):
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        with zipfile.ZipFile(archive, 'w') as z:
                            for filename, arch in entries:
                                z.writestr(filename, synthetic_elf(arch))
                    with self.assertRaises(ValueError):
                        check_zip(archive, '0.4.0', 'amd64')

    def test_elf_arch(self):
        self.assertEqual(elf_arch(synthetic_elf('amd64')), 'amd64')
        self.assertEqual(elf_arch(synthetic_elf('arm64')), 'arm64')
        with self.assertRaises(ValueError):
            elf_arch(b'not-an-elf')


if __name__ == '__main__':
    unittest.main()
