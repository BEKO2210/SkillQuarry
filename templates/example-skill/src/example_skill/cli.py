"""Command-line entry point for the example skill."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import SkillError, __version__, render_json, summarise_paths

EXIT_OK = 0
EXIT_ERROR = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="example-skill", description="Summarise UTF-8 text files")
    parser.add_argument("--version", action="version", version=f"example-skill {__version__}")
    parser.add_argument("files", nargs="+", help="files to summarise")
    parser.add_argument("--out", help="write the report here instead of stdout")
    args = parser.parse_args(argv)
    try:
        summaries = summarise_paths([Path(item) for item in args.files])
    except SkillError as exc:
        print(f"example-skill: {exc}", file=sys.stderr)
        return EXIT_ERROR
    report = render_json(summaries)
    if args.out:
        from .core import atomic_write_text
        atomic_write_text(Path(args.out), report)
    else:
        print(report, end="")
    return EXIT_OK
