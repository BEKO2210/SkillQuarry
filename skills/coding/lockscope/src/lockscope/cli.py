"""The `lockscope` command.

    lockscope scan <crate>            analyse and report
    lockscope repair <crate>          analyse, repair what is safe, verify
    lockscope explain <report.json>   read a stored report
    lockscope doctor                  is this machine able to run the skill

Exit codes: 0 nothing dangerous proven, 1 a dangerous lock lifetime, 2 findings
that need a human, 3 the analysis itself could not run.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from . import __version__, engine, report, syntax, verify

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_MANUAL = 2
EXIT_ERROR = 3


class ScanError(RuntimeError):
    """The analysis could not be performed — not a finding about the code."""


def _resolver(root: Path, command: str, warmup: float):
    from .semantics import RustAnalyzerResolver

    return RustAnalyzerResolver(root, command=command, warmup_timeout=warmup)


def _paths(root: Path, only: list[str] | None) -> list[Path]:
    if only:
        chosen = [root / item for item in only]
        missing = [str(path) for path in chosen if not path.is_file()]
        if missing:
            raise ScanError("no such file: " + ", ".join(missing))
        return sorted(chosen)
    found = syntax.rust_files(root)
    if not found:
        raise ScanError(f"no .rs files under {root}")
    return found


def scan(root: Path, files: list[str] | None, command: str, warmup: float, include_evidence: bool):
    from . import lsp

    paths = _paths(root, files)
    started = time.monotonic()
    with _resolver(root, command, warmup) as resolver:
        analysis = engine.analyze(paths, resolver, root)
        timings = resolver.timings.as_dict()
    timings["total_seconds"] = round(time.monotonic() - started, 3)
    toolchain = lsp.toolchain_versions(command)
    toolchain.update(syntax.versions())
    return analysis, report.build(analysis, toolchain, timings=timings, include_evidence=include_evidence)


def repair(root: Path, files: list[str] | None, command: str, warmup: float, run_tests: bool):
    """Repair what is safe, then let independent checks judge the result."""
    from . import lsp, repair as repair_module

    paths = _paths(root, files)
    started = time.monotonic()
    before_unsafe = verify.unsafe_count(paths)

    with _resolver(root, command, warmup) as resolver:
        before = engine.analyze(paths, resolver, root)

    repairs: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    actionable = {
        (item["file"], int(item["line"]))
        for item in before.findings
        if str(item.get("kind")) in report.ACTIONABLE
    }
    for path in paths:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        if not any(file == relative for file, _ in actionable):
            continue
        made, refused = repair_module.repair_file(path, relative)
        refusals.extend(item.as_dict() for item in refused)
        if made is not None:
            repairs.append(made.as_dict())

    verification: dict[str, Any] = {}
    verdict = report.PASS
    if repairs:
        with _resolver(root, command, warmup) as resolver:
            after = engine.analyze(paths, resolver, root)
        cleared = len(before.findings) - len(after.findings)
        checked = verify.cargo_check(root)
        tested = verify.cargo_test(root) if run_tests else None
        unsafe_after = verify.unsafe_count(paths)
        verification = {
            "findings_before": len(before.findings),
            "findings_after": len(after.findings),
            "findings_cleared": cleared,
            "cargo_check": checked.as_dict(),
            "unsafe": verify.unsafe_delta(before_unsafe, unsafe_after),
            "reanalysis_verdict": report.verdict_for(after),
        }
        if tested is not None:
            verification["cargo_test"] = tested.as_dict()
        healthy = (
            checked.passed
            and not verification["unsafe"]["introduced"]
            and (tested is None or tested.passed)
        )
        verdict = report.PASS if healthy and cleared > 0 else report.FAIL
        analysis = after
    else:
        analysis = before
        verdict = report.verdict_for(before)

    from . import lsp as lsp_module

    toolchain = lsp_module.toolchain_versions(command)
    toolchain.update(syntax.versions())
    timings = {"total_seconds": round(time.monotonic() - started, 3)}
    return analysis, report.build(
        analysis, toolchain, repairs=repairs, refusals=refusals,
        verification=verification, timings=timings, verdict=verdict,
    )


def doctor(command: str) -> tuple[int, str]:
    from . import lsp

    rows: list[tuple[str, str, str]] = []
    versions = lsp.toolchain_versions(command)
    for key in ("rustc", "cargo", "rust_analyzer"):
        value = versions.get(key, "not available")
        rows.append(("ok" if value != "not available" else "FAIL", key, value))
    try:
        parsers = syntax.versions()
        rows.append(("ok", "tree-sitter", parsers["tree_sitter"]))
        rows.append(("ok", "tree-sitter-rust", parsers["tree_sitter_rust"]))
    except Exception as exc:  # pragma: no cover - only without the parser installed
        rows.append(("FAIL", "tree-sitter", f"not importable: {exc}"))
    text = "\n".join(f"{status:<4}  {subject:<18} {detail}" for status, subject, detail in rows)
    return (EXIT_ERROR if any(status == "FAIL" for status, _, _ in rows) else EXIT_OK), text


def _exit_code(verdict: str) -> int:
    return {report.PASS: EXIT_OK, report.FAIL: EXIT_FINDINGS, report.MANUAL_REVIEW: EXIT_MANUAL}[verdict]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lockscope", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"lockscope {__version__}")
    parser.add_argument("--rust-analyzer", default="rust-analyzer", help="path to the language server")
    parser.add_argument("--warmup", type=float, default=90.0, help="seconds to wait for the first answer")
    parser.add_argument("--json", metavar="PATH", help="write the report here ('-' for stdout)")
    sub = parser.add_subparsers(dest="command", required=True)

    scanner = sub.add_parser("scan", help="analyse a crate and report")
    scanner.add_argument("crate", nargs="?", default=".")
    scanner.add_argument("--file", action="append", dest="files", help="limit to this file (repeatable)")
    scanner.add_argument("--evidence", action="store_true", help="keep the raw semantic evidence in the report")

    fixer = sub.add_parser("repair", help="apply the one safe repair and verify it")
    fixer.add_argument("crate", nargs="?", default=".")
    fixer.add_argument("--file", action="append", dest="files")
    fixer.add_argument("--no-tests", action="store_true", help="skip cargo test during verification")

    explainer = sub.add_parser("explain", help="print a stored report")
    explainer.add_argument("report")

    sub.add_parser("doctor", help="check this machine")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        code, text = doctor(args.rust_analyzer)
        print(text)
        return code

    if args.command == "explain":
        try:
            stored = json.loads(Path(args.report).read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"lockscope: {exc}")
            return EXIT_ERROR
        print(report.summary(stored))
        return _exit_code(str(stored.get("verdict", report.MANUAL_REVIEW)))

    root = Path(args.crate).expanduser().resolve()
    if not root.is_dir():
        print(f"lockscope: {root} is not a directory")
        return EXIT_ERROR

    try:
        if args.command == "scan":
            _, built = scan(root, args.files, args.rust_analyzer, args.warmup, args.evidence)
        else:
            _, built = repair(root, args.files, args.rust_analyzer, args.warmup, not args.no_tests)
    except (ScanError, RuntimeError) as exc:
        print(f"lockscope: {exc}")
        return EXIT_ERROR

    if args.json == "-":
        print(report.dumps(built), end="")
    else:
        if args.json:
            Path(args.json).write_text(report.dumps(built), "utf-8")
        print(report.summary(built))
    return _exit_code(str(built["verdict"]))
