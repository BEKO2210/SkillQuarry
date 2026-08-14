#!/usr/bin/env python3
"""Build one reproducible archive per skill in dist/. Standard library only.

Release assets are how installs become countable: GitHub reports a download count
per asset through its public API, so the marketplace can show real numbers without
tracking anybody.

The archives are byte-for-byte reproducible — sorted entries, fixed timestamp,
uid/gid zeroed, only the executable bit kept — so two builds of the same commit
produce the same file, and the SHA256SUMS beside them mean something.

    python3 tools/package_skills.py            # write dist/
    python3 tools/package_skills.py --check    # verify archives match the sources
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "registry" / "skills.json"
DIST = REPO / "dist"
EXIT_STALE = 3

# Fixed so the archive depends on content only, never on when it was built.
FIXED_MTIME = 0
IGNORED_DIRECTORIES = {"__pycache__", "target", "node_modules", ".git"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


class PackageError(RuntimeError):
    """The archives cannot be built from what is on disk."""


def load_registry() -> list[dict[str, Any]]:
    try:
        document = json.loads(REGISTRY.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot read the registry: {exc}") from exc
    skills = document.get("skills")
    if not isinstance(skills, list) or not skills:
        raise PackageError("registry has no skills; run tools/render_readme.py first")
    return skills


def packable_files(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.rglob("*")
        if path.is_file() and not path.is_symlink()
        and not (IGNORED_DIRECTORIES & set(path.parts))
        and path.suffix not in IGNORED_SUFFIXES
    )


def build_archive(skill: dict[str, Any]) -> bytes:
    """A gzip tarball whose bytes depend only on the skill's contents."""
    directory = REPO / str(skill["path"])
    if not directory.is_dir():
        raise PackageError(f"{skill['name']}: {directory} does not exist")
    root = f"{skill['name']}-{skill['version']}"

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for path in packable_files(directory):
            info = tarfile.TarInfo(f"{root}/{path.relative_to(directory).as_posix()}")
            data = path.read_bytes()
            info.size = len(data)
            info.mtime = FIXED_MTIME
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            archive.addfile(info, io.BytesIO(data))

    compressed = io.BytesIO()
    # mtime=0 keeps the gzip header itself reproducible.
    import gzip
    with gzip.GzipFile(fileobj=compressed, mode="wb", compresslevel=9, mtime=0) as handle:
        handle.write(raw.getvalue())
    return compressed.getvalue()


def render() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    sums: list[str] = []
    for skill in load_registry():
        name = f"{skill['name']}-{skill['version']}.tar.gz"
        data = build_archive(skill)
        files[name] = data
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    files["SHA256SUMS"] = ("\n".join(sums) + "\n").encode("utf-8")
    return files


def current() -> dict[str, bytes]:
    if not DIST.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in sorted(DIST.iterdir()) if path.is_file()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if dist/ differs from the sources")
    args = parser.parse_args(argv)

    try:
        files = render()
    except PackageError as exc:
        print(f"package_skills: {exc}", file=sys.stderr)
        return 2

    if args.check:
        existing = current()
        if existing != files:
            differing = sorted(set(files) ^ set(existing)) or \
                sorted(k for k in files if existing.get(k) != files[k])
            print(f"package_skills: dist/ is out of date: {', '.join(differing)}", file=sys.stderr)
            return EXIT_STALE
        print(f"package_skills: dist/ matches the sources ({len(files)} files)")
        return 0

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    for name, data in files.items():
        (DIST / name).write_bytes(data)
    print(f"package_skills: wrote {len(files)} files to dist/")
    for line in files["SHA256SUMS"].decode("utf-8").splitlines():
        print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
