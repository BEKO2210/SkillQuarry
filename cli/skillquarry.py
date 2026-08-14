#!/usr/bin/env python3
"""skillquarry — search, inspect, install, update and diagnose SkillQuarry skills.

This is a local client, not a package manager with a network: it reads a quarry
checked out on this machine, verifies each skill's checksum against the registry
before touching anything, and then runs that skill's own installer. Nothing is
downloaded, and no skill is installed whose files no longer match what the
registry describes.

    skillquarry search unsafe
    skillquarry info cordon
    skillquarry install strata --prefix ~/.local
    skillquarry update
    skillquarry doctor

The quarry is found in this order: --quarry, $SKILLQUARRY_ROOT, the directory the
launcher recorded at install time, then the current directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

__version__ = "1.0.0"

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_MISMATCH = 3

IGNORED_DIRECTORIES = {"__pycache__", "target", "node_modules", ".git"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}

STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
STATE_FILE = Path(os.environ.get("SKILLQUARRY_STATE", STATE_HOME / "skillquarry" / "installed.json"))
STATE_VERSION = 1


class QuarryError(RuntimeError):
    """Anything the client refuses to do without guessing."""


# --------------------------------------------------------------------------- io


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def skill_checksum(directory: Path) -> str:
    """Same definition as tools/render_readme.py; kept here so the client stands alone."""
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


# ----------------------------------------------------------------------- quarry


def find_quarry(explicit: str | None = None) -> Path:
    candidates = [explicit, os.environ.get("SKILLQUARRY_ROOT"), os.environ.get("SKILLQUARRY_DEFAULT_ROOT"), "."]
    for candidate in candidates:
        if not candidate:
            continue
        root = Path(candidate).expanduser().resolve()
        if (root / "registry" / "skills.json").is_file():
            return root
    raise QuarryError(
        "no quarry found. Pass --quarry /path/to/SkillQuarry, set SKILLQUARRY_ROOT, "
        "or run from inside a checkout."
    )


def load_registry(root: Path) -> list[dict[str, Any]]:
    path = root / "registry" / "skills.json"
    try:
        document = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuarryError(f"cannot read {path}: {exc}") from exc
    skills = document.get("skills")
    if not isinstance(skills, list):
        raise QuarryError(f"{path} has no skills array")
    return skills


def find_skill(skills: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for skill in skills:
        if skill.get("name") == name:
            return skill
    known = ", ".join(sorted(str(item.get("name")) for item in skills))
    raise QuarryError(f"no skill named {name!r}. Known: {known}")


def load_manifest(root: Path, skill: dict[str, Any]) -> dict[str, Any]:
    path = root / str(skill.get("path", "")) / "skill.json"
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuarryError(f"cannot read {path}: {exc}") from exc


# ------------------------------------------------------------------------ state


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"state_version": STATE_VERSION, "installed": {}}
    try:
        state = json.loads(STATE_FILE.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuarryError(f"install record at {STATE_FILE} is unreadable: {exc}") from exc
    if state.get("state_version") != STATE_VERSION or not isinstance(state.get("installed"), dict):
        raise QuarryError(f"install record at {STATE_FILE} has an unsupported format")
    return state


def save_state(state: dict[str, Any]) -> None:
    atomic_write_json(STATE_FILE, state)


# ---------------------------------------------------------------------- actions


def matches(skill: dict[str, Any], *, agent: str | None, platform: str | None, category: str | None,
            quality: str | None, offline: bool, no_secrets: bool, keyword: str | None) -> bool:
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


def verify_skill(root: Path, skill: dict[str, Any]) -> None:
    directory = root / str(skill.get("path", ""))
    if not directory.is_dir():
        raise QuarryError(f"{skill.get('name')}: {directory} does not exist")
    actual = skill_checksum(directory)
    if actual != skill.get("checksum"):
        raise QuarryError(
            f"{skill.get('name')}: files do not match the registry checksum.\n"
            f"  registry: {skill.get('checksum')}\n"
            f"  on disk:  {actual}\n"
            "Refusing to install. Re-run `python3 tools/render_readme.py` in the quarry "
            "if the change was intentional."
        )


def run_installer(root: Path, skill: dict[str, Any], manifest: dict[str, Any], script: str,
                  prefix: str | None) -> subprocess.CompletedProcess[str]:
    directory = root / str(skill["path"])
    entrypoints = manifest.get("entrypoints") or {}
    name = entrypoints.get(script)
    if not name:
        raise QuarryError(f"{skill['name']} declares no {script} entrypoint")
    path = directory / name
    if not path.is_file():
        raise QuarryError(f"{skill['name']}: {script} script {path} is missing")
    environment = dict(os.environ)
    if prefix:
        variable = entrypoints.get("prefix_env")
        if not variable:
            raise QuarryError(
                f"{skill['name']} does not declare entrypoints.prefix_env, so --prefix cannot be honoured"
            )
        environment[variable] = str(Path(prefix).expanduser())
    return subprocess.run(
        ["bash", str(path)], cwd=directory, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600, check=False,
    )


def install(root: Path, name: str, prefix: str | None, *, force: bool = False) -> dict[str, Any]:
    skills = load_registry(root)
    skill = find_skill(skills, name)
    verify_skill(root, skill)
    manifest = load_manifest(root, skill)

    state = load_state()
    record = state["installed"].get(name)
    if record and not force and record.get("checksum") == skill.get("checksum"):
        raise QuarryError(f"{name} {record.get('version')} is already installed; pass --force to reinstall")

    result = run_installer(root, skill, manifest, "install", prefix)
    if result.returncode != 0:
        raise QuarryError(f"{name}: installer failed with exit {result.returncode}:\n{result.stdout.strip()}")

    state["installed"][name] = {
        "version": skill.get("version"),
        "checksum": skill.get("checksum"),
        "quarry": str(root),
        "prefix": str(Path(prefix).expanduser()) if prefix else None,
        "output": result.stdout.strip()[-2000:],
    }
    save_state(state)
    return state["installed"][name]


def uninstall(root: Path, name: str) -> None:
    state = load_state()
    if name not in state["installed"]:
        raise QuarryError(f"{name} is not recorded as installed")
    skill = find_skill(load_registry(root), name)
    manifest = load_manifest(root, skill)
    prefix = state["installed"][name].get("prefix")
    result = run_installer(root, skill, manifest, "uninstall", prefix)
    if result.returncode != 0:
        raise QuarryError(f"{name}: uninstaller failed with exit {result.returncode}:\n{result.stdout.strip()}")
    del state["installed"][name]
    save_state(state)


def outdated(root: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Installed skills whose registry entry has moved on."""
    skills = {str(item.get("name")): item for item in load_registry(root)}
    stale = []
    for name, record in sorted(load_state()["installed"].items()):
        skill = skills.get(name)
        if not skill:
            continue
        if skill.get("checksum") != record.get("checksum"):
            stale.append((name, record, skill))
    return stale


def diagnose(root: Path) -> list[tuple[str, str, str]]:
    """Return (status, subject, detail) rows. `status` is ok, warn or fail."""
    rows: list[tuple[str, str, str]] = []
    rows.append(("ok" if sys.version_info >= (3, 10) else "fail", "python",
                 f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} (3.10+ required)"))
    rows.append(("ok" if shutil.which("git") else "fail", "git",
                 shutil.which("git") or "not found in PATH"))
    rows.append(("ok", "quarry", str(root)))

    try:
        skills = load_registry(root)
    except QuarryError as exc:
        rows.append(("fail", "registry", str(exc)))
        return rows
    rows.append(("ok", "registry", f"{len(skills)} skills"))

    for skill in skills:
        name = str(skill.get("name"))
        try:
            verify_skill(root, skill)
            rows.append(("ok", f"checksum:{name}", "matches the files on disk"))
        except QuarryError:
            rows.append(("fail", f"checksum:{name}", "does not match the files on disk"))
        missing = [binary for binary in ((skill.get("requires") or {}).get("binaries") or [])
                   if not shutil.which(binary)]
        if missing:
            rows.append(("warn", f"requires:{name}", "missing: " + ", ".join(missing)))

    try:
        state = load_state()
    except QuarryError as exc:
        rows.append(("fail", "install record", str(exc)))
        return rows
    rows.append(("ok", "install record", f"{len(state['installed'])} installed ({STATE_FILE})"))
    for name, record, skill in outdated(root):
        rows.append(("warn", f"outdated:{name}",
                     f"installed {record.get('version')}, quarry has {skill.get('version')}"))

    bin_dir = str(Path.home() / ".local" / "bin")
    on_path = bin_dir in os.environ.get("PATH", "").split(os.pathsep)
    rows.append(("ok" if on_path else "warn", "PATH",
                 f"{bin_dir} {'is' if on_path else 'is not'} in PATH"))
    return rows


# -------------------------------------------------------------------- rendering


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


def format_info(root: Path, skill: dict[str, Any], installed: dict[str, Any] | None) -> str:
    security = skill.get("security") or {}
    tests = skill.get("tests") or {}
    lines = [
        f"{skill.get('displayName')} ({skill.get('name')}) {skill.get('version')}",
        "",
        str(skill.get("description", "")),
        "",
        f"category      {skill.get('category')}",
        f"quality       {skill.get('quality')}",
        f"license       {skill.get('license')}",
        f"agents        {', '.join(skill.get('compatibility') or []) or '-'}",
        f"platforms     {', '.join(skill.get('platforms') or []) or '-'}",
        f"tests         {tests.get('count', '-')} ({tests.get('coverage', 'n/a')})",
        f"requires      {', '.join((skill.get('requires') or {}).get('binaries') or []) or 'nothing extra'}",
        f"network       {security.get('network_access', 'undeclared')}",
        f"secrets       {'required' if security.get('requires_secrets') else 'none'}",
        f"destructive   {'; '.join(security.get('destructive_operations') or []) or 'none declared'}",
        f"reviewed by   {security.get('reviewed_by', 'not recorded')}",
        f"checksum      {skill.get('checksum')}",
        f"path          {root / str(skill.get('path'))}",
    ]
    if installed:
        lines += ["", f"installed     {installed.get('version')} at {installed.get('prefix') or 'the default prefix'}"]
        if installed.get("checksum") != skill.get("checksum"):
            lines.append("              differs from the quarry; run `skillquarry update`")
    else:
        lines += ["", "installed     no"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillquarry", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"skillquarry {__version__}")
    parser.add_argument("--quarry", help="path to a SkillQuarry checkout")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="find skills")
    search.add_argument("keyword", nargs="?")
    search.add_argument("--agent")
    search.add_argument("--platform", choices=["linux", "macos", "windows"])
    search.add_argument("--category")
    search.add_argument("--quality", choices=["experimental", "verified", "tested", "trusted", "certified"])
    search.add_argument("--offline", action="store_true", help="only skills that need no network of their own")
    search.add_argument("--no-secrets", action="store_true", help="only skills that need no credentials")
    search.add_argument("--json", action="store_true")

    info = sub.add_parser("info", help="show one skill in detail")
    info.add_argument("name")

    installer = sub.add_parser("install", help="verify and install a skill")
    installer.add_argument("name")
    installer.add_argument("--prefix", help="install target, passed to the skill's own installer")
    installer.add_argument("--force", action="store_true", help="reinstall even if unchanged")

    remover = sub.add_parser("uninstall", help="run the skill's uninstaller and forget it")
    remover.add_argument("name")

    updater = sub.add_parser("update", help="reinstall installed skills whose files changed")
    updater.add_argument("name", nargs="?")
    updater.add_argument("--dry-run", action="store_true", help="only report what would change")

    validator = sub.add_parser("validate", help="check a skill directory against the quarry rules")
    validator.add_argument("path", nargs="?", default=".")

    sub.add_parser("list", help="list every skill in the quarry")
    sub.add_parser("doctor", help="check this machine, the quarry and the install record")
    return parser


def command_validate(root: Path, target: Path) -> int:
    """Delegate to the quarry's own validator so there is one set of rules."""
    script = root / "tools" / "validate_skills.py"
    if not script.is_file():
        raise QuarryError(f"the quarry at {root} has no tools/validate_skills.py")
    manifest = target / "skill.json"
    if not manifest.is_file():
        raise QuarryError(f"{target} contains no skill.json")
    result = subprocess.run([sys.executable, str(script)], cwd=root, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, check=False)
    print(result.stdout.strip())
    return EXIT_OK if result.returncode == 0 else EXIT_MISMATCH


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = find_quarry(args.quarry)

        if args.command in {"search", "list"}:
            skills = load_registry(root)
            if args.command == "list":
                selected = skills
            else:
                selected = [s for s in skills if matches(
                    s, agent=args.agent, platform=args.platform, category=args.category,
                    quality=args.quality, offline=args.offline, no_secrets=args.no_secrets,
                    keyword=args.keyword)]
                if args.json:
                    print(json.dumps(selected, indent=2, ensure_ascii=False, sort_keys=True))
                    return EXIT_OK
            if not selected:
                print("no skill matches those filters")
                return EXIT_OK
            for skill in selected:
                print(format_row(skill))
            return EXIT_OK

        if args.command == "info":
            skill = find_skill(load_registry(root), args.name)
            print(format_info(root, skill, load_state()["installed"].get(args.name)))
            return EXIT_OK

        if args.command == "install":
            record = install(root, args.name, args.prefix, force=args.force)
            print(f"installed {args.name} {record['version']}")
            print(record["output"])
            return EXIT_OK

        if args.command == "uninstall":
            uninstall(root, args.name)
            print(f"uninstalled {args.name}")
            return EXIT_OK

        if args.command == "update":
            stale = outdated(root)
            if args.name:
                stale = [item for item in stale if item[0] == args.name]
            if not stale:
                print("everything installed is up to date")
                return EXIT_OK
            for name, record, skill in stale:
                print(f"{name}: {record.get('version')} -> {skill.get('version')}")
                if args.dry_run:
                    continue
                install(root, name, record.get("prefix"), force=True)
                print(f"  updated {name}")
            return EXIT_OK

        if args.command == "validate":
            return command_validate(root, Path(args.path).expanduser().resolve())

        rows = diagnose(root)
        symbols = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
        for status, subject, detail in rows:
            print(f"{symbols[status]}  {subject:<22} {detail}")
        return EXIT_MISMATCH if any(status == "fail" for status, _, _ in rows) else EXIT_OK

    except QuarryError as exc:
        print(f"skillquarry: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())  # pragma: no cover
