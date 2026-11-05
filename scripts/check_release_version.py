#!/usr/bin/env python3
"""Check the five explicit stable-version markers; no network or writes."""
import argparse
from pathlib import Path
import re
import stat

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
PATTERNS = {
    "cpa-updater.c": re.compile(r'Version\\":\\"([^"\\]*)\\"'),
    "test_plugin.py": re.compile(r"\['Version'\],\s*'([^']*)'"),
    "README.md": re.compile(r'^# CPA Web Updater v([^\r\n]*)$', re.M),
    "cliproxy-updater-worker": re.compile(r'^# CPA Web Updater v([^\r\n:]*): fixed, verified official stable releases only\.$', re.M),
    "tests/test_official.py": re.compile(r"plugin\['metadata'\]\['version'\] == '([^']*)'"),
}


def regular(root, name):
    path = Path(root) / name
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError(f"Symlink refused: {part}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Not a regular file: {path}")
    return path


def source_versions(root=ROOT):
    result = {}
    for name, pattern in PATTERNS.items():
        matches = pattern.findall(regular(root, name).read_text(encoding='utf-8'))
        if len(matches) != 1 or not VERSION.fullmatch(matches[0]):
            raise ValueError(f"{name}: expected one complete ASCII stable version, got {matches}")
        result[name] = matches[0]
    if len(set(result.values())) != 1:
        raise ValueError(f"Version mismatch: {result}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag')
    args = parser.parse_args()
    version = next(iter(source_versions().values()))
    if args.tag is not None:
        if not args.tag.startswith('v') or not VERSION.fullmatch(args.tag[1:]):
            parser.error('Invalid stable release tag')
        if args.tag[1:] != version:
            parser.error('Tag does not match source version')
    print(f'Versions agree: {version}')


if __name__ == '__main__':
    main()
