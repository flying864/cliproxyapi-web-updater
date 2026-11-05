#!/usr/bin/env python3
"""Developer-only v0.3.0 overlay. Best-effort rollback, not crash-atomic.

Never runs git reset/clean, tag, push, install or deployment commands.
Run without concurrent checkout edits; forced termination or failed storage may
require manual restoration from the printed backup directory. Local apply checks
are a subset, not full CI: official-host, worker, installer and cross-architecture
acceptance remain the responsibility of the verification workflows.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from check_release_version import ROOT, PATTERNS, regular, source_versions
from bump_version import replace_bytes

# Deliberately explicit: missing source members fail before the first write.
NEW_FILES = (
    'registry.json', 'STORE_PUBLISHING.md', 'OFFICIAL_REGISTRY_PR.md',
    'README_OVERLAY.md', 'apply_to_repo.sh',
    '.github/workflows/release-plugin.yml', '.github/workflows/verify-core.yml',
    '.github/workflows/build-store.yml',
    'scripts/check_release_version.py', 'scripts/bump_version.py',
    'scripts/apply_overlay.py', 'scripts/store_artifacts.py',
    'scripts/market_preflight.py', 'scripts/validate_registry.py',
    'scripts/smoke_plugin.py', 'tests/test_store_packaging.py',
    'tests/test_store_version.py', 'tests/test_store_apply.py',
    'tests/test_store_workflows.py', 'tests/test_store_preflight.py',
)
VERIFY = '.github/workflows/verify.yml'
OLD_VERIFY_SHA256 = '2bc3420f1066237e47ecfca80c740489726529294843916ebb972b01d18da407'


def git(dest, *args):
    return subprocess.check_output(['git', '-C', str(dest), *args], text=True).strip()


def safe_destination(dest, name):
    path = dest / name
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError(f'Symlink refused: {part}')
        if part == dest:
            break
    return path


def apply(dest, source=ROOT):
    dest = Path(dest).resolve()
    source = Path(source).resolve()
    if Path(git(dest, 'rev-parse', '--show-toplevel')).resolve() != dest:
        raise ValueError('Destination must be the actual Git top-level')
    if git(dest, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Destination must be clean, including untracked files')
    for tool in ('python3', 'bash', 'gcc', 'git'):
        if not shutil.which(tool):
            raise ValueError(f'Missing required dependency: {tool}')
    if set(source_versions(source).values()) != {'0.4.0'}:
        raise ValueError('Source must be the final v0.4.0 checkout')
    if set(source_versions(dest).values()) != {'0.3.0'}:
        raise ValueError('Destination must be v0.3.0')
    prepared = {}
    for name in NEW_FILES:
        src = regular(source, name)
        target = safe_destination(dest, name)
        if os.path.lexists(target):
            raise ValueError(f'Refusing existing overlay target (including ignored): {name}')
        for parent in target.parents:
            if parent == dest:
                break
            if parent.exists() and not parent.is_dir():
                raise ValueError(f'Non-directory parent: {parent}')
        prepared[name] = (src.read_bytes(), src.stat().st_mode & 0o7777)
    # Only replace the exact reviewed old workflow, not arbitrary user CI.
    old_verify = regular(dest, VERIFY).read_bytes()
    if hashlib.sha256(old_verify).hexdigest() != OLD_VERIFY_SHA256:
        raise ValueError('verify.yml differs from reviewed v0.3.0 baseline')
    new_verify = regular(source, VERIFY).read_bytes()
    if b'./.github/workflows/verify-core.yml' not in new_verify:
        raise ValueError('Source verify.yml must call verify-core.yml')
    prepared[VERIFY] = (new_verify, regular(dest, VERIFY).stat().st_mode & 0o7777)
    for name, pattern in PATTERNS.items():
        path = regular(dest, name)
        text = path.read_text(encoding='utf-8')
        match = pattern.search(text)
        assert match is not None
        updated = text[:match.start(1)] + '0.4.0' + text[match.end(1):]
        if name == 'tests/test_official.py':
            if updated.encode() != regular(source, name).read_bytes():
                raise ValueError('Official test source has changes beyond its version assertion')
        # In particular README is edited in-place, never copied from the source.
        prepared[name] = (updated.encode(), path.stat().st_mode & 0o7777)
    # Allocate via tempfile (honors TMPDIR); retain backup if restoration fails.
    backup = Path(tempfile.mkdtemp(prefix='cpa-overlay-'))
    originals = {}
    written = []
    created_dirs = []
    try:
        for name in prepared:
            path = dest / name
            if path.exists():
                originals[name] = (path.read_bytes(), path.stat().st_mode & 0o7777)
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, saved)
        for name, (content, mode) in prepared.items():
            path = safe_destination(dest, name)
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_dirs.append(directory)
            replace_bytes(path, content, mode)
            written.append(name)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        commands = [
            ['python3', 'scripts/check_release_version.py', '--tag', 'v0.4.0'],
            ['python3', 'scripts/validate_registry.py'],
            ['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_store_*.py', '-v'],
            ['python3', 'test_plugin.py'],
            ['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC', '-shared',
             'cpa-updater.c', '-o', str(backup / 'check.so')],
        ]
        for command in commands:
            subprocess.run(command, cwd=dest, env=env, check=True)
    except BaseException:
        errors = []
        for name in reversed(written):
            try:
                path = safe_destination(dest, name)
                if name in originals:
                    replace_bytes(path, *originals[name])
                else:
                    path.unlink()
            except Exception as error:
                errors.append(f'{name}: {error}')
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()  # Never remove contents; concurrent files survive.
            except OSError:
                pass
        if errors:
            print(f'Restoration incomplete: {errors}; backups: {backup}', file=sys.stderr)
        else:
            shutil.rmtree(backup)
        raise
    else:
        shutil.rmtree(backup)
        print('Applied developer overlay; local checks are NOT full CI. Review diff; no tag, push or deployment performed.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: apply_to_repo.sh /path/to/clean-v0.3.0-checkout')
    try:
        apply(sys.argv[1])
    except Exception as error:
        raise SystemExit(str(error))
