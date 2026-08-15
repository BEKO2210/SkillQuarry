#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

RUNS = 25

CASES = {
    "cvc5": {
        "repo": "https://github.com/cvc5/cvc5.git",
        "broken": "38912c71996affb29683b9f7caa25ad574afacee",
        "fixed": "61602d09095f70ef6381a035a41b6d6a47c5d325",
    },
    "dalec": {
        "repo": "https://github.com/project-dalec/dalec.git",
        "broken": "e0964d3e9f2e199f31331c7eb3ae9839f0153f33",
        "fixed": "ea705b3b3a52467fd2ffbdc08f3fa2ec289483f4",
    },
    "min_html": {
        "repo": "https://github.com/QQSHI13/min-html.git",
        "broken": "3e384a90f841facebcfc9faeae0ace03f2cecf4a",
        "fixed": "2f65441ecefaa5d6411c7cb3658642c776e65c3f",
    },
}


def run(cmd, *, cwd=None, env=None, timeout=900):
    print("+", " ".join(map(str, cmd)), flush=True)
    proc = subprocess.run(
        [str(x) for x in cmd],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-120:])
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(map(str, cmd))}\n{tail}")
    return proc.stdout


def checkout(repo: str, sha: str, dest: Path):
    run(["git", "init", "-q", str(dest)])
    run(["git", "remote", "add", "origin", repo], cwd=dest)
    run(["git", "fetch", "-q", "--depth=1", "origin", sha], cwd=dest, timeout=300)
    run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=dest)


def digest_files(paths):
    h = hashlib.sha256()
    for path in paths:
        path = Path(path)
        data = path.read_bytes()
        name = path.name.encode()
        h.update(len(name).to_bytes(8, "big"))
        h.update(name)
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def probe_cvc5(repo_dir: Path):
    script = repo_dir / "src/options/mkoptions.py"
    tomls = sorted((repo_dir / "src/options").glob("*_options.toml"))
    if not tomls:
        raise RuntimeError("no *_options.toml inputs found")

    digests = []
    with tempfile.TemporaryDirectory(prefix="entropy-cvc5-out-") as td:
        base = Path(td)
        for i in range(RUNS):
            root = base / f"run-{i:02d}"
            build = root / "build"
            out = root / "out"
            build.mkdir(parents=True)
            (out / "options").mkdir(parents=True)
            (out / "main").mkdir(parents=True)
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = str(1000 + i)
            run(
                [sys.executable, script, repo_dir / "src", build, out, *tomls],
                cwd=repo_dir,
                env=env,
                timeout=120,
            )
            witness = out / "options/options_public.cpp"
            if not witness.is_file():
                raise RuntimeError(f"missing witness: {witness}")
            digests.append(digest_files([witness]))
    return digests


DALEC_TEST = r'''package dalec

import (
    "context"
    "crypto/sha256"
    "fmt"
    "testing"

    "github.com/moby/buildkit/client/llb"
)

func TestEntropyProbe(t *testing.T) {
    ctx := context.Background()
    cfg := &RepoPlatformConfig{GPGKeyRoot: "/etc/apt/keyrings"}
    sOpt := SourceOpts{
        GetContext: func(name string, opts ...llb.LocalOption) (*llb.State, error) {
            st := llb.Local(name, opts...)
            return &st, nil
        },
    }

    for run := 0; run < 25; run++ {
        keys := make(map[string]Source, 12)
        for i := 0; i < 12; i++ {
            keys[fmt.Sprintf("key-%02d.gpg", i)] = Source{
                Inline: &SourceInline{File: &SourceInlineFile{Contents: fmt.Sprintf("key-material-%d", i)}},
            }
        }
        configs := []PackageRepositoryConfig{{Keys: keys}}
        runOpt, _ := GetRepoKeys(configs, cfg, sOpt)
        st := llb.Scratch().Run(llb.Args([]string{"true"}), runOpt).Root()
        def, err := st.Marshal(ctx)
        if err != nil {
            t.Fatal(err)
        }
        h := sha256.New()
        for _, op := range def.Def {
            _, _ = h.Write(op)
        }
        fmt.Printf("ENTROPY_DIGEST %x\n", h.Sum(nil))
    }
}
'''


def probe_dalec(repo_dir: Path):
    harness = repo_dir / "zz_entropy_probe_test.go"
    harness.write_text(DALEC_TEST, encoding="utf-8")
    try:
        output = run(
            ["go", "test", "-run", "^TestEntropyProbe$", "-count=1", "-v", "."],
            cwd=repo_dir,
            timeout=1200,
        )
    finally:
        harness.unlink(missing_ok=True)
    digests = re.findall(r"^ENTROPY_DIGEST\s+([0-9a-f]{64})$", output, flags=re.MULTILINE)
    if len(digests) != RUNS:
        raise RuntimeError(f"expected {RUNS} Dalec digests, got {len(digests)}")
    return digests


def probe_min_html(repo_dir: Path):
    target = repo_dir / "target-entropy"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    run(
        ["cargo", "build", "--quiet", "-p", "minify-html-common"],
        cwd=repo_dir,
        env=env,
        timeout=1200,
    )
    candidates = [
        p for p in target.glob("debug/build/minify-html-common-*/build-script-build")
        if p.is_file() and os.access(p, os.X_OK)
    ]
    if not candidates:
        raise RuntimeError("could not locate minify-html-common build-script-build")
    # A single package revision should produce one executable build script. If Cargo
    # leaves more than one, use the newest executable and record the exact path.
    build_script = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    print(f"min-html build script: {build_script}", flush=True)

    digests = []
    with tempfile.TemporaryDirectory(prefix="entropy-min-html-out-") as td:
        base = Path(td)
        for i in range(RUNS):
            out = base / f"run-{i:02d}"
            out.mkdir()
            child_env = os.environ.copy()
            child_env["OUT_DIR"] = str(out)
            run([build_script], cwd=repo_dir / "minify-html-common", env=child_env, timeout=120)
            attrs = out / "attrs.rs"
            entities = out / "entities.rs"
            if not attrs.is_file() or not entities.is_file():
                raise RuntimeError("min-html build script did not create attrs.rs and entities.rs")
            digests.append(digest_files([attrs, entities]))
    return digests


PROBERS = {
    "cvc5": probe_cvc5,
    "dalec": probe_dalec,
    "min_html": probe_min_html,
}


def probe_revision(case_name: str, repo_url: str, sha: str, root: Path):
    dest = root / f"{case_name}-{sha[:10]}"
    checkout(repo_url, sha, dest)
    start = time.monotonic()
    digests = PROBERS[case_name](dest)
    elapsed = time.monotonic() - start
    return {
        "sha": sha,
        "runs": len(digests),
        "distinct": len(set(digests)),
        "digests": digests,
        "elapsed_s": round(elapsed, 3),
    }


def main():
    results = {}
    recovered = 0
    infra = 0

    with tempfile.TemporaryDirectory(prefix="build-entropy-") as td:
        root = Path(td)
        for name, cfg in CASES.items():
            print(f"\n=== CASE {name} ===", flush=True)
            case_result = {"repo": cfg["repo"]}
            try:
                broken = probe_revision(name, cfg["repo"], cfg["broken"], root)
                fixed = probe_revision(name, cfg["repo"], cfg["fixed"], root)
                ok = broken["distinct"] > 1 and fixed["distinct"] == 1
                case_result.update({"broken": broken, "fixed": fixed, "recovered": ok})
                if ok:
                    recovered += 1
                print(
                    f"CASE_RESULT {name}: broken_distinct={broken['distinct']} "
                    f"fixed_distinct={fixed['distinct']} recovered={ok}",
                    flush=True,
                )
            except Exception as exc:
                infra += 1
                case_result.update({"infra": True, "error": str(exc)})
                print(f"CASE_INFRA {name}: {exc}", flush=True)
            results[name] = case_result

    gate_pass = infra == 0 and recovered >= 2
    summary = {
        "protocol": "build-entropy-v0-frozen",
        "runs_per_revision": RUNS,
        "recovered": recovered,
        "required": 2,
        "infra_cases": infra,
        "gate_pass": gate_pass,
        "cases": results,
    }
    print("\nRESULT_JSON " + json.dumps(summary, sort_keys=True), flush=True)

    if infra:
        print(f"GATE: INFRA ({infra} case(s) did not execute cleanly)", flush=True)
        return 2
    if gate_pass:
        print(f"GATE: PASS ({recovered}/3 recovered; required >=2)", flush=True)
        return 0
    print(f"GATE: FAIL ({recovered}/3 recovered; required >=2)", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
