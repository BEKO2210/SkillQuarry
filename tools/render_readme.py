#!/usr/bin/env python3
"""Render the generated parts of README.md and registry/skills.json from skill manifests.

Every skill owns its own facts in `skills/<category>/<name>/skill.json`. This script
is the only writer of the generated README blocks, so adding, updating or removing a
skill never requires a hand edit of the README: drop the folder in, and CI regenerates.

Usage:
    python3 tools/render_readme.py            # write README.md and registry/skills.json
    python3 tools/render_readme.py --check    # exit 3 if either file is out of date
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_SLUG = "BEKO2210/SkillQuarry"
REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
REGISTRY = REPO / "registry" / "skills.json"
SKILLS_DIR = REPO / "skills"

REQUIRED_FIELDS = ("name", "displayName", "version", "description", "category", "license")
EXIT_STALE = 3

AGENT_LABELS = {
    "claude-code": "Claude Code",
    "agent-neutral-manual-mode": "Any agent (manual mode)",
    "codex": "Codex",
    "gemini": "Gemini",
    "mcp": "MCP",
}

CATEGORY_LABELS = {
    "autonomous": "🤖 Autonomous agents",
    "security": "🔐 Security",
    "coding": "💻 Coding",
    "testing": "🧪 Testing",
    "ui-ux": "🎨 UI / UX",
    "devops": "📦 DevOps",
    "mobile": "📱 Mobile",
    "web": "🌐 Web",
    "documentation": "📚 Documentation",
    "integrations": "🔌 Integrations",
    "utilities": "🛠️ Utilities",
}

QUALITY_COLORS = {
    "experimental": "8a6d3b",
    "verified": "5b8298",
    "tested": "2ea043",
    "trusted": "1f6feb",
    "certified": "f0932b",
}


class ManifestError(RuntimeError):
    """A skill manifest is missing or malformed; rendering must not guess."""


def discover_manifests() -> list[dict[str, Any]]:
    """Load every skills/<category>/<name>/skill.json, sorted for stable output."""
    manifests: list[dict[str, Any]] = []
    for path in sorted(SKILLS_DIR.glob("*/*/skill.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestError(f"{path.relative_to(REPO)}: unreadable manifest: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError(f"{path.relative_to(REPO)}: manifest must be a JSON object")
        missing = [field for field in REQUIRED_FIELDS if not data.get(field)]
        if missing:
            raise ManifestError(f"{path.relative_to(REPO)}: missing fields: {', '.join(missing)}")
        data["_dir"] = path.parent.relative_to(REPO).as_posix()
        manifests.append(data)
    if not manifests:
        raise ManifestError("no skill manifests found under skills/*/*/skill.json")
    manifests.sort(key=lambda item: (str(item["category"]), str(item["name"])))
    return manifests


IGNORED_DIRECTORIES = {"__pycache__", "target", "node_modules", ".git"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def skill_checksum(directory: Path) -> str:
    """A content hash over everything a user would install.

    Every tracked file is hashed with its repository-relative path and its
    executable bit, so a renamed file, a changed byte or a lost `chmod +x` all
    change the result. Build output and caches are excluded — they are not part of
    the skill and differ per machine.
    """
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if IGNORED_DIRECTORIES & set(path.parts) or path.suffix in IGNORED_SUFFIXES:
            continue
        relative = path.relative_to(directory).as_posix()
        executable = "x" if path.stat().st_mode & 0o111 else "-"
        digest.update(f"{relative}\0{executable}\0".encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _tests(manifest: dict[str, Any]) -> dict[str, Any]:
    tests = manifest.get("tests")
    return tests if isinstance(tests, dict) else {}


def _agents(manifest: dict[str, Any]) -> str:
    value = manifest.get("agents") or manifest.get("compatibility") or []
    return ", ".join(AGENT_LABELS.get(str(item), str(item)) for item in value) or "—"


def _category(manifest: dict[str, Any]) -> str:
    key = str(manifest["category"])
    return CATEGORY_LABELS.get(key, key.replace("-", " ").capitalize())


def _workflow(manifest: dict[str, Any]) -> str:
    return str(manifest.get("workflow") or f"{manifest['name']}-tests.yml")


def _quality_badge(manifest: dict[str, Any]) -> str:
    quality = str(manifest.get("quality", "experimental")).lower()
    color = QUALITY_COLORS.get(quality, "5b8298")
    label = quality.capitalize()
    tests = _tests(manifest)
    detail = ""
    if tests.get("count"):
        detail = f"{tests['count']} tests"
        if tests.get("coverage"):
            detail += ", 100% core coverage" if "100" in str(tests["coverage"]) else f", {tests['coverage']}"
    badge = f"![{label}](https://img.shields.io/badge/{label}-{color}?style=flat-square&label=)"
    report = tests.get("report")
    if detail and report:
        return f"{badge} [{detail}]({manifest['_dir']}/{report})"
    return f"{badge} {detail}".strip()


def render_table(manifests: list[dict[str, Any]]) -> str:
    lines = [
        "| Skill | Category | What it does | Agents | Quality |",
        "|---|---|---|---|---|",
    ]
    for manifest in manifests:
        lines.append(
            f"| **[{manifest['displayName']}]({manifest['_dir']})** "
            f"| {_category(manifest)} "
            f"| {manifest['description']} "
            f"| {_agents(manifest)} "
            f"| {_quality_badge(manifest)} |"
        )
    return "\n".join(lines)


def render_stats(manifests: list[dict[str, Any]]) -> str:
    total_tests = sum(int(_tests(m).get("count") or 0) for m in manifests)
    categories = len({str(m["category"]) for m in manifests})
    badges = [
        f"![Skills](https://img.shields.io/badge/skills-{len(manifests)}-f0932b?style=for-the-badge)",
        f"![Categories](https://img.shields.io/badge/categories-{categories}-5b8298?style=for-the-badge)",
        f"![Tests](https://img.shields.io/badge/tests-{total_tests}%20passing-2ea043?style=for-the-badge)",
        "![Dependencies](https://img.shields.io/badge/dependencies-none-3d5568?style=for-the-badge)",
    ]
    return "\n".join(badges)


def render_ci(manifests: list[dict[str, Any]]) -> str:
    """One CI badge per skill, so a new skill never needs a hand-edited badge row."""
    badges = []
    for manifest in manifests:
        workflow = _workflow(manifest)
        badges.append(
            f"[![{manifest['displayName']} tests](https://img.shields.io/github/actions/workflow/status/"
            f"{REPO_SLUG}/{workflow}?style=flat-square&logo=githubactions&logoColor=white"
            f"&label={manifest['displayName']})](https://github.com/{REPO_SLUG}/actions/workflows/{workflow})"
        )
    return "\n".join(badges)


def render_cards(manifests: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for manifest in manifests:
        directory = manifest["_dir"]
        parts = [f"### {manifest['displayName']}", ""]
        banner = manifest.get("banner")
        if banner:
            parts += [
                "<div align=\"center\">",
                "",
                f"<img src=\"{banner}\" alt=\"{manifest['displayName']} — {manifest.get('tagline', '')}\" width=\"720\">",
                "",
                "</div>",
                "",
            ]
        if manifest.get("tagline"):
            parts += [f"**{manifest['tagline']}**", ""]
        parts += [str(manifest["description"]), ""]
        highlights = manifest.get("highlights")
        if isinstance(highlights, list) and highlights:
            parts += [f"- {item}" for item in highlights] + [""]
        quickstart = manifest.get("quickstart")
        if quickstart:
            parts += ["```bash", str(quickstart).strip(), "```", ""]
        links = [f"[Documentation]({directory}/README.md)", f"[Skill]({directory}/SKILL.md)"]
        report = _tests(manifest).get("report")
        if report:
            links.append(f"[Test report]({directory}/{report})")
        if manifest.get("research"):
            links.append(f"[Research]({directory}/{manifest['research']})")
        parts += [" · ".join(links), ""]
        blocks.append("\n".join(parts).rstrip())
    return "\n\n---\n\n".join(blocks)


def render_registry(manifests: list[dict[str, Any]]) -> str:
    entries = []
    for manifest in manifests:
        tests = _tests(manifest)
        entries.append({
            "checksum": skill_checksum(REPO / manifest["_dir"]),
            "name": manifest["name"],
            "displayName": manifest["displayName"],
            "version": manifest["version"],
            "description": manifest["description"],
            "category": manifest["category"],
            "license": manifest["license"],
            "path": manifest["_dir"],
            "compatibility": manifest.get("compatibility", []),
            "platforms": manifest.get("platforms", []),
            "quality": manifest.get("quality", "experimental"),
            "security": manifest.get("security", {}),
            "requires": manifest.get("requires", {}),
            "workflow": _workflow(manifest),
            "tests": {"count": tests.get("count"), "coverage": tests.get("coverage")},
        })
    document = {
        "schema_version": 2,
        "generated_by": "tools/render_readme.py",
        "skills": entries,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def replace_block(text: str, marker: str, body: str) -> str:
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    if start not in text or end not in text:
        raise ManifestError(f"README.md is missing the {marker} markers")
    head, rest = text.split(start, 1)
    _stale, tail = rest.split(end, 1)
    return f"{head}{start}\n{body}\n{end}{tail}"


def render_readme(manifests: list[dict[str, Any]]) -> str:
    text = README.read_text("utf-8")
    text = replace_block(text, "SKILLS:STATS", render_stats(manifests))
    text = replace_block(text, "SKILLS:CI", render_ci(manifests))
    text = replace_block(text, "SKILLS:TABLE", render_table(manifests))
    text = replace_block(text, "SKILLS:CARDS", render_cards(manifests))
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify generated files are current")
    args = parser.parse_args(argv)

    try:
        manifests = discover_manifests()
        readme = render_readme(manifests)
        registry = render_registry(manifests)
    except ManifestError as exc:
        print(f"render_readme: {exc}", file=sys.stderr)
        return 2

    stale = [
        name for name, path, content in (
            ("README.md", README, readme),
            ("registry/skills.json", REGISTRY, registry),
        )
        if not path.exists() or path.read_text("utf-8") != content
    ]

    if args.check:
        if stale:
            print("render_readme: out of date: " + ", ".join(stale), file=sys.stderr)
            print("run `python3 tools/render_readme.py` and commit the result", file=sys.stderr)
            return EXIT_STALE
        print(f"render_readme: up to date ({len(manifests)} skills)")
        return 0

    README.write_text(readme, encoding="utf-8")
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(registry, encoding="utf-8")
    print(f"render_readme: wrote {len(manifests)} skills" + (f" (updated: {', '.join(stale)})" if stale else " (no change)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
