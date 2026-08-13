"""Strata — generational handoff runner for Claude Code.

Each generation is a separate `claude -p` process with a fresh context. The
generation knows its context will be discarded and must return a compact,
schema-validated handoff. The runner persists that handoff atomically and
injects it into the next fresh generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Any, Iterable

__version__ = "1.0.0"

STATE_DIR = ".strata"
SCHEMA_VERSION = 2
DEFAULT_MAX_GENERATIONS = 20
DEFAULT_MAX_TURNS = 24
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_MAX_HANDOFF_BYTES = 16_000
DEFAULT_STALL_LIMIT = 3
DEFAULT_ENGINE_FAILURE_LIMIT = 3
DEFAULT_TURN_LIMIT_STRIKES = 3
# Claude Code denies every write in `auto` when running headless, so the loop
# would burn generations without touching the repository. See TEST_REPORT.md.
DEFAULT_PERMISSION_MODE = "acceptEdits"

EXIT_OK = 0
EXIT_STOPPED_WITHOUT_COMPLETION = 3
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130

HANDOFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["continue", "complete", "blocked"]},
        "summary": {"type": "string", "maxLength": 4000},
        "completed": {"type": "array", "items": {"type": "string", "maxLength": 800}, "maxItems": 12},
        "decisions": {"type": "array", "items": {"type": "string", "maxLength": 800}, "maxItems": 12},
        "failed_attempts": {"type": "array", "items": {"type": "string", "maxLength": 1000}, "maxItems": 8},
        "changed_files": {"type": "array", "items": {"type": "string", "maxLength": 400}, "maxItems": 40},
        "read_first": {"type": "array", "items": {"type": "string", "maxLength": 400}, "maxItems": 12},
        "next_action": {"type": "string", "maxLength": 2000},
        "tests": {"type": "array", "items": {"type": "string", "maxLength": 1000}, "maxItems": 12},
        "blockers": {"type": "array", "items": {"type": "string", "maxLength": 1000}, "maxItems": 8},
        "completion_evidence": {"type": "array", "items": {"type": "string", "maxLength": 1000}, "maxItems": 12},
    },
    "required": [
        "status", "summary", "completed", "decisions", "failed_attempts",
        "changed_files", "read_first", "next_action", "tests", "blockers",
        "completion_evidence"
    ],
}

LIST_FIELDS = [
    "completed", "decisions", "failed_attempts", "changed_files",
    "read_first", "tests", "blockers", "completion_evidence",
]


class StrataError(RuntimeError):
    """Any condition the runner refuses to continue through."""


@dataclass
class Config:
    task: str
    max_generations: int = DEFAULT_MAX_GENERATIONS
    max_turns: int = DEFAULT_MAX_TURNS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_handoff_bytes: int = DEFAULT_MAX_HANDOFF_BYTES
    stall_limit: int = DEFAULT_STALL_LIMIT
    turn_limit_strikes: int = DEFAULT_TURN_LIMIT_STRIKES
    model: str | None = None
    effort: str | None = None
    permission_mode: str = DEFAULT_PERMISSION_MODE
    max_budget_usd: float | None = None
    claude_bin: str = "claude"
    claude_args: list[str] | None = None
    verify: list[str] | None = None
    verify_shell: bool = False
    allow_dirty: bool = False


@dataclass
class RuntimeState:
    schema_version: int
    task_sha256: str
    generation: int
    phase: str
    last_handoff: dict[str, Any] | None
    last_prompt_sha256: str | None
    stall_fingerprint: str | None
    stall_count: int
    consecutive_engine_failures: int
    started_at: float
    updated_at: float
    consecutive_turn_limits: int = 0
    last_error: str | None = None
    completed: bool = False


def _from_mapping(cls, obj: dict[str, Any]):
    """Build a dataclass from persisted JSON, tolerating unknown keys.

    State written by a different Strata build must never crash the runner with a
    raw TypeError; unsupported schema versions are rejected explicitly instead.
    """
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in obj.items() if k in known})


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(path.parent, os.O_DIRECTORY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()  # pragma: no cover - Windows only
        proc.wait(timeout=2)
    except Exception:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()  # pragma: no cover - Windows only
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


def _run_managed(args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif os.name == "nt":  # pragma: no cover - Windows only
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)  # pragma: no cover
    proc = subprocess.Popen(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        exc.stdout = stdout
        exc.stderr = stderr
        raise
    except KeyboardInterrupt:
        _terminate_process_tree(proc)
        raise
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _run_capture(args: list[str], cwd: Path, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, check=False,
    )


def ensure_git_repo(repo: Path) -> None:
    if not repo.exists():
        raise StrataError(f"Path does not exist: {repo}")
    cp = _run_capture(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if cp.returncode != 0 or cp.stdout.strip() != "true":
        raise StrataError(f"Not a git work tree: {repo}")


def _bounded_signal(text: str, *, max_lines: int = 160, max_chars: int = 12_000) -> str:
    lines = text.strip().splitlines()
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... <{omitted} more lines omitted; inspect with git locally if needed>"]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n... <signal truncated by character budget>"
    return out


def git_status(repo: Path) -> str:
    cp = _run_capture(["git", "status", "--short", "--untracked-files=normal"], repo)
    return _bounded_signal(cp.stdout) if cp.returncode == 0 else "<git status unavailable>"


def git_diff_stat(repo: Path) -> str:
    cp = _run_capture(["git", "diff", "--stat", "--", "."], repo)
    out = cp.stdout.strip()
    staged = _run_capture(["git", "diff", "--cached", "--stat", "--", "."], repo)
    staged_out = staged.stdout.strip()
    parts = []
    if out:
        parts.append("unstaged:\n" + out)
    if staged_out:
        parts.append("staged:\n" + staged_out)
    return _bounded_signal("\n".join(parts)) if parts else "<no tracked diff stat>"


def baseline_guard(repo: Path, allow_dirty: bool) -> None:
    status = git_status(repo)
    if status and not allow_dirty:
        raise StrataError(
            "Repository is not clean. Refusing to start so existing work is not confused with Strata changes. "
            "Commit/stash it, or pass --allow-dirty explicitly.\n" + status
        )


def state_paths(repo: Path) -> dict[str, Path]:
    root = repo / STATE_DIR
    return {
        "root": root,
        "config": root / "config.json",
        "state": root / "state.json",
        "lock": root / "run.lock",
        "history": root / "history.jsonl",
        "last_prompt": root / "last-prompt.txt",
        "last_raw": root / "last-claude.json",
        "verify": root / "last-verification.json",
    }


class RunLock:
    """Advisory single-writer lock so two runners cannot edit one repository."""

    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            # Best-effort fallback for platforms without fcntl.
            marker = self.path.with_suffix(".owner")
            try:
                fd2 = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd2, str(os.getpid()).encode())
                os.close(fd2)
            except FileExistsError as exc:
                raise StrataError("Another Strata runner appears to be active") from exc
        except BlockingIOError as exc:
            os.close(self.fd)
            self.fd = None
            raise StrataError("Another Strata runner is already active in this repository") from exc
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"pid={os.getpid()}\n".encode())
        os.fsync(self.fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            try:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(self.fd)
            self.fd = None
        try:
            self.path.with_suffix(".owner").unlink(missing_ok=True)
        except Exception:
            pass


def init_state(repo: Path, config: Config) -> RuntimeState:
    paths = state_paths(repo)
    paths["root"].mkdir(parents=True, exist_ok=True)
    config_obj = asdict(config)
    config_obj["repo"] = str(repo)
    config_obj["strata_version"] = __version__
    atomic_write(paths["config"], _json_bytes(config_obj))
    now = time.time()
    st = RuntimeState(
        schema_version=SCHEMA_VERSION,
        task_sha256=sha256_text(config.task),
        generation=0,
        phase="initialized",
        last_handoff=None,
        last_prompt_sha256=None,
        stall_fingerprint=None,
        stall_count=0,
        consecutive_engine_failures=0,
        consecutive_turn_limits=0,
        started_at=now,
        updated_at=now,
    )
    save_state(repo, st)
    ensure_git_exclude(repo)
    return st


def ensure_git_exclude(repo: Path) -> None:
    """Keep runner state out of the user's working tree without editing .gitignore."""
    git_dir_cp = _run_capture(["git", "rev-parse", "--git-dir"], repo)
    if git_dir_cp.returncode != 0:
        return
    git_dir = Path(git_dir_cp.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (repo / git_dir).resolve()
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text("utf-8") if exclude.exists() else ""
    line = f"/{STATE_DIR}/"
    if line not in {x.strip() for x in existing.splitlines()}:
        with exclude.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")


def _read_json(path: Path, what: str) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise StrataError(f"Corrupted {what} at {path}: {exc}") from exc
    if not isinstance(obj, dict):
        raise StrataError(f"Corrupted {what} at {path}: expected a JSON object")
    return obj


def load_state(repo: Path) -> RuntimeState:
    path = state_paths(repo)["state"]
    if not path.exists():
        raise StrataError("No state found. Start with `strata start ...`.")
    obj = _read_json(path, "runner state")
    if obj.get("schema_version") != SCHEMA_VERSION:
        raise StrataError(
            f"Unsupported state schema_version={obj.get('schema_version')}; expected {SCHEMA_VERSION}. "
            "Finish or `strata reset` the previous run."
        )
    return _from_mapping(RuntimeState, obj)


def load_config(repo: Path) -> Config:
    path = state_paths(repo)["config"]
    if not path.exists():
        raise StrataError("No config found. Start with `strata start ...`.")
    obj = _read_json(path, "runner config")
    return _from_mapping(Config, obj)


def save_state(repo: Path, st: RuntimeState) -> None:
    st.updated_at = time.time()
    atomic_write(state_paths(repo)["state"], _json_bytes(asdict(st)))


def append_history(repo: Path, obj: dict[str, Any]) -> None:
    path = state_paths(repo)["history"]
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSONL append is diagnostic only; canonical state remains atomic state.json.
    with path.open("ab") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
        f.flush()
        os.fsync(f.fileno())


def handoff_fingerprint(handoff: dict[str, Any]) -> str:
    material = {
        "status": handoff.get("status"),
        "summary": handoff.get("summary", "").strip().lower(),
        "next_action": handoff.get("next_action", "").strip().lower(),
        "blockers": handoff.get("blockers", []),
        "read_first": handoff.get("read_first", []),
    }
    return sha256_text(json.dumps(material, sort_keys=True, ensure_ascii=False))


# Item budget per list field at full size, ordered by how much the next generation
# needs it. Lower tiers scale these down until the handoff fits the byte budget.
_COMPACTION_CAPS: dict[str, int] = {
    "blockers": 5,
    "read_first": 8,
    "changed_files": 20,
    "failed_attempts": 4,
    "next_action_chars": 1200,
    "summary_chars": 1800,
    "tests": 6,
    "decisions": 6,
    "completed": 6,
    "completion_evidence": 6,
}
# Item character caps mirror the schema maxLength values.
_ITEM_CHAR_CAPS: dict[str, int] = {
    "completed": 800, "decisions": 800, "failed_attempts": 1000, "changed_files": 400,
    "read_first": 400, "tests": 1000, "blockers": 1000, "completion_evidence": 1000,
}
_COMPACTION_TIERS = (1.0, 0.7, 0.5, 0.35, 0.25, 0.15, 0.1, 0.05, 0.0)


def _compact_at(handoff: dict[str, Any], factor: float) -> dict[str, Any]:
    """Shrink every field by `factor`; at 0.0 only a minimal navigable core survives."""
    out = dict(handoff)
    for key in LIST_FIELDS:
        items = [str(v) for v in out.get(key, [])]
        keep = max(1, round(_COMPACTION_CAPS[key] * factor)) if factor > 0 else 0
        char_cap = max(80, round(_ITEM_CHAR_CAPS[key] * factor)) if factor > 0 else 0
        out[key] = [item[:char_cap] for item in items[:keep]]
    summary_cap = max(200, round(_COMPACTION_CAPS["summary_chars"] * factor)) if factor > 0 else 200
    action_cap = max(200, round(_COMPACTION_CAPS["next_action_chars"] * factor)) if factor > 0 else 200
    out["summary"] = out.get("summary", "")[:summary_cap]
    out["next_action"] = out.get("next_action", "")[:action_cap]
    return out


def compact_handoff(handoff: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Force a handoff under the byte budget without ever breaking the schema.

    A schema-maximal handoff is far larger than the default budget, so a single
    fixed set of caps is not enough: the tiers are tried in order and the first
    one that fits wins. The last tier keeps only a minimal navigable core —
    status, a short summary and the next action.
    """
    if len(_json_bytes(handoff)) <= max_bytes:
        return handoff
    for factor in _COMPACTION_TIERS:
        candidate = _compact_at(handoff, factor)
        if len(_json_bytes(candidate)) <= max_bytes:
            return candidate
    raise StrataError(
        f"Handoff exceeds hard budget of {max_bytes} bytes even after maximum compaction; "
        "raise --max-handoff-bytes"
    )


def build_prompt(repo: Path, config: Config, st: RuntimeState, recovery_note: str | None = None) -> str:
    generation = st.generation + 1
    previous = st.last_handoff
    status = git_status(repo)
    diffstat = git_diff_stat(repo)
    previous_json = json.dumps(previous, ensure_ascii=False, indent=2) if previous else "<none; this is generation 1>"
    recovery = recovery_note or "<none>"
    # The stable prefix comes first. Dynamic generation state follows, so repeated
    # generations share the longest possible identical prefix for cache reuse.
    return f"""STRATA — GENERATIONAL HANDOFF

MASTER TASK (immutable):
{config.task}

EXECUTION CONTRACT (immutable):
- Every generation has a FRESH conversation context. Never assume hidden knowledge from a previous generation.
- Work directly in the current repository. Inspect only what is needed; do not reread the whole repo by default.
- You KNOW this context will be discarded after this generation.
- Before finishing, return a compact, high-signal handoff through the required structured output schema.
- The next generation receives this immutable prefix, the validated handoff, git status, and diff stat.
- Treat the handoff as engineering memory, NOT a narrative report. Preserve facts whose rediscovery would cost more tokens than storing them.
- Never claim COMPLETE merely because code was written. Completion requires concrete evidence appropriate to the task.
- Do not perform destructive git operations (reset --hard, clean -fd, force checkout) unless the master task explicitly requires them.
- Do not undo unrelated pre-existing user changes.
- If a previous approach failed, do not repeat it unless new evidence justifies doing so.
- If blocked, state the exact blocker and smallest next action.
- Keep read_first narrowly scoped: files the NEXT generation should inspect first, not everything you touched.
- Turns are limited. Prefer finishing one verified step and handing off over leaving work half-applied.

DYNAMIC GENERATION STATE
Generation: {generation}

PREVIOUS VERIFIED HANDOFF:
{previous_json}

RECOVERY NOTE:
{recovery}

CURRENT GIT STATUS (bounded navigation signal, not full context):
{status or '<clean>'}

CURRENT DIFF STAT (bounded navigation signal):
{diffstat}

NOW:
1. Continue from the handoff instead of restarting discovery.
2. Perform the highest-value next work toward MASTER TASK.
3. Run useful tests/checks during the generation where practical.
4. End with structured handoff data only via the required schema.
"""


def build_claude_command(config: Config, prompt: str) -> list[str]:
    cmd = [
        config.claude_bin,
        "-p",
        prompt,
        "--output-format", "json",
        "--json-schema", json.dumps(HANDOFF_SCHEMA, separators=(",", ":")),
        "--no-session-persistence",
        "--max-turns", str(config.max_turns),
        "--permission-mode", config.permission_mode,
    ]
    if config.model:
        cmd += ["--model", config.model]
    if config.effort:
        cmd += ["--effort", config.effort]
    if config.max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(config.max_budget_usd)]
    cmd += list(config.claude_args or [])
    return cmd


class TurnLimitReached(StrataError):
    """Claude Code stopped the generation at --max-turns before handing off."""


class BudgetExhausted(StrataError):
    """Claude Code stopped because --max-budget-usd was reached."""


def classify_engine_error(returncode: int, stdout: str, stderr: str) -> StrataError:
    """Turn a non-zero Claude Code exit into the most specific error we can prove.

    Claude Code still prints its JSON envelope on stdout when it aborts, so the
    abort reason is recoverable instead of being reported as a generic failure.
    """
    subtype = None
    try:
        obj = json.loads(stdout)
        if isinstance(obj, dict):
            subtype = obj.get("subtype") or obj.get("stop_reason")
    except (json.JSONDecodeError, TypeError):
        pass
    tail = (stderr or stdout or "").strip()[-4000:]
    if subtype == "error_max_turns":
        return TurnLimitReached(
            "Claude Code hit --max-turns before producing a handoff. "
            "Repository edits from this generation may be partially applied."
        )
    if isinstance(subtype, str) and "budget" in subtype:
        return BudgetExhausted(f"Claude Code stopped on the configured budget limit ({subtype}).")
    if subtype:
        return StrataError(f"Claude Code exited {returncode} ({subtype}): {tail}")
    return StrataError(f"Claude Code exited {returncode}: {tail}")


def extract_handoff(raw: dict[str, Any]) -> dict[str, Any]:
    handoff = raw.get("structured_output")
    if not isinstance(handoff, dict):
        raise StrataError("Claude JSON response is missing object field `structured_output`")
    # Local validation, independent of Claude Code's own schema enforcement.
    missing = [k for k in HANDOFF_SCHEMA["required"] if k not in handoff]
    if missing:
        raise StrataError(f"Structured handoff missing fields: {', '.join(missing)}")
    if handoff.get("status") not in {"continue", "complete", "blocked"}:
        raise StrataError("Invalid handoff status")
    for key in LIST_FIELDS:
        if not isinstance(handoff.get(key), list) or not all(isinstance(v, str) for v in handoff[key]):
            raise StrataError(f"Handoff field {key!r} must be a list of strings")
    for key in ["summary", "next_action"]:
        if not isinstance(handoff.get(key), str):
            raise StrataError(f"Handoff field {key!r} must be a string")
    status = handoff["status"]
    if status == "continue" and not handoff["next_action"].strip():
        raise StrataError("A continuing generation must provide a non-empty next_action")
    if status == "complete" and not handoff["completion_evidence"]:
        raise StrataError("A complete generation must provide completion_evidence")
    if status == "blocked" and not handoff["blockers"]:
        raise StrataError("A blocked generation must provide at least one blocker")
    return handoff


def _usage_summary(raw: dict[str, Any]) -> dict[str, Any]:
    # Preserve whatever Claude Code exposes without coupling to one release's usage shape.
    keys = ["session_id", "total_cost_usd", "duration_ms", "duration_api_ms", "num_turns", "usage"]
    return {k: raw[k] for k in keys if k in raw}


def run_claude_generation(repo: Path, config: Config, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cmd = build_claude_command(config, prompt)
    try:
        cp = _run_managed(cmd, repo, config.timeout_seconds)
    except FileNotFoundError as exc:
        raise StrataError(f"Claude Code binary not found: {config.claude_bin}") from exc
    except subprocess.TimeoutExpired as exc:
        raise StrataError(f"Claude generation timed out after {config.timeout_seconds}s") from exc
    if cp.returncode != 0:
        raise classify_engine_error(cp.returncode, cp.stdout or "", cp.stderr or "")
    try:
        raw = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise StrataError(f"Claude Code returned invalid JSON: {cp.stdout[-2000:]}") from exc
    if not isinstance(raw, dict):
        raise StrataError("Claude Code returned JSON that is not an object")
    handoff = extract_handoff(raw)
    return handoff, raw


def run_verification(repo: Path, commands: Iterable[str], *, use_shell: bool = False) -> tuple[bool, list[dict[str, Any]]]:
    """Run independent completion checks. A failing check outranks the agent's own claim."""
    results: list[dict[str, Any]] = []
    all_ok = True
    for command in commands:
        started = time.time()
        try:
            if use_shell:
                args: Any = command
            else:
                args = shlex.split(command)
                if not args:
                    raise ValueError("empty command")
            cp = subprocess.run(
                args, cwd=repo, text=True, shell=use_shell, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=900, check=False,
            )
            ok = cp.returncode == 0
            results.append({
                "command": command, "ok": ok, "returncode": cp.returncode,
                "output_tail": cp.stdout[-6000:], "duration_s": round(time.time() - started, 3),
            })
        except Exception as exc:
            ok = False
            results.append({
                "command": command, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                "duration_s": round(time.time() - started, 3),
            })
        all_ok = all_ok and ok
    return all_ok, results


def verification_failure_handoff(handoff: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [r for r in results if not r.get("ok")]
    compact = []
    for r in failed[:5]:
        tail = (r.get("output_tail") or r.get("error", ""))[-1200:].strip()
        compact.append(f"{r.get('command')}: failed rc={r.get('returncode', '?')} {tail}")
    new = dict(handoff)
    new["status"] = "continue"
    new["blockers"] = (new.get("blockers", []) + ["Independent completion verification failed."] + compact)[:8]
    new["next_action"] = "Fix the independently verified failures, rerun the relevant checks, then reassess completion."
    new["completion_evidence"] = []
    return new


def recover_if_needed(st: RuntimeState) -> str | None:
    if st.phase in {"running", "interrupted", "engine_error", "turn_limit"}:
        return (
            f"Previous runner stopped/crashed or failed around generation {st.generation + 1} (phase={st.phase}). "
            "Assume repository edits may have been partially applied. Inspect current git status/diff before changing anything. "
            "The last canonical handoff below is still trusted; no unvalidated conclusion from the interrupted/failed generation is trusted."
        )
    return None


def run_loop(repo: Path, config: Config, st: RuntimeState, *, one_generation: bool = False) -> RuntimeState:
    paths = state_paths(repo)
    recovery_note = recover_if_needed(st)
    while not st.completed and st.generation < config.max_generations:
        prompt = build_prompt(repo, config, st, recovery_note=recovery_note)
        recovery_note = None
        atomic_write(paths["last_prompt"], prompt.encode("utf-8"))
        st.phase = "running"
        st.last_prompt_sha256 = sha256_text(prompt)
        save_state(repo, st)
        gen = st.generation + 1
        print(f"[strata] generation {gen}/{config.max_generations}", flush=True)
        try:
            handoff, raw = run_claude_generation(repo, config, prompt)
            atomic_write(paths["last_raw"], _json_bytes(raw))
            handoff = compact_handoff(handoff, config.max_handoff_bytes)
            st.consecutive_engine_failures = 0
            st.consecutive_turn_limits = 0
        except KeyboardInterrupt:
            st.phase = "interrupted"
            st.last_error = "Interrupted by user"
            save_state(repo, st)
            raise
        except BudgetExhausted as exc:
            # Not retryable: another generation would immediately hit the same wall.
            st.phase = "budget_exhausted"
            st.last_error = str(exc)
            append_history(repo, {"generation": gen, "event": "budget_exhausted", "error": str(exc), "time": time.time()})
            save_state(repo, st)
            return st
        except TurnLimitReached as exc:
            st.consecutive_turn_limits += 1
            st.phase = "turn_limit"
            st.last_error = str(exc)
            append_history(repo, {"generation": gen, "event": "turn_limit", "error": str(exc), "time": time.time()})
            st.generation = gen
            save_state(repo, st)
            if st.consecutive_turn_limits >= config.turn_limit_strikes:
                st.last_error = (
                    f"{st.consecutive_turn_limits} consecutive generations hit --max-turns={config.max_turns} "
                    "without handing off. Raise --max-turns or split the task."
                )
                save_state(repo, st)
                return st
            recovery_note = (
                f"Generation {gen} was cut off at the {config.max_turns}-turn limit before it could hand off. "
                "Its conclusions are unknown and untrusted. Inspect the repository for partial edits, then take the "
                "smallest verifiable step and hand off early."
            )
            if one_generation:
                return st
            continue
        except StrataError as exc:
            st.consecutive_engine_failures += 1
            st.phase = "engine_error"
            st.last_error = str(exc)
            append_history(repo, {"generation": gen, "event": "engine_error", "error": str(exc), "time": time.time()})
            save_state(repo, st)
            if st.consecutive_engine_failures >= DEFAULT_ENGINE_FAILURE_LIMIT:
                raise StrataError(
                    f"Stopping after {st.consecutive_engine_failures} consecutive Claude engine failures: {exc}"
                ) from exc
            # Fresh context on next attempt; no untrusted handoff is fabricated.
            recovery_note = (
                f"Generation {gen} failed at the Claude runner boundary: {exc}. "
                "Inspect current repo state for partial edits and continue safely."
            )
            st.generation = gen
            save_state(repo, st)
            if one_generation:
                return st
            continue

        st.generation = gen
        st.last_handoff = handoff
        st.phase = "handoff_saved"
        st.last_error = None

        fp = handoff_fingerprint(handoff)
        if fp == st.stall_fingerprint:
            st.stall_count += 1
        else:
            st.stall_fingerprint = fp
            st.stall_count = 1

        append_history(repo, {
            "generation": gen, "event": "handoff", "handoff": handoff,
            "usage": _usage_summary(raw), "time": time.time(),
        })
        save_state(repo, st)

        if st.stall_count >= config.stall_limit and handoff["status"] != "complete":
            st.phase = "stalled"
            st.last_error = f"Same handoff fingerprint repeated {st.stall_count} times; refusing to burn more tokens."
            save_state(repo, st)
            return st

        if handoff["status"] == "blocked":
            st.phase = "blocked"
            save_state(repo, st)
            return st

        if handoff["status"] == "complete":
            verify_cmds = config.verify or []
            if verify_cmds:
                ok, results = run_verification(repo, verify_cmds, use_shell=config.verify_shell)
                atomic_write(paths["verify"], _json_bytes({"ok": ok, "results": results}))
                append_history(repo, {"generation": gen, "event": "verification", "ok": ok, "results": results, "time": time.time()})
                if not ok:
                    st.last_handoff = compact_handoff(
                        verification_failure_handoff(handoff, results), config.max_handoff_bytes
                    )
                    st.phase = "verification_failed"
                    st.stall_fingerprint = None
                    st.stall_count = 0
                    save_state(repo, st)
                    if one_generation:
                        return st
                    continue
            st.completed = True
            st.phase = "complete"
            save_state(repo, st)
            return st

        if one_generation:
            return st

    if not st.completed and st.generation >= config.max_generations:
        st.phase = "max_generations"
        st.last_error = f"Reached max_generations={config.max_generations} without verified completion"
        save_state(repo, st)
    return st


def validate_persisted_integrity(config: Config, st: RuntimeState) -> None:
    if st.schema_version != SCHEMA_VERSION:
        raise StrataError(f"Unsupported state schema_version={st.schema_version}; expected {SCHEMA_VERSION}")
    if sha256_text(config.task) != st.task_sha256:
        raise StrataError("Persisted master task hash mismatch. Refusing to continue with mutated task/config state.")
    if st.generation < 0 or config.max_generations < 1 or config.max_turns < 1:
        raise StrataError("Invalid persisted numeric limits")


def collect_metrics(repo: Path) -> dict[str, Any]:
    path = state_paths(repo)["history"]
    generations = 0
    total_cost = 0.0
    usage_totals: dict[str, float] = {}
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict) or obj.get("event") != "handoff":
                continue
            generations += 1
            meta = obj.get("usage", {})
            if not isinstance(meta, dict):
                continue
            if isinstance(meta.get("total_cost_usd"), (int, float)):
                total_cost += float(meta["total_cost_usd"])
            usage = meta.get("usage", {})
            if isinstance(usage, dict):
                for k, v in usage.items():
                    if isinstance(v, (int, float)):
                        usage_totals[k] = usage_totals.get(k, 0.0) + float(v)
    return {"completed_generations": generations, "total_cost_usd": round(total_cost, 6), "usage": usage_totals}


def metrics(repo: Path) -> None:
    print(json.dumps(collect_metrics(repo), indent=2, ensure_ascii=False))


def status_report(repo: Path) -> dict[str, Any]:
    st = load_state(repo)
    cfg = load_config(repo)
    return {
        "strata_version": __version__,
        "phase": st.phase,
        "generation": st.generation,
        "max_generations": cfg.max_generations,
        "completed": st.completed,
        "stall_count": st.stall_count,
        "last_error": st.last_error,
        "last_handoff": st.last_handoff,
    }


def print_status(repo: Path) -> None:
    print(json.dumps(status_report(repo), indent=2, ensure_ascii=False))


def reset_state(repo: Path) -> None:
    root = state_paths(repo)["root"]
    if root.exists():
        import shutil
        shutil.rmtree(root)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="strata",
        description="Strata — fresh-context, crash-safe generational handoff runner for Claude Code",
    )
    p.add_argument("--version", action="version", version=f"strata {__version__}")
    p.add_argument("--repo", default=".", help="Git repository path")
    sub = p.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Initialize and run a new generational loop")
    start.add_argument("task", help="Immutable master task")
    start.add_argument("--max-generations", type=int, default=DEFAULT_MAX_GENERATIONS)
    start.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    start.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    start.add_argument("--max-handoff-bytes", type=int, default=DEFAULT_MAX_HANDOFF_BYTES)
    start.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
    start.add_argument("--turn-limit-strikes", type=int, default=DEFAULT_TURN_LIMIT_STRIKES)
    start.add_argument("--model")
    start.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    start.add_argument("--permission-mode", default=DEFAULT_PERMISSION_MODE,
                       choices=["acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"])
    start.add_argument("--max-budget-usd", type=float)
    start.add_argument("--claude-bin", default="claude")
    start.add_argument("--claude-arg", action="append", default=[],
                       help="Extra argument passed through to Claude Code (repeatable)")
    start.add_argument("--verify", action="append", default=[],
                       help="Independent completion check (repeatable)")
    start.add_argument("--verify-shell", action="store_true",
                       help="Run --verify commands through the shell (enables pipes and &&)")
    start.add_argument("--allow-dirty", action="store_true")
    start.add_argument("--one-generation", action="store_true")

    resume = sub.add_parser("resume", help="Resume/recover from persisted state")
    resume.add_argument("--one-generation", action="store_true")

    sub.add_parser("status", help="Show persisted state")
    sub.add_parser("metrics", help="Summarize token/cost metadata reported by Claude Code")
    sub.add_parser("reset", help="Delete only the Strata runner state")
    return p.parse_args(argv)


def _exit_code_for(st: RuntimeState) -> int:
    if st.completed or st.phase == "handoff_saved":
        return EXIT_OK
    return EXIT_STOPPED_WITHOUT_COMPLETION


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    repo = Path(ns.repo).resolve()
    try:
        ensure_git_repo(repo)
        if ns.command == "status":
            print_status(repo)
            return EXIT_OK
        if ns.command == "metrics":
            metrics(repo)
            return EXIT_OK
        if ns.command == "reset":
            reset_state(repo)
            print("[strata] state removed")
            return EXIT_OK
        # Exclude runner state before creating the lock file; otherwise the lock itself
        # would make a clean repository look dirty during the start safety check.
        ensure_git_exclude(repo)
        paths = state_paths(repo)
        with RunLock(paths["lock"]):
            if ns.command == "start":
                baseline_guard(repo, ns.allow_dirty)
                if paths["state"].exists():
                    raise StrataError("Existing Strata state found. Use `resume`, or `reset` before a new task.")
                cfg = Config(
                    task=ns.task,
                    max_generations=ns.max_generations,
                    max_turns=ns.max_turns,
                    timeout_seconds=ns.timeout,
                    max_handoff_bytes=ns.max_handoff_bytes,
                    stall_limit=ns.stall_limit,
                    turn_limit_strikes=ns.turn_limit_strikes,
                    model=ns.model,
                    effort=ns.effort,
                    permission_mode=ns.permission_mode,
                    max_budget_usd=ns.max_budget_usd,
                    claude_bin=ns.claude_bin,
                    claude_args=ns.claude_arg,
                    verify=ns.verify,
                    verify_shell=ns.verify_shell,
                    allow_dirty=ns.allow_dirty,
                )
                st = init_state(repo, cfg)
            else:
                cfg = load_config(repo)
                st = load_state(repo)
                validate_persisted_integrity(cfg, st)
                if st.completed:
                    print("[strata] already complete")
                    return EXIT_OK
            final = run_loop(repo, cfg, st, one_generation=ns.one_generation)
            print(f"[strata] phase={final.phase} generation={final.generation}")
            if final.last_error and not final.completed:
                print(f"[strata] {final.last_error}", file=sys.stderr)
            return _exit_code_for(final)
    except StrataError as exc:
        print(f"[strata] ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\n[strata] interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())  # pragma: no cover
