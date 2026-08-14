from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import scan_repository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cacheclosure")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    findings = scan_repository(Path(args.path))
    if args.as_json:
        print(json.dumps([f.to_dict() for f in findings], indent=2, sort_keys=True))
    else:
        if not findings:
            print("cacheclosure: no proven cache-key closure defects found")
        for f in findings:
            print(f"{f.severity} {f.code} {f.workflow}:{f.line} {f.message}")
    return 1 if findings else 0
