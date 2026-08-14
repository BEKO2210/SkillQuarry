#!/usr/bin/env python3
"""A1 harness amendment: fixes fixture construction before any synthetic case ran.

Run 31849318020 failed before measuring a candidate because the final fixture
used dict(**base, drift=True) while base already contained drift=False. This
wrapper replaces only synthetic_cases() with the same frozen cases and gates,
using normal mapping override syntax for identical_noise. All measurement,
bootstrap, thresholds, labels and real-repository code remain in run_pro_test.py.
"""
from pathlib import Path
import run_pro_test as base


def synthetic_cases_a1(root: Path):
    baseline = dict(
        large_repeats=24,
        small_repeats=24,
        setup_cycles=0,
        alloc_mb=0,
        wrong=False,
        drift=False,
    )
    noise = {**baseline, "drift": True}
    cases = [
        ("near_14", "ACCEPT", ["large"], baseline,
         dict(large_repeats=21, small_repeats=21, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ("near_25", "ACCEPT", ["large"], baseline,
         dict(large_repeats=19, small_repeats=19, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ("near_5", "REJECT", ["large"], baseline,
         dict(large_repeats=23, small_repeats=23, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ("wrong_but_fast", "REJECT", ["large"], baseline,
         dict(large_repeats=17, small_repeats=17, setup_cycles=0, alloc_mb=0, wrong=True, drift=False)),
        ("memory_for_speed", "REJECT", ["large"], baseline,
         dict(large_repeats=20, small_repeats=20, setup_cycles=0, alloc_mb=48, wrong=False, drift=False)),
        ("cold_warm_tradeoff", "REJECT", ["large"], baseline,
         dict(large_repeats=20, small_repeats=20, setup_cycles=350000, alloc_mb=0, wrong=False, drift=False)),
        ("benchmark_overfit", "REJECT", ["large", "small"], baseline,
         dict(large_repeats=19, small_repeats=50, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ("identical_noise", "REJECT", ["large"], noise, noise),
    ]

    out = []
    for idx, (name, expected, workloads, bcfg, ccfg) in enumerate(cases):
        case_dir = root / name
        case_dir.mkdir(parents=True)
        base_file = case_dir / "baseline.py"
        cand_file = case_dir / "candidate.py"
        base.make_worker(base_file, bcfg)
        base.make_worker(cand_file, ccfg)
        metrics, correctness = base.paired_measure(
            base_file, cand_file, workloads, base.SEED + idx
        )
        primary = metrics["large"]
        reasons = []
        if not correctness:
            reasons.append("semantic_mismatch")
        if primary["speedup_lb95"] < base.MIN_SPEEDUP_LB:
            reasons.append("speedup_not_proven")
        if max(v["candidate_over_baseline_median"] for v in metrics.values()) > base.MAX_WORKLOAD_REGRESSION:
            reasons.append("workload_regression")
        if max(v["cold_regression_median"] for v in metrics.values()) > base.MAX_COLD_REGRESSION:
            reasons.append("cold_regression")
        if max(v["extra_rss_bytes"] for v in metrics.values()) > base.MAX_EXTRA_RSS:
            reasons.append("memory_regression")
        verdict = "ACCEPT" if not reasons else "REJECT"
        out.append({
            "name": name,
            "expected": expected,
            "verdict": verdict,
            "match": verdict == expected,
            "correctness": correctness,
            "reasons": reasons,
            "metrics": metrics,
        })
    return out


if __name__ == "__main__":
    base.synthetic_cases = synthetic_cases_a1
    base.main()
