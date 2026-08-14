#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX=${CORDON_PREFIX:-"$HOME/.local"}
exec python3 "$ROOT/installer.py" uninstall --root "$ROOT" --prefix "$PREFIX"
