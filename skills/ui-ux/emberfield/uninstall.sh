#!/usr/bin/env bash
# Remove exactly what install.sh created.
set -euo pipefail

PREFIX="${EMBERFIELD_PREFIX:-$HOME/.claude}"
TARGET="$PREFIX/skills/emberfield"

if [ -f "$TARGET/.emberfield" ]; then
  rm -rf "$TARGET"
  echo "removed emberfield from $PREFIX/skills"
else
  echo "nothing to remove: $TARGET was not installed by install.sh"
fi
