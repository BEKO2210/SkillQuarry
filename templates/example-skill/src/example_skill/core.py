"""Minimal but real skill logic: summarise text files without reading them twice.

This is the template every SkillQuarry skill is copied from. It is deliberately
small, has no third-party dependencies, and is covered by its own tests at 100%.
Replace this module with your own; keep the shape.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

__version__ = "1.0.0"

DEFAULT_MAX_BYTES = 5 * 1024 * 1024


class SkillError(RuntimeError):
    """Any condition the skill refuses to continue through."""


@dataclass(frozen=True)
class FileSummary:
    path: str
    lines: int
    words: int
    bytes: int


def atomic_write_text(path: Path, text: str) -> None:
    """Write a file so a reader never sees a half-written result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def summarise_file(path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> FileSummary:
    """Count lines, words and bytes of one text file.

    Refuses oversized and unreadable files loudly instead of reporting zeros —
    a silent zero is indistinguishable from an empty file.
    """
    if not path.is_file():
        raise SkillError(f"not a readable file: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise SkillError(f"{path} is {size} bytes, above the {max_bytes}-byte limit")
    try:
        text = path.read_text("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillError(f"{path} is not UTF-8 text: {exc}") from exc
    return FileSummary(path.name, len(text.splitlines()), len(text.split()), size)


def summarise_paths(paths: list[Path], *, max_bytes: int = DEFAULT_MAX_BYTES) -> list[FileSummary]:
    if not paths:
        raise SkillError("no files given")
    return [summarise_file(path, max_bytes=max_bytes) for path in sorted(paths)]


def render_json(summaries: list[FileSummary]) -> str:
    totals = {
        "files": len(summaries),
        "lines": sum(item.lines for item in summaries),
        "words": sum(item.words for item in summaries),
        "bytes": sum(item.bytes for item in summaries),
    }
    return json.dumps({"totals": totals, "files": [asdict(item) for item in summaries]}, indent=2) + "\n"
