#!/usr/bin/env bash
set -euo pipefail
PREFIX="${CACHECLOSURE_PREFIX:-$HOME/.local}"
rm -f "$PREFIX/bin/cacheclosure"
rm -rf "$PREFIX/share/cacheclosure"
echo "Removed CacheClosure from $PREFIX"
