#!/usr/bin/env bash
set -euo pipefail
PREFIX="${HITMAP_PREFIX:-$HOME/.local}"
rm -f "$PREFIX/bin/hitmap"
rm -rf "$PREFIX/share/hitmap"
echo "Removed HITMAP from $PREFIX"
