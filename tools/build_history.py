#!/usr/bin/env python3
"""Derive each skill's history from git into registry/history.json. Standard library only.

The history is taken from the repository itself rather than from a hand-written
changelog, so it cannot claim a release that never happened. For every commit that
touched a skill it records the date, the subject and the version the manifest
carried at that commit; from that, the version timeline follows.

Committing the result keeps the site build free of git: the generator reads this
file, CI regenerates it.

    python3 tools/build_history.py            # write registry/history.json
    python3 tools/build_history.py --check    # exit 3 if it is out of date
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "registry" / "skills.json"
HISTORY = REPO / "registry" / "history.json"
MAX_COMMITS = 20
EXIT_STALE = 3
SEPARATOR = "\x1f"


class HistoryError(RuntimeError):
    """History cannot be derived from this checkout."""


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=120, check=False)
    if result.returncode != 0:
        raise HistoryError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def ensure_full_history() -> None:
    """A shallow clone would silently produce a truncated, wrong history."""
    if git("rev-parse", "--is-shallow-repository").strip() == "true":
        raise HistoryError(
            "this is a shallow clone; history would be incomplete. "
            "Fetch with depth 0 (actions/checkout: fetch-depth: 0)."
        )


def load_registry() -> list[dict[str, Any]]:
    try:
        document = json.loads(REGISTRY.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoryError(f"cannot read the registry: {exc}") from exc
    skills = document.get("skills")
    if not isinstance(skills, list) or not skills:
        raise HistoryError("registry has no skills; run tools/render_readme.py first")
    return skills


def version_at(sha: str, path: str) -> str | None:
    """The version the manifest carried at that commit, if it had one."""
    try:
        content = git("show", f"{sha}:{path}/skill.json")
    except HistoryError:
        return None
    try:
        return str(json.loads(content).get("version"))
    except json.JSONDecodeError:
        return None


def commits_for(path: str) -> list[dict[str, Any]]:
    raw = git("log", f"--max-count={MAX_COMMITS}", f"--pretty=format:%h{SEPARATOR}%cI{SEPARATOR}%s",
              "--", path)
    entries = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, date, subject = line.split(SEPARATOR, 2)
        entries.append({"sha": sha, "date": date, "subject": subject, "version": version_at(sha, path)})
    return entries


def timeline(commits: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Each version with the date it first appeared, newest first."""
    first_seen: dict[str, str] = {}
    for commit in reversed(commits):  # oldest first
        version = commit.get("version")
        if version and version not in first_seen:
            first_seen[version] = commit["date"]
    return [{"version": version, "date": date} for version, date in reversed(list(first_seen.items()))]


def render() -> str:
    ensure_full_history()
    skills = load_registry()
    document: dict[str, Any] = {"schema_version": 1, "skills": {}}
    for skill in skills:
        name = str(skill["name"])
        commits = commits_for(str(skill["path"]))
        document["skills"][name] = {
            "commits": commits,
            "versions": timeline(commits),
            "last_changed": commits[0]["date"] if commits else None,
        }
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if registry/history.json is out of date")
    args = parser.parse_args(argv)

    try:
        document = render()
    except HistoryError as exc:
        print(f"build_history: {exc}", file=sys.stderr)
        return 2

    existing = HISTORY.read_text("utf-8") if HISTORY.exists() else ""
    if args.check:
        if existing != document:
            print("build_history: registry/history.json is out of date; run tools/build_history.py",
                  file=sys.stderr)
            return EXIT_STALE
        print("build_history: registry/history.json is up to date")
        return 0

    HISTORY.write_text(document, encoding="utf-8")
    count = len(json.loads(document)["skills"])
    print(f"build_history: wrote history for {count} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
