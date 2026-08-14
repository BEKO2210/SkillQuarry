#!/usr/bin/env bash
# Dependency-free installer: copies the module and writes a small launcher.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${EXAMPLE_SKILL_PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/example-skill"
BIN_DIR="$PREFIX/bin"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found" >&2; exit 2; }

mkdir -p "$APP_DIR" "$BIN_DIR"
rm -rf "$APP_DIR/example_skill"
cp -R "$ROOT/src/example_skill" "$APP_DIR/example_skill"
find "$APP_DIR/example_skill" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

cat > "$BIN_DIR/example-skill" <<WRAPPER
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m example_skill "\$@"
WRAPPER
chmod 0755 "$BIN_DIR/example-skill"

echo "Installed: $BIN_DIR/example-skill"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: add $BIN_DIR to PATH" ;;
esac
"$BIN_DIR/example-skill" --version
echo "Self-check: PASS"
