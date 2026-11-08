from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from native_artifacts import elf_arch


def synthetic_elf(arch):
    b = bytearray(1024)
    b[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', b, 16, 3)
    struct.pack_into('<H', b, 18, {'amd64': 62, 'arm64': 183}[arch])
    return bytes(b)


class TestNativeELF(unittest.TestCase):
    def test_reject_wrong_type_encoding_and_machine(self):
        for label, offset, value in [('ELF32', 4, 1), ('big-endian', 5, 2),
                                     ('ET_EXEC', 16, 2), ('unknown machine', 18, 1)]:
            with self.subTest(label=label):
                data = bytearray(synthetic_elf('amd64'))
                data[offset] = value
                with self.assertRaises(ValueError):
                    elf_arch(data)
        with self.assertRaises(ValueError):
            elf_arch(synthetic_elf('amd64')[:63])

    def test_elf_arch(self):
        self.assertEqual(elf_arch(synthetic_elf('amd64')), 'amd64')
        self.assertEqual(elf_arch(synthetic_elf('arm64')), 'arm64')
        with self.assertRaises(ValueError):
            elf_arch(b'not-an-elf')


if __name__ == '__main__':
    unittest.main()
