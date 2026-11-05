#!/usr/bin/env python3
"""Validate official schema v1 registry entry for this plugin."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REPO = 'https://github.com/flying864/cliproxyapi-web-updater'


def validate(path=ROOT / 'registry.json'):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('plugins'), list):
        raise ValueError('Expected schema_version: 1 and plugins list')
    found = set()
    for entry in data['plugins']:
        for k in ['id', 'name', 'description', 'author', 'repository']:
            if not isinstance(entry.get(k), str) or not entry[k].strip():
                raise ValueError('Invalid or absent required field: ' + k)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', entry['id']):
            raise ValueError('Invalid ID')
        if entry['id'] in found:
            raise ValueError('Duplicate ID')
        found.add(entry['id'])
        if entry['id'] != 'cpa-updater' or entry['repository'] != EXPECTED_REPO:
            raise ValueError('Unexpected plugin/repository')
        if 'version' in entry and not re.fullmatch(r'\d+\.\d+\.\d+', entry['version']):
            raise ValueError('Invalid version fallback')
    if found != {'cpa-updater'}:
        raise ValueError('Expected exactly one cpa-updater entry')
    return True


if __name__ == '__main__':
    validate()
    print('Registry schema v1: OK')
