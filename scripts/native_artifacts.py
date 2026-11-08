"""Shared native ELF validation; no packaging or publication support."""
import struct

ARCH_MACHINE = {'amd64': 62, 'arm64': 183}


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


