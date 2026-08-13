"""Console-script entry point for `strata`."""

from __future__ import annotations

import sys

from .runner import main


def run() -> int:
    return main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(run())
