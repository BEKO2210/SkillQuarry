"""Allows `python3 -m example_skill`."""

from __future__ import annotations

import sys

from .cli import main

raise SystemExit(main(sys.argv[1:]))
