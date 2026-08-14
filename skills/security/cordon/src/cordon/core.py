"""Cordon core: deterministic Git change envelopes for coding-agent runs.

Runtime dependencies: Python 3.10 standard library and Git. Claude Code is only
required for ``run`` and ``resume``; ``arm``/``check`` remain agent-neutral.
"""
from __future__ import annotations

import contextlib
import dataclasses
import errno
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

SCHEMA_VERSION = 1
STATE_DIR_NAME = ".cordon"
DEFAULT_MAX_FILES = 25
DEFAULT_MAX_ADDED_LINES = 2_000
DEFAULT_MAX_DELETED_LINES = 1_000
DEFAULT_MAX_WORKING_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_BINARY_FILES = 2
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_TURNS = 30
DEFAULT_TIMEOUT_SECONDS = 1_800
DEFAULT_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_PATTERN_LENGTH = 512
MAX_PATTERNS = 256
MAX_LABEL_LENGTH = 16_384
MAX_VERIFIERS = 8
MAX_VERIFIER_LENGTH = 4_096
MAX_STORED_VERIFIER_BYTES = 16_384
MAX_UNTRACKED_SCAN_BYTES = 64 * 1024 * 1024
MAX_HIDDEN_PATHS_REPORTED = 10
VALID_PHASES = frozenset({"armed", "running", "agent_finished", "accepted", "rejected", "engine_error", "interrupted"})
VALID_CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultracode"})


class CordonError(RuntimeError):
    """Base class for named Cordon failures."""


class RepositoryError(CordonError):
    """The target repository cannot be audited safely."""


class StateError(CordonError):
    """Persistent Cordon state is absent, corrupt, or inconsistent."""


class PolicyError(CordonError):
    """The requested policy is invalid."""


class LockError(CordonError):
    """Another Cordon operation already owns the repository lock."""


class ProcessError(CordonError):
    """A managed subprocess could not be started or completed."""


@dataclasses.dataclass(frozen=True)
class Limits:
    max_files: int = DEFAULT_MAX_FILES
    max_added_lines: int = DEFAULT_MAX_ADDED_LINES
    max_deleted_lines: int = DEFAULT_MAX_DELETED_LINES
    max_working_bytes: int = DEFAULT_MAX_WORKING_BYTES
    max_binary_files: int = DEFAULT_MAX_BINARY_FILES

    def validate(self) -> None:
        for name, value in dataclasses.asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise PolicyError(f"{name} must be a non-negative integer")


@dataclasses.dataclass(frozen=True)
class Policy:
    allow: tuple[str, ...]
    deny: tuple[str, ...] = ()
    limits: Limits = dataclasses.field(default_factory=Limits)
    allow_commits: bool = False

    def validate(self) -> None:
        self.limits.validate()
        if not self.allow:
            raise PolicyError("at least one --allow pattern is required")
        if len(self.allow) + len(self.deny) > MAX_PATTERNS:
            raise PolicyError(f"at most {MAX_PATTERNS} allow/deny patterns are supported")
        for pattern in self.allow + self.deny:
            validate_pattern(pattern)


@dataclasses.dataclass(frozen=True)
class ProcessResult:
    args: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limited: bool = False


@dataclasses.dataclass(frozen=True)
class VerificationResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    passed: bool
    timed_out: bool = False
    output_limited: bool = False


@dataclasses.dataclass(frozen=True)
class AuditResult:
    passed: bool
    baseline: str
    current_head: str
    head_changed: bool
    changed_files: tuple[str, ...]
    added_lines: int
    deleted_lines: int
    working_bytes: int
    binary_files: int
    violations: tuple[str, ...]
    verification: tuple[VerificationResult, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "baseline": self.baseline,
            "current_head": self.current_head,
            "head_changed": self.head_changed,
            "changed_files": list(self.changed_files),
            "metrics": {
                "files": len(self.changed_files),
                "added_lines": self.added_lines,
                "deleted_lines": self.deleted_lines,
                "working_bytes": self.working_bytes,
                "binary_files": self.binary_files,
            },
            "violations": list(self.violations),
            "verification": [dataclasses.asdict(item) for item in self.verification],
        }


def utc_now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise StateError(f"cannot read {path}: {exc}") from exc
    return sha256_bytes(data)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.EINVAL, errno.ENOTSUP, errno.EACCES}:
            return
        raise
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()
        raise


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json(value) + b"\n")


def _reader_thread(pipe: Any, buffer: bytearray, cap: int, limit_event: threading.Event) -> None:
    try:
        while True:
            chunk = pipe.read(65_536)
            if not chunk:
                return
            remaining = cap + 1 - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            if len(buffer) > cap:
                limit_event.set()
                return
    finally:
        pipe.close()


def _terminate_process_group(process: subprocess.Popen[bytes], grace_seconds: float = 0.4) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":  # pragma: no cover - Windows is not a tested target
        process.terminate()  # pragma: no cover
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    if process.poll() is None:
        if os.name == "nt":  # pragma: no cover - Windows is not a tested target
            process.kill()  # pragma: no cover
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1)


def run_bounded_process(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    output_cap: int = DEFAULT_OUTPUT_BYTES,
    env: dict[str, str] | None = None,
) -> ProcessResult:
    if not isinstance(output_cap, int) or isinstance(output_cap, bool) or output_cap < 1:
        raise ProcessError("output cap must be a positive integer")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ProcessError("timeout must be a finite positive number")
    try:
        process = subprocess.Popen(
            list(args),
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        raise ProcessError(f"cannot start {args[0]!r}: {exc}") from exc
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = bytearray()
    stderr = bytearray()
    limited = threading.Event()
    threads = [
        threading.Thread(target=_reader_thread, args=(process.stdout, stdout, output_cap, limited), daemon=True),
        threading.Thread(target=_reader_thread, args=(process.stderr, stderr, output_cap, limited), daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None:
        if limited.is_set():
            _terminate_process_group(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _terminate_process_group(process)
            break
        time.sleep(0.01)
    for thread in threads:
        thread.join(timeout=1)
    if any(thread.is_alive() for thread in threads):
        _terminate_process_group(process)
        raise ProcessError("subprocess output reader did not terminate")
    return ProcessResult(
        tuple(str(item) for item in args),
        process.returncode if process.returncode is not None else -signal.SIGKILL,
        bytes(stdout[:output_cap]),
        bytes(stderr[:output_cap]),
        timed_out=timed_out,
        output_limited=limited.is_set(),
    )


def _git(repo: Path, args: Sequence[str], *, output_cap: int = DEFAULT_OUTPUT_BYTES) -> bytes:
    result = run_bounded_process(
        ["git", "--no-pager", *args], cwd=repo, timeout=60, output_cap=output_cap
    )
    if result.output_limited:
        raise RepositoryError(f"git {' '.join(args)} exceeded the {output_cap}-byte output limit")
    if result.timed_out:
        raise RepositoryError(f"git {' '.join(args)} timed out")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RepositoryError(f"git {' '.join(args)} failed ({result.returncode}): {detail}")
    return result.stdout


def repository_root(path: Path) -> Path:
    candidate = path.resolve()
    output = _git(candidate, ["rev-parse", "--show-toplevel"])
    root = Path(os.fsdecode(output.rstrip(b"\n"))).resolve()
    return root


def current_head(repo: Path) -> str:
    return _git(repo, ["rev-parse", "--verify", "HEAD"]).decode("ascii").strip()


def clean_worktree(repo: Path) -> bool:
    return _git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=normal"]) == b""


def state_dir(repo: Path) -> Path:
    return repo / STATE_DIR_NAME


def _git_path(repo: Path, relative: str) -> Path:
    git_path = _git(repo, ["rev-parse", "--git-path", relative])
    path = Path(os.fsdecode(git_path.rstrip(b"\n")))
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def _exclude_path(repo: Path) -> Path:
    return _git_path(repo, "info/exclude")


def _lock_path(repo: Path) -> Path:
    return _git_path(repo, "cordon.lock")


def ensure_local_exclude(repo: Path) -> str:
    path = _exclude_path(repo)
    existing = path.read_bytes() if path.exists() else b""
    marker = f"/{STATE_DIR_NAME}/".encode("ascii")
    if marker not in existing.splitlines():
        suffix = b"" if not existing or existing.endswith(b"\n") else b"\n"
        atomic_write_bytes(path, existing + suffix + marker + b"\n")
    return sha256_file(path)


def verify_local_exclude(repo: Path, expected_sha256: str) -> None:
    path = _exclude_path(repo)
    if not path.exists() or sha256_file(path) != expected_sha256:
        raise StateError(".git/info/exclude changed after Cordon was armed")


def validate_pattern(pattern: str) -> None:
    if not isinstance(pattern, str) or not pattern:
        raise PolicyError("path patterns must be non-empty strings")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise PolicyError(f"path pattern exceeds {MAX_PATTERN_LENGTH} characters")
    if "\x00" in pattern:
        raise PolicyError("path patterns may not contain NUL")
    if pattern.startswith("/") or pattern.startswith("./"):
        raise PolicyError("path patterns must be repository-relative without a leading slash")
    parts = pattern.split("/")
    if any(part in {".", ".."} for part in parts):
        raise PolicyError("path patterns may not contain '.' or '..' path segments")


def _verifier_args(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip():
        raise PolicyError("--verify command must be a non-empty string")
    if len(command) > MAX_VERIFIER_LENGTH:
        raise PolicyError(f"--verify command exceeds {MAX_VERIFIER_LENGTH} characters")
    try:
        args = shlex.split(command, posix=True)
    except ValueError as exc:
        raise PolicyError(f"invalid --verify command: {exc}") from exc
    if not args or not args[0]:
        raise PolicyError("--verify command may not resolve to an empty executable")
    return args


def _validate_verifier_set(commands: Sequence[str]) -> None:
    if isinstance(commands, (str, bytes)):
        raise PolicyError("verifiers must be supplied as a sequence of command strings")
    if len(commands) > MAX_VERIFIERS:
        raise PolicyError(f"at most {MAX_VERIFIERS} verifier commands are supported")
    for command in commands:
        _verifier_args(command)


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    validate_pattern(pattern)
    pieces: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    pieces.append("(?:.*/)?")
                    index += 1
                else:
                    pieces.append(".*")
                continue
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        index += 1
    pieces.append("$")
    return re.compile("".join(pieces), re.DOTALL)


def path_allowed(path: str, policy: Policy) -> bool:
    if any(_pattern_regex(pattern).match(path) for pattern in policy.deny):
        return False
    return any(_pattern_regex(pattern).match(path) for pattern in policy.allow)


def policy_to_dict(policy: Policy) -> dict[str, Any]:
    return {
        "allow": list(policy.allow),
        "deny": list(policy.deny),
        "limits": dataclasses.asdict(policy.limits),
        "allow_commits": policy.allow_commits,
    }


def policy_from_dict(value: Any) -> Policy:
    if not isinstance(value, dict):
        raise StateError("policy must be a JSON object")
    required = {"allow", "deny", "limits", "allow_commits"}
    if set(value) != required:
        raise StateError("policy fields do not match the Cordon schema")
    if not isinstance(value["allow"], list) or not all(isinstance(item, str) for item in value["allow"]):
        raise StateError("policy.allow must be a list of strings")
    if not isinstance(value["deny"], list) or not all(isinstance(item, str) for item in value["deny"]):
        raise StateError("policy.deny must be a list of strings")
    if not isinstance(value["limits"], dict):
        raise StateError("policy.limits must be a JSON object")
    expected_limit_fields = set(dataclasses.asdict(Limits()))
    if set(value["limits"]) != expected_limit_fields:
        raise StateError("policy.limits fields do not match the Cordon schema")
    limits = Limits(**value["limits"])
    if not isinstance(value["allow_commits"], bool):
        raise StateError("policy.allow_commits must be boolean")
    policy = Policy(tuple(value["allow"]), tuple(value["deny"]), limits, value["allow_commits"])
    try:
        policy.validate()
    except PolicyError as exc:
        raise StateError(f"invalid stored policy: {exc}") from exc
    return policy


def _config_hash(config: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(config))


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except FileNotFoundError as exc:
        raise StateError(f"{label} is missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError(f"{label} must contain a JSON object")
    return value


def save_state(repo: Path, state: dict[str, Any]) -> None:
    atomic_write_json(state_dir(repo) / "state.json", state)


def load_session(repo: Path) -> tuple[dict[str, Any], dict[str, Any], Policy]:
    config = _load_json_object(state_dir(repo) / "config.json", "Cordon config")
    state = _load_json_object(state_dir(repo) / "state.json", "Cordon state")
    config_required = {
        "schema_version", "mode", "label", "baseline", "policy", "verify", "claude", "created_at"
    }
    if set(config) != config_required or config.get("schema_version") != SCHEMA_VERSION:
        raise StateError("Cordon config schema is unsupported or malformed")
    state_required = {
        "schema_version", "phase", "attempt", "max_attempts", "config_sha256",
        "exclude_sha256", "last_error", "last_audit", "updated_at"
    }
    if set(state) != state_required or state.get("schema_version") != SCHEMA_VERSION:
        raise StateError("Cordon state schema is unsupported or malformed")
    if state.get("config_sha256") != _config_hash(config):
        raise StateError("Cordon config hash does not match state")
    if not isinstance(state.get("attempt"), int) or isinstance(state.get("attempt"), bool) or state["attempt"] < 0:
        raise StateError("Cordon state attempt is invalid")
    if not isinstance(state.get("max_attempts"), int) or isinstance(state.get("max_attempts"), bool) or state["max_attempts"] < 1:
        raise StateError("Cordon state max_attempts is invalid")
    if state.get("phase") not in VALID_PHASES:
        raise StateError("Cordon state phase is invalid")
    if state["attempt"] > state["max_attempts"]:
        raise StateError("Cordon state attempt exceeds max_attempts")
    if state.get("last_error") is not None and not isinstance(state.get("last_error"), str):
        raise StateError("Cordon state last_error is invalid")
    if not isinstance(state.get("updated_at"), str) or not state["updated_at"]:
        raise StateError("Cordon state updated_at is invalid")
    if not isinstance(config.get("baseline"), str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", config["baseline"]):
        raise StateError("Cordon baseline is invalid")
    if config.get("mode") not in {"manual", "claude"}:
        raise StateError("Cordon mode is invalid")
    if (
        not isinstance(config.get("label"), str)
        or not config["label"].strip()
        or len(config["label"]) > MAX_LABEL_LENGTH
    ):
        raise StateError("Cordon label is invalid")
    if not isinstance(config.get("verify"), list):
        raise StateError("Cordon verifier list is invalid")
    try:
        _validate_verifier_set(config["verify"])
    except PolicyError as exc:
        raise StateError(f"Cordon verifier list is invalid: {exc}") from exc
    if not isinstance(config.get("claude"), dict):
        raise StateError("Cordon Claude configuration is invalid")
    try:
        _validate_claude_config(config["claude"])
    except PolicyError as exc:
        raise StateError(f"Cordon Claude configuration is invalid: {exc}") from exc
    if not isinstance(config.get("created_at"), str) or not config["created_at"]:
        raise StateError("Cordon created_at is invalid")
    policy = policy_from_dict(config["policy"])
    verify_local_exclude(repo, str(state.get("exclude_sha256")))
    return config, state, policy


@contextlib.contextmanager
def repository_lock(repo: Path) -> Iterator[None]:
    path = _lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    if os.name == "nt":  # pragma: no cover - Windows is not a tested target
        try:  # pragma: no cover
            import msvcrt  # pragma: no cover
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # pragma: no cover
        except OSError as exc:  # pragma: no cover
            handle.close()  # pragma: no cover
            raise LockError("another Cordon process owns this repository") from exc  # pragma: no cover
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise LockError("another Cordon process owns this repository") from exc
    try:
        yield
    finally:
        if os.name == "nt":  # pragma: no cover - Windows is not a tested target
            import msvcrt  # pragma: no cover
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # pragma: no cover
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _parse_numstat(data: bytes) -> dict[bytes, tuple[int | None, int | None]]:
    result: dict[bytes, tuple[int | None, int | None]] = {}
    for record in data.split(b"\x00"):
        if not record:
            continue
        first = record.find(b"\t")
        second = record.find(b"\t", first + 1)
        if first < 0 or second < 0:
            raise RepositoryError("git --numstat returned a malformed record")
        added_raw, deleted_raw, path = record[:first], record[first + 1:second], record[second + 1:]
        if not path:
            raise RepositoryError("git --numstat returned an empty path")
        if added_raw == b"-" and deleted_raw == b"-":
            result[path] = (None, None)
            continue
        try:
            result[path] = (int(added_raw), int(deleted_raw))
        except ValueError as exc:
            raise RepositoryError("git --numstat returned invalid line counts") from exc
    return result


def _git_visible_changes(repo: Path, baseline: str) -> tuple[dict[bytes, tuple[int | None, int | None]], set[bytes]]:
    numstat = _parse_numstat(
        _git(repo, ["diff", "--no-ext-diff", "--no-renames", "--numstat", "-z", baseline, "--", "."])
    )
    untracked_raw = _git(repo, ["ls-files", "--others", "--exclude-standard", "-z"])
    untracked = {item for item in untracked_raw.split(b"\x00") if item}
    return numstat, untracked


def _display_path(path: bytes) -> str:
    return path.decode("utf-8", "surrogateescape")


def index_hidden_paths(repo: Path) -> tuple[bytes, ...]:
    """Tracked paths whose index flags hide worktree modifications from `git diff`.

    `git update-index --assume-unchanged` (lowercase status letter) and
    `--skip-worktree` (`S`) both make a modified tracked file invisible to the
    diff Cordon audits, which would let a change slip past the envelope. Cordon
    refuses to arm while such flags exist and treats any flag appearing later as
    a violation, so the audit never reports a blind spot as a clean result.
    """
    hidden: list[bytes] = []
    for record in _git(repo, ["ls-files", "-v", "-z"]).split(b"\x00"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise RepositoryError("git ls-files -v returned a malformed record")
        letter, path = record[:1], record[2:]
        # Lowercase letter = assume-unchanged; `S` = skip-worktree.
        if letter == b"S" or letter.islower():
            hidden.append(path)
    return tuple(sorted(hidden))


def _hidden_path_remedy(paths: Sequence[bytes]) -> str:
    listing = ", ".join(_display_path(path) for path in paths[:MAX_HIDDEN_PATHS_REPORTED])
    if len(paths) > MAX_HIDDEN_PATHS_REPORTED:
        listing += f", ... (+{len(paths) - MAX_HIDDEN_PATHS_REPORTED} more)"
    return (
        f"{listing}. Clear them with `git update-index --no-assume-unchanged <path>` "
        "or `git update-index --no-skip-worktree <path>`."
    )


def _measure_untracked(
    repo: Path,
    raw_path: bytes,
    *,
    scan_budget: int = MAX_UNTRACKED_SCAN_BYTES,
) -> tuple[int, int, bool, str | None, int]:
    if scan_budget < 0:
        raise PolicyError("untracked scan budget must be non-negative")
    path = repo / os.fsdecode(raw_path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return 0, 0, False, "untracked path disappeared during audit", 0
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        size = len(os.fsencode(target))
        return size, 1, False, None, 0
    if not stat.S_ISREG(info.st_mode):
        return 0, 0, False, "untracked path is not a regular file or symlink", 0
    size = info.st_size
    binary = False
    lines = 0
    scanned = 0
    last_byte = b""
    try:
        with open(path, "rb") as handle:
            while True:
                remaining = scan_budget - scanned
                chunk = handle.read(min(65_536, remaining + 1))
                if not chunk:
                    break
                scanned += len(chunk)
                if scanned > scan_budget:
                    return max(size, scanned), 0, binary, "untracked scan safety cap exceeded during read", scanned
                if b"\x00" in chunk:
                    binary = True
                lines += chunk.count(b"\n")
                last_byte = chunk[-1:]
    except OSError as exc:
        return max(size, scanned), 0, False, f"cannot read untracked path: {exc}", scanned
    if scanned and not binary and last_byte != b"\n":
        lines += 1
    return max(size, scanned), lines, binary, None, scanned


def audit_policy(repo: Path, baseline: str, policy: Policy) -> AuditResult:
    policy.validate()
    head = current_head(repo)
    numstat, untracked = _git_visible_changes(repo, baseline)
    paths = set(numstat) | untracked
    violations: list[str] = []
    display_paths = sorted((_display_path(path) for path in paths), key=lambda item: item.encode("utf-8", "surrogateescape"))
    hidden = index_hidden_paths(repo)
    if hidden:
        violations.append(
            "paths hidden from the audit by git index flags set after arming: " + _hidden_path_remedy(hidden)
        )
    if head != baseline and not policy.allow_commits:
        violations.append("HEAD changed from the armed baseline; commits are not allowed")
    for path in display_paths:
        if not path_allowed(path, policy):
            violations.append(f"path outside policy: {path}")
    added_lines = 0
    deleted_lines = 0
    binary_files = 0
    working_bytes = 0
    for raw_path, counts in numstat.items():
        if counts == (None, None):
            binary_files += 1
        else:
            assert counts[0] is not None and counts[1] is not None
            added_lines += counts[0]
            deleted_lines += counts[1]
    untracked_total = 0
    for raw_path in untracked:
        path = repo / os.fsdecode(raw_path)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            size = len(os.fsencode(os.readlink(path)))
        elif stat.S_ISREG(info.st_mode):
            size = info.st_size
        else:
            size = 0
        untracked_total += size
    scan_untracked = untracked_total <= MAX_UNTRACKED_SCAN_BYTES
    if not scan_untracked:
        violations.append(
            f"untracked scan safety cap exceeded: {untracked_total} > {MAX_UNTRACKED_SCAN_BYTES}"
        )
    if scan_untracked:
        scanned_untracked = 0
        measured_untracked_bytes = 0
        for raw_path in sorted(untracked):
            remaining = MAX_UNTRACKED_SCAN_BYTES - scanned_untracked
            size, lines, binary, problem, scanned = _measure_untracked(
                repo, raw_path, scan_budget=remaining
            )
            scanned_untracked += scanned
            measured_untracked_bytes += size
            if problem:
                violations.append(f"{_display_path(raw_path)}: {problem}")
            if binary:
                binary_files += 1
            elif not problem:
                added_lines += lines
        working_bytes += measured_untracked_bytes
    else:
        working_bytes += untracked_total
    for raw_path in numstat:
        path = repo / os.fsdecode(raw_path)
        if path.exists() or path.is_symlink():
            try:
                info = os.lstat(path)
            except OSError as exc:
                violations.append(f"{_display_path(raw_path)}: cannot stat changed path: {exc}")
                continue
            if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                if raw_path not in untracked:
                    working_bytes += info.st_size
            else:
                violations.append(f"{_display_path(raw_path)}: changed path has unsupported file type")
    limits = policy.limits
    if len(display_paths) > limits.max_files:
        violations.append(f"file budget exceeded: {len(display_paths)} > {limits.max_files}")
    if added_lines > limits.max_added_lines:
        violations.append(f"added-line budget exceeded: {added_lines} > {limits.max_added_lines}")
    if deleted_lines > limits.max_deleted_lines:
        violations.append(f"deleted-line budget exceeded: {deleted_lines} > {limits.max_deleted_lines}")
    if working_bytes > limits.max_working_bytes:
        violations.append(f"working-byte budget exceeded: {working_bytes} > {limits.max_working_bytes}")
    if binary_files > limits.max_binary_files:
        violations.append(f"binary-file budget exceeded: {binary_files} > {limits.max_binary_files}")
    return AuditResult(
        not violations,
        baseline,
        head,
        head != baseline,
        tuple(display_paths),
        added_lines,
        deleted_lines,
        working_bytes,
        binary_files,
        tuple(violations),
    )


def _stored_verifier_text(data: bytes) -> str:
    clipped = data[:MAX_STORED_VERIFIER_BYTES]
    text = clipped.decode("utf-8", "replace")
    if len(data) > MAX_STORED_VERIFIER_BYTES:
        text += "\n...[truncated by Cordon]"
    return text


def run_verifiers(repo: Path, commands: Sequence[str], *, timeout: float, output_cap: int) -> tuple[VerificationResult, ...]:
    _validate_verifier_set(commands)
    results: list[VerificationResult] = []
    for command in commands:
        args = _verifier_args(command)
        outcome = run_bounded_process(args, cwd=repo, timeout=timeout, output_cap=output_cap)
        results.append(
            VerificationResult(
                command,
                outcome.returncode,
                _stored_verifier_text(outcome.stdout),
                _stored_verifier_text(outcome.stderr),
                outcome.returncode == 0 and not outcome.timed_out and not outcome.output_limited,
                outcome.timed_out,
                outcome.output_limited,
            )
        )
    return tuple(results)


def audit_with_verification(
    repo: Path,
    baseline: str,
    policy: Policy,
    verify: Sequence[str],
    *,
    verify_timeout: float = 300,
    output_cap: int = DEFAULT_OUTPUT_BYTES,
) -> AuditResult:
    audit = audit_policy(repo, baseline, policy)
    if not audit.passed or not verify:
        return audit
    verification = run_verifiers(repo, verify, timeout=verify_timeout, output_cap=output_cap)
    failures = [item for item in verification if not item.passed]
    violations = list(audit.violations)
    for item in failures:
        reason = "timeout" if item.timed_out else "output limit" if item.output_limited else f"exit {item.returncode}"
        violations.append(f"verifier failed ({reason}): {item.command}")
    return dataclasses.replace(audit, passed=not violations, violations=tuple(violations), verification=verification)


def build_claude_args(config: dict[str, Any], prompt: str) -> list[str]:
    claude = config["claude"]
    args = [
        str(claude.get("binary", "claude")),
        "-p",
        prompt,
        "--output-format",
        "json",
        "--no-session-persistence",
        "--max-turns",
        str(claude["max_turns"]),
        "--permission-mode",
        "acceptEdits",
    ]
    if claude.get("max_budget_usd") is not None:
        args.extend(["--max-budget-usd", str(claude["max_budget_usd"])])
    if claude.get("model"):
        args.extend(["--model", str(claude["model"])])
    if claude.get("effort"):
        args.extend(["--effort", str(claude["effort"])])
    return args


def _recovery_context(audit: AuditResult | None, error: str | None) -> str:
    parts: list[str] = []
    if error:
        parts.append(f"Previous attempt ended before acceptance: {error}")
    if audit:
        parts.append("Current Git-visible changed paths: " + (", ".join(audit.changed_files) if audit.changed_files else "none"))
        if audit.verification:
            failed = [item for item in audit.verification if not item.passed]
            for item in failed:
                detail = (item.stderr or item.stdout).strip()
                parts.append(f"Verifier {item.command!r} failed with exit {item.returncode}: {detail[:2000]}")
    return "\n".join(parts)


def build_prompt(config: dict[str, Any], attempt: int, prior_audit: AuditResult | None, error: str | None) -> str:
    policy = policy_from_dict(config["policy"])
    allowed = ", ".join(policy.allow)
    denied = ", ".join(policy.deny) if policy.deny else "none"
    recovery = _recovery_context(prior_audit, error)
    limits = policy.limits
    commit_rule = "Commits are allowed by this envelope." if policy.allow_commits else "Do not commit."
    return (
        "You are working inside a Cordon change envelope.\n"
        f"Task: {config['label']}\n"
        f"Allowed repository-relative paths: {allowed}\n"
        f"Denied paths: {denied}\n"
        f"Budgets: files <= {limits.max_files}; added lines <= {limits.max_added_lines}; "
        f"deleted lines <= {limits.max_deleted_lines}; working bytes <= {limits.max_working_bytes}; "
        f"binary files <= {limits.max_binary_files}.\n"
        f"{commit_rule} Do not reset, clean, stash, or modify Cordon state. "
        "Cordon will independently inspect the resulting Git worktree and run configured verification commands. "
        "Your statement that the task is complete is not proof of completion.\n"
        f"Attempt: {attempt}\n"
        + (f"Recovery context:\n{recovery}\n" if recovery else "")
    )


def _validate_claude_config(claude: dict[str, Any]) -> None:
    if not isinstance(claude.get("binary", "claude"), str) or not claude.get("binary", "claude"):
        raise PolicyError("Claude binary must be a non-empty string")
    turns = claude.get("max_turns", DEFAULT_MAX_TURNS)
    if not isinstance(turns, int) or isinstance(turns, bool) or turns < 1:
        raise PolicyError("max_turns must be a positive integer")
    timeout = claude.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise PolicyError("timeout_seconds must be a finite positive number")
    budget = claude.get("max_budget_usd")
    if budget is not None and (
        not isinstance(budget, (int, float))
        or isinstance(budget, bool)
        or not math.isfinite(budget)
        or budget <= 0
    ):
        raise PolicyError("max_budget_usd must be a finite positive number when supplied")
    if claude.get("model") is not None and (not isinstance(claude["model"], str) or not claude["model"]):
        raise PolicyError("model must be a non-empty string when supplied")
    effort = claude.get("effort")
    if effort is not None and effort not in VALID_CLAUDE_EFFORTS:
        raise PolicyError(
            "effort must be one of: " + ", ".join(sorted(VALID_CLAUDE_EFFORTS))
        )


def _arm_session_unlocked(
    root: Path,
    *,
    label: str,
    policy: Policy,
    verify: Sequence[str],
    mode: str,
    max_attempts: int,
    claude: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy.validate()
    if not isinstance(label, str) or not label.strip():
        raise PolicyError("label/task must be non-empty")
    if len(label) > MAX_LABEL_LENGTH:
        raise PolicyError(f"label/task exceeds {MAX_LABEL_LENGTH} characters")
    if mode not in {"manual", "claude"}:
        raise PolicyError("mode must be manual or claude")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
        raise PolicyError("max_attempts must be a positive integer")
    if state_dir(root).exists():
        raise StateError("Cordon is already armed; run `cordon reset` before starting a new envelope")
    if not clean_worktree(root):
        raise RepositoryError("working tree must be clean before Cordon is armed")
    hidden = index_hidden_paths(root)
    if hidden:
        raise RepositoryError(
            "these tracked paths are hidden from `git diff` by index flags and would be "
            "invisible to the audit: " + _hidden_path_remedy(hidden)
        )
    _validate_verifier_set(verify)
    claude_config = dict(claude or {})
    claude_config.setdefault("binary", "claude")
    claude_config.setdefault("max_turns", DEFAULT_MAX_TURNS)
    claude_config.setdefault("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    claude_config.setdefault("max_budget_usd", None)
    claude_config.setdefault("model", None)
    claude_config.setdefault("effort", None)
    _validate_claude_config(claude_config)
    baseline = current_head(root)
    exclude_hash = ensure_local_exclude(root)
    config = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "label": label.strip(),
        "baseline": baseline,
        "policy": policy_to_dict(policy),
        "verify": list(verify),
        "claude": claude_config,
        "created_at": utc_now(),
    }
    state = {
        "schema_version": SCHEMA_VERSION,
        "phase": "armed",
        "attempt": 0,
        "max_attempts": max_attempts,
        "config_sha256": _config_hash(config),
        "exclude_sha256": exclude_hash,
        "last_error": None,
        "last_audit": None,
        "updated_at": utc_now(),
    }
    state_dir(root).mkdir(parents=True, exist_ok=False)
    atomic_write_json(state_dir(root) / "config.json", config)
    save_state(root, state)
    return config, state


def arm_session(
    repo: Path,
    *,
    label: str,
    policy: Policy,
    verify: Sequence[str] = (),
    mode: str = "manual",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    claude: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = repository_root(repo)
    with repository_lock(root):
        return _arm_session_unlocked(
            root,
            label=label,
            policy=policy,
            verify=verify,
            mode=mode,
            max_attempts=max_attempts,
            claude=claude,
        )


def _audit_from_dict(value: Any) -> AuditResult | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise StateError("stored audit is not a JSON object")
    try:
        verification = tuple(VerificationResult(**item) for item in value.get("verification", []))
        metrics = value["metrics"]
        return AuditResult(
            bool(value["passed"]),
            str(value["baseline"]),
            str(value["current_head"]),
            bool(value["head_changed"]),
            tuple(str(item) for item in value["changed_files"]),
            int(metrics["added_lines"]),
            int(metrics["deleted_lines"]),
            int(metrics["working_bytes"]),
            int(metrics["binary_files"]),
            tuple(str(item) for item in value["violations"]),
            verification,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StateError(f"stored audit is malformed: {exc}") from exc


def _write_audit(repo: Path, audit: AuditResult) -> None:
    atomic_write_json(state_dir(repo) / "audit.json", audit.as_dict())


def check_session(repo: Path, *, verify_timeout: float = 300, output_cap: int = DEFAULT_OUTPUT_BYTES) -> AuditResult:
    root = repository_root(repo)
    with repository_lock(root):
        config, state, policy = load_session(root)
        audit = audit_with_verification(
            root,
            config["baseline"],
            policy,
            config["verify"],
            verify_timeout=verify_timeout,
            output_cap=output_cap,
        )
        _write_audit(root, audit)
        state["last_audit"] = audit.as_dict()
        state["phase"] = "accepted" if audit.passed else "rejected"
        state["last_error"] = None if audit.passed else "; ".join(audit.violations)
        state["updated_at"] = utc_now()
        save_state(root, state)
        return audit


def _run_agent_attempt(
    root: Path,
    config: dict[str, Any],
    state: dict[str, Any],
    policy: Policy,
    *,
    output_cap: int,
) -> tuple[ProcessResult, AuditResult]:
    if state["attempt"] >= state["max_attempts"]:
        raise StateError(f"attempt limit reached ({state['max_attempts']})")
    previous = _audit_from_dict(state["last_audit"])
    state["attempt"] += 1
    state["phase"] = "running"
    state["updated_at"] = utc_now()
    save_state(root, state)
    prompt = build_prompt(config, state["attempt"], previous, state["last_error"])
    args = build_claude_args(config, prompt)
    timeout = float(config["claude"]["timeout_seconds"])
    try:
        result = run_bounded_process(args, cwd=root, timeout=timeout, output_cap=output_cap)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            state["phase"] = "interrupted"
            state["last_error"] = type(exc).__name__
            state["updated_at"] = utc_now()
            save_state(root, state)
        raise
    verify_local_exclude(root, state["exclude_sha256"])
    if result.timed_out:
        state["phase"] = "engine_error"
        state["last_error"] = "Claude Code timed out"
    elif result.output_limited:
        state["phase"] = "engine_error"
        state["last_error"] = f"Claude Code exceeded the {output_cap}-byte output limit"
    elif result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        state["phase"] = "engine_error"
        state["last_error"] = f"Claude Code exited {result.returncode}: {detail[:2000]}"
    else:
        state["phase"] = "agent_finished"
        state["last_error"] = None
    audit = audit_with_verification(root, config["baseline"], policy, config["verify"], output_cap=output_cap)
    if result.returncode == 0 and not result.timed_out and not result.output_limited:
        state["phase"] = "accepted" if audit.passed else "rejected"
        if not audit.passed:
            state["last_error"] = "; ".join(audit.violations)
    state["last_audit"] = audit.as_dict()
    state["updated_at"] = utc_now()
    _write_audit(root, audit)
    save_state(root, state)
    return result, audit


def run_claude_session(
    repo: Path,
    *,
    label: str,
    policy: Policy,
    verify: Sequence[str] = (),
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    claude: dict[str, Any] | None = None,
    output_cap: int = DEFAULT_OUTPUT_BYTES,
) -> tuple[ProcessResult, AuditResult]:
    root = repository_root(repo)
    with repository_lock(root):
        config, state = _arm_session_unlocked(
            root,
            label=label,
            policy=policy,
            verify=verify,
            mode="claude",
            max_attempts=max_attempts,
            claude=claude,
        )
        return _run_agent_attempt(root, config, state, policy, output_cap=output_cap)


def resume_claude_session(repo: Path, *, output_cap: int = DEFAULT_OUTPUT_BYTES) -> tuple[ProcessResult, AuditResult]:
    root = repository_root(repo)
    with repository_lock(root):
        config, state, policy = load_session(root)
        if config["mode"] != "claude":
            raise StateError("manual envelopes cannot be resumed with Claude")
        if state["phase"] == "accepted":
            raise StateError("Cordon envelope is already accepted")
        preflight = audit_policy(root, config["baseline"], policy)
        if not preflight.passed:
            state["last_audit"] = preflight.as_dict()
            state["last_error"] = "; ".join(preflight.violations)
            state["phase"] = "rejected"
            state["updated_at"] = utc_now()
            _write_audit(root, preflight)
            save_state(root, state)
            raise PolicyError("current partial changes violate the Cordon envelope; refusing to resume")
        return _run_agent_attempt(root, config, state, policy, output_cap=output_cap)


def session_status(repo: Path) -> dict[str, Any]:
    root = repository_root(repo)
    config, state, _policy = load_session(root)
    return {
        "mode": config["mode"],
        "label": config["label"],
        "baseline": config["baseline"],
        "phase": state["phase"],
        "attempt": state["attempt"],
        "max_attempts": state["max_attempts"],
        "last_error": state["last_error"],
        "last_audit": state["last_audit"],
    }


def reset_session(repo: Path) -> None:
    root = repository_root(repo)
    folder = state_dir(root)
    if not folder.exists():
        return
    with repository_lock(root):
        tombstone = folder.with_name(f"{folder.name}.remove-{os.getpid()}-{time.time_ns()}")
        os.replace(folder, tombstone)
        _fsync_directory(root)
        shutil.rmtree(tombstone)
        _fsync_directory(root)
