#!/usr/bin/env bash
# Shared stdlib transaction; fixed production paths, no environment overrides.
set -Eeuo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$HERE/install_helper.py" install
