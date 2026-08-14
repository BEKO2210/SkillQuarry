#!/usr/bin/env bash
# Removes exactly what install.sh created.
set -euo pipefail

PREFIX="${EXAMPLE_SKILL_PREFIX:-$HOME/.local}"
rm -rf "$PREFIX/share/example-skill"
rm -f "$PREFIX/bin/example-skill"
echo "Removed: $PREFIX/bin/example-skill and $PREFIX/share/example-skill"
