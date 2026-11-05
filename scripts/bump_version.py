#!/usr/bin/env python3
"""Bump five markers, restoring ordinary failures; not crash-atomic across files."""
import argparse
import os
from pathlib import Path
import tempfile
from check_release_version import ROOT, VERSION, PATTERNS, regular, source_versions


def replace_bytes(path, content, mode):
    # Same-directory replacement preserves mode and never follows a leaf symlink.
    fd, name = tempfile.mkstemp(prefix='.cpa-version-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def bump(version, root=ROOT):
    if not VERSION.fullmatch(version):
        raise ValueError('Version must be three ASCII dotted numbers')
    source_versions(root)
    prepared = []
    for name, pattern in PATTERNS.items():
        path = regular(root, name)
        original = path.read_bytes()
        text = original.decode('utf-8')
        match = pattern.search(text)
        if match is None:
            raise ValueError(f'Version marker changed during preparation: {name}')
        begin, end = match.span(1)
        updated = text[:begin] + version + text[end:]
        if pattern.findall(updated) != [version]:
            raise ValueError(f'Invalid replacement: {name}')
        prepared.append((path, original, updated.encode('utf-8'), path.stat().st_mode & 0o7777))
    written = []
    try:
        for path, original, updated, mode in prepared:
            regular(root, str(path.relative_to(root)))
            replace_bytes(path, updated, mode)
            written.append((path, original, mode))
    except Exception as error:
        failures = []
        for path, original, mode in reversed(written):
            try:
                replace_bytes(path, original, mode)
            except Exception as restore:
                failures.append(f'{path}: {restore}')
        if failures:
            raise RuntimeError(f'{error}; restoration incomplete: {failures}') from error
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('version')
    args = parser.parse_args()
    bump(args.version)
    print(f'Updated version markers to {args.version}')


if __name__ == '__main__':
    main()
