#!/usr/bin/env python3

import hashlib
import itertools
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

VARIANTS = ("A", "B", "C", "D")
PAIR_BUDGET = 2
RANDOM_TRIALS = 1000
BASELINE = (3, 3, 3, 3)
METRICS = ("arc", "mutex", "clone", "box_dyn")


@dataclass(frozen=True)
class Landscape:
    name: str
    singles: dict[str, tuple[int, int, int, int]]
    winner: tuple[str, str] | None
    aligned: bool


def landscapes() -> list[Landscape]:
    return [
        Landscape(
            "ownership_lock",
            {
                "A": (1, 4, 3, 3),
                "B": (4, 1, 3, 3),
                "C": (2, 3, 5, 3),
                "D": (3, 5, 2, 3),
            },
            ("A", "B"),
            True,
        ),
        Landscape(
            "lock_clone",
            {
                "A": (3, 1, 4, 3),
                "B": (5, 3, 2, 3),
                "C": (3, 4, 1, 3),
                "D": (2, 3, 3, 5),
            },
            ("A", "C"),
            True,
        ),
        Landscape(
            "clone_dispatch",
            {
                "A": (3, 3, 0, 4),
                "B": (2, 4, 3, 3),
                "C": (4, 2, 3, 3),
                "D": (3, 3, 4, 0),
            },
            ("A", "D"),
            True,
        ),
        Landscape(
            "ownership_dispatch",
            {
                "A": (1, 3, 5, 3),
                "B": (3, 3, 3, 1),
                "C": (3, 3, 3, 5),
                "D": (5, 3, 1, 3),
            },
            ("B", "C"),
            True,
        ),
        Landscape(
            "dual_boundary",
            {
                "A": (2, 5, 3, 3),
                "B": (3, 2, 5, 3),
                "C": (5, 3, 3, 1),
                "D": (3, 5, 3, 4),
            },
            ("A", "C"),
            True,
        ),
        # Deliberately adversarial: A+B has the strongest opposite-sign single
        # deltas, but the actual compatible synergy is C+D. A heuristic that
        # equates complementarity with compatibility should miss this under a
        # two-pair release budget.
        Landscape(
            "adversarial_compatibility",
            {
                "A": (3, 3, 0, 5),
                "B": (3, 3, 5, 0),
                "C": (2, 4, 3, 3),
                "D": (4, 2, 3, 3),
            },
            ("C", "D"),
            False,
        ),
        Landscape(
            "control_no_synergy_1",
            {
                "A": (1, 4, 3, 3),
                "B": (4, 1, 3, 3),
                "C": (3, 3, 1, 4),
                "D": (3, 3, 4, 1),
            },
            None,
            False,
        ),
        Landscape(
            "control_no_synergy_2",
            {
                "A": (2, 5, 3, 3),
                "B": (5, 2, 3, 3),
                "C": (3, 3, 2, 5),
                "D": (3, 3, 5, 2),
            },
            None,
            False,
        ),
    ]


def dominates(left, right) -> bool:
    return all(a <= b for a, b in zip(left, right)) and any(
        a < b for a, b in zip(left, right)
    )


def complementarity(a, b) -> int:
    da = [x - y for x, y in zip(a, BASELINE)]
    db = [x - y for x, y in zip(b, BASELINE)]
    return sum(abs(x * y) for x, y in zip(da, db) if x * y < 0)


def pair_cost(landscape: Landscape, pair: tuple[str, str]):
    pair = tuple(sorted(pair))
    a = landscape.singles[pair[0]]
    b = landscape.singles[pair[1]]
    if landscape.winner is not None and pair == tuple(sorted(landscape.winner)):
        return tuple(min(x, y) for x, y in zip(a, b))
    return tuple(max(x, y) for x, y in zip(a, b))


def write_crate(root: Path, costs: tuple[int, int, int, int]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Cargo.toml").write_text(
        '[package]\nname = "crypticshift_fixture"\nversion = "0.1.0"\nedition = "2024"\n\n[lib]\npath = "src/lib.rs"\n',
        encoding="utf-8",
    )
    src = root / "src"
    src.mkdir(exist_ok=True)
    arc, mutex, clone, box_dyn = costs
    lines = [
        "use std::hint::black_box;",
    ]
    if arc:
        lines.append("use std::sync::Arc;")
    if mutex:
        lines.append("use std::sync::Mutex;")
    lines += ["", "pub fn transform(input: &str) -> String {"]
    for i in range(arc):
        lines += [
            f"    let arc_{i} = Arc::new(input.to_owned());",
            f"    black_box(Arc::strong_count(&arc_{i}));",
            f"    black_box(arc_{i}.len());",
        ]
    for i in range(mutex):
        lines += [
            f"    let mutex_{i} = Mutex::new(input.len());",
            f"    {{ let mut guard = mutex_{i}.lock().expect(\"mutex poisoned\"); *guard += 1; }}",
            f"    black_box(*mutex_{i}.lock().expect(\"mutex poisoned\"));",
        ]
    for i in range(clone):
        lines += [
            f"    let clone_source_{i} = input.to_owned();",
            f"    let cloned_{i} = clone_source_{i}.clone();",
            f"    black_box(clone_source_{i}.len() + cloned_{i}.len());",
        ]
    for i in range(box_dyn):
        lines += [
            f"    let boxed_{i}: Box<dyn Fn(usize) -> usize> = Box::new(|value| value + 1);",
            f"    black_box(boxed_{i}(input.len()));",
        ]
    lines += [
        "    input.split_whitespace().collect::<Vec<_>>().join(\"-\").to_uppercase()",
        "}",
        "",
        "#[cfg(test)]",
        "mod tests {",
        "    use super::transform;",
        "",
        "    #[test]",
        "    fn behavior_is_stable() {",
        '        assert_eq!(transform("  alpha beta  "), "ALPHA-BETA");',
        '        assert_eq!(transform("one"), "ONE");',
        "    }",
        "}",
        "",
    ]
    (src / "lib.rs").write_text("\n".join(lines), encoding="utf-8")


def measured_fitness(source: str):
    return (
        source.count("Arc::new("),
        source.count("Mutex::new("),
        source.count(".clone()"),
        source.count("Box<dyn Fn("),
    )


def validate(root: Path, target_dir: Path) -> dict:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    commands = [
        ["cargo", "check", "--quiet"],
        ["cargo", "clippy", "--quiet", "--", "-D", "warnings"],
        ["cargo", "test", "--quiet"],
    ]
    evidence = []
    for args in commands:
        completed = subprocess.run(
            args,
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
        evidence.append(
            {
                "command": " ".join(args),
                "pass": completed.returncode == 0,
                "tail": (completed.stdout + completed.stderr)[-800:],
            }
        )
        if completed.returncode != 0:
            return {"pass": False, "evidence": evidence}
    return {"pass": True, "evidence": evidence}


def evaluate_candidate(
    work: Path,
    target: Path,
    label: str,
    costs: tuple[int, int, int, int],
) -> dict:
    if work.exists():
        shutil.rmtree(work)
    write_crate(work, costs)
    source = (work / "src/lib.rs").read_text(encoding="utf-8")
    measured = measured_fitness(source)
    validation = validate(work, target)
    return {
        "label": label,
        "declared_fitness": list(costs),
        "measured_fitness": list(measured),
        "fitness_matches_source": measured == costs,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "valid": validation["pass"],
        "validation": validation,
    }


def main() -> int:
    failures: list[str] = []
    report_landscapes = []

    with tempfile.TemporaryDirectory(prefix="crypticshift-small-") as tmp:
        arena = Path(tmp)
        work = arena / "candidate"
        target = arena / "target"

        baseline_eval = evaluate_candidate(work, target, "baseline", BASELINE)
        if not baseline_eval["valid"] or not baseline_eval["fitness_matches_source"]:
            print(json.dumps({"fatal": "baseline invalid", "baseline": baseline_eval}, indent=2))
            return 2

        for landscape in landscapes():
            evaluated = {}
            source_hashes = set()

            for variant in VARIANTS:
                result = evaluate_candidate(
                    work,
                    target,
                    variant,
                    landscape.singles[variant],
                )
                evaluated[variant] = result
                source_hashes.add(result["source_sha256"])
                if not result["valid"]:
                    failures.append(f"{landscape.name}: singleton {variant} failed Rust gates")
                if not result["fitness_matches_source"]:
                    failures.append(f"{landscape.name}: singleton {variant} fitness mismatch")
                if dominates(tuple(result["measured_fitness"]), BASELINE):
                    failures.append(f"{landscape.name}: singleton {variant} unexpectedly dominates baseline")

            pairs = list(itertools.combinations(VARIANTS, 2))
            for pair in pairs:
                label = "".join(pair)
                costs = pair_cost(landscape, pair)
                result = evaluate_candidate(work, target, label, costs)
                evaluated[label] = result
                source_hashes.add(result["source_sha256"])
                if not result["valid"]:
                    failures.append(f"{landscape.name}: pair {label} failed Rust gates")
                if not result["fitness_matches_source"]:
                    failures.append(f"{landscape.name}: pair {label} fitness mismatch")

            if len(source_hashes) != len(VARIANTS) + len(pairs):
                failures.append(f"{landscape.name}: structurally duplicate candidate sources")

            greedy_winner = next(
                (
                    variant
                    for variant in VARIANTS
                    if dominates(tuple(evaluated[variant]["measured_fitness"]), BASELINE)
                ),
                None,
            )

            ranked_pairs = sorted(
                pairs,
                key=lambda pair: (
                    -complementarity(
                        tuple(evaluated[pair[0]]["measured_fitness"]),
                        tuple(evaluated[pair[1]]["measured_fitness"]),
                    ),
                    pair,
                ),
            )
            cryptic_tested = ranked_pairs[:PAIR_BUDGET]
            cryptic_winner = next(
                (
                    "".join(pair)
                    for pair in cryptic_tested
                    if dominates(tuple(evaluated["".join(pair)]["measured_fitness"]), BASELINE)
                ),
                None,
            )

            exhaustive_winners = [
                "".join(pair)
                for pair in pairs
                if dominates(tuple(evaluated["".join(pair)]["measured_fitness"]), BASELINE)
            ]

            random_successes = 0
            rng = random.Random(10_000 + len(report_landscapes))
            for _ in range(RANDOM_TRIALS):
                chosen = rng.sample(pairs, PAIR_BUDGET)
                if any(
                    dominates(tuple(evaluated["".join(pair)]["measured_fitness"]), BASELINE)
                    for pair in chosen
                ):
                    random_successes += 1
            random_rate = random_successes / RANDOM_TRIALS

            expected_has_evolution = landscape.winner is not None
            cryptic_found = cryptic_winner is not None
            greedy_found = greedy_winner is not None

            if expected_has_evolution and not exhaustive_winners:
                failures.append(f"{landscape.name}: hidden synergy not actually Pareto-improving")
            if not expected_has_evolution and exhaustive_winners:
                failures.append(f"{landscape.name}: control unexpectedly has an improving pair")
            if not expected_has_evolution and cryptic_found:
                failures.append(f"{landscape.name}: CrypticShift false-positive evolution")

            report_landscapes.append(
                {
                    "name": landscape.name,
                    "expected_winner": None if landscape.winner is None else "".join(sorted(landscape.winner)),
                    "aligned_with_complementarity": landscape.aligned,
                    "single_fitness": {
                        key: evaluated[key]["measured_fitness"] for key in VARIANTS
                    },
                    "pair_ranking": [
                        {
                            "pair": "".join(pair),
                            "complementarity": complementarity(
                                tuple(evaluated[pair[0]]["measured_fitness"]),
                                tuple(evaluated[pair[1]]["measured_fitness"]),
                            ),
                            "fitness": evaluated["".join(pair)]["measured_fitness"],
                            "dominates_baseline": dominates(
                                tuple(evaluated["".join(pair)]["measured_fitness"]), BASELINE
                            ),
                        }
                        for pair in ranked_pairs
                    ],
                    "greedy_winner": greedy_winner,
                    "cryptic_pairs_tested": ["".join(pair) for pair in cryptic_tested],
                    "cryptic_winner": cryptic_winner,
                    "exhaustive_winners": exhaustive_winners,
                    "random_release_success_rate": round(random_rate, 4),
                }
            )

    synergy_rows = [row for row in report_landscapes if row["expected_winner"] is not None]
    control_rows = [row for row in report_landscapes if row["expected_winner"] is None]
    aligned_rows = [row for row in synergy_rows if row["aligned_with_complementarity"]]
    adversarial_rows = [row for row in synergy_rows if not row["aligned_with_complementarity"]]

    metrics = {
        "landscapes": len(report_landscapes),
        "synergy_landscapes": len(synergy_rows),
        "controls": len(control_rows),
        "pair_budget_after_reservoir": PAIR_BUDGET,
        "crypticshift_synergy_successes": sum(row["cryptic_winner"] is not None for row in synergy_rows),
        "crypticshift_synergy_success_rate": round(
            sum(row["cryptic_winner"] is not None for row in synergy_rows) / len(synergy_rows), 4
        ),
        "crypticshift_aligned_success_rate": round(
            sum(row["cryptic_winner"] is not None for row in aligned_rows) / len(aligned_rows), 4
        ),
        "crypticshift_adversarial_success_rate": round(
            sum(row["cryptic_winner"] is not None for row in adversarial_rows) / len(adversarial_rows), 4
        ),
        "greedy_synergy_success_rate": round(
            sum(row["greedy_winner"] is not None for row in synergy_rows) / len(synergy_rows), 4
        ),
        "random_release_mean_success_rate": round(
            sum(row["random_release_success_rate"] for row in synergy_rows) / len(synergy_rows), 4
        ),
        "control_false_positives": sum(row["cryptic_winner"] is not None for row in control_rows),
        "all_rust_candidates_valid": not any("failed Rust gates" in item for item in failures),
    }

    # Acceptance criteria were fixed before execution.
    if metrics["crypticshift_synergy_success_rate"] < 0.80:
        failures.append("CrypticShift found fewer than 80% of hidden synergy landscapes")
    if metrics["crypticshift_aligned_success_rate"] < 1.0:
        failures.append("CrypticShift missed an aligned complementarity landscape")
    if metrics["control_false_positives"] != 0:
        failures.append("CrypticShift produced a false-positive on a no-synergy control")
    if metrics["greedy_synergy_success_rate"] != 0.0:
        failures.append("greedy baseline unexpectedly escaped a synergy landscape")
    if metrics["random_release_mean_success_rate"] >= metrics["crypticshift_synergy_success_rate"]:
        failures.append("CrypticShift did not beat equal-budget random release")
    if metrics["crypticshift_adversarial_success_rate"] != 0.0:
        failures.append("adversarial control unexpectedly failed to expose heuristic limitation")

    report = {
        "verdict": "PASS_SMALL" if not failures else "FAIL_SMALL",
        "baseline_fitness": dict(zip(METRICS, BASELINE)),
        "metrics": metrics,
        "failures": failures,
        "landscapes": report_landscapes,
        "limitations": [
            "Synthetic compiler-backed landscapes, not real historical Rust refactors.",
            "Candidate integration costs are generated from a controlled compatibility model.",
            "Complementarity ranking is deliberately aligned in five positive landscapes and deliberately broken in one adversarial landscape.",
            "This tests the reservoir/release search hypothesis, not autonomous patch synthesis.",
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
