#!/usr/bin/env python3
"""Build the static marketplace in site/ from the registry. Standard library only.

The site is generated from exactly the same data the README and the client use, so
it cannot drift into describing a skill that is not there. It is plain files: no
build step, no framework, no external request at runtime — searching and filtering
happen in the browser over data embedded in the page.

    python3 tools/build_site.py            # write site/
    python3 tools/build_site.py --check    # exit 3 if site/ is out of date
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "registry" / "skills.json"
SITE = REPO / "site"
ASSETS = REPO / "assets"
REPO_SLUG = "BEKO2210/SkillQuarry"
SOURCE_URL = f"https://github.com/{REPO_SLUG}"
EXIT_STALE = 3

CATEGORY_LABELS = {
    "autonomous": "Autonomous agents", "security": "Security", "coding": "Coding",
    "testing": "Testing", "ui-ux": "UI / UX", "devops": "DevOps", "mobile": "Mobile",
    "web": "Web", "documentation": "Documentation", "integrations": "Integrations",
    "utilities": "Utilities",
}
AGENT_LABELS = {
    "claude-code": "Claude Code", "agent-neutral-manual-mode": "Any agent (manual mode)",
    "codex": "Codex", "gemini": "Gemini", "mcp": "MCP",
}


class SiteError(RuntimeError):
    """The site cannot be built from what is on disk."""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _display(path: Path) -> str:
    """Repository-relative where possible; absolute otherwise, never an exception."""
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


def load_registry() -> list[dict[str, Any]]:
    try:
        document = json.loads(REGISTRY.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SiteError(f"cannot read {_display(REGISTRY)}: {exc}") from exc
    skills = document.get("skills")
    if not isinstance(skills, list) or not skills:
        raise SiteError("registry has no skills; run tools/render_readme.py first")
    return skills


def load_manifest(skill: dict[str, Any]) -> dict[str, Any]:
    path = REPO / str(skill.get("path", "")) / "skill.json"
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SiteError(f"cannot read {path}: {exc}") from exc


STYLE = """
:root {
  color-scheme: dark light;
  --ground: #0d141b; --raised: #131c25; --edge: #24313d;
  --ink: #f4f8fb; --muted: #9fb8c9; --dim: #6e8598;
  --accent: #ffd479; --accent-deep: #f0932b;
  --slate: #5b8298; --ok: #2ea043; --warn: #d29922;
  --radius: 14px;
}
@media (prefers-color-scheme: light) {
  :root {
    --ground: #f4f7f9; --raised: #ffffff; --edge: #d7e0e7;
    --ink: #14202b; --muted: #4a6a80; --dim: #6e8598;
    --accent: #b3730c; --accent-deep: #8a5806;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--ground); color: var(--ink);
  font: 16px/1.6 "Segoe UI", -apple-system, "Helvetica Neue", Arial, sans-serif;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 0 20px; }
header.top { border-bottom: 1px solid var(--edge); padding: 28px 0 22px; }
header.top img { width: 100%; max-width: 760px; height: auto; }
.lede { color: var(--muted); margin: 18px 0 0; }
.stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0 0; padding: 0; list-style: none; }
.stats li {
  border: 1px solid var(--edge); border-radius: 999px; padding: 4px 14px;
  font-size: 14px; color: var(--muted); background: var(--raised);
}
.stats b { color: var(--accent); }
.controls { display: grid; gap: 12px; margin: 26px 0 10px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); align-items: end; }
.controls label { display: block; font-size: 13px; color: var(--dim); margin-bottom: 5px; }
input, select {
  width: 100%; padding: 9px 11px; border-radius: 10px; font: inherit;
  background: var(--raised); color: var(--ink); border: 1px solid var(--edge);
}
input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.toggles { display: flex; gap: 18px; flex-wrap: wrap; margin: 4px 0 0; color: var(--muted); font-size: 14px; }
.toggles label { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 14px; color: var(--muted); }
.toggles input { width: auto; }
.count { color: var(--dim); font-size: 14px; margin: 14px 0 6px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); padding: 0 0 40px; }
.card {
  background: var(--raised); border: 1px solid var(--edge); border-radius: var(--radius);
  padding: 20px; display: flex; flex-direction: column; gap: 10px;
}
.card h2 { margin: 0; font-size: 20px; }
.card h2 a { color: var(--ink); }
.card .tagline { color: var(--accent); font-size: 14px; margin: -4px 0 0; }
.card p { margin: 0; color: var(--muted); font-size: 15px; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; padding-top: 6px; }
.tag {
  font-size: 12px; letter-spacing: .02em; padding: 3px 9px; border-radius: 999px;
  border: 1px solid var(--edge); color: var(--muted);
}
.tag.ok { color: var(--ok); border-color: var(--ok); }
.tag.warn { color: var(--warn); border-color: var(--warn); }
.tag.accent { color: var(--accent); border-color: var(--accent-deep); }
.empty { color: var(--muted); padding: 30px 0 60px; }
main { padding-top: 26px; }
h1.title { margin: 0 0 4px; font-size: 34px; }
.subtitle { color: var(--accent); margin: 0 0 18px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0 28px; font-size: 15px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--edge); vertical-align: top; }
th { color: var(--dim); font-weight: 600; width: 190px; }
pre {
  background: var(--raised); border: 1px solid var(--edge); border-radius: 12px;
  padding: 14px 16px; overflow-x: auto; font-size: 14px;
}
code { font-family: "Cascadia Code", "SF Mono", Consolas, monospace; }
ul.plain { padding-left: 20px; color: var(--muted); }
footer { border-top: 1px solid var(--edge); margin-top: 40px; padding: 22px 0 50px; color: var(--dim); font-size: 14px; }
.back { display: inline-block; margin: 22px 0 10px; font-size: 14px; }
.banner { width: 100%; max-width: 760px; height: auto; margin: 6px 0 18px; }
""".strip()

SCRIPT = """
const skills = JSON.parse(document.getElementById('skill-data').textContent);
const controls = ['q', 'agent', 'platform', 'category', 'quality'].map((id) => document.getElementById(id));
const toggles = ['offline', 'nosecrets'].map((id) => document.getElementById(id));
const grid = document.getElementById('grid');
const count = document.getElementById('count');

function matches(skill) {
  const [q, agent, platform, category, quality] = controls.map((el) => el.value);
  const [offline, noSecrets] = toggles.map((el) => el.checked);
  if (agent && !(skill.compatibility || []).includes(agent)) return false;
  if (platform && !(skill.platforms || []).includes(platform)) return false;
  if (category && skill.category !== category) return false;
  if (quality && skill.quality !== quality) return false;
  if (offline && (skill.security || {}).network_access !== 'none') return false;
  if (noSecrets && (skill.security || {}).requires_secrets !== false) return false;
  if (q) {
    const needle = q.toLowerCase();
    const hay = [skill.name, skill.displayName, skill.description, (skill.keywords || []).join(' ')]
      .join(' ').toLowerCase();
    if (!hay.includes(needle)) return false;
  }
  return true;
}

function apply() {
  let shown = 0;
  for (const card of grid.children) {
    const skill = skills.find((item) => item.name === card.dataset.name);
    const visible = matches(skill);
    card.hidden = !visible;
    if (visible) shown += 1;
  }
  count.textContent = shown === skills.length
    ? `${skills.length} skills`
    : `${shown} of ${skills.length} skills`;
  document.getElementById('empty').hidden = shown !== 0;
}

for (const el of [...controls, ...toggles]) {
  el.addEventListener(el.tagName === 'INPUT' && el.type !== 'checkbox' ? 'input' : 'change', apply);
}
apply();
""".strip()


def page(title: str, description: str, body: str, *, depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="icon" href="{up}assets/skillquarry-logo.svg" type="image/svg+xml">
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
{body}
<footer><div class="wrap">
Generated from <code>registry/skills.json</code> by <code>tools/build_site.py</code>. No tracking, no external requests.
· <a href="{SOURCE_URL}">Source on GitHub</a>
</div></footer>
</body>
</html>
"""


def card(skill: dict[str, Any], manifest: dict[str, Any]) -> str:
    security = skill.get("security") or {}
    tests = skill.get("tests") or {}
    tags = [f'<span class="tag accent">{esc(CATEGORY_LABELS.get(skill.get("category"), skill.get("category")))}</span>']
    if tests.get("count"):
        tags.append(f'<span class="tag ok">{esc(tests["count"])} tests</span>')
    if security.get("network_access") == "none":
        tags.append('<span class="tag ok">offline</span>')
    if security.get("destructive_operations"):
        tags.append('<span class="tag warn">destructive</span>')
    for agent in skill.get("compatibility") or []:
        tags.append(f'<span class="tag">{esc(AGENT_LABELS.get(agent, agent))}</span>')
    tagline = manifest.get("tagline")
    return f"""      <article class="card" data-name="{esc(skill['name'])}">
        <h2><a href="skills/{esc(skill['name'])}.html">{esc(skill.get('displayName'))}</a></h2>
        {f'<p class="tagline">{esc(tagline)}</p>' if tagline else ''}
        <p>{esc(skill.get('description'))}</p>
        <div class="tags">{''.join(tags)}</div>
      </article>"""


def options(values: list[str], labels: dict[str, str], placeholder: str) -> str:
    parts = [f'<option value="">{esc(placeholder)}</option>']
    for value in values:
        parts.append(f'<option value="{esc(value)}">{esc(labels.get(value, value))}</option>')
    return "".join(parts)


def build_index(skills: list[dict[str, Any]], manifests: dict[str, dict[str, Any]]) -> str:
    agents = sorted({a for s in skills for a in (s.get("compatibility") or [])})
    platforms = sorted({p for s in skills for p in (s.get("platforms") or [])})
    categories = sorted({str(s.get("category")) for s in skills})
    qualities = sorted({str(s.get("quality")) for s in skills})
    total_tests = sum(int((s.get("tests") or {}).get("count") or 0) for s in skills)
    data = json.dumps(skills, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")

    body = f"""<header class="top"><div class="wrap">
  <img src="assets/skillquarry-banner.svg" alt="SkillQuarry — the open marketplace for agent skills">
  <p class="lede">Reusable capabilities for AI coding agents: inspectable, tested, versioned, and installable with one command.</p>
  <ul class="stats">
    <li><b>{len(skills)}</b> skills</li>
    <li><b>{len(categories)}</b> categories</li>
    <li><b>{total_tests}</b> tests passing</li>
    <li><b>0</b> dependencies</li>
  </ul>
</div></header>
<main class="wrap">
  <div class="controls">
    <div><label for="q">Search</label><input id="q" type="search" placeholder="name, description, keyword" autocomplete="off"></div>
    <div><label for="agent">Agent</label><select id="agent">{options(agents, AGENT_LABELS, "Any agent")}</select></div>
    <div><label for="platform">Platform</label><select id="platform">{options(platforms, {}, "Any platform")}</select></div>
    <div><label for="category">Category</label><select id="category">{options(categories, CATEGORY_LABELS, "Any category")}</select></div>
    <div><label for="quality">Quality</label><select id="quality">{options(qualities, {}, "Any level")}</select></div>
  </div>
  <div class="toggles">
    <label><input type="checkbox" id="offline"> needs no network of its own</label>
    <label><input type="checkbox" id="nosecrets"> needs no credentials</label>
  </div>
  <p class="count" id="count">{len(skills)} skills</p>
  <div class="grid" id="grid">
{chr(10).join(card(skill, manifests[skill["name"]]) for skill in skills)}
  </div>
  <p class="empty" id="empty" hidden>No skill matches those filters.</p>
</main>
<script type="application/json" id="skill-data">{data}</script>
<script>{SCRIPT}</script>"""
    return page("SkillQuarry — the open marketplace for agent skills",
                "Discover, inspect and install reusable capabilities for AI coding agents.", body)


def build_detail(skill: dict[str, Any], manifest: dict[str, Any]) -> str:
    security = skill.get("security") or {}
    tests = skill.get("tests") or {}
    name = str(skill["name"])
    source = f"{SOURCE_URL}/tree/main/{skill['path']}"
    banner = manifest.get("banner")

    rows = [
        ("Category", CATEGORY_LABELS.get(skill.get("category"), skill.get("category"))),
        ("Version", skill.get("version")),
        ("Quality", skill.get("quality")),
        ("License", skill.get("license")),
        ("Agents", ", ".join(AGENT_LABELS.get(a, a) for a in skill.get("compatibility") or []) or "—"),
        ("Platforms", ", ".join(skill.get("platforms") or []) or "—"),
        ("Tests", f"{tests.get('count', '—')} — {tests.get('coverage', 'no coverage figure')}"),
        ("Needs installed", ", ".join((skill.get("requires") or {}).get("binaries") or []) or "nothing extra"),
        ("Network access", security.get("network_access", "undeclared")),
        ("Credentials", "required" if security.get("requires_secrets") else "none"),
        ("Writes outside the repository", "yes" if security.get("writes_outside_repository") else "no"),
        ("Irreversible operations", "; ".join(security.get("destructive_operations") or []) or "none declared"),
        ("Independently reviewed", security.get("reviewed_by", "not recorded")),
        ("Checksum", skill.get("checksum")),
    ]
    table = "\n".join(f"    <tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>" for key, value in rows)

    highlights = manifest.get("highlights") or []
    highlight_block = ""
    if highlights:
        items = "\n".join(f"    <li>{esc(item)}</li>" for item in highlights)
        highlight_block = f"  <h2>What it does</h2>\n  <ul class=\"plain\">\n{items}\n  </ul>\n"

    quickstart = manifest.get("quickstart")
    quickstart_block = f"  <h2>Quickstart</h2>\n  <pre><code>{esc(quickstart)}</code></pre>\n" if quickstart else ""

    links = [f'<a href="{esc(source)}">Source</a>',
             f'<a href="{esc(source)}/README.md">Documentation</a>',
             f'<a href="{esc(source)}/SKILL.md">SKILL.md</a>']
    if tests.get("report"):
        links.append(f'<a href="{esc(source)}/{esc(tests["report"])}">Test report</a>')

    body = f"""<main class="wrap">
  <a class="back" href="../index.html">&larr; all skills</a>
  {f'<img class="banner" src="../{esc(banner)}" alt="{esc(skill.get("displayName"))}">' if banner else ''}
  <h1 class="title">{esc(skill.get('displayName'))}</h1>
  {f'<p class="subtitle">{esc(manifest["tagline"])}</p>' if manifest.get('tagline') else ''}
  <p>{esc(skill.get('description'))}</p>
{highlight_block}  <h2>Install</h2>
  <pre><code>git clone {esc(SOURCE_URL)}.git
cd SkillQuarry/cli &amp;&amp; ./install.sh
skillquarry info {esc(name)}
skillquarry install {esc(name)}</code></pre>
  <p>Installation verifies the checksum below before running the skill's own installer.</p>
{quickstart_block}  <h2>Facts</h2>
  <table>
{table}
  </table>
  <p>{' · '.join(links)}</p>
</main>"""
    return page(f"{skill.get('displayName')} — SkillQuarry", str(skill.get("description", "")), body, depth=1)


def render() -> dict[str, str]:
    """Every generated file, as path-relative-to-site -> content."""
    skills = load_registry()
    manifests = {str(skill["name"]): load_manifest(skill) for skill in skills}
    files = {
        "index.html": build_index(skills, manifests),
        "style.css": STYLE + "\n",
        "registry.json": json.dumps({"schema_version": 2, "skills": skills}, indent=2,
                                    ensure_ascii=False, sort_keys=True) + "\n",
        ".nojekyll": "",
    }
    for skill in skills:
        files[f"skills/{skill['name']}.html"] = build_detail(skill, manifests[str(skill["name"])])
    for asset in sorted(ASSETS.glob("*.svg")):
        files[f"assets/{asset.name}"] = asset.read_text("utf-8")
    return files


def current() -> dict[str, str]:
    if not SITE.is_dir():
        return {}
    found = {}
    for path in sorted(SITE.rglob("*")):
        if path.is_file():
            found[path.relative_to(SITE).as_posix()] = path.read_text("utf-8")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if site/ differs from what would be generated")
    args = parser.parse_args(argv)

    try:
        files = render()
    except SiteError as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 2

    existing = current()
    if args.check:
        if existing != files:
            missing = sorted(set(files) - set(existing))
            extra = sorted(set(existing) - set(files))
            changed = sorted(k for k in set(files) & set(existing) if files[k] != existing[k])
            print("build_site: site/ is out of date", file=sys.stderr)
            for label, items in (("missing", missing), ("stale", changed), ("unexpected", extra)):
                if items:
                    print(f"  {label}: {', '.join(items)}", file=sys.stderr)
            print("  run `python3 tools/build_site.py` and commit the result", file=sys.stderr)
            return EXIT_STALE
        print(f"build_site: site/ is up to date ({len(files)} files)")
        return 0

    if SITE.exists():
        shutil.rmtree(SITE)
    for relative, content in files.items():
        target = SITE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(f"build_site: wrote {len(files)} files to site/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
