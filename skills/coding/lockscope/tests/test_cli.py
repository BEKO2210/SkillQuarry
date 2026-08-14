"""The command: what it prints, what it writes, and what it exits with.

Exit codes matter more than output here — this is what a CI job reads.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from lockscope import cli, engine, report


def run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


def stored(path: Path, verdict: str, findings=None) -> Path:
    analysis = engine.Analysis(findings=findings or [])
    built = report.build(analysis, {"rustc": "1.97.1"}, verdict=verdict)
    path.write_text(report.dumps(built), "utf-8")
    return path


class ExitCodeTests(unittest.TestCase):
    def test_a_clean_report_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            path = stored(Path(temp) / "r.json", report.PASS)
            self.assertEqual(run("explain", str(path))[0], cli.EXIT_OK)

    def test_a_dangerous_finding_exits_one(self):
        with tempfile.TemporaryDirectory() as temp:
            path = stored(Path(temp) / "r.json", report.FAIL, [
                {"kind": "sync_lock_across_await", "severity": "critical",
                 "confidence": "semantic", "file": "a.rs", "line": 3, "function": "f"},
            ])
            code, text = run("explain", str(path))
            self.assertEqual(code, cli.EXIT_FINDINGS)
            self.assertIn("sync_lock_across_await", text)

    def test_something_only_a_human_can_decide_exits_two(self):
        with tempfile.TemporaryDirectory() as temp:
            path = stored(Path(temp) / "r.json", report.MANUAL_REVIEW)
            self.assertEqual(run("explain", str(path))[0], cli.EXIT_MANUAL)

    def test_a_report_that_cannot_be_read_exits_three(self):
        code, text = run("explain", "/nonexistent/report.json")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("lockscope:", text)

    def test_a_missing_crate_directory_is_refused(self):
        code, text = run("scan", "/nonexistent/crate")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("is not a directory", text)

    def test_a_directory_without_rust_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            code, text = run("scan", temp)
            self.assertEqual(code, cli.EXIT_ERROR)
            self.assertIn("no .rs files", text)


class ArgumentTests(unittest.TestCase):
    def test_the_version_is_reported(self):
        with self.assertRaises(SystemExit) as caught:
            run("--version")
        self.assertEqual(caught.exception.code, 0)

    def test_a_command_is_required(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])

    def test_scan_defaults_to_the_current_directory(self):
        self.assertEqual(cli.build_parser().parse_args(["scan"]).crate, ".")

    def test_files_can_be_limited_and_repeated(self):
        args = cli.build_parser().parse_args(["scan", ".", "--file", "a.rs", "--file", "b.rs"])
        self.assertEqual(args.files, ["a.rs", "b.rs"])


class DoctorTests(unittest.TestCase):
    def test_doctor_names_every_tool_it_needs(self):
        code, text = run("doctor")
        for subject in ("rustc", "cargo", "rust_analyzer", "tree-sitter"):
            self.assertIn(subject, text)
        self.assertIn(code, {cli.EXIT_OK, cli.EXIT_ERROR})

    def test_doctor_fails_when_a_tool_is_missing(self):
        code, text = run("--rust-analyzer", "definitely-not-installed", "doctor")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("FAIL", text)


class OutputTests(unittest.TestCase):
    def test_a_report_can_be_written_to_a_file(self):
        with tempfile.TemporaryDirectory() as temp:
            source = stored(Path(temp) / "r.json", report.PASS)
            self.assertEqual(json.loads(source.read_text())["schema"], report.SCHEMA)

    def test_the_summary_is_printed_when_no_json_path_is_given(self):
        with tempfile.TemporaryDirectory() as temp:
            path = stored(Path(temp) / "r.json", report.PASS)
            _, text = run("explain", str(path))
            self.assertIn("verdict     PASS", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
