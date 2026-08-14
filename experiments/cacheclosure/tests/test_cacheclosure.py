from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from cacheclosure.cli import main
from cacheclosure.core import evaluate_hash_call, extract_hash_calls, parse_cache_steps, scan_repository


KINESIS_BROKEN = """name: Build
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Cache west modules
        uses: actions/cache@v4
        env:
          cache-name: cache-zephyr-modules
        with:
          path: |
            modules/
            tools/
            zephyr/
            bootloader/
            zmk/
          key: ${{ runner.os }}-build-${{ env.cache-name }}-${{ hashFiles('manifest-dir/west.yml') }}
      - name: West Init
        run: west init -l config
      - name: West Update
        run: west update
"""
KINESIS_FIXED = KINESIS_BROKEN.replace("manifest-dir/west.yml", "config/west.yml")

ZUBAN_WORKFLOW_BROKEN = """name: build
env:
  ROOT: /home/runner/zuban-build
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: cache source + cargo
        uses: actions/cache@v4
        with:
          path: |
            ${{ env.ROOT }}/zuban
            ~/.cargo/registry
            ~/.cargo/git
          key: zuban-${{ inputs.zuban_rev }}-${{ hashFiles('scripts/setup.sh') }}
      - name: setup
        run: bash scripts/setup.sh
      - name: build
        run: bash scripts/build.sh
"""
ZUBAN_WORKFLOW_FIXED = ZUBAN_WORKFLOW_BROKEN.replace(
    "hashFiles('scripts/setup.sh')", "hashFiles('scripts/setup.sh', 'patches/*.patch')"
)
COMMON_SH = '''#!/usr/bin/env bash
ROOT=${ROOT:-$HOME/zuban-build}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SRC=$ROOT/zuban
'''
SETUP_SH = '''#!/usr/bin/env bash
set -e
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
mkdir -p $ROOT
if [ ! -d $SRC ]; then
  git clone --depth 1 https://github.com/zubanls/zuban.git $SRC
fi
'''
BUILD_SH = '''#!/usr/bin/env bash
set -e
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
cd $SRC
if [ ! -f .patched ]; then
  git apply $REPO/patches/*.patch
  touch .patched
fi
bash scripts/build-wasm.sh
'''

YAPBOARD_BROKEN = """name: CI
jobs:
  test:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache@v4
        with:
          path: .build
          key: ${{ runner.os }}-spm-build-${{ hashFiles('Package.resolved') }}
      - run: swift build
"""
YAPBOARD_FIXED = YAPBOARD_BROKEN.replace(
    "${{ runner.os }}-spm-build-",
    "${{ runner.os }}-${{ github.event.repository.name }}-spm-build-",
)



def write_repo(root: Path, workflow: str, *, zuban: bool = False, package_resolved: bool = False) -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "build.yml").write_text(workflow, encoding="utf-8")
    if "west.yml" in workflow:
        (root / "config").mkdir()
        (root / "config" / "west.yml").write_text("manifest:\n  remotes: []\n", encoding="utf-8")
    if zuban:
        (root / "scripts").mkdir()
        (root / "patches").mkdir()
        (root / "scripts" / "common.sh").write_text(COMMON_SH, encoding="utf-8")
        (root / "scripts" / "setup.sh").write_text(SETUP_SH, encoding="utf-8")
        (root / "scripts" / "build.sh").write_text(BUILD_SH, encoding="utf-8")
        (root / "patches" / "min-size.patch").write_text("diff --git a/Cargo.toml b/Cargo.toml\n", encoding="utf-8")
    if package_resolved:
        (root / "Package.resolved").write_text('{"pins": []}\n', encoding="utf-8")


class CacheClosureTests(unittest.TestCase):
    def test_hash_call_parses_multiple_patterns(self):
        key = "x-${{ hashFiles('a.txt', 'b/*.txt', '!b/skip.txt') }}"
        self.assertEqual(extract_hash_calls(key), [("a.txt", "b/*.txt", "!b/skip.txt")])

    def test_hash_call_without_literal_arguments_is_ignored(self):
        self.assertEqual(extract_hash_calls("${{ hashFiles(env.FILE) }}"), [])

    def test_hash_call_evaluation_honors_negative_patterns(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "b").mkdir()
            (root / "a.txt").write_text("a")
            (root / "b" / "x.txt").write_text("x")
            (root / "b" / "skip.txt").write_text("s")
            got = evaluate_hash_call(root, ("a.txt", "b/*.txt", "!b/skip.txt"))
            self.assertEqual(got, {"a.txt", "b/x.txt"})

    def test_kinesis_broken_recovers_historical_witness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, KINESIS_BROKEN)
            findings = scan_repository(root)
            self.assertEqual([f.code for f in findings], ["EMPTY_HASH_INPUT"])
            self.assertEqual(findings[0].evidence["patterns"], ["manifest-dir/west.yml"])

    def test_kinesis_historical_repair_removes_witness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, KINESIS_FIXED)
            self.assertEqual(scan_repository(root), [])

    def test_zuban_broken_recovers_historical_witness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, ZUBAN_WORKFLOW_BROKEN, zuban=True)
            findings = scan_repository(root)
            self.assertEqual([f.code for f in findings], ["SENTINEL_UNKEYED_INPUT"])
            self.assertEqual(findings[0].evidence["input_pattern"], "patches/*.patch")
            self.assertEqual(findings[0].evidence["unkeyed_files"], ["patches/min-size.patch"])
            self.assertTrue(str(findings[0].evidence["sentinel"]).endswith("/zuban/.patched"))

    def test_zuban_historical_repair_removes_witness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, ZUBAN_WORKFLOW_FIXED, zuban=True)
            self.assertEqual(scan_repository(root), [])

    def test_yapboard_is_honest_historical_miss(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, YAPBOARD_BROKEN, package_resolved=True)
            self.assertEqual(scan_repository(root), [])

    def test_yapboard_historical_repair_also_has_no_witness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, YAPBOARD_FIXED, package_resolved=True)
            self.assertEqual(scan_repository(root), [])

    def test_non_cache_workflow_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, "jobs:\n  x:\n    steps:\n      - run: echo ok\n")
            self.assertEqual(scan_repository(root), [])

    def test_parse_cache_step_block_path_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, ZUBAN_WORKFLOW_BROKEN, zuban=True)
            steps = parse_cache_steps(root / ".github" / "workflows" / "build.yml")
            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0].name, "cache source + cargo")
            self.assertEqual(steps[0].paths[0], "${{ env.ROOT }}/zuban")

    def test_sentinel_outside_cached_path_not_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, ZUBAN_WORKFLOW_BROKEN.replace("${{ env.ROOT }}/zuban", "/tmp/elsewhere"), zuban=True)
            self.assertEqual(scan_repository(root), [])

    def test_sentinel_without_touch_not_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, ZUBAN_WORKFLOW_BROKEN, zuban=True)
            build = root / "scripts" / "build.sh"
            build.write_text(build.read_text().replace("  touch .patched\n", ""))
            self.assertEqual(scan_repository(root), [])

    def test_unmatched_repo_input_does_not_invent_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, ZUBAN_WORKFLOW_BROKEN, zuban=True)
            (root / "patches" / "min-size.patch").unlink()
            self.assertEqual(scan_repository(root), [])

    def test_json_shape_is_serializable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_repo(root, KINESIS_BROKEN)
            finding = scan_repository(root)[0]
            self.assertEqual(json.loads(json.dumps(finding.to_dict()))["code"], "EMPTY_HASH_INPUT")

    def test_cli_exit_codes_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            broken = Path(td) / "broken"
            fixed = Path(td) / "fixed"
            write_repo(broken, KINESIS_BROKEN)
            write_repo(fixed, KINESIS_FIXED)
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(main([str(broken), "--json"]), 1)
            self.assertIn("EMPTY_HASH_INPUT", out.getvalue())
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(main([str(fixed)]), 0)
            self.assertIn("no proven", out.getvalue())


if __name__ == "__main__":
    unittest.main()
