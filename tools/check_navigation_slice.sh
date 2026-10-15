#!/usr/bin/env bash
# Build current sources and run localhost-only navigation/UWB transport tests.
set -eo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec python3 "$ROOT/tools/check_navigation_slice.py" "$@"
