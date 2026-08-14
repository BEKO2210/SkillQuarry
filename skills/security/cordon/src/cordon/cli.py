"""Command-line interface for Cordon."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import (
    DEFAULT_MAX_ADDED_LINES,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_BINARY_FILES,
    DEFAULT_MAX_DELETED_LINES,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TURNS,
    DEFAULT_MAX_WORKING_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    CordonError,
    Limits,
    Policy,
    arm_session,
    check_session,
    reset_session,
    resume_claude_session,
    run_claude_session,
    session_status,
)


def _policy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow", action="append", required=True, metavar="GLOB", help="allowed repo-relative path pattern; repeatable")
    parser.add_argument("--deny", action="append", default=[], metavar="GLOB", help="denied path pattern; deny wins; repeatable")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-added-lines", type=int, default=DEFAULT_MAX_ADDED_LINES)
    parser.add_argument("--max-deleted-lines", type=int, default=DEFAULT_MAX_DELETED_LINES)
    parser.add_argument("--max-working-bytes", type=int, default=DEFAULT_MAX_WORKING_BYTES)
    parser.add_argument("--max-binary-files", type=int, default=DEFAULT_MAX_BINARY_FILES)
    parser.add_argument("--allow-commits", action="store_true", help="allow HEAD to move after arming")
    parser.add_argument("--verify", action="append", default=[], metavar="COMMAND", help="independent verifier command; parsed with shlex, not a shell")
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)


def _claude_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--claude", default="claude", metavar="PATH", help="Claude Code executable")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, metavar="SECONDS")
    parser.add_argument("--max-budget-usd", type=float)
    parser.add_argument("--model")
    parser.add_argument("--effort")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cordon", description="Deterministic Git change envelopes for coding agents")
    parser.add_argument("--version", action="version", version=f"cordon {__version__}")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="path inside target Git repository")
    sub = parser.add_subparsers(dest="command", required=True)

    arm = sub.add_parser("arm", help="arm a vendor-neutral envelope; run your agent separately, then check")
    arm.add_argument("label", help="short description of the intended change")
    _policy_arguments(arm)

    run = sub.add_parser("run", help="arm the envelope and execute one Claude Code attempt")
    run.add_argument("task", help="task sent to Claude Code")
    _policy_arguments(run)
    _claude_arguments(run)

    sub.add_parser("check", help="audit current Git-visible changes and run configured verifiers")
    sub.add_parser("resume", help="resume a failed/interrupted Claude envelope with a fresh attempt")
    sub.add_parser("status", help="show current envelope state")
    sub.add_parser("reset", help="remove only .cordon state; source changes are untouched")
    return parser


def _policy(ns: argparse.Namespace) -> Policy:
    return Policy(
        tuple(ns.allow),
        tuple(ns.deny),
        Limits(ns.max_files, ns.max_added_lines, ns.max_deleted_lines, ns.max_working_bytes, ns.max_binary_files),
        ns.allow_commits,
    )


def _claude_config(ns: argparse.Namespace) -> dict[str, object]:
    return {
        "binary": ns.claude,
        "max_turns": ns.max_turns,
        "timeout_seconds": ns.timeout,
        "max_budget_usd": ns.max_budget_usd,
        "model": ns.model,
        "effort": ns.effort,
    }


def _print_audit(audit: object) -> None:
    print(json.dumps(audit.as_dict(), indent=2, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    try:
        if ns.command == "arm":
            _config, state = arm_session(
                ns.repo,
                label=ns.label,
                policy=_policy(ns),
                verify=ns.verify,
                mode="manual",
                max_attempts=ns.max_attempts,
            )
            print(json.dumps({"phase": state["phase"], "mode": "manual"}, indent=2))
            return 0
        if ns.command == "run":
            process, audit = run_claude_session(
                ns.repo,
                label=ns.task,
                policy=_policy(ns),
                verify=ns.verify,
                max_attempts=ns.max_attempts,
                claude=_claude_config(ns),
            )
            _print_audit(audit)
            if process.timed_out or process.output_limited or process.returncode != 0:
                return 4
            return 0 if audit.passed else 3
        if ns.command == "check":
            audit = check_session(ns.repo)
            _print_audit(audit)
            return 0 if audit.passed else 3
        if ns.command == "resume":
            process, audit = resume_claude_session(ns.repo)
            _print_audit(audit)
            if process.timed_out or process.output_limited or process.returncode != 0:
                return 4
            return 0 if audit.passed else 3
        if ns.command == "status":
            print(json.dumps(session_status(ns.repo), indent=2, ensure_ascii=True))
            return 0
        if ns.command == "reset":
            reset_session(ns.repo)
            print("Cordon state removed; repository changes were not modified.")
            return 0
        raise AssertionError(f"unhandled command: {ns.command}")
    except CordonError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
