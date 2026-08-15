#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${HITMAP_PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/hitmap"
BIN_DIR="$PREFIX/bin"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found" >&2; exit 2; }

mkdir -p "$APP_DIR" "$BIN_DIR"
rm -rf "$APP_DIR/hitmap"
cp -R "$ROOT/src/hitmap" "$APP_DIR/hitmap"
find "$APP_DIR/hitmap" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

cat > "$BIN_DIR/hitmap" <<WRAPPER
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m hitmap "\$@"
WRAPPER
chmod 0755 "$BIN_DIR/hitmap"

echo "Installed: $BIN_DIR/hitmap"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: add $BIN_DIR to PATH" ;;
esac
"$BIN_DIR/hitmap" --version
echo "Self-check: PASS"
