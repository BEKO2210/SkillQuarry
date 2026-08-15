#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

RUNS = 25
CONTROL_RUNS = 10
VERIFY_RUNS = 100

CASES = {
    "pyc": {
        "repo": "https://github.com/jplevyak/pyc.git",
        "broken": "840178f52f64b7335fb6d86f00a55e70a0c5c766",
        "fixed": "03dad0b8aae0fde7105f4aa920724e6d090f5dd7",
    },
    "grafel": {
        "repo": "https://github.com/cajasmota/grafel.git",
        "broken": "5941babb1f338156212d627e74808832447398a0",
        "fixed": "d7fb21b3e317a1592e0d05b56913238d68a94fc8",
    },
    "lang": {
        "repo": "https://github.com/JakeChampion/lang.git",
        "broken": "9b24b15f252dd39a52dcdbbeedc88bb795268003",
        "fixed": "2426535e5c550ae8d8eb335ef6bf9008acf7c0f7",
    },
}

PYC_FIXTURE = '''class Entropy(object):
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    m1 = 6
    m2 = 7
    m3 = 8
    m4 = 9
    m5 = 10

x = Entropy()
print(x.a + x.b + x.c + x.d + x.e + x.m1 + x.m2 + x.m3 + x.m4 + x.m5)
'''

GRAFEL_TEST = r'''package main

import (
    "crypto/sha256"
    "fmt"
    "os"
    "path/filepath"
    "testing"
    "time"
)

func entropyFixture(t *testing.T) string {
    t.Helper()
    root := t.TempDir()
    files := map[string]string{
        "init.lua": `local M = {}
local autopairs = require('nvim-autopairs')
local lint = require('lint')
local function outer(x)
  local inner = function(y)
    print(y)
    return y + 1
  end
  return inner(x)
end
function M.run()
  autopairs.setup({})
  lint.setup({})
  outer(1)
end
return M
`,
        "helpers.lua": `local H = {}
function H.format(s)
  return tostring(s)
end
function H.parse(s)
  return tonumber(s)
end
return H
`,
        "README.md": "# Fixture\n\n## Setup\n\nRun `require('init').run()` to exercise the extractor.\n\n## Helpers\n\nThe `helpers` module exposes `format` and `parse`.\n",
    }
    for p, body := range files {
        full := filepath.Join(root, p)
        if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil { t.Fatal(err) }
        if err := os.WriteFile(full, []byte(body), 0o644); err != nil { t.Fatal(err) }
    }
    return root
}

func TestEntropyHoldout(t *testing.T) {
    fixture := entropyFixture(t)
    if err := os.Setenv("SOURCE_DATE_EPOCH", "1700000000"); err != nil { t.Fatal(err) }
    outDir := os.Getenv("ENTROPY_OUT")
    if outDir == "" { t.Fatal("ENTROPY_OUT missing") }
    if err := os.MkdirAll(outDir, 0o755); err != nil { t.Fatal(err) }
    for i := 0; i < 25; i++ {
        out := filepath.Join(t.TempDir(), "graph.json")
        start := time.Now()
        if err := Index(fixture, out, "fixture", nil, false, false); err != nil {
            t.Fatalf("run %d: %v", i, err)
        }
        elapsed := time.Since(start).Nanoseconds()
        data, err := os.ReadFile(out)
        if err != nil { t.Fatal(err) }
        if err := os.WriteFile(filepath.Join(outDir, fmt.Sprintf("run-%02d.bin", i)), data, 0o644); err != nil { t.Fatal(err) }
        sum := sha256.Sum256(data)
        fmt.Printf("ENTROPY_DIGEST %x\n", sum)
        fmt.Printf("ENTROPY_TIME_NS %d\n", elapsed)
    }
}
'''

LANG_TEST = r'''package modload_test

import (
    "crypto/sha256"
    "fmt"
    "os"
    "path/filepath"
    "testing"
    "time"

    "github.com/jakechampion/lang/internal/modload"
    "github.com/jakechampion/lang/internal/printer"
)

func entropyWriteProject(t *testing.T) string {
    t.Helper()
    root := t.TempDir()
    files := map[string]string{
        "main.fern": `
import "./a";
import "./b";
import "./c";
function main(): i32 { return a_top() + b_top() + c_top(); }
`,
        "a.fern": `pub function a_top(): i32 { return 1; }`,
        "b.fern": `pub function b_top(): i32 { return 2; }`,
        "c.fern": `pub function c_top(): i32 { return 3; }`,
    }
    for p, body := range files {
        full := filepath.Join(root, p)
        if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil { t.Fatal(err) }
        if err := os.WriteFile(full, []byte(body), 0o644); err != nil { t.Fatal(err) }
    }
    return filepath.Join(root, "main.fern")
}

func TestEntropyHoldout(t *testing.T) {
    entry := entropyWriteProject(t)
    outDir := os.Getenv("ENTROPY_OUT")
    if outDir == "" { t.Fatal("ENTROPY_OUT missing") }
    if err := os.MkdirAll(outDir, 0o755); err != nil { t.Fatal(err) }
    for i := 0; i < 25; i++ {
        start := time.Now()
        prog, _, err := modload.Load(entry)
        if err != nil { t.Fatalf("run %d: %v", i, err) }
        data := []byte(printer.Print(prog))
        elapsed := time.Since(start).Nanoseconds()
        if err := os.WriteFile(filepath.Join(outDir, fmt.Sprintf("run-%02d.bin", i)), data, 0o644); err != nil { t.Fatal(err) }
        sum := sha256.Sum256(data)
        fmt.Printf("ENTROPY_DIGEST %x\n", sum)
        fmt.Printf("ENTROPY_TIME_NS %d\n", elapsed)
    }
}
'''


def run(cmd, *, cwd=None, env=None, timeout=1200):
    shown = " ".join(str(x) for x in cmd)
    print("+", shown, flush=True)
    proc = subprocess.run(
        [str(x) for x in cmd], cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-160:])
        raise RuntimeError(f"command failed ({proc.returncode}): {shown}\n{tail}")
    return proc.stdout


def checkout(repo, sha, dest):
    run(["git", "init", "-q", str(dest)])
    run(["git", "remote", "add", "origin", repo], cwd=dest)
    run(["git", "fetch", "-q", "--depth=1", "origin", sha], cwd=dest, timeout=300)
    run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=dest)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def directory_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        rel = p.relative_to(root).as_posix().encode()
        data = p.read_bytes()
        mode = p.stat().st_mode & 0o777
        h.update(len(rel).to_bytes(8, "big")); h.update(rel)
        h.update(mode.to_bytes(4, "big"))
        h.update(len(data).to_bytes(8, "big")); h.update(data)
    return h.hexdigest()


def summarize_witnesses(witnesses, timings):
    if len(witnesses) != RUNS or len(timings) != RUNS:
        raise RuntimeError(f"expected {RUNS} witnesses/timings, got {len(witnesses)}/{len(timings)}")
    digests = [sha(x) for x in witnesses]
    return {
        "runs": RUNS,
        "distinct": len(set(digests)),
        "digests": digests,
        "median_execution_s": statistics.median(timings),
    }


def probe_pyc(repo: Path):
    run(["make", "-j2"], cwd=repo, timeout=1200)
    src = repo / "entropy_fixture.py"
    src.write_text(PYC_FIXTURE, encoding="utf-8")
    witnesses, timings = [], []
    try:
        for i in range(RUNS):
            for old in repo.glob("entropy_fixture.py.*"):
                if old.is_file(): old.unlink()
            start = time.perf_counter()
            run([repo / "pyc", "-D", repo, src], cwd=repo, timeout=180)
            timings.append(time.perf_counter() - start)
            candidates = sorted(p for p in repo.glob("entropy_fixture.py*.c") if p.is_file())
            if not candidates:
                candidates = sorted(p for p in repo.glob("entropy_fixture*.c") if p.is_file())
            if len(candidates) != 1:
                raise RuntimeError(f"expected one generated C witness, got {[p.name for p in candidates]}")
            witnesses.append(candidates[0].read_bytes())
    finally:
        src.unlink(missing_ok=True)
    return summarize_witnesses(witnesses, timings), witnesses


def parse_go_outputs(output: str, out_dir: Path):
    ns = [int(x) for x in re.findall(r"^ENTROPY_TIME_NS\s+(\d+)$", output, flags=re.MULTILINE)]
    witnesses = [p.read_bytes() for p in sorted(out_dir.glob("run-*.bin"))]
    return witnesses, [x / 1_000_000_000 for x in ns]


def probe_grafel(repo: Path, scratch: Path):
    harness = repo / "cmd/archigraph/zz_entropy_holdout_test.go"
    harness.write_text(GRAFEL_TEST, encoding="utf-8")
    out_dir = scratch / "grafel-out"
    out_dir.mkdir()
    env = os.environ.copy(); env["ENTROPY_OUT"] = str(out_dir)
    try:
        output = run(["go", "test", "-run", "^TestEntropyHoldout$", "-count=1", "-v", "./cmd/archigraph"], cwd=repo, env=env, timeout=1200)
    finally:
        harness.unlink(missing_ok=True)
    witnesses, timings = parse_go_outputs(output, out_dir)
    return summarize_witnesses(witnesses, timings), witnesses


def probe_lang(repo: Path, scratch: Path):
    harness = repo / "internal/modload/zz_entropy_holdout_test.go"
    harness.write_text(LANG_TEST, encoding="utf-8")
    out_dir = scratch / "lang-out"
    out_dir.mkdir()
    env = os.environ.copy(); env["ENTROPY_OUT"] = str(out_dir)
    try:
        output = run(["go", "test", "-run", "^TestEntropyHoldout$", "-count=1", "-v", "./internal/modload"], cwd=repo, env=env, timeout=1200)
    finally:
        harness.unlink(missing_ok=True)
    witnesses, timings = parse_go_outputs(output, out_dir)
    return summarize_witnesses(witnesses, timings), witnesses


PROBERS = {"pyc": probe_pyc, "grafel": probe_grafel, "lang": probe_lang}


def probe_revision(name, cfg, rev, root):
    repo = root / f"{name}-{rev[:10]}"
    checkout(cfg["repo"], rev, repo)
    scratch = root / f"scratch-{name}-{rev[:10]}"; scratch.mkdir()
    if name == "pyc":
        result, witnesses = probe_pyc(repo)
    else:
        result, witnesses = PROBERS[name](repo, scratch)
    result["sha"] = rev
    return result, witnesses


def first_distinct_pair(witnesses):
    if not witnesses: return None
    first = witnesses[0]; first_hash = sha(first)
    for item in witnesses[1:]:
        if sha(item) != first_hash:
            return first, item
    return None


def verify_cost(pair):
    a, b = pair
    samples = []
    for _ in range(VERIFY_RUNS):
        start = time.perf_counter()
        da = hashlib.sha256(a).digest(); db = hashlib.sha256(b).digest()
        _ = da != db
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def run_controls(repo_root: Path):
    controls = {}

    readme_hashes = []
    for _ in range(CONTROL_RUNS):
        run([sys.executable, "tools/render_readme.py"], cwd=repo_root, timeout=120)
        h = hashlib.sha256()
        for rel in ["README.md", "registry/skills.json"]:
            data = (repo_root / rel).read_bytes(); h.update(rel.encode()); h.update(data)
        readme_hashes.append(h.hexdigest())
    controls["render_readme"] = {"runs": CONTROL_RUNS, "distinct": len(set(readme_hashes)), "digests": readme_hashes}

    site_hashes = []
    for _ in range(CONTROL_RUNS):
        run([sys.executable, "tools/build_site.py"], cwd=repo_root, timeout=120)
        site_hashes.append(directory_digest(repo_root / "site"))
    controls["build_site"] = {"runs": CONTROL_RUNS, "distinct": len(set(site_hashes)), "digests": site_hashes}
    return controls


def main():
    repo_root = Path(__file__).resolve().parents[2]
    results = {}
    recovered = 0
    infra = 0
    asymmetry_ok = True

    with tempfile.TemporaryDirectory(prefix="entropy-holdout-") as td:
        root = Path(td)
        for name, cfg in CASES.items():
            print(f"\n=== UNSEEN CASE {name} ===", flush=True)
            item = {"repo": cfg["repo"]}
            try:
                broken, broken_witnesses = probe_revision(name, cfg, cfg["broken"], root)
                fixed, _ = probe_revision(name, cfg, cfg["fixed"], root)
                ok = broken["distinct"] > 1 and fixed["distinct"] == 1
                item.update({"broken": broken, "fixed": fixed, "recovered": ok})
                if ok:
                    recovered += 1
                    pair = first_distinct_pair(broken_witnesses)
                    if pair is None:
                        raise RuntimeError("recovered case has no byte-distinct witness pair")
                    verify_s = verify_cost(pair)
                    ratio = verify_s / broken["median_execution_s"] if broken["median_execution_s"] else float("inf")
                    item["asymmetry"] = {
                        "verification_median_s": verify_s,
                        "discovery_median_s": broken["median_execution_s"],
                        "ratio": ratio,
                        "pass": ratio <= 0.25,
                    }
                    asymmetry_ok = asymmetry_ok and ratio <= 0.25
                print(f"HOLDOUT_RESULT {name}: broken={broken['distinct']} fixed={fixed['distinct']} recovered={ok}", flush=True)
            except Exception as exc:
                infra += 1
                item.update({"infra": True, "error": str(exc)})
                print(f"HOLDOUT_INFRA {name}: {exc}", flush=True)
            results[name] = item

        try:
            controls = run_controls(repo_root)
            fp_flagged = sum(1 for x in controls.values() if x["distinct"] > 1)
            print(f"CONTROL_RESULT flagged={fp_flagged}/2", flush=True)
        except Exception as exc:
            infra += 1
            controls = {"infra": True, "error": str(exc)}
            fp_flagged = 2
            print(f"CONTROL_INFRA: {exc}", flush=True)

    gate_pass = infra == 0 and recovered >= 2 and fp_flagged == 0 and asymmetry_ok
    summary = {
        "protocol": "build-entropy-unseen-v0-frozen",
        "runs_per_revision": RUNS,
        "control_runs": CONTROL_RUNS,
        "recovered": recovered,
        "required": 2,
        "infra_cases": infra,
        "false_positive_controls_flagged": fp_flagged,
        "asymmetry_pass": asymmetry_ok,
        "gate_pass": gate_pass,
        "cases": results,
        "controls": controls,
    }
    print("\nRESULT_JSON " + json.dumps(summary, sort_keys=True), flush=True)
    if infra:
        print(f"GATE: INFRA ({infra})", flush=True); return 2
    if gate_pass:
        print(f"GATE: PASS ({recovered}/3 unseen, FP {fp_flagged}/2, asymmetry pass)", flush=True); return 0
    print(f"GATE: FAIL ({recovered}/3 unseen, FP {fp_flagged}/2, asymmetry={asymmetry_ok})", flush=True); return 1


if __name__ == "__main__":
    raise SystemExit(main())
