#!/usr/bin/env python3
"""Query and verify registry/skills.json. Standard library only.

The registry is generated from the manifests, so this never edits it — it answers
questions about it and checks that what is on disk still matches what it claims.

    python3 tools/registry.py list
    python3 tools/registry.py list --agent claude-code --platform linux --quality tested
    python3 tools/registry.py show cordon
    python3 tools/registry.py verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_readme import REPO, skill_checksum  # noqa: E402

REGISTRY = REPO / "registry" / "skills.json"
EXIT_MISMATCH = 3
EXIT_ERROR = 2


class RegistryError(RuntimeError):
    """The registry is missing or unreadable; querying it would be guesswork."""


def _display(path: Path) -> str:
    """Repository-relative where possible; absolute otherwise, never an exception."""
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


def load() -> list[dict[str, Any]]:
    try:
        document = json.loads(REGISTRY.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read {_display(REGISTRY)}: {exc}") from exc
    skills = document.get("skills")
    if not isinstance(skills, list):
        raise RegistryError("registry has no skills array; run tools/render_readme.py")
    return skills


def matches(skill: dict[str, Any], *, agent: str | None, platform: str | None,
            category: str | None, quality: str | None, offline: bool,
            no_secrets: bool, keyword: str | None) -> bool:
    """Every filter is a conjunction; an absent field never counts as a match."""
    security = skill.get("security") or {}
    if agent and agent not in (skill.get("compatibility") or []):
        return False
    if platform and platform not in (skill.get("platforms") or []):
        return False
    if category and skill.get("category") != category:
        return False
    if quality and skill.get("quality") != quality:
        return False
    if offline and security.get("network_access") not in {"none", None}:
        return False
    if no_secrets and security.get("requires_secrets") is not False:
        return False
    if keyword:
        haystack = " ".join([
            str(skill.get("name", "")), str(skill.get("displayName", "")),
            str(skill.get("description", "")), " ".join(skill.get("keywords") or []),
        ]).lower()
        if keyword.lower() not in haystack:
            return False
    return True


def verify(skills: list[dict[str, Any]]) -> list[str]:
    """Recompute every checksum; a mismatch means the registry is stale."""
    problems: list[str] = []
    for skill in skills:
        directory = REPO / str(skill.get("path", ""))
        if not directory.is_dir():
            problems.append(f"{skill.get('name')}: path {skill.get('path')} does not exist")
            continue
        actual = skill_checksum(directory)
        recorded = skill.get("checksum")
        if recorded != actual:
            problems.append(
                f"{skill.get('name')}: checksum {recorded} does not match the files on disk ({actual})"
            )
    return problems


def format_row(skill: dict[str, Any]) -> str:
    security = skill.get("security") or {}
    tests = skill.get("tests") or {}
    flags = []
    if security.get("network_access") == "none":
        flags.append("offline")
    if security.get("runs_external_commands"):
        flags.append("runs-commands")
    if security.get("destructive_operations"):
        flags.append("destructive")
    return (
        f"{skill.get('name', '?'):<10} {skill.get('version', '?'):<8} "
        f"{skill.get('category', '?'):<12} {str(skill.get('quality', '?')):<12} "
        f"{str(tests.get('count', '-')):>4} tests  {', '.join(flags) or '-'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list skills, optionally filtered")
    listing.add_argument("--agent", help="only skills compatible with this agent")
    listing.add_argument("--platform", choices=["linux", "macos", "windows"])
    listing.add_argument("--category")
    listing.add_argument("--quality", choices=["experimental", "verified", "tested", "trusted", "certified"])
    listing.add_argument("--offline", action="store_true", help="only skills that need no network of their own")
    listing.add_argument("--no-secrets", action="store_true", help="only skills that need no credentials")
    listing.add_argument("--keyword", help="substring of name, description or keywords")
    listing.add_argument("--json", action="store_true", help="print matching entries as JSON")

    show = sub.add_parser("show", help="print one skill's registry entry")
    show.add_argument("name")

    sub.add_parser("verify", help="recompute checksums and compare them with the registry")

    args = parser.parse_args(argv)

    try:
        skills = load()
    except RegistryError as exc:
        print(f"registry: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.command == "verify":
        problems = verify(skills)
        if problems:
            for problem in problems:
                print(f"registry: {problem}", file=sys.stderr)
            print("registry: run `python3 tools/render_readme.py` and commit the result", file=sys.stderr)
            return EXIT_MISMATCH
        print(f"registry: {len(skills)} checksums match the files on disk")
        return 0

    if args.command == "show":
        for skill in skills:
            if skill.get("name") == args.name:
                print(json.dumps(skill, indent=2, ensure_ascii=False, sort_keys=True))
                return 0
        print(f"registry: no skill named {args.name!r}", file=sys.stderr)
        return EXIT_ERROR

    selected = [
        skill for skill in skills
        if matches(skill, agent=args.agent, platform=args.platform, category=args.category,
                   quality=args.quality, offline=args.offline, no_secrets=args.no_secrets,
                   keyword=args.keyword)
    ]
    if args.json:
        print(json.dumps(selected, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if not selected:
        print("no skill matches those filters")
        return 0
    for skill in selected:
        print(format_row(skill))
    print(f"\n{len(selected)} of {len(skills)} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
