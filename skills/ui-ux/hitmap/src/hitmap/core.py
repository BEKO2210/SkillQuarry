from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SAMPLE_FRACTIONS = (
    (0.50, 0.50),
    (0.20, 0.20), (0.80, 0.20), (0.20, 0.80), (0.80, 0.80),
    (0.50, 0.20), (0.80, 0.50), (0.50, 0.80), (0.20, 0.50),
)


@dataclass(frozen=True)
class Finding:
    finding_id: str
    selector: str
    reason: str
    reachable_points: int
    sampled_points: int
    occluders: tuple[str, ...]
    confidence: str


def sample_points(rect: dict[str, float]) -> list[tuple[int, int]]:
    x = float(rect["x"])
    y = float(rect["y"])
    w = float(rect["width"])
    h = float(rect["height"])
    if w <= 0 or h <= 0:
        return []
    return [
        (round(x + w * fx), round(y + h * fy))
        for fx, fy in SAMPLE_FRACTIONS
    ]


def stable_finding_id(index: int, selector: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in selector).strip("-")
    safe = "-".join(part for part in safe.split("-") if part)[:48] or "target"
    return f"HITMAP-{index:04d}-{safe}"


def classify_probe(probe: dict[str, Any], index: int) -> Finding | None:
    if not probe.get("eligible", False):
        return None
    samples = probe.get("samples") or []
    if len(samples) != 9:
        return None
    reachable = sum(1 for sample in samples if sample.get("reachable") is True)
    if reachable:
        return None
    occluders = tuple(
        sorted({str(sample.get("receiver") or "<none>") for sample in samples})
    )
    selector = str(probe.get("selector") or "<unknown>")
    return Finding(
        finding_id=stable_finding_id(index, selector),
        selector=selector,
        reason="visible enabled target has zero pointer-reachable sampled points",
        reachable_points=0,
        sampled_points=9,
        occluders=occluders,
        confidence="geometry",
    )


def summarize(probes: list[dict[str, Any]]) -> dict[str, Any]:
    findings = []
    for index, probe in enumerate(probes, start=1):
        finding = classify_probe(probe, index)
        if finding:
            findings.append(finding)
    return {
        "verdict": "FAIL" if findings else "PASS",
        "targets": len(probes),
        "findings": [
            {
                "id": f.finding_id,
                "selector": f.selector,
                "reason": f.reason,
                "reachable_points": f.reachable_points,
                "sampled_points": f.sampled_points,
                "occluders": list(f.occluders),
                "confidence": f.confidence,
            }
            for f in findings
        ],
    }
