#!/usr/bin/env bash
# Dependency-free installer: copies the module and writes a small launcher.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${STRATA_PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/strata"
BIN_DIR="$PREFIX/bin"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found" >&2; exit 2; }
command -v git >/dev/null 2>&1 || { echo "ERROR: git not found" >&2; exit 2; }

mkdir -p "$APP_DIR" "$BIN_DIR"
rm -rf "$APP_DIR/strata"
cp -R "$ROOT/src/strata" "$APP_DIR/strata"
find "$APP_DIR/strata" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$APP_DIR/strata" -type f -name '*.pyc' -delete 2>/dev/null || true

cat > "$BIN_DIR/strata" <<WRAPPER
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m strata "\$@"
WRAPPER
chmod 0755 "$BIN_DIR/strata"

echo "Installed: $BIN_DIR/strata"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: add $BIN_DIR to PATH" ;;
esac
"$BIN_DIR/strata" --version
echo "Self-check: PASS"
