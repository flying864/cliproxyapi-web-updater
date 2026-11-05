#!/usr/bin/env python3
"""Fetch the pinned official amd64 host for integration tests (not production updates)."""
import argparse
import hashlib
from pathlib import Path
import tarfile
import tempfile
import urllib.request

VERSION = '8.0.56'
SHA256 = '6f313dfdfbb62154de97a446cfc47d5a3419723484ea9f3bc1fb0a3015d195e7'
URL = ('https://github.com/router-for-me/CLIProxyAPI/releases/download/v' + VERSION
       + '/CLIProxyAPI_' + VERSION + '_linux_amd64.tar.gz')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; choose a new test-artifact path')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(URL, headers={'User-Agent': 'cliproxyapi-web-updater-tests'})
    with tempfile.TemporaryFile() as archive:
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(request, timeout=60) as response:
            while True:
                data = response.read(1024 * 1024)
                if not data:
                    break
                total += len(data)
                if total > 80 * 1024 * 1024:
                    raise RuntimeError('official test download exceeded size budget')
                archive.write(data)
                digest.update(data)
        if digest.hexdigest() != SHA256:
            raise RuntimeError('official test artifact SHA256 mismatch')
        archive.seek(0)
        with tarfile.open(fileobj=archive, mode='r:gz') as package:
            members = [m for m in package.getmembers()
                       if m.name.removeprefix('./') == 'cli-proxy-api']
            if len(members) != 1 or not members[0].isfile() or members[0].size > 150 * 1024 * 1024:
                raise RuntimeError('unexpected official test archive layout')
            stream = package.extractfile(members[0])
            if stream is None:
                raise RuntimeError('official binary member has no readable data')
            with args.output.open('xb') as output:
                while data := stream.read(1024 * 1024):
                    output.write(data)
        args.output.chmod(0o755)
    print('Verified official CLIProxyAPI v' + VERSION + ': ' + str(args.output))


if __name__ == '__main__':
    main()
