"""Lock sites, lock order, and findings.

The engine turns structured syntax plus semantic evidence into lock sites, then
into findings. It never decides that something is a lock because of how the
method is spelled: a user-defined `lock()` on a plain struct resolves to that
struct's own source and is dropped here.

Everything in this module is deterministic. Given the same files and the same
semantic answers it produces byte-identical output, which is what makes a
re-analysis after a repair meaningful evidence rather than a second opinion.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Protocol

from . import syntax

# How wide an exclusive critical section may be before it is worth mentioning.
# A number this blunt is an advisory, and the finding says so.
LARGE_SECTION_LINES = 40

SEVERITY_ORDER = ("critical", "high", "medium", "low", "advisory")


@dataclass(frozen=True)
class LockSite:
    """One resolved lock acquisition and the life of its guard."""

    file: str
    function: str
    line: int
    guard: str
    lock_expr: str
    lock_key: str
    family: str            # "sync" or "async"
    mode: str              # "exclusive" or "read"
    origin: str            # "source" or "macro"
    awaits_while_live: int
    scope_end_line: int
    explicit_drop_line: int | None
    last_use_line: int
    span_lines: int
    evidence: str = ""

    def sort_key(self) -> tuple:
        return (self.file, self.function, self.line, self.guard, self.origin)


@dataclass
class Analysis:
    """Everything one run learned, in a stable order."""

    lock_sites: list[LockSite] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    files_analyzed: int = 0
    unresolved: list[dict[str, Any]] = field(default_factory=list)

    def kinds_in(self, function: str) -> set[str]:
        return {
            str(item["kind"]) for item in self.findings
            if item.get("function") == function
        }


class Resolver(Protocol):
    """Whatever can answer 'what type is this, really?'."""

    def evidence_for(
        self, path: Path, points: tuple[tuple[str, syntax.Point], ...], op: str,
        op_point: syntax.Point | None = None,
    ) -> str:
        ...

    def function_at(self, path: Path, point: syntax.Point) -> str:
        ...

    def definition_key(self, path: Path, points: tuple[tuple[str, syntax.Point], ...], fallback: str) -> str:
        ...

    def expand_macro(self, path: Path, point: syntax.Point) -> str:
        ...


def classify(evidence: str, op: str) -> tuple[str, str] | None:
    """Which lock family and mode the semantic evidence proves, if any.

    The evidence is hover text plus the URIs a definition and type definition
    resolve to. A tokio mutex resolves into the tokio crate's source, a std one
    into the standard library — that is the fact this reads, not the identifier.
    """
    text = evidence.lower().replace("\\", "/")
    is_tokio = "tokio::sync" in text or "/tokio-" in text or "/tokio/src/sync/" in text
    is_parking = "parking_lot" in text or "/parking_lot-" in text or "/lock_api-" in text
    is_std = "std::sync" in text or "/library/std/src/sync/" in text or "/std/src/sync/" in text
    if is_tokio:
        family = "async"
    elif is_parking or is_std:
        family = "sync"
    else:
        return None
    mode = "read" if op in {"read", "read_owned"} else "exclusive"
    return family, mode


def site_from_candidate(
    path: Path, candidate: syntax.Candidate, family: str, mode: str,
    function: str, lock_key: str, evidence: str, root: Path | None = None,
) -> LockSite:
    return LockSite(
        file=_relative(path, root),
        function=function,
        line=candidate.line,
        guard=candidate.guard,
        lock_expr=candidate.lock_expr,
        lock_key=lock_key,
        family=family,
        mode=mode,
        origin=candidate.origin,
        awaits_while_live=candidate.awaits_while_live,
        scope_end_line=candidate.live_end_line,
        explicit_drop_line=candidate.explicit_drop_line,
        last_use_line=candidate.last_use_line,
        span_lines=max(0, candidate.live_end_line - candidate.line),
        evidence=evidence,
    )


def _relative(path: Path, root: Path | None) -> str:
    if root is None:
        return path.name
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def find_cycles(sites: list[LockSite]) -> list[list[str]]:
    """Lock-order cycles, from acquisitions nested inside a live guard.

    An edge exists only where one guard is still live while another is taken in
    the same function — evidence in the code, not a guess about what two names
    might mean. Cycles are the strongly connected components of that graph.
    """
    edges: dict[str, set[str]] = {}
    display: dict[str, str] = {}
    by_function: dict[tuple[str, str], list[LockSite]] = {}
    for site in sites:
        display.setdefault(site.lock_key, site.lock_expr)
        by_function.setdefault((site.file, site.function), []).append(site)

    for group in by_function.values():
        ordered = sorted(group, key=lambda s: (s.line, s.span_lines))
        for outer in ordered:
            for inner in ordered:
                if inner.line <= outer.line or inner.line > outer.scope_end_line:
                    continue
                if outer.explicit_drop_line is not None and inner.line >= outer.explicit_drop_line:
                    continue
                edges.setdefault(outer.lock_key, set()).add(inner.lock_key)

    nodes = set(edges)
    for targets in edges.values():
        nodes.update(targets)

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for following in sorted(edges.get(node, set())):
            if following not in indices:
                visit(following)
                lowlink[node] = min(lowlink[node], lowlink[following])
            elif following in on_stack:
                lowlink[node] = min(lowlink[node], indices[following])
        if lowlink[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or component[0] in edges.get(component[0], set()):
                components.append(component)

    for node in sorted(nodes):
        if node not in indices:
            visit(node)

    cycles = [sorted(display.get(key, key) for key in component) for component in components]
    cycles.sort()
    return cycles


def findings_for(sites: list[LockSite], cycles: list[list[str]]) -> list[dict[str, Any]]:
    """The judgement, with the kind of evidence behind each item attached."""
    out: list[dict[str, Any]] = []
    for site in sites:
        if site.awaits_while_live:
            if site.family == "sync":
                kind, severity = "sync_lock_across_await", "critical"
            elif site.mode == "exclusive":
                kind, severity = "exclusive_lock_across_await", "high"
            else:
                kind, severity = "read_lock_across_await", "medium"
            out.append({
                "kind": kind,
                "severity": severity,
                "confidence": "semantic",
                "file": site.file,
                "function": site.function,
                "line": site.line,
                "lock": site.lock_expr,
                "guard": site.guard,
                "awaits": site.awaits_while_live,
                "span_lines": site.span_lines,
                "origin": site.origin,
                "evidence": (
                    f"{site.family} {site.mode} guard `{site.guard}` is live across "
                    f"{site.awaits_while_live} await point(s) up to line {site.scope_end_line}"
                ),
            })
        if site.mode == "exclusive" and site.span_lines >= LARGE_SECTION_LINES:
            out.append({
                "kind": "large_exclusive_critical_section",
                "severity": "advisory" if site.awaits_while_live == 0 else "high",
                "confidence": "heuristic",
                "file": site.file,
                "function": site.function,
                "line": site.line,
                "lock": site.lock_expr,
                "guard": site.guard,
                "span_lines": site.span_lines,
                "origin": site.origin,
                "evidence": (
                    f"exclusive guard `{site.guard}` spans {site.span_lines} lines "
                    f"(advisory threshold {LARGE_SECTION_LINES})"
                ),
            })
    for cycle in cycles:
        out.append({
            "kind": "lock_order_cycle",
            "severity": "critical",
            "confidence": "graph",
            "cycle": cycle,
            "evidence": "acquisition order forms a cycle: " + " -> ".join(cycle + cycle[:1]),
        })
    out.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return out


def analyze_source(
    path: Path,
    resolver: Resolver,
    root: Path | None = None,
    on_unresolved: Callable[[dict[str, Any]], None] | None = None,
) -> list[LockSite]:
    """Lock sites in one file: structured candidates, semantically confirmed."""
    source = path.read_bytes()
    tree = syntax.parse(source)
    sites: list[LockSite] = []

    for candidate in syntax.candidates_in(source, tree):
        evidence = resolver.evidence_for(
            path, candidate.receiver_points, candidate.op, candidate.op_point
        )
        classified = classify(evidence, candidate.op)
        if classified is None:
            if on_unresolved is not None:
                on_unresolved({
                    "file": _relative(path, root),
                    "line": candidate.line,
                    "guard": candidate.guard,
                    "op": candidate.op,
                    "reason": "no lock family proven by semantic resolution",
                })
            continue
        family, mode = classified
        sites.append(site_from_candidate(
            path, candidate, family, mode,
            resolver.function_at(path, candidate.guard_point),
            # The fallback identity is relative: an absolute path would make
            # the report differ between two checkouts of the same code.
            resolver.definition_key(
                path, candidate.receiver_points,
                f"{_relative(path, root)}#expr:{candidate.lock_expr}",
            ),
            evidence, root,
        ))

    for invocation in syntax.macro_invocations_in(source, tree):
        expansion = resolver.expand_macro(path, invocation.point)
        if not expansion:
            continue
        acquisition = syntax.acquisition_in_expansion(expansion)
        if acquisition is None:
            continue
        guard, op = acquisition
        evidence = resolver.evidence_for(path, invocation.identifier_points, op)
        classified = classify(evidence, op)
        if classified is None:
            continue
        family, mode = classified
        live_end, drop_line, last_use, awaits = syntax.macro_guard_lifetime(source, invocation, guard)
        name = invocation.identifier_points[0][0] if invocation.identifier_points else guard
        sites.append(LockSite(
            file=_relative(path, root),
            function=resolver.function_at(path, invocation.point),
            line=invocation.point.line + 1,
            guard=guard,
            lock_expr=name,
            lock_key=resolver.definition_key(
                path, invocation.identifier_points, f"{_relative(path, root)}#macro:{name}"
            ),
            family=family,
            mode=mode,
            origin="macro",
            awaits_while_live=awaits,
            scope_end_line=live_end,
            explicit_drop_line=drop_line,
            last_use_line=last_use,
            span_lines=max(0, live_end - (invocation.point.line + 1)),
            evidence=evidence,
        ))

    sites.sort(key=LockSite.sort_key)
    return sites


def analyze(
    paths: list[Path], resolver: Resolver, root: Path | None = None,
) -> Analysis:
    """Analyse a set of files as one workspace."""
    sites: list[LockSite] = []
    unresolved: list[dict[str, Any]] = []
    for path in paths:
        sites.extend(analyze_source(path, resolver, root, unresolved.append))
    sites.sort(key=LockSite.sort_key)
    cycles = find_cycles(sites)
    unresolved.sort(key=lambda item: (item["file"], item["line"], item["guard"]))
    return Analysis(
        lock_sites=sites,
        cycles=cycles,
        findings=findings_for(sites, cycles),
        files_analyzed=len(paths),
        unresolved=unresolved,
    )


def worst_severity(findings: list[dict[str, Any]]) -> str | None:
    for severity in SEVERITY_ORDER:
        if any(item.get("severity") == severity for item in findings):
            return severity
    return None


def without_evidence(site: LockSite) -> LockSite:
    """A lock site with the raw hover text removed, for compact reports."""
    return replace(site, evidence="")
