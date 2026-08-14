"""Tests for the example skill. Copy this shape for your own skill."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from example_skill.cli import EXIT_ERROR, EXIT_OK, main
from example_skill.core import (
    DEFAULT_MAX_BYTES, SkillError, atomic_write_text, render_json,
    summarise_file, summarise_paths,
)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path


class SummaryTests(Base):
    def test_counts_lines_words_and_bytes(self) -> None:
        path = self.write("a.txt", "one two\nthree\n")
        summary = summarise_file(path)
        self.assertEqual((summary.lines, summary.words, summary.bytes), (2, 3, 14))

    def test_file_without_trailing_newline_still_counts_its_last_line(self) -> None:
        self.assertEqual(summarise_file(self.write("b.txt", "only")).lines, 1)

    def test_empty_file_is_all_zeroes(self) -> None:
        summary = summarise_file(self.write("empty.txt", ""))
        self.assertEqual((summary.lines, summary.words, summary.bytes), (0, 0, 0))

    def test_missing_file_is_an_error_not_a_zero(self) -> None:
        with self.assertRaises(SkillError):
            summarise_file(self.root / "nope.txt")
        with self.assertRaises(SkillError):
            summarise_file(self.root)  # a directory is not a readable file

    def test_oversized_file_is_refused_with_its_size(self) -> None:
        path = self.write("big.txt", "x" * 100)
        with self.assertRaisesRegex(SkillError, "100 bytes"):
            summarise_file(path, max_bytes=10)

    def test_non_utf8_file_is_refused(self) -> None:
        path = self.root / "binary.bin"
        path.write_bytes(b"\xff\xfe\x00")
        with self.assertRaisesRegex(SkillError, "not UTF-8"):
            summarise_file(path)

    def test_paths_are_summarised_in_a_stable_order(self) -> None:
        second = self.write("b.txt", "b\n")
        first = self.write("a.txt", "a\n")
        self.assertEqual([item.path for item in summarise_paths([second, first])], ["a.txt", "b.txt"])

    def test_no_files_is_an_error(self) -> None:
        with self.assertRaises(SkillError):
            summarise_paths([])

    def test_default_limit_is_generous_enough_for_source_files(self) -> None:
        self.assertGreaterEqual(DEFAULT_MAX_BYTES, 1024 * 1024)


class RenderTests(Base):
    def test_totals_add_up(self) -> None:
        report = json.loads(render_json(summarise_paths([
            self.write("a.txt", "one two\n"), self.write("b.txt", "three\n"),
        ])))
        self.assertEqual(report["totals"], {"files": 2, "lines": 2, "words": 3, "bytes": 14})
        self.assertEqual([item["path"] for item in report["files"]], ["a.txt", "b.txt"])


class AtomicWriteTests(Base):
    def test_write_replaces_content_and_leaves_no_temp_file(self) -> None:
        target = self.root / "nested" / "out.json"
        atomic_write_text(target, "first")
        atomic_write_text(target, "second")
        self.assertEqual(target.read_text("utf-8"), "second")
        self.assertEqual([p.name for p in target.parent.iterdir() if p.name.startswith(".out.json.")], [])

    def test_failed_replace_leaves_no_temp_file(self) -> None:
        import example_skill.core as core
        real_replace = core.os.replace
        core.os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            with self.assertRaises(OSError):
                atomic_write_text(self.root / "x.json", "data")
        finally:
            core.os.replace = real_replace
        self.assertEqual([p for p in self.root.iterdir() if p.name.startswith(".x.json.")], [])


class CommandLineTests(Base):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_reports_to_stdout(self) -> None:
        code, out, _ = self.run_cli(str(self.write("a.txt", "one two\n")))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["totals"]["words"], 2)

    def test_writes_a_report_file(self) -> None:
        target = self.root / "report.json"
        code, out, _ = self.run_cli(str(self.write("a.txt", "hi\n")), "--out", str(target))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(target.read_text("utf-8"))["totals"]["files"], 1)

    def test_unreadable_file_fails_with_a_named_cause(self) -> None:
        code, _, err = self.run_cli(str(self.root / "missing.txt"))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("not a readable file", err)

    def test_version_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(io.StringIO()):
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
