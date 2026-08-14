#!/usr/bin/env bash
# Removes the client. Skills it installed stay; remove those with `skillquarry uninstall`.
set -euo pipefail

PREFIX="${SKILLQUARRY_PREFIX:-$HOME/.local}"
rm -rf "$PREFIX/share/skillquarry"
rm -f "$PREFIX/bin/skillquarry"
echo "Removed: $PREFIX/bin/skillquarry and $PREFIX/share/skillquarry"
echo "Skills installed through it were left in place."
