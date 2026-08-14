#!/usr/bin/env python3
"""One deliberately narrow LockScope repair used by the pro experiment.

It performs exactly one transformation class: if a guard is acquired, then an
independent await happens before the guard's first use, move the acquisition to
immediately after the last such await. It refuses ambiguous/control-flow-heavy
cases instead of trying to be clever.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import asdict, dataclass
from pathlib import Path


ACQUIRE = re.compile(
    r"^(?P<indent>\s*)let\s+(?P<mut>mut\s+)?(?P<guard>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<rhs>.+\.(?:lock|read|write)\(\)(?:\.await|\.unwrap\(\)|\?)?)\s*;\s*$"
)
CONTROL = re.compile(r"\b(if|else|match|for|while|loop|return|break|continue)\b")


@dataclass(frozen=True)
class Repair:
    guard: str
    from_line: int
    to_line: int
    acquisition: str


def repair_lines(lines: list[str]) -> tuple[list[str], Repair | None]:
    for index, line in enumerate(lines):
        match = ACQUIRE.match(line)
        if not match:
            continue
        guard = match.group("guard")
        word = re.compile(r"\b" + re.escape(guard) + r"\b")
        first_use: int | None = None
        for later in range(index + 1, min(len(lines), index + 80)):
            clean = lines[later].split("//", 1)[0]
            if re.search(r"\bdrop\s*\(\s*" + re.escape(guard) + r"\s*\)", clean):
                first_use = later
                break
            if word.search(clean):
                first_use = later
                break
            # Refuse to cross a closing brace before first use; doing so would
            # move the binding into another lexical scope.
            if clean.strip() == "}":
                break
        if first_use is None:
            continue

        between = lines[index + 1:first_use]
        await_offsets = [offset for offset, row in enumerate(between) if ".await" in row]
        if not await_offsets:
            continue
        target = index + 1 + await_offsets[-1]

        # The supported repair deliberately refuses branching or another guard
        # acquisition in the crossed region. This keeps it a dependency motion,
        # not a control-flow rewrite.
        crossed = lines[index + 1:target + 1]
        if any(CONTROL.search(row.split("//", 1)[0]) for row in crossed):
            continue
        if any(ACQUIRE.match(row) for row in crossed):
            continue
        if any(word.search(row.split("//", 1)[0]) for row in crossed):
            continue

        repaired = list(lines)
        acquisition = repaired.pop(index)
        # After pop(), the old target shifts by one. Insert after the awaited
        # statement, therefore at the original target index.
        repaired.insert(target, acquisition)
        return repaired, Repair(
            guard=guard,
            from_line=index + 1,
            to_line=target + 1,
            acquisition=acquisition.strip(),
        )
    return list(lines), None


def repair_file(path: Path) -> Repair | None:
    original = path.read_text("utf-8")
    had_trailing_newline = original.endswith("\n")
    lines = original.splitlines()
    repaired, result = repair_lines(lines)
    if result is None:
        return None
    rendered = "\n".join(repaired) + ("\n" if had_trailing_newline else "")
    if "unsafe" in rendered and "unsafe" not in original:
        raise RuntimeError("repair unexpectedly introduced unsafe")
    path.write_text(rendered, "utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    args = parser.parse_args()
    result = repair_file(Path(args.file))
    if result is None:
        print("NO_REPAIR")
        return 2
    print(asdict(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
