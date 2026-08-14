#!/usr/bin/env python3
"""Dependency-free installer/uninstaller for Cordon."""
from __future__ import annotations

import argparse
import errno
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

VERSION = "1.0.0"


def fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.EINVAL, errno.ENOTSUP, errno.EACCES}:
            return
        raise
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EACCES}:
            raise
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        fsync_dir(path.parent)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.glob("*.py"), key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def install(root: Path, prefix: Path) -> Path:
    if sys.version_info < (3, 10):
        raise RuntimeError("Cordon requires Python 3.10 or newer")
    if shutil.which("git") is None:
        raise RuntimeError("git was not found on PATH")
    source = root / "src" / "cordon"
    if not (source / "core.py").is_file():
        raise RuntimeError(f"Cordon source package is missing: {source}")

    releases = prefix / "share" / "cordon" / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / f"{VERSION}-{source_digest(source)}"
    if not release.exists():
        stage = Path(tempfile.mkdtemp(prefix=".cordon-release-", dir=str(releases)))
        try:
            package = stage / "cordon"
            package.mkdir()
            for src in sorted(source.glob("*.py"), key=lambda item: item.name):
                atomic_write(package / src.name, src.read_bytes(), 0o644)
            fsync_dir(package)
            fsync_dir(stage)
            os.replace(stage, release)
            fsync_dir(releases)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    launcher = prefix / "bin" / "cordon"
    script = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.path.insert(0, {str(release)!r})\n"
        "from cordon.cli import main\n"
        "raise SystemExit(main())\n"
    ).encode("utf-8")
    atomic_write(launcher, script, 0o755)
    return launcher


def uninstall(prefix: Path) -> None:
    launcher = prefix / "bin" / "cordon"
    share = prefix / "share" / "cordon"
    launcher.unlink(missing_ok=True)
    if launcher.parent.exists():
        fsync_dir(launcher.parent)
    shutil.rmtree(share, ignore_errors=True)
    parent = share.parent
    if parent.exists():
        fsync_dir(parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("install", "uninstall"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    ns = parser.parse_args(argv)
    try:
        if ns.operation == "install":
            launcher = install(ns.root.resolve(), ns.prefix.expanduser().resolve())
            print(f"Installed: {launcher}")
        else:
            uninstall(ns.prefix.expanduser().resolve())
            print("Cordon program files removed; repository .cordon state was not modified.")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
