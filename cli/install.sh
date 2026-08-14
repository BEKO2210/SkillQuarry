#!/usr/bin/env bash
# Installs the skillquarry client and records which quarry it came from.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
QUARRY="$(cd -- "$ROOT/.." && pwd)"
PREFIX="${SKILLQUARRY_PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/skillquarry"
BIN_DIR="$PREFIX/bin"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found" >&2; exit 2; }

mkdir -p "$APP_DIR" "$BIN_DIR"
install -m 0644 "$ROOT/skillquarry.py" "$APP_DIR/skillquarry.py"

cat > "$BIN_DIR/skillquarry" <<WRAPPER
#!/usr/bin/env bash
set -euo pipefail
# The quarry this client was installed from; --quarry and SKILLQUARRY_ROOT win.
export SKILLQUARRY_DEFAULT_ROOT="\${SKILLQUARRY_DEFAULT_ROOT:-$QUARRY}"
exec python3 "$APP_DIR/skillquarry.py" "\$@"
WRAPPER
chmod 0755 "$BIN_DIR/skillquarry"

echo "Installed: $BIN_DIR/skillquarry (quarry: $QUARRY)"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: add $BIN_DIR to PATH" ;;
esac
"$BIN_DIR/skillquarry" --version
echo "Self-check: PASS"
