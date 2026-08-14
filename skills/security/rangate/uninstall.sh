#!/usr/bin/env bash
set -euo pipefail

SKILLS_ROOT="${RANGATE_SKILLS_DIR:-$HOME/.claude/skills}"
TARGET="$SKILLS_ROOT/rangate"

rm -f "$TARGET/SKILL.md" "$TARGET/REFERENCE.md"
rmdir "$TARGET" 2>/dev/null || true

printf 'Removed RanGate managed files from: %s\n' "$TARGET"
