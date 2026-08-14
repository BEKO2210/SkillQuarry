from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import glob
import re
from typing import Iterable


_HASH_CALL_RE = re.compile(r"hashFiles\s*\((.*?)\)", re.S)
_QUOTED_RE = re.compile(r"(['\"])(.*?)\1", re.S)
_STEP_RE = re.compile(r"^(\s*)-\s+", re.M)
_CACHE_USE_RE = re.compile(r"\buses:\s*actions/cache@", re.I)
_RUN_RE = re.compile(r"^\s*run:\s*(.*)$")
_SCRIPT_INVOKE_RE = re.compile(
    r"(?:^|[;&|]\s*|\b)(?:bash|sh|python3?|source|\.)\s+['\"]?([A-Za-z0-9_./-]+\.(?:sh|py))",
    re.M,
)
_SOURCE_BASENAME_RE = re.compile(r"\b(?:source|\.)\b[^\n]*?/([A-Za-z0-9_.-]+\.sh)\b")
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_CD_RE = re.compile(r"^\s*cd\s+['\"]?([^'\"\s]+)['\"]?\s*$")
_SENTINEL_IF_RE = re.compile(r"^\s*if\s+\[\s*!\s+-f\s+['\"]?([^'\"\s\]]+)['\"]?\s*\]\s*;?\s*then\s*$")
_TOUCH_RE = re.compile(r"\btouch\s+['\"]?([^'\"\s;]+)")
_REPO_INPUT_RE = re.compile(
    r"(?:\$REPO|\$\{REPO\}|\$GITHUB_WORKSPACE|\$\{GITHUB_WORKSPACE\})/([A-Za-z0-9_./*?{}\[\]-]+)"
)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    workflow: str
    line: int
    cache_name: str
    message: str
    evidence: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CacheStep:
    workflow: Path
    start: int
    end: int
    job_end: int
    name: str
    key: str
    paths: tuple[str, ...]

    @property
    def line(self) -> int:
        return self.start + 1


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _collect_block_scalar(lines: list[str], index: int, value: str) -> tuple[str, int]:
    if value not in {"|", ">", "|-", ">-", "|+", ">+"}:
        return value.strip().strip("'\""), index
    base = _indent(lines[index])
    out: list[str] = []
    j = index + 1
    while j < len(lines):
        raw = lines[j]
        if raw.strip() and _indent(raw) <= base:
            break
        out.append(raw.strip())
        j += 1
    sep = "\n" if value.startswith("|") else " "
    return sep.join(part for part in out if part), j - 1


def _field(lines: list[str], start: int, end: int, key: str) -> str:
    rx = re.compile(rf"^\s*(?:-\s+)?{re.escape(key)}:\s*(.*)$")
    for i in range(start, end):
        m = rx.match(lines[i])
        if m:
            value, _ = _collect_block_scalar(lines, i, m.group(1).strip())
            return value
    return ""


def _step_bounds(lines: list[str]) -> list[tuple[int, int, int]]:
    starts: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)-\s+", line)
        if m:
            starts.append((i, len(m.group(1))))
    out: list[tuple[int, int, int]] = []
    for pos, (start, ind) in enumerate(starts):
        end = len(lines)
        for later_start, later_ind in starts[pos + 1 :]:
            if later_ind == ind:
                end = later_start
                break
            if later_ind < ind:
                end = later_start
                break
        job_end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].strip() and _indent(lines[j]) < ind:
                job_end = j
                break
        out.append((start, end, job_end))
    return out


def parse_cache_steps(workflow: Path) -> list[CacheStep]:
    lines = workflow.read_text(encoding="utf-8").splitlines()
    steps: list[CacheStep] = []
    for start, end, job_end in _step_bounds(lines):
        block = "\n".join(lines[start:end])
        if not _CACHE_USE_RE.search(block):
            continue
        key = _field(lines, start, end, "key")
        path_value = _field(lines, start, end, "path")
        paths = tuple(p.strip() for p in path_value.splitlines() if p.strip())
        name = _field(lines, start, end, "name") or "actions/cache"
        steps.append(CacheStep(workflow, start, end, job_end, name, key, paths))
    return steps


def extract_hash_calls(key: str) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    for m in _HASH_CALL_RE.finditer(key):
        args = tuple(match[1] for match in _QUOTED_RE.findall(m.group(1)))
        if args:
            calls.append(args)
    return calls


def _expand_glob(root: Path, pattern: str) -> set[str]:
    pattern = pattern.strip()
    if not pattern or "${{" in pattern:
        return set()
    negated = pattern.startswith("!")
    if negated:
        pattern = pattern[1:]
    pattern = pattern.lstrip("/").removeprefix("./")
    matches: set[str] = set()
    for value in glob.glob(str(root / pattern), recursive=True):
        p = Path(value)
        if p.is_file():
            try:
                matches.add(p.relative_to(root).as_posix())
            except ValueError:
                pass
    return matches


def evaluate_hash_call(root: Path, patterns: Iterable[str]) -> set[str]:
    selected: set[str] = set()
    for pattern in patterns:
        if pattern.startswith("!"):
            selected -= _expand_glob(root, pattern)
        else:
            selected |= _expand_glob(root, pattern)
    return selected


def _normalize_symbolic(value: str, variables: dict[str, str]) -> str:
    value = value.strip().strip("'\"")
    value = re.sub(r"\$\{\{\s*env\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", r"$\1", value)
    value = re.sub(r"\$\{\{\s*github\.workspace\s*\}\}", "<repo>", value, flags=re.I)
    value = value.replace("${GITHUB_WORKSPACE}", "<repo>").replace("$GITHUB_WORKSPACE", "<repo>")
    value = value.replace("${REPO}", "<repo>").replace("$REPO", "<repo>")
    for _ in range(8):
        old = value
        for name, replacement in variables.items():
            value = value.replace("${" + name + "}", replacement).replace("$" + name, replacement)
        if value == old:
            break
    value = re.sub(r"/+", "/", value)
    return value.rstrip("/") or "/"


def _join_symbolic(base: str, child: str, variables: dict[str, str]) -> str:
    child = _normalize_symbolic(child, variables)
    if child.startswith(("/", "$", "<repo>")):
        return child
    return _normalize_symbolic(base.rstrip("/") + "/" + child, variables)


def _is_under(path: str, parent: str) -> bool:
    p = path.rstrip("/")
    base = parent.rstrip("/")
    return p == base or p.startswith(base + "/")


def _read_script_closure(root: Path, script: Path) -> list[Path]:
    pending = [script]
    seen: set[Path] = set()
    ordered: list[Path] = []
    while pending:
        current = pending.pop(0)
        current = current.resolve()
        if current in seen or not current.is_file():
            continue
        try:
            current.relative_to(root.resolve())
        except ValueError:
            continue
        seen.add(current)
        ordered.append(current)
        text = current.read_text(encoding="utf-8")
        for basename in _SOURCE_BASENAME_RE.findall(text):
            candidate = current.parent / basename
            if candidate.is_file():
                pending.append(candidate)
        for invoked in _SCRIPT_INVOKE_RE.findall(text):
            candidate = (current.parent / invoked).resolve() if not invoked.startswith("/") else Path(invoked)
            if candidate.is_file():
                pending.append(candidate)
    return ordered


def _script_variables(root: Path, scripts: list[Path]) -> dict[str, str]:
    variables = {"REPO": "<repo>", "GITHUB_WORKSPACE": "<repo>"}
    for script in reversed(scripts):
        for raw in script.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            m = _ASSIGN_RE.match(line)
            if not m:
                continue
            name, value = m.groups()
            if "BASH_SOURCE" in value and "/.." in value and "pwd" in value:
                variables[name] = "<repo>"
                continue
            default = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]+)\}", value)
            if default and default.group(1) == name:
                variables.setdefault(name, "$" + name)
                continue
            if "$(" in value or "`" in value:
                continue
            variables[name] = _normalize_symbolic(value, variables)
    return variables


def _run_commands(lines: list[str], start: int, end: int) -> list[str]:
    commands: list[str] = []
    i = start
    while i < end:
        m = _RUN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        value, last = _collect_block_scalar(lines, i, m.group(1).strip())
        commands.append(value)
        i = last + 1
    return commands


def _direct_scripts(root: Path, commands: Iterable[str]) -> list[Path]:
    scripts: list[Path] = []
    seen: set[Path] = set()
    for command in commands:
        for token in _SCRIPT_INVOKE_RE.findall(command):
            candidate = (root / token).resolve()
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                scripts.append(candidate)
    return scripts


def _sentinel_findings(root: Path, cache: CacheStep, key_files: set[str]) -> list[Finding]:
    lines = cache.workflow.read_text(encoding="utf-8").splitlines()
    commands = _run_commands(lines, cache.end, cache.job_end)
    findings: list[Finding] = []
    cache_paths_raw = [_normalize_symbolic(p, {}) for p in cache.paths]
    for direct in _direct_scripts(root, commands):
        scripts = _read_script_closure(root, direct)
        variables = _script_variables(root, scripts)
        cache_paths = [_normalize_symbolic(p, variables) for p in cache_paths_raw]
        for script in scripts:
            cwd = "<repo>"
            script_lines = script.read_text(encoding="utf-8").splitlines()
            i = 0
            while i < len(script_lines):
                stripped = script_lines[i].strip()
                cd = _CD_RE.match(stripped)
                if cd:
                    cwd = _join_symbolic(cwd, cd.group(1), variables)
                    i += 1
                    continue
                gate = _SENTINEL_IF_RE.match(stripped)
                if not gate:
                    i += 1
                    continue
                depth = 1
                block: list[str] = []
                j = i + 1
                while j < len(script_lines) and depth:
                    token = script_lines[j].strip()
                    if token.startswith("if ") and token.endswith("then"):
                        depth += 1
                    elif token == "fi" or token.startswith("fi "):
                        depth -= 1
                        if depth == 0:
                            break
                    if depth:
                        block.append(script_lines[j])
                    j += 1
                marker = gate.group(1)
                touched = any(_normalize_symbolic(m.group(1), variables) == _normalize_symbolic(marker, variables)
                              for raw in block for m in [_TOUCH_RE.search(raw)] if m)
                if not touched:
                    i = max(j + 1, i + 1)
                    continue
                marker_path = _join_symbolic(cwd, marker, variables)
                if not any(_is_under(marker_path, cp) for cp in cache_paths):
                    i = max(j + 1, i + 1)
                    continue
                patterns: set[str] = set()
                for raw in block:
                    patterns.update(_REPO_INPUT_RE.findall(raw))
                for pattern in sorted(patterns):
                    input_files = _expand_glob(root, pattern)
                    missing = sorted(input_files - key_files)
                    if not missing:
                        continue
                    findings.append(Finding(
                        code="SENTINEL_UNKEYED_INPUT",
                        severity="HIGH",
                        workflow=cache.workflow.relative_to(root).as_posix(),
                        line=cache.line,
                        cache_name=cache.name,
                        message=(
                            f"cached sentinel {marker_path} can suppress work that reads {pattern}, "
                            "but the primary cache key does not cover those files"
                        ),
                        evidence={
                            "script": script.relative_to(root).as_posix(),
                            "sentinel": marker_path,
                            "cache_paths": cache_paths,
                            "input_pattern": pattern,
                            "unkeyed_files": missing,
                        },
                    ))
                i = max(j + 1, i + 1)
    return findings


def scan_repository(root: Path | str) -> list[Finding]:
    root = Path(root).resolve()
    workflows = sorted((root / ".github" / "workflows").glob("*.yml")) + sorted(
        (root / ".github" / "workflows").glob("*.yaml")
    )
    findings: list[Finding] = []
    for workflow in workflows:
        for cache in parse_cache_steps(workflow):
            calls = extract_hash_calls(cache.key)
            key_files: set[str] = set()
            for patterns in calls:
                resolved = evaluate_hash_call(root, patterns)
                key_files |= resolved
                if not resolved:
                    findings.append(Finding(
                        code="EMPTY_HASH_INPUT",
                        severity="HIGH",
                        workflow=workflow.relative_to(root).as_posix(),
                        line=cache.line,
                        cache_name=cache.name,
                        message=(
                            f"hashFiles({', '.join(repr(p) for p in patterns)}) resolves to zero files; "
                            "this hash contribution is invariant to repository changes"
                        ),
                        evidence={"patterns": list(patterns), "matched_files": []},
                    ))
            findings.extend(_sentinel_findings(root, cache, key_files))
    unique: dict[tuple[object, ...], Finding] = {}
    for f in findings:
        key = (f.code, f.workflow, f.line, str(f.evidence))
        unique[key] = f
    return sorted(unique.values(), key=lambda f: (f.workflow, f.line, f.code))
