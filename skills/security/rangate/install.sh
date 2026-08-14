#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -P "$(dirname "$0")" && pwd)"
SKILLS_ROOT="${RANGATE_SKILLS_DIR:-$HOME/.claude/skills}"
TARGET="$SKILLS_ROOT/rangate"

mkdir -p "$TARGET"

install_atomic() {
  src="$1"
  dst="$2"
  tmp="$(mktemp "$TARGET/.rangate-install.XXXXXX")"
  trap 'rm -f "$tmp"' RETURN
  cat "$src" > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$dst"
  trap - RETURN
}

install_atomic "$ROOT/SKILL.md" "$TARGET/SKILL.md"
install_atomic "$ROOT/REFERENCE.md" "$TARGET/REFERENCE.md"

printf 'Installed RanGate skill: %s\n' "$TARGET"
printf 'Invoke in Claude Code with: /rangate <task>\n'
