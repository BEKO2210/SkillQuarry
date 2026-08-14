#!/usr/bin/env python3
from __future__ import annotations

import itertools
import json
import os
import random
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

METRICS = ("arc", "mutex", "clone", "box_dyn")
SLOTS = ("A", "B", "C", "D")
BASE_SLOT = (2, 2, 2, 2)
BASELINE = tuple(x * len(SLOTS) for x in BASE_SLOT)
PAIR_BUDGET = 3
TRIPLE_BUDGET = 6
RANDOM_TRIALS = 2000


@dataclass(frozen=True)
class Landscape:
    name: str
    deltas: dict[str, tuple[int, int, int, int]]
    max_combo: int
    positive: bool
    adversarial: bool = False


def landscapes() -> list[Landscape]:
    return [
        Landscape("ownership_lock", {"A": (-2, 2, 0, 0), "B": (1, -2, 0, 0), "C": (0, 0, 2, -1), "D": (0, 0, -1, 2)}, 2, True),
        Landscape("lock_clone", {"A": (0, -2, 2, 0), "B": (2, 0, 0, -1), "C": (0, 1, -2, 0), "D": (-1, 0, 0, 2)}, 2, True),
        Landscape("clone_dispatch", {"A": (0, 0, -2, 2), "B": (2, -1, 0, 0), "C": (-1, 2, 0, 0), "D": (0, 0, 1, -2)}, 2, True),
        Landscape("arc_dispatch", {"A": (-2, 0, 0, 2), "B": (0, 2, -1, 0), "C": (1, 0, 0, -2), "D": (0, -1, 2, 0)}, 2, True),
        Landscape("triple_cycle_one", {"A": (-2, 2, 0, 0), "B": (0, -2, 2, 0), "C": (1, 0, -2, 0), "D": (0, 0, 2, -1)}, 3, True),
        Landscape("triple_cycle_two", {"A": (0, -2, 2, 0), "B": (0, 0, -2, 2), "C": (0, 1, 0, -2), "D": (2, 0, -1, 0)}, 3, True),
        Landscape("dense_decoys", {"A": (-2, 2, -1, 1), "B": (1, -2, 2, 0), "C": (2, 0, -2, 1), "D": (1, -2, 1, -1)}, 3, True),
        Landscape("adversarial_ranking", {"A": (-2, 2, -2, 2), "B": (2, -2, 2, -1), "C": (-1, 1, -1, 1), "D": (0, -1, 1, -1)}, 2, True, True),
        Landscape("control_no_synergy_one", {"A": (-2, 2, 0, 0), "B": (2, -1, 0, 0), "C": (0, 0, -2, 2), "D": (0, 0, 2, -1)}, 3, False),
        Landscape("control_no_synergy_two", {"A": (-1, 2, 0, 0), "B": (2, -1, 0, 0), "C": (0, 0, -1, 2), "D": (0, 0, 2, -1)}, 3, False),
        Landscape("control_no_synergy_three", {"A": (-2, 0, 2, 0), "B": (2, 0, -1, 0), "C": (0, -2, 0, 2), "D": (0, 2, 0, -1)}, 3, False),
    ]


def add(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(x + y for x, y in zip(a, b))


def candidate_vector(land: Landscape, combo: tuple[str, ...]) -> tuple[int, ...]:
    value = BASELINE
    for slot in combo:
        value = add(value, land.deltas[slot])
    return value


def dominates(value: tuple[int, ...], baseline: tuple[int, ...] = BASELINE) -> bool:
    return all(x <= y for x, y in zip(value, baseline)) and any(x < y for x, y in zip(value, baseline))


def complementarity(land: Landscape, combo: tuple[str, ...]) -> int:
    score = 0
    for left, right in itertools.combinations(combo, 2):
        dl, dr = land.deltas[left], land.deltas[right]
        for x, y in zip(dl, dr):
            if x * y < 0:
                score += min(abs(x), abs(y))
    return score * 10 + len(combo)


def combo_universe(land: Landscape) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for size in range(2, land.max_combo + 1):
        out.extend(itertools.combinations(SLOTS, size))
    return out


def rust_slot_source(counts: tuple[int, int, int, int], label: str) -> str:
    arc, mutex, clone, box_dyn = counts
    imports = ["use std::hint::black_box;"]
    if arc:
        imports.append("use std::sync::Arc;")
    if mutex:
        imports.append("use std::sync::Mutex;")
    lines = imports + ["", f"pub fn run_{label.lower()}() -> usize {{", "    let mut sink = 0usize;"]
    for i in range(arc):
        lines += [f"    let arc_{i} = Arc::new({i + 1}usize);", f"    sink = sink.wrapping_add(*arc_{i});"]
    for i in range(mutex):
        lines += [f"    let mutex_{i} = Mutex::new({i + 1}usize);", f"    sink = sink.wrapping_add(*mutex_{i}.lock().expect(\"lock\"));"]
    for i in range(clone):
        lines += [f"    let owned_{i} = String::from(\"slot-{label}-{i}\");", f"    let cloned_{i} = owned_{i}.clone();", f"    sink = sink.wrapping_add(cloned_{i}.len());", f"    black_box(owned_{i});"]
    for i in range(box_dyn):
        lines += [f"    let callback_{i}: Box<dyn Fn(usize) -> usize> = Box::new(|x| x.wrapping_add(1));", f"    sink = sink.wrapping_add(callback_{i}({i}));"]
    lines += ["    black_box(sink);", "    10", "}", ""]
    return "\n".join(lines)


def write_search_project(root: Path, land: Landscape, combo: tuple[str, ...]) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "Cargo.toml").write_text("[package]\nname='crypticshift_fixture'\nversion='0.0.0'\nedition='2024'\n\n[dependencies]\n", encoding="utf-8")
    mods = []
    calls = []
    for slot in SLOTS:
        mods.append(f"mod {slot.lower()};")
        calls.append(f"{slot.lower()}::run_{slot.lower()}()")
        counts = BASE_SLOT if slot not in combo else add(BASE_SLOT, land.deltas[slot])
        if any(x < 0 for x in counts):
            raise AssertionError((land.name, slot, counts))
        (root / "src" / f"{slot.lower()}.rs").write_text(rust_slot_source(counts, slot), encoding="utf-8")
    lib = "\n".join(mods) + "\n\npub fn total() -> usize {\n    " + " + ".join(calls) + "\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n    #[test]\n    fn behavior_is_stable() { assert_eq!(total(), 40); }\n}\n"
    (root / "src" / "lib.rs").write_text(lib, encoding="utf-8")


def source_fitness(root: Path) -> tuple[int, int, int, int]:
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((root / "src").glob("*.rs")))
    return (text.count("Arc::new("), text.count("Mutex::new("), text.count(".clone()"), text.count("Box<dyn Fn("))


def run(cmd: list[str], cwd: Path, *, env: dict[str, str] | None = None, expect: int | None = 0) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    if expect is not None and cp.returncode != expect:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{cp.stdout[-4000:]}")
    return cp


def cargo_validate(root: Path, target: Path) -> tuple[bool, str]:
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = str(target)
    for cmd in (["cargo", "check", "--quiet"], ["cargo", "clippy", "--quiet", "--", "-D", "warnings"], ["cargo", "test", "--quiet"]):
        cp = run(list(cmd), root, env=env, expect=None)
        if cp.returncode != 0:
            return False, cp.stdout[-2500:]
    return True, ""


def evaluate_landscape(land: Landscape, work: Path) -> dict:
    project = work / land.name
    target = work / "target" / land.name
    write_search_project(project, land, ())
    ok, err = cargo_validate(project, target)
    if not ok:
        raise AssertionError(f"baseline invalid for {land.name}: {err}")
    measured_base = source_fitness(project)
    if measured_base != BASELINE:
        raise AssertionError((land.name, "baseline metric drift", measured_base, BASELINE))

    single: dict[str, tuple[int, ...]] = {}
    fingerprints: set[str] = set()
    for slot in SLOTS:
        write_search_project(project, land, (slot,))
        ok, err = cargo_validate(project, target)
        if not ok:
            raise AssertionError(f"singleton {land.name}/{slot} invalid: {err}")
        fit = source_fitness(project)
        single[slot] = fit
        if fit != candidate_vector(land, (slot,)):
            raise AssertionError((land.name, slot, fit, candidate_vector(land, (slot,))))
        if dominates(fit):
            raise AssertionError(f"singleton unexpectedly dominates in {land.name}: {slot} {fit}")
        fp = "|".join((project / "src" / f"{s.lower()}.rs").read_text() for s in SLOTS)
        if fp in fingerprints:
            raise AssertionError(f"duplicate singleton source in {land.name}: {slot}")
        fingerprints.add(fp)

    universe = combo_universe(land)
    evaluated: dict[tuple[str, ...], dict] = {}
    for combo in universe:
        write_search_project(project, land, combo)
        ok, err = cargo_validate(project, target)
        fit = source_fitness(project)
        evaluated[combo] = {"valid": ok, "fitness": fit, "dominates": ok and dominates(fit), "error": err[-500:]}

    winners = [combo for combo, row in evaluated.items() if row["dominates"]]
    ranked = sorted(universe, key=lambda combo: (-complementarity(land, combo), len(combo), combo))
    budget = TRIPLE_BUDGET if land.max_combo == 3 else PAIR_BUDGET
    selected = ranked[:budget]
    cryptic_winners = [combo for combo in selected if evaluated[combo]["dominates"]]
    cryptic_success = bool(cryptic_winners)
    greedy_success = any(dominates(value) for value in single.values())

    rnd = random.Random(0xC0FFEE + sum(ord(ch) for ch in land.name))
    successes = 0
    for _ in range(RANDOM_TRIALS):
        picks = rnd.sample(universe, min(budget, len(universe)))
        if any(evaluated[combo]["dominates"] for combo in picks):
            successes += 1
    random_rate = successes / RANDOM_TRIALS

    repeat_rankings = [tuple(sorted(universe, key=lambda combo: (-complementarity(land, combo), len(combo), combo))[:budget]) for _ in range(3)]
    if len(set(repeat_rankings)) != 1:
        raise AssertionError(f"nondeterministic ranking in {land.name}")

    return {
        "name": land.name,
        "positive": land.positive,
        "adversarial": land.adversarial,
        "max_combo": land.max_combo,
        "budget": budget,
        "single_fitness": {key: list(value) for key, value in single.items()},
        "exhaustive_winners": ["".join(combo) for combo in winners],
        "cryptic_selected": ["".join(combo) for combo in selected],
        "cryptic_success": cryptic_success,
        "greedy_success": greedy_success,
        "random_success_rate": round(random_rate, 4),
        "top_scores": [{"combo": "".join(combo), "score": complementarity(land, combo), "dominates": evaluated[combo]["dominates"]} for combo in ranked[: min(6, len(ranked))]],
    }


def write_crate(root: Path, cargo: str, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Cargo.toml").write_text(cargo, encoding="utf-8")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def semantic_probes(work: Path) -> list[dict]:
    results: list[dict] = []

    root = work / "probe_lifetime"
    write_crate(root, "[package]\nname='probe_lifetime'\nversion='0.0.0'\nedition='2024'\n", {"src/lib.rs": """
pub struct Borrowed<'a> { raw: &'a str }
impl<'a> Borrowed<'a> { pub fn len(&self) -> usize { self.raw.len() } pub fn is_empty(&self) -> bool { self.raw.is_empty() } }
pub struct Owned { raw: String }
impl Owned { pub fn new(raw: &str) -> Self { Self { raw: raw.to_owned() } } pub fn len(&self) -> usize { self.raw.len() } pub fn is_empty(&self) -> bool { self.raw.is_empty() } }
#[cfg(test)] mod tests { use super::*; #[test] fn same_behavior() { let s = String::from("abcd"); assert_eq!(Borrowed { raw: &s }.len(), Owned::new(&s).len()); } }
"""})
    ok, err = cargo_validate(root, work / "target" / "probe_lifetime")
    results.append({"name": "lifetime_owned_boundary", "pass": ok, "detail": err[-300:]})

    root = work / "probe_async_send"
    write_crate(root, "[package]\nname='probe_async_send'\nversion='0.0.0'\nedition='2024'\n", {"src/lib.rs": """
use std::sync::{Arc, Mutex};
pub async fn worker(state: Arc<Mutex<usize>>) -> usize { let value = { *state.lock().expect("lock") }; async {}.await; value }
fn assert_send<T: Send>(_: &T) {}
#[cfg(test)] mod tests { use super::*; #[test] fn future_is_send() { let f = worker(Arc::new(Mutex::new(7))); assert_send(&f); } }
"""})
    ok, err = cargo_validate(root, work / "target" / "probe_async_send")
    results.append({"name": "async_send_positive", "pass": ok, "detail": err[-300:]})

    root = work / "probe_async_not_send"
    write_crate(root, "[package]\nname='probe_async_not_send'\nversion='0.0.0'\nedition='2024'\n", {"src/lib.rs": """
use std::sync::{Arc, Mutex};
pub async fn worker(state: Arc<Mutex<usize>>) -> usize { let guard = state.lock().expect("lock"); async {}.await; *guard }
fn assert_send<T: Send>(_: &T) {}
pub fn prove() { let f = worker(Arc::new(Mutex::new(7))); assert_send(&f); }
"""})
    cp = run(["cargo", "check", "--quiet"], root, env={**os.environ, "CARGO_TARGET_DIR": str(work / "target" / "probe_async_not_send")}, expect=None)
    results.append({"name": "async_send_negative", "pass": cp.returncode != 0 and ("Send" in cp.stdout or "cannot be sent" in cp.stdout), "detail": cp.stdout[-500:]})

    root = work / "probe_borrow_negative"
    write_crate(root, "[package]\nname='probe_borrow_negative'\nversion='0.0.0'\nedition='2024'\n", {"src/lib.rs": "pub fn broken(v: &mut Vec<i32>) { let a = &mut v[0]; let b = &mut v[1]; *a += *b; }\n"})
    cp = run(["cargo", "check", "--quiet"], root, env={**os.environ, "CARGO_TARGET_DIR": str(work / "target" / "probe_borrow_negative")}, expect=None)
    results.append({"name": "borrow_conflict_negative", "pass": cp.returncode != 0 and ("E0499" in cp.stdout or "more than once" in cp.stdout), "detail": cp.stdout[-500:]})

    root = work / "probe_trait_negative"
    write_crate(root, "[package]\nname='probe_trait_negative'\nversion='0.0.0'\nedition='2024'\n", {"src/lib.rs": "pub trait Mark { fn mark(&self) -> usize; }\nimpl<T> Mark for T { fn mark(&self) -> usize { 1 } }\nimpl Mark for u8 { fn mark(&self) -> usize { 2 } }\n"})
    cp = run(["cargo", "check", "--quiet"], root, env={**os.environ, "CARGO_TARGET_DIR": str(work / "target" / "probe_trait_negative")}, expect=None)
    results.append({"name": "trait_coherence_negative", "pass": cp.returncode != 0 and ("E0119" in cp.stdout or "conflicting implementations" in cp.stdout), "detail": cp.stdout[-500:]})

    root = work / "probe_thread_negative"
    write_crate(root, "[package]\nname='probe_thread_negative'\nversion='0.0.0'\nedition='2024'\n", {"src/lib.rs": "use std::{cell::RefCell, rc::Rc};\npub fn broken() { let state = Rc::new(RefCell::new(1usize)); std::thread::spawn(move || { *state.borrow_mut() += 1; }).join().unwrap(); }\n"})
    cp = run(["cargo", "check", "--quiet"], root, env={**os.environ, "CARGO_TARGET_DIR": str(work / "target" / "probe_thread_negative")}, expect=None)
    results.append({"name": "thread_confinement_negative", "pass": cp.returncode != 0 and ("E0277" in cp.stdout or "cannot be sent between threads" in cp.stdout), "detail": cp.stdout[-500:]})

    root = work / "probe_features"
    write_crate(root, "[package]\nname='probe_features'\nversion='0.0.0'\nedition='2024'\n\n[features]\ndefault=[]\nfast=[]\n", {"src/lib.rs": "#[cfg(feature=\"fast\")] pub fn mode() -> &'static str { \"fast\" }\n#[cfg(not(feature=\"fast\"))] pub fn mode() -> &'static str { \"safe\" }\n#[cfg(test)] mod tests { use super::*; #[test] fn valid_mode() { assert!(matches!(mode(), \"fast\" | \"safe\")); } }\n"})
    env = {**os.environ, "CARGO_TARGET_DIR": str(work / "target" / "probe_features")}
    commands = [["cargo", "check", "--quiet", "--no-default-features"], ["cargo", "check", "--quiet", "--all-features"], ["cargo", "test", "--quiet", "--no-default-features"], ["cargo", "test", "--quiet", "--all-features"]]
    ok = all(run(command, root, env=env, expect=None).returncode == 0 for command in commands)
    results.append({"name": "feature_matrix_positive", "pass": ok, "detail": ""})

    root = work / "probe_workspace"
    root.mkdir(parents=True, exist_ok=True)
    (root / "Cargo.toml").write_text("[workspace]\nmembers=['api','app']\nresolver='3'\n", encoding="utf-8")
    write_crate(root / "api", "[package]\nname='api'\nversion='0.0.0'\nedition='2024'\n", {"src/lib.rs": "pub fn normalize(s: &str) -> String { s.trim().to_ascii_lowercase() }\n"})
    write_crate(root / "app", "[package]\nname='app'\nversion='0.0.0'\nedition='2024'\n\n[dependencies]\napi={path='../api'}\n", {"src/lib.rs": "pub fn run(s: &str) -> String { api::normalize(s) }\n#[cfg(test)] mod tests { use super::*; #[test] fn behavior() { assert_eq!(run(\" HeLLo \"), \"hello\"); } }\n"})
    env = {**os.environ, "CARGO_TARGET_DIR": str(work / "target" / "probe_workspace")}
    commands = [["cargo", "check", "--workspace", "--quiet"], ["cargo", "clippy", "--workspace", "--quiet", "--", "-D", "warnings"], ["cargo", "test", "--workspace", "--quiet"]]
    ok = all(run(command, root, env=env, expect=None).returncode == 0 for command in commands)
    results.append({"name": "workspace_api_positive", "pass": ok, "detail": ""})

    root = work / "probe_patch_conflict"
    root.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q"], root)
    run(["git", "config", "user.email", "test@example.invalid"], root)
    run(["git", "config", "user.name", "CrypticShift Test"], root)
    (root / "state.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (root / "other.txt").write_text("one\ntwo\n", encoding="utf-8")
    run(["git", "add", "."], root)
    run(["git", "commit", "-qm", "base"], root)
    base_sha = run(["git", "rev-parse", "HEAD"], root).stdout.strip()
    (root / "state.txt").write_text("alpha\nBETA-A\ngamma\n", encoding="utf-8")
    patch_a = run(["git", "diff", "--", "state.txt"], root).stdout
    run(["git", "reset", "--hard", "-q", base_sha], root)
    (root / "state.txt").write_text("alpha\nBETA-B\ngamma\n", encoding="utf-8")
    patch_b = run(["git", "diff", "--", "state.txt"], root).stdout
    run(["git", "reset", "--hard", "-q", base_sha], root)
    (root / "other.txt").write_text("one\nTWO-C\n", encoding="utf-8")
    patch_c = run(["git", "diff", "--", "other.txt"], root).stdout
    run(["git", "reset", "--hard", "-q", base_sha], root)
    path_a, path_b, path_c = root / "a.patch", root / "b.patch", root / "c.patch"
    path_a.write_text(patch_a, encoding="utf-8")
    path_b.write_text(patch_b, encoding="utf-8")
    path_c.write_text(patch_c, encoding="utf-8")
    run(["git", "apply", str(path_a)], root)
    conflict = run(["git", "apply", "--check", str(path_b)], root, expect=None).returncode != 0
    disjoint = run(["git", "apply", "--check", str(path_c)], root, expect=None).returncode == 0
    results.append({"name": "real_patch_conflict", "pass": conflict and disjoint, "detail": f"conflict={conflict} disjoint={disjoint}"})

    unsafe_hits = []
    for path in work.rglob("*.rs"):
        if re.search(r"\bunsafe\b", path.read_text(encoding="utf-8")):
            unsafe_hits.append(str(path.relative_to(work)))
    results.append({"name": "no_unsafe_escape_hatch", "pass": not unsafe_hits, "detail": ",".join(unsafe_hits)})
    return results


def main() -> int:
    started = time.monotonic()
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="crypticshift-pro-") as directory:
        work = Path(directory)
        landscape_results = []
        for land in landscapes():
            try:
                landscape_results.append(evaluate_landscape(land, work / "search"))
            except Exception as exc:
                failures.append(f"landscape {land.name}: {exc}")
        try:
            probes = semantic_probes(work / "semantic")
        except Exception as exc:
            probes = [{"name": "semantic_harness", "pass": False, "detail": repr(exc)}]
        for probe in probes:
            if not probe["pass"]:
                failures.append(f"semantic probe failed: {probe['name']}: {probe.get('detail', '')}")

    positives = [row for row in landscape_results if row["positive"]]
    aligned = [row for row in positives if not row["adversarial"]]
    adversarial = [row for row in positives if row["adversarial"]]
    controls = [row for row in landscape_results if not row["positive"]]
    cryptic_rate = sum(row["cryptic_success"] for row in positives) / len(positives) if positives else 0.0
    aligned_rate = sum(row["cryptic_success"] for row in aligned) / len(aligned) if aligned else 0.0
    greedy_rate = sum(row["greedy_success"] for row in positives) / len(positives) if positives else 0.0
    random_rate = sum(row["random_success_rate"] for row in positives) / len(positives) if positives else 0.0
    false_positives = sum(row["cryptic_success"] for row in controls)
    adversarial_success = sum(row["cryptic_success"] for row in adversarial)
    runtime = time.monotonic() - started

    if aligned_rate < 0.85:
        failures.append(f"aligned CrypticShift success too low: {aligned_rate:.3f}")
    if cryptic_rate < 0.70:
        failures.append(f"overall CrypticShift success too low: {cryptic_rate:.3f}")
    if cryptic_rate < random_rate + 0.20:
        failures.append(f"CrypticShift advantage over random too small: {cryptic_rate:.3f} vs {random_rate:.3f}")
    if greedy_rate > 0.25:
        failures.append(f"greedy unexpectedly strong: {greedy_rate:.3f}")
    if false_positives != 0:
        failures.append(f"control false positives: {false_positives}")
    if adversarial and adversarial_success == len(adversarial):
        failures.append("adversarial case failed to expose any ranking limitation")
    if runtime > 300:
        failures.append(f"runtime too high: {runtime:.1f}s")

    result = {
        "verdict": "PASS_PRO" if not failures else "FAIL_PRO",
        "metrics": {
            "landscapes": len(landscape_results),
            "positive_landscapes": len(positives),
            "aligned_positive_landscapes": len(aligned),
            "adversarial_positive_landscapes": len(adversarial),
            "controls": len(controls),
            "cryptic_success_rate": round(cryptic_rate, 4),
            "cryptic_aligned_success_rate": round(aligned_rate, 4),
            "greedy_success_rate": round(greedy_rate, 4),
            "random_mean_success_rate": round(random_rate, 4),
            "control_false_positives": false_positives,
            "adversarial_successes": adversarial_success,
            "semantic_probes": len(probes),
            "semantic_probes_passed": sum(bool(probe["pass"]) for probe in probes),
            "runtime_seconds": round(runtime, 2),
        },
        "acceptance": {
            "aligned_rate_min": 0.85,
            "overall_rate_min": 0.70,
            "advantage_over_random_min": 0.20,
            "greedy_rate_max": 0.25,
            "control_false_positives": 0,
            "must_expose_adversarial_limit": True,
            "runtime_seconds_max": 300,
        },
        "landscapes": landscape_results,
        "semantic_probes": probes,
        "failures": failures,
        "limitations": [
            "Search landscapes are real compiler-backed multi-file Rust transformations but still synthetic fixtures.",
            "Variant generation is deterministic and not LLM-authored.",
            "Fitness proxies are static architecture costs, not wall-clock performance.",
            "Exhaustive upper bound is feasible only because each landscape has four variants.",
            "The test covers pair/triple release and semantic failure handling, not arbitrary repository-scale patch synthesis.",
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
