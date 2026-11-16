#!/usr/bin/env bash
# Thin wrapper; the build itself is run_all.py (Python only, no shell utilities needed; works on Windows too).
set -euo pipefail
cd "$(dirname "$0")"
exec python3 run_all.py "$@"
