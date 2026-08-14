#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

SEED = 0x50465247
SAMPLES = 9
BOOTSTRAPS = 2000
MIN_SPEEDUP_LB = 1.08
MAX_WORKLOAD_REGRESSION = 1.20
MAX_COLD_REGRESSION = 1.25
MAX_EXTRA_RSS = 32 * 1024 * 1024


def sh(cmd, cwd=None, timeout=600, check=True, env=None):
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout, env=env)
    if check and cp.returncode:
        raise RuntimeError(f"command failed {cmd}:\n{cp.stdout[-4000:]}\n{cp.stderr[-4000:]}")
    return cp


def percentile(xs, q):
    ys = sorted(xs)
    pos = (len(ys) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ys[lo]
    return ys[lo] * (hi - pos) + ys[hi] * (pos - lo)


def bootstrap_speedup_lb(ratios, seed):
    logs = [math.log(x) for x in ratios]
    rng = random.Random(seed)
    vals = []
    n = len(logs)
    for _ in range(BOOTSTRAPS):
        vals.append(math.exp(sum(logs[rng.randrange(n)] for _ in range(n)) / n))
    return percentile(vals, 0.025), math.exp(sum(logs) / n)


def parse_json_output(cp):
    if cp.returncode:
        raise RuntimeError(cp.stderr[-4000:] or cp.stdout[-4000:])
    lines = [x for x in cp.stdout.splitlines() if x.strip()]
    if not lines:
        raise RuntimeError('worker emitted no output')
    return json.loads(lines[-1])


def run_worker(path, workload, mode, sample_ids):
    cp = sh([sys.executable, str(path), workload, mode, json.dumps(sample_ids)], timeout=120)
    return parse_json_output(cp)


def paired_measure(base, cand, workloads, seed):
    rng = random.Random(seed)
    result = {}
    all_digests = []
    for workload in workloads:
        cold_rows = []
        for i in range(3):
            order = [('base', base), ('cand', cand)]
            rng.shuffle(order)
            pair = {}
            for label, path in order:
                pair[label] = run_worker(path, workload, 'cold', [i])
            cold_rows.append(pair)
            all_digests.append((pair['base']['digest'], pair['cand']['digest']))

        rows = []
        ids = list(range(SAMPLES))
        for chunk_start in range(0, len(ids), 3):
            chunk = ids[chunk_start:chunk_start + 3]
            order = [('base', base), ('cand', cand)]
            rng.shuffle(order)
            batch = {}
            for label, path in order:
                batch[label] = run_worker(path, workload, 'warm', chunk)
            for j in range(len(chunk)):
                pair = {
                    'base': {'warm_ns': batch['base']['warm_ns'][j], 'rss_bytes': batch['base']['rss_bytes'], 'digest': batch['base']['digest']},
                    'cand': {'warm_ns': batch['cand']['warm_ns'][j], 'rss_bytes': batch['cand']['rss_bytes'], 'digest': batch['cand']['digest']},
                }
                rows.append(pair)
                all_digests.append((pair['base']['digest'], pair['cand']['digest']))

        ratios = [r['base']['warm_ns'] / r['cand']['warm_ns'] for r in rows]
        lb, gmean = bootstrap_speedup_lb(ratios, seed ^ int(hashlib.sha256(workload.encode()).hexdigest()[:8], 16))
        cold_ratios = [r['cand']['cold_ns'] / r['base']['cold_ns'] for r in cold_rows]
        base_rss = statistics.median(r['base']['rss_bytes'] for r in rows)
        cand_rss = statistics.median(r['cand']['rss_bytes'] for r in rows)
        result[workload] = {
            'speedup_median': statistics.median(ratios),
            'speedup_gmean': gmean,
            'speedup_lb95': lb,
            'candidate_over_baseline_median': statistics.median(r['cand']['warm_ns'] / r['base']['warm_ns'] for r in rows),
            'cold_regression_median': statistics.median(cold_ratios),
            'base_rss_bytes': int(base_rss),
            'cand_rss_bytes': int(cand_rss),
            'extra_rss_bytes': int(cand_rss - base_rss),
        }
    return result, all(a == b for a, b in all_digests)


WORKER_TEMPLATE = r'''
import json, resource, sys, time
LARGE_REPEATS = {large_repeats}
SMALL_REPEATS = {small_repeats}
SETUP_CYCLES = {setup_cycles}
ALLOC_MB = {alloc_mb}
WRONG = {wrong}
DRIFT = {drift}
KEEP = None

def checksum(size):
    x = 0
    for i in range(size):
        x = (x + (((i * 2654435761) ^ (i >> 3)) & 0xffffffff)) & 0xffffffffffffffff
    return x

def repeated(size, repeats):
    last = 0
    for _ in range(repeats):
        last = checksum(size)
    return last

def spin(n):
    x = 0
    for i in range(n):
        x = ((x << 5) - x + i) & 0xffffffff
    return x

workload = sys.argv[1]
mode = sys.argv[2]
sample_ids = json.loads(sys.argv[3])
size = 2500 if workload == 'large' else 500
repeats = LARGE_REPEATS if workload == 'large' else SMALL_REPEATS

def setup():
    global KEEP
    if SETUP_CYCLES:
        spin(SETUP_CYCLES)
    if ALLOC_MB:
        KEEP = bytearray(ALLOC_MB * 1024 * 1024)
        KEEP[0] = 1
        KEEP[-1] = 1

if mode == 'cold':
    t0 = time.perf_counter_ns()
    setup()
    out = repeated(size, repeats)
    cold_ns = time.perf_counter_ns() - t0
    if WRONG:
        out += 1
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss = int(raw if sys.platform == 'darwin' else raw * 1024)
    print(json.dumps({{'cold_ns': cold_ns, 'rss_bytes': rss, 'digest': str(out)}}))
else:
    setup()
    vals = []
    out = 0
    for sample in sample_ids:
        if DRIFT and sample >= 0:
            time.sleep((sample % 5) * 0.0008)
        t1 = time.perf_counter_ns()
        out = repeated(size, repeats)
        vals.append(time.perf_counter_ns() - t1)
    if WRONG:
        out += 1
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss = int(raw if sys.platform == 'darwin' else raw * 1024)
    print(json.dumps({{'warm_ns': vals, 'rss_bytes': rss, 'digest': str(out)}}))
'''


def make_worker(path, cfg):
    path.write_text(WORKER_TEMPLATE.format(**cfg))


def synthetic_cases(root):
    base = dict(large_repeats=24, small_repeats=24, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)
    cases = [
        ('near_14', 'ACCEPT', ['large'], base, dict(large_repeats=21, small_repeats=21, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ('near_25', 'ACCEPT', ['large'], base, dict(large_repeats=19, small_repeats=19, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ('near_5', 'REJECT', ['large'], base, dict(large_repeats=23, small_repeats=23, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ('wrong_but_fast', 'REJECT', ['large'], base, dict(large_repeats=17, small_repeats=17, setup_cycles=0, alloc_mb=0, wrong=True, drift=False)),
        ('memory_for_speed', 'REJECT', ['large'], base, dict(large_repeats=20, small_repeats=20, setup_cycles=0, alloc_mb=48, wrong=False, drift=False)),
        ('cold_warm_tradeoff', 'REJECT', ['large'], base, dict(large_repeats=20, small_repeats=20, setup_cycles=350000, alloc_mb=0, wrong=False, drift=False)),
        ('benchmark_overfit', 'REJECT', ['large', 'small'], base, dict(large_repeats=19, small_repeats=50, setup_cycles=0, alloc_mb=0, wrong=False, drift=False)),
        ('identical_noise', 'REJECT', ['large'], dict(**base, drift=True), dict(**base, drift=True)),
    ]
    out = []
    for idx, (name, expected, workloads, bcfg, ccfg) in enumerate(cases):
        d = root / name
        d.mkdir(parents=True)
        base_file = d / 'baseline.py'
        cand_file = d / 'candidate.py'
        make_worker(base_file, bcfg)
        make_worker(cand_file, ccfg)
        metrics, correctness = paired_measure(base_file, cand_file, workloads, SEED + idx)
        primary = metrics['large']
        reasons = []
        if not correctness:
            reasons.append('semantic_mismatch')
        if primary['speedup_lb95'] < MIN_SPEEDUP_LB:
            reasons.append('speedup_not_proven')
        if max(v['candidate_over_baseline_median'] for v in metrics.values()) > MAX_WORKLOAD_REGRESSION:
            reasons.append('workload_regression')
        if max(v['cold_regression_median'] for v in metrics.values()) > MAX_COLD_REGRESSION:
            reasons.append('cold_regression')
        if max(v['extra_rss_bytes'] for v in metrics.values()) > MAX_EXTRA_RSS:
            reasons.append('memory_regression')
        verdict = 'ACCEPT' if not reasons else 'REJECT'
        out.append({'name': name, 'expected': expected, 'verdict': verdict, 'match': verdict == expected,
                    'correctness': correctness, 'reasons': reasons, 'metrics': metrics})
    return out


def clone_pair(url, commit, root, label):
    repo = root / f'{label}-repo'
    base = root / f'{label}-base'
    cand = root / f'{label}-cand'
    sh(['git', 'clone', '--quiet', '--no-checkout', url, str(repo)], timeout=300)
    sh(['git', '-C', str(repo), 'fetch', '--quiet', '--depth=2', 'origin', commit], timeout=300)
    parent = sh(['git', '-C', str(repo), 'rev-parse', f'{commit}^']).stdout.strip()
    sh(['git', '-C', str(repo), 'worktree', 'add', '--quiet', '--detach', str(base), parent], timeout=120)
    sh(['git', '-C', str(repo), 'worktree', 'add', '--quiet', '--detach', str(cand), commit], timeout=120)
    return base, cand, parent


def run_json_command(cmd, cwd=None, timeout=120):
    return parse_json_output(sh(cmd, cwd=cwd, timeout=timeout))


def pair_commands(base_cmd, cand_cmd, base_cwd=None, cand_cwd=None, samples=11, seed=SEED):
    rng = random.Random(seed)
    for _ in range(2):
        run_json_command(base_cmd, base_cwd)
        run_json_command(cand_cmd, cand_cwd)
    rows = []
    for _ in range(samples):
        order = [('base', base_cmd, base_cwd), ('cand', cand_cmd, cand_cwd)]
        rng.shuffle(order)
        row = {}
        for label, cmd, cwd in order:
            row[label] = run_json_command(cmd, cwd)
        rows.append(row)
    correctness = all(r['base']['digest'] == r['cand']['digest'] for r in rows)
    ratios = [r['base']['elapsed_ns'] / r['cand']['elapsed_ns'] for r in rows]
    lb, gmean = bootstrap_speedup_lb(ratios, seed)
    return {'correctness': correctness, 'speedup_median': statistics.median(ratios),
            'speedup_gmean': gmean, 'speedup_lb95': lb, 'samples': samples}


def write_serde_driver(driver, dep_path):
    driver.mkdir(parents=True)
    (driver / 'src').mkdir()
    (driver / 'Cargo.toml').write_text(textwrap.dedent(f'''\
        [package]
        name = "perfforge_serde_driver"
        version = "0.0.0"
        edition = "2021"
        [dependencies]
        serde_json = {{ path = {json.dumps(str(dep_path))} }}
    '''))
    (driver / 'src' / 'main.rs').write_text(r'''use std::hint::black_box;
use std::time::Instant;
fn main() {
    let encoded = "\\u0041\\u00df\\u6771\\ud834\\udd1e".repeat(900);
    let input = format!("\"{}\"", encoded);
    let start = Instant::now();
    let mut digest: u64 = 0;
    for _ in 0..90 {
        let s: String = serde_json::from_str(&input).unwrap();
        digest ^= s.len() as u64;
        digest = digest.wrapping_add(s.as_bytes().first().copied().unwrap_or(0) as u64);
        black_box(&s);
    }
    println!("{{\"elapsed_ns\":{},\"digest\":\"{}\"}}", start.elapsed().as_nanos(), digest);
}
''')
    sh(['cargo', 'build', '--release', '--quiet', '--manifest-path', str(driver / 'Cargo.toml')], timeout=600)
    return driver / 'target' / 'release' / 'perfforge_serde_driver'


def serde_case(root, label, commit, expected):
    base, cand, parent = clone_pair('https://github.com/serde-rs/json.git', commit, root, label)
    base_test = sh(['cargo', 'test', '--quiet', '--lib'], cwd=base, timeout=600, check=False)
    cand_test = sh(['cargo', 'test', '--quiet', '--lib'], cwd=cand, timeout=600, check=False)
    bdrv = write_serde_driver(root / f'{label}-driver-base', base)
    cdrv = write_serde_driver(root / f'{label}-driver-cand', cand)
    metrics = pair_commands([str(bdrv)], [str(cdrv)], seed=SEED ^ len(label))
    reasons = []
    if base_test.returncode or cand_test.returncode or not metrics['correctness']:
        reasons.append('correctness_failure')
    if metrics['speedup_lb95'] < MIN_SPEEDUP_LB:
        reasons.append('speedup_not_proven')
    verdict = 'ACCEPT' if not reasons else 'REJECT'
    return {'name': label, 'repo': 'serde-rs/json', 'commit': commit, 'parent': parent, 'expected': expected,
            'verdict': verdict, 'match': verdict == expected, 'reasons': reasons, 'metrics': metrics,
            'base_tests': base_test.returncode, 'cand_tests': cand_test.returncode}


def write_lodash_runner(path):
    path.write_text(r'''const _ = require('./lodash.js');
const input = (' \t\n\r').repeat(12000) + 'hello' + (' \t\n\r').repeat(12000);
const loops = 8;
let out = '';
const start = process.hrtime.bigint();
for (let i = 0; i < loops; i++) out = _.trim(input);
console.log(JSON.stringify({elapsed_ns: Number(process.hrtime.bigint() - start), digest: out + ':' + out.length}));
''')


def lodash_case(root):
    commit = 'c4847ebe7d14540bb28a8b932a9ce1b9ecbfee1a'
    base, cand, parent = clone_pair('https://github.com/lodash/lodash.git', commit, root, 'lodash')
    write_lodash_runner(base / 'perfforge_runner.js')
    write_lodash_runner(cand / 'perfforge_runner.js')
    probe = r'''const _=require('./lodash.js'); const xs=['','  a  ','\tA\n','  0b101  ','-0x1','  1.2e3  ']; console.log(JSON.stringify({elapsed_ns:1,digest:JSON.stringify(xs.map(x=>[_.trim(x),_.trimEnd(x),String(_.toNumber(x))]))}));'''
    (base / 'perfforge_probe.js').write_text(probe)
    (cand / 'perfforge_probe.js').write_text(probe)
    pb = run_json_command(['node', 'perfforge_probe.js'], base)
    pc = run_json_command(['node', 'perfforge_probe.js'], cand)
    metrics = pair_commands(['node', 'perfforge_runner.js'], ['node', 'perfforge_runner.js'], base, cand, seed=SEED ^ 77)
    reasons = []
    if pb['digest'] != pc['digest'] or not metrics['correctness']:
        reasons.append('correctness_failure')
    if metrics['speedup_lb95'] < MIN_SPEEDUP_LB:
        reasons.append('speedup_not_proven')
    verdict = 'ACCEPT' if not reasons else 'REJECT'
    return {'name': 'lodash_large_trim', 'repo': 'lodash/lodash', 'commit': commit, 'parent': parent,
            'expected': 'ACCEPT', 'verdict': verdict, 'match': verdict == 'ACCEPT', 'reasons': reasons, 'metrics': metrics}


def run_synthetic():
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='perfforge-pro-synth-') as td:
        cases = synthetic_cases(Path(td))
    exact = sum(x['match'] for x in cases)
    false_accepts = [x['name'] for x in cases if x['verdict'] == 'ACCEPT' and x['expected'] != 'ACCEPT']
    false_rejects = [x['name'] for x in cases if x['verdict'] == 'REJECT' and x['expected'] == 'ACCEPT']
    verdict = 'PASS_SYNTHETIC' if exact == len(cases) and not false_accepts and not false_rejects else 'FAIL_SYNTHETIC'
    return {'verdict': verdict, 'cases': cases, 'summary': {'exact': exact, 'total': len(cases),
            'false_accepts': false_accepts, 'false_rejects': false_rejects,
            'elapsed_seconds': round(time.monotonic() - start, 3)},
            'environment': {'platform': platform.platform(), 'python': sys.version.split()[0]}}


def run_real():
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='perfforge-pro-real-') as td:
        root = Path(td)
        cases = [
            serde_case(root, 'serde_unicode_speedup', '86d0e114e1370deb0b00cc97f5aec8c3869d835e', 'ACCEPT'),
            lodash_case(root),
            serde_case(root, 'serde_neutral_change', '236cc8247d32a5cb337850d75f68265fdb4bc14e', 'REJECT'),
        ]
    exact = sum(x['match'] for x in cases)
    verdict = 'PASS_REAL' if exact == len(cases) else 'FAIL_REAL'
    return {'verdict': verdict, 'cases': cases,
            'summary': {'exact': exact, 'total': len(cases), 'elapsed_seconds': round(time.monotonic() - start, 3)},
            'environment': {'platform': platform.platform(), 'python': sys.version.split()[0]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['synthetic', 'real'], required=True)
    args = ap.parse_args()
    data = run_synthetic() if args.mode == 'synthetic' else run_real()
    print(json.dumps(data, indent=2, sort_keys=True))
    raise SystemExit(0 if data['verdict'] in ('PASS_SYNTHETIC', 'PASS_REAL') else 1)


if __name__ == '__main__':
    main()
