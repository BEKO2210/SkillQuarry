#!/usr/bin/env bash
# Install Emberfield as an agent skill: the skill file, its templates and its
# provenance land where Claude Code discovers skills. Nothing else is touched,
# nothing is downloaded.
set -euo pipefail

PREFIX="${EMBERFIELD_PREFIX:-$HOME/.claude}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$PREFIX/skills/emberfield"

mkdir -p "$TARGET/templates" "$TARGET/examples"
cp "$HERE/SKILL.md" "$HERE/LICENSE.txt" "$HERE/NOTICE.md" "$TARGET/"
cp "$HERE"/templates/*.* "$TARGET/templates/"
if compgen -G "$HERE/examples/*" >/dev/null; then
  cp "$HERE"/examples/* "$TARGET/examples/"
fi
# The uninstaller refuses to delete a directory it cannot identify as ours.
printf 'installed by emberfield/install.sh\n' > "$TARGET/.emberfield"

echo "installed emberfield into $TARGET"
