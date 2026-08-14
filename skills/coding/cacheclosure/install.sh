#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${CACHECLOSURE_PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/cacheclosure"
BIN_DIR="$PREFIX/bin"
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found" >&2; exit 2; }
mkdir -p "$APP_DIR" "$BIN_DIR"
rm -rf "$APP_DIR/cacheclosure"
cp -R "$ROOT/src/cacheclosure" "$APP_DIR/cacheclosure"
find "$APP_DIR/cacheclosure" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$BIN_DIR/cacheclosure" <<WRAPPER
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m cacheclosure "\$@"
WRAPPER
chmod 0755 "$BIN_DIR/cacheclosure"
echo "Installed: $BIN_DIR/cacheclosure"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "NOTE: add $BIN_DIR to PATH" ;; esac
