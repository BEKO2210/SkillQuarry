#!/usr/bin/env bash
# Removes only what install.sh created. Repository state under .strata/ is untouched.
set -euo pipefail

PREFIX="${STRATA_PREFIX:-$HOME/.local}"
rm -rf "$PREFIX/share/strata"
rm -f "$PREFIX/bin/strata"
echo "Removed: $PREFIX/bin/strata and $PREFIX/share/strata"
