#!/usr/bin/env bash
# Developer checkout overlay only: never install, tag, push or deploy.
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
command -v python3 >/dev/null || { printf 'python3 is required\n' >&2; exit 1; }
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$HERE/scripts/apply_overlay.py" "${1:?Usage: bash apply_to_repo.sh /path/to/clean-v0.3.0-checkout}"
