#!/usr/bin/env python3
"""Small LockScope prototype: lexical/NLL-aware async lock analysis for Rust.

This is an experiment, not a production parser. It intentionally limits itself to
straightforward `let guard = lock.{lock,read,write}().await` and
`std::sync::Mutex::lock().unwrap()` acquisition forms so the small test can be
falsified without pretending regex is a complete Rust semantic frontend.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class LockSite:
    function: str
    line: int
    guard: str
    lock_expr: str
    mode: str
    family: str
    last_use_line: int
    awaits_while_live: int
    span_lines: int


@dataclass(frozen=True)
class Analysis:
    lock_sites: list[LockSite]
    cycles: list[list[str]]
    findings: list[dict[str, object]]


ASYNC_ACQUIRE = re.compile(
    r"\blet\s+(?:mut\s+)?(?P<guard>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<expr>[^;]+?)\.(?P<op>lock|read|write)\(\)\.await\s*;"
)
SYNC_ACQUIRE = re.compile(
    r"\blet\s+(?:mut\s+)?(?P<guard>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<expr>[^;]+?)\.lock\(\)(?:\.unwrap\(\)|\?)\s*;"
)
ASYNC_FN = re.compile(r"\b(?:pub\s+)?async\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)")


def _strip_line_comment(line: str) -> str:
    return line.split("//", 1)[0]


def _functions(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return async function ranges using brace balance.

    The prototype deliberately does not claim macro expansion or full Rust syntax
    support. The adversarial coverage for those belongs in a later parser-backed
    test if this concept survives.
    """
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(lines):
        match = ASYNC_FN.search(_strip_line_comment(lines[i]))
        if not match:
            i += 1
            continue
        name = match.group(1)
        start = i
        depth = 0
        seen_open = False
        j = i
        while j < len(lines):
            clean = _strip_line_comment(lines[j])
            opens = clean.count("{")
            closes = clean.count("}")
            depth += opens
            seen_open = seen_open or opens > 0
            depth -= closes
            if seen_open and depth <= 0:
                out.append((name, start, j))
                i = j + 1
                break
            j += 1
        else:
            out.append((name, start, len(lines) - 1))
            i = len(lines)
    return out


def _norm_expr(expr: str) -> str:
    value = re.sub(r"\s+", "", expr.strip())
    value = re.sub(r"\.clone\(\)$", "", value)
    return value


def analyze_text(text: str) -> Analysis:
    lines = text.splitlines()
    sites: list[LockSite] = []
    by_function: dict[str, list[LockSite]] = {}

    for function, start, end in _functions(lines):
        function_sites: list[LockSite] = []
        for index in range(start, end + 1):
            clean = _strip_line_comment(lines[index])
            match = ASYNC_ACQUIRE.search(clean)
            family = "async"
            if not match:
                match = SYNC_ACQUIRE.search(clean)
                family = "sync"
            if not match:
                continue

            guard = match.group("guard")
            lock_expr = _norm_expr(match.group("expr"))
            if family == "async":
                mode = "read" if match.group("op") == "read" else "exclusive"
            else:
                mode = "exclusive"

            word = re.compile(r"\b" + re.escape(guard) + r"\b")
            explicit_drop = re.compile(r"\bdrop\s*\(\s*" + re.escape(guard) + r"\s*\)")
            last_use = index
            drop_line: int | None = None
            for later in range(index + 1, end + 1):
                candidate = _strip_line_comment(lines[later])
                if explicit_drop.search(candidate):
                    drop_line = later
                    break
                if word.search(candidate):
                    last_use = later

            # Approximate NLL: an await after the last textual guard use is not
            # counted as lock-held. Explicit drop ends the lifetime immediately.
            live_end = drop_line if drop_line is not None else last_use
            awaits = sum(
                ".await" in _strip_line_comment(lines[later])
                for later in range(index + 1, live_end + 1)
            )
            site = LockSite(
                function=function,
                line=index + 1,
                guard=guard,
                lock_expr=lock_expr,
                mode=mode,
                family=family,
                last_use_line=live_end + 1,
                awaits_while_live=awaits,
                span_lines=max(0, live_end - index),
            )
            sites.append(site)
            function_sites.append(site)
        by_function[function] = function_sites

    edges: set[tuple[str, str]] = set()
    for function_sites in by_function.values():
        for outer in function_sites:
            for inner in function_sites:
                if inner.line <= outer.line:
                    continue
                if inner.line <= outer.last_use_line and inner.lock_expr != outer.lock_expr:
                    edges.add((outer.lock_expr, inner.lock_expr))

    cycles: list[list[str]] = []
    for left, right in sorted(edges):
        if (right, left) in edges and [right, left] not in cycles:
            cycles.append([left, right])

    findings: list[dict[str, object]] = []
    for site in sites:
        if site.awaits_while_live:
            if site.family == "sync":
                kind, severity = "sync_lock_across_await", "critical"
            elif site.mode == "exclusive":
                kind, severity = "exclusive_lock_across_await", "high"
            else:
                kind, severity = "read_lock_across_await", "medium"
            findings.append(
                {
                    "kind": kind,
                    "severity": severity,
                    "function": site.function,
                    "line": site.line,
                    "lock": site.lock_expr,
                    "awaits": site.awaits_while_live,
                    "span_lines": site.span_lines,
                }
            )
        if site.mode == "exclusive" and site.span_lines >= 40:
            findings.append(
                {
                    "kind": "large_exclusive_critical_section",
                    "severity": "high",
                    "function": site.function,
                    "line": site.line,
                    "lock": site.lock_expr,
                    "span_lines": site.span_lines,
                }
            )

    for left, right in cycles:
        findings.append(
            {
                "kind": "lock_order_cycle",
                "severity": "critical",
                "cycle": [left, right, left],
            }
        )

    return Analysis(lock_sites=sites, cycles=cycles, findings=findings)


def as_jsonable(analysis: Analysis) -> dict[str, object]:
    return {
        "lock_sites": [asdict(site) for site in analysis.lock_sites],
        "cycles": analysis.cycles,
        "findings": analysis.findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    combined = "\n".join(Path(path).read_text("utf-8") for path in args.files)
    print(json.dumps(as_jsonable(analyze_text(combined)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
