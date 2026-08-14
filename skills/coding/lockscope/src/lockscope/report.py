"""The result envelope.

One shape for every run, sorted the same way every time, so two runs of the same
code produce identical bytes and a diff of two reports is meaningful. The verdict
is deliberately coarse: PASS when nothing dangerous was proven, FAIL when it was,
MANUAL_REVIEW when the evidence is real but the fix is not this program's to make.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from . import engine

SCHEMA = "lockscope.report/1"

PASS = "PASS"
FAIL = "FAIL"
MANUAL_REVIEW = "MANUAL_REVIEW"

# Findings this skill can act on. Anything else is a real observation that a
# person has to weigh, because the safe transformation is not mechanical.
ACTIONABLE = {"sync_lock_across_await", "exclusive_lock_across_await", "read_lock_across_await"}


def verdict_for(analysis: engine.Analysis) -> str:
    kinds = {str(item.get("kind")) for item in analysis.findings}
    if not kinds:
        return PASS
    if kinds - ACTIONABLE:
        # A lock-order cycle or a wide critical section is never auto-repaired.
        return MANUAL_REVIEW
    return FAIL


def build(
    analysis: engine.Analysis,
    toolchain: dict[str, str],
    *,
    repairs: list[dict[str, Any]] | None = None,
    refusals: list[dict[str, Any]] | None = None,
    verification: dict[str, Any] | None = None,
    timings: dict[str, float] | None = None,
    verdict: str | None = None,
    include_evidence: bool = False,
) -> dict[str, Any]:
    sites = []
    for site in sorted(analysis.lock_sites, key=engine.LockSite.sort_key):
        row = asdict(site if include_evidence else engine.without_evidence(site))
        if not include_evidence:
            row.pop("evidence", None)
        sites.append(row)
    return {
        "schema": SCHEMA,
        "version": _version(),
        "toolchain": dict(sorted(toolchain.items())),
        "files_analyzed": analysis.files_analyzed,
        "lock_sites": sites,
        "cycles": analysis.cycles,
        "findings": analysis.findings,
        "unresolved": analysis.unresolved,
        "repairs": sorted(repairs or [], key=lambda item: json.dumps(item, sort_keys=True)),
        "refusals": sorted(refusals or [], key=lambda item: json.dumps(item, sort_keys=True)),
        "verification": verification or {},
        "timings": dict(sorted((timings or {}).items())),
        "verdict": verdict or verdict_for(analysis),
    }


def _version() -> str:
    from . import __version__

    return __version__


def dumps(report: dict[str, Any]) -> str:
    """Stable text: sorted keys, fixed separators, one trailing newline."""
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def summary(report: dict[str, Any]) -> str:
    """A few lines for a terminal, with the worst thing first."""
    findings = report.get("findings") or []
    lines = [
        f"verdict     {report.get('verdict')}",
        f"files       {report.get('files_analyzed')}",
        f"lock sites  {len(report.get('lock_sites') or [])}",
        f"findings    {len(findings)}",
    ]
    order = {name: index for index, name in enumerate(engine.SEVERITY_ORDER)}
    for item in sorted(findings, key=lambda f: (order.get(str(f.get("severity")), 99), str(f.get("file", "")), int(f.get("line", 0) or 0))):
        if item.get("kind") == "lock_order_cycle":
            # Closed on purpose: a cycle that is printed open reads like a
            # chain, and a chain is not the problem being reported.
            ring = list(item.get("cycle") or [])
            lines.append(f"  {item['severity']:<8} lock_order_cycle  {' -> '.join(ring + ring[:1])}")
            continue
        lines.append(
            f"  {item['severity']:<8} {item['kind']}  {item.get('file')}:{item.get('line')}"
            f" in {item.get('function')}  ({item.get('confidence')})"
        )
    for repair in report.get("repairs") or []:
        lines.append(f"  repaired  {repair.get('file')}:{repair.get('from_line')} -> {repair.get('to_line')}"
                     f"  guard `{repair.get('guard')}`")
    for refusal in report.get("refusals") or []:
        lines.append(f"  refused   {refusal.get('file')}:{refusal.get('line')}  {refusal.get('reason')}")
    return "\n".join(lines)
