#!/usr/bin/env python3
"""Scaffold a new skill from templates/example-skill. Standard library only.

    python3 tools/new_skill.py --name my-skill --display "My Skill" --category testing

Copies the template, renames the module, the CLI and every reference to them, and
leaves a skill that already validates and passes its own coverage gate. What it
does not do is invent content: descriptions, taglines and test reports are marked
TODO so nobody ships a manifest describing the template instead of their skill.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "templates" / "example-skill"
SKILLS = REPO / "skills"
SCHEMA = REPO / "registry" / "schema.json"

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
EXIT_ERROR = 2


class ScaffoldError(RuntimeError):
    """The request cannot be satisfied without guessing."""


def categories() -> list[str]:
    schema = json.loads(SCHEMA.read_text("utf-8"))
    return list(schema["properties"]["category"]["enum"])


def module_name(skill_name: str) -> str:
    return skill_name.replace("-", "_")


def rewrite(text: str, name: str, display: str) -> str:
    """Replace every template identifier. Longest names first, so no partial hits."""
    return (
        text.replace("example_skill", module_name(name))
        .replace("example-skill", name)
        .replace("EXAMPLE_SKILL_PREFIX", f"{module_name(name).upper()}_PREFIX")
        .replace("Example Skill", display)
    )


def scaffold(name: str, display: str, category: str, *, force: bool = False) -> Path:
    if not NAME_PATTERN.match(name):
        raise ScaffoldError(f"{name!r} is not a valid skill name (lowercase, kebab-case)")
    if category not in categories():
        raise ScaffoldError(f"{category!r} is not a category in registry/schema.json")
    if not TEMPLATE.is_dir():
        raise ScaffoldError(f"template is missing: {TEMPLATE}")

    target = SKILLS / category / name
    if target.exists():
        if not force:
            raise ScaffoldError(f"{target.relative_to(REPO)} already exists; pass --force to replace it")
        shutil.rmtree(target)

    for source in sorted(TEMPLATE.rglob("*")):
        if "__pycache__" in source.parts:
            continue
        relative = Path(*[rewrite(part, name, display) for part in source.relative_to(TEMPLATE).parts])
        destination = target / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.write_text(rewrite(source.read_text("utf-8"), name, display), encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(source, destination)
        destination.chmod(source.stat().st_mode)

    manifest_path = target / "skill.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["name"] = name
    manifest["displayName"] = display
    manifest["version"] = "0.1.0"
    manifest["category"] = category
    manifest["description"] = f"TODO: describe {display} in plain sentences a reviewer can check."
    manifest["tagline"] = "TODO: one line."
    manifest["quality"] = "experimental"
    manifest["keywords"] = ["todo"]
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="registry identifier, lowercase kebab-case")
    parser.add_argument("--display", required=True, help="human-facing name")
    parser.add_argument("--category", required=True, choices=categories())
    parser.add_argument("--force", action="store_true", help="replace an existing directory")
    args = parser.parse_args(argv)

    try:
        target = scaffold(args.name, args.display, args.category, force=args.force)
    except ScaffoldError as exc:
        print(f"new_skill: {exc}", file=sys.stderr)
        return EXIT_ERROR

    relative = target.relative_to(REPO)
    print(f"new_skill: created {relative}")
    print()
    print("Next:")
    print(f"  1. cd {relative} && python3 tests/run_tests.py --min 100")
    print(f"  2. replace src/{module_name(args.name)}/core.py with your logic and rewrite the tests")
    print("  3. fill in the TODO fields in skill.json")
    print(f"  4. add .github/workflows/{args.name}-tests.yml")
    print("  5. python3 tools/validate_skills.py && python3 tools/render_readme.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
