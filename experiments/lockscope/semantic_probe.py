#!/usr/bin/env python3
"""Compiler-adjacent LockScope prototype used only by the preregistered pro test.

Lock acquisition candidates are discovered syntactically, but lock *identity* and
lock *family* are resolved through rust-analyzer. In particular, names such as
`Mutex`, aliases, and user-defined `lock()` methods are not trusted.

This is still an experiment. It is not a full Rust data-flow engine: explicit
moves of a guard into another owner and arbitrary procedural-macro expansions
remain outside its production claim. The pro fixture exercises the supported
macro expansion path directly.
"""
from __future__ import annotations

import bisect
import json
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LockSite:
    function: str
    line: int
    guard: str
    lock_expr: str
    lock_key: str
    mode: str
    family: str
    origin: str
    type_text: str
    method_definition: str
    scope_end_line: int
    explicit_drop_line: int | None
    last_textual_use_line: int
    awaits_while_live: int
    span_lines: int


@dataclass(frozen=True)
class Analysis:
    lock_sites: list[LockSite]
    cycles: list[list[str]]
    findings: list[dict[str, object]]


class LspError(RuntimeError):
    pass


class LspClient:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.proc = subprocess.Popen(
            ["rust-analyzer"],
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self._next_id = 1
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._opened: set[str] = set()
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()
        result = self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self.root.as_uri(),
                "capabilities": {
                    "workspace": {"configuration": False},
                    "textDocument": {
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                        "foldingRange": {"lineFoldingOnly": True},
                    },
                },
                "initializationOptions": {
                    "checkOnSave": False,
                    "cargo": {"buildScripts": {"enable": False}},
                    "procMacro": {"enable": True},
                },
            },
            timeout=30,
        )
        if result is None:
            raise LspError("rust-analyzer initialize returned no result")
        self.notify("initialized", {})

    def _reader_loop(self) -> None:
        assert self.proc.stdout is not None
        stream = self.proc.stdout
        try:
            while True:
                headers: dict[str, str] = {}
                while True:
                    line = stream.readline()
                    if not line:
                        return
                    if line in (b"\r\n", b"\n"):
                        break
                    decoded = line.decode("ascii", errors="replace").strip()
                    if ":" in decoded:
                        key, value = decoded.split(":", 1)
                        headers[key.lower()] = value.strip()
                length = int(headers.get("content-length", "0"))
                if length <= 0:
                    continue
                payload = stream.read(length)
                if not payload:
                    return
                self._messages.put(json.loads(payload.decode("utf-8")))
        except Exception as exc:  # pragma: no cover - diagnostic path
            self._messages.put({"__reader_error__": repr(exc)})

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.proc.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _answer_server_request(self, msg: dict[str, Any]) -> None:
        method = str(msg.get("method", ""))
        params = msg.get("params") or {}
        if method == "workspace/configuration":
            items = params.get("items") or []
            result: Any = [None for _ in items]
        elif method in {"client/registerCapability", "window/workDoneProgress/create"}:
            result = None
        else:
            result = None
        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def request(self, method: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"LSP request timed out: {method}")
            try:
                msg = self._messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"LSP request timed out: {method}") from exc
            if "__reader_error__" in msg:
                raise LspError(str(msg["__reader_error__"]))
            if "id" in msg and "method" in msg:
                self._answer_server_request(msg)
                continue
            if msg.get("id") != request_id:
                # Notifications and responses to server-generated bookkeeping are
                # irrelevant because requests are strictly sequential here.
                continue
            if "error" in msg:
                raise LspError(f"{method}: {msg['error']}")
            return msg.get("result")

    def open_file(self, path: Path) -> str:
        path = path.resolve()
        uri = path.as_uri()
        if uri not in self._opened:
            text = path.read_text("utf-8")
            self.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "rust",
                        "version": 1,
                        "text": text,
                    }
                },
            )
            self._opened.add(uri)
        return uri

    def close(self) -> None:
        try:
            self.request("shutdown", {}, timeout=3)
        except Exception:
            pass
        try:
            self.notify("exit", {})
        except Exception:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=3)

    def __enter__(self) -> "LspClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


ACQUIRE = re.compile(
    r"\blet\s+(?:mut\s+)?(?P<guard>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<expr>[^;]{1,500}?)\."
    r"(?P<op>lock_owned|read_owned|write_owned|lock|read|write)\s*\(\s*\)"
    r"(?P<tail>[^;]{0,160});",
    re.MULTILINE | re.DOTALL,
)
MACRO_CALL = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)!\s*\((?P<args>[^;]{1,300}?)\)\s*;",
    re.MULTILINE | re.DOTALL,
)
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DROP_TEMPLATE = r"\bdrop\s*\(\s*{guard}\s*\)"
SKIP_LOCK_EXPR_IDENTIFIERS = {
    "self",
    "Arc",
    "Rc",
    "Box",
    "Pin",
    "clone",
    "as_ref",
    "as_mut",
    "borrow",
    "borrow_mut",
    "get_ref",
}


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return starts


def _offset_to_position(starts: list[int], offset: int) -> tuple[int, int]:
    line = bisect.bisect_right(starts, offset) - 1
    return line, offset - starts[line]


def _line_end_offset(text: str, starts: list[int], line: int) -> int:
    if line + 1 < len(starts):
        return starts[line + 1] - 1
    return len(text)


def _contains(rng: dict[str, Any], line: int, character: int = 0) -> bool:
    start = rng.get("start") or {}
    end = rng.get("end") or {}
    sl, sc = int(start.get("line", -1)), int(start.get("character", 0))
    el, ec = int(end.get("line", -1)), int(end.get("character", 0))
    if line < sl or line > el:
        return False
    if line == sl and character < sc:
        return False
    if line == el and character > ec:
        return False
    return True


def _flatten_function_symbols(items: Any) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = int(item.get("kind", 0) or 0)
        rng = item.get("range") or (item.get("location") or {}).get("range")
        if kind in {6, 12} and isinstance(rng, dict):  # Method / Function
            out.append((str(item.get("name", "<unknown>")), rng))
        out.extend(_flatten_function_symbols(item.get("children")))
    return out


def _hover_text(result: Any) -> str:
    if not result:
        return ""
    contents = result.get("contents") if isinstance(result, dict) else result
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return str(contents.get("value", ""))
    if isinstance(contents, list):
        parts: list[str] = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("value", "")))
        return "\n".join(parts)
    return str(contents)


def _location(result: Any) -> tuple[str, dict[str, Any]] | None:
    if not result:
        return None
    item = result[0] if isinstance(result, list) else result
    if not isinstance(item, dict):
        return None
    uri = item.get("uri") or item.get("targetUri")
    rng = item.get("range") or item.get("targetSelectionRange") or item.get("targetRange")
    if isinstance(uri, str) and isinstance(rng, dict):
        return uri, rng
    return None


def _definition_key(location: tuple[str, dict[str, Any]] | None, fallback: str) -> str:
    if not location:
        return fallback
    uri, rng = location
    start = rng.get("start") or {}
    return f"{uri}#{int(start.get('line', 0))}:{int(start.get('character', 0))}"


def _definition_uri(location: tuple[str, dict[str, Any]] | None) -> str:
    return location[0] if location else ""


def _classify_lock(hover: str, method_definition: str, op: str) -> tuple[str, str] | None:
    evidence = f"{hover}\n{method_definition}".lower().replace("\\", "/")
    is_tokio = (
        "tokio::sync" in evidence
        or "/tokio-/" in evidence
        or "/tokio/src/sync/" in evidence
    )
    is_parking = "parking_lot" in evidence or "/lock_api-" in evidence
    is_std = "std::sync" in evidence or "/library/std/src/sync/" in evidence
    if is_tokio:
        family = "async"
    elif is_parking or is_std:
        family = "sync"
    else:
        return None
    mode = "read" if op in {"read", "read_owned"} else "exclusive"
    return family, mode


def _pick_lock_identifier(expr: str) -> re.Match[str] | None:
    matches = list(IDENT.finditer(expr))
    useful = [m for m in matches if m.group(0) not in SKIP_LOCK_EXPR_IDENTIFIERS]
    if useful:
        return useful[-1]
    return matches[-1] if matches else None


def _normalize_expr(expr: str) -> str:
    return re.sub(r"\s+", "", expr.strip())


def _function_for_line(
    symbols: list[tuple[str, dict[str, Any]]], line: int, character: int
) -> tuple[str, dict[str, Any] | None]:
    matches = [
        (name, rng)
        for name, rng in symbols
        if _contains(rng, line, character)
    ]
    if not matches:
        return "<unknown>", None
    matches.sort(
        key=lambda item: (
            int((item[1].get("end") or {}).get("line", 10**9))
            - int((item[1].get("start") or {}).get("line", 0)),
            len(item[0]),
        )
    )
    return matches[0]


def _scope_end_line(
    folds: Any, function_range: dict[str, Any] | None, line: int
) -> int:
    candidates: list[tuple[int, int]] = []
    if isinstance(folds, list):
        for item in folds:
            if not isinstance(item, dict):
                continue
            start = int(item.get("startLine", -1))
            end = int(item.get("endLine", -1))
            if start <= line < end:
                candidates.append((end - start, end))
    if candidates:
        candidates.sort()
        return candidates[0][1]
    if function_range:
        return int((function_range.get("end") or {}).get("line", line))
    return line


def _guard_lifetime(
    text: str,
    starts: list[int],
    guard: str,
    declaration_end: int,
    scope_end_line: int,
) -> tuple[int, int | None, int, int]:
    scope_end_offset = _line_end_offset(text, starts, scope_end_line)
    tail = text[declaration_end:scope_end_offset]
    drop_re = re.compile(DROP_TEMPLATE.format(guard=re.escape(guard)))
    drop = drop_re.search(tail)
    if drop:
        live_end_offset = declaration_end + drop.end()
        drop_line, _ = _offset_to_position(starts, declaration_end + drop.start())
        explicit_drop_line: int | None = drop_line + 1
    else:
        live_end_offset = scope_end_offset
        explicit_drop_line = None

    word = re.compile(r"\b" + re.escape(guard) + r"\b")
    last_use_offset = declaration_end
    for match in word.finditer(text, declaration_end, live_end_offset):
        last_use_offset = match.start()
    last_use_line, _ = _offset_to_position(starts, last_use_offset)
    live_end_line, _ = _offset_to_position(starts, max(declaration_end, live_end_offset - 1))
    awaits = len(re.findall(r"\.await\b", text[declaration_end:live_end_offset]))
    return live_end_line + 1, explicit_drop_line, last_use_line + 1, awaits


def _find_cycles(sites: list[LockSite]) -> list[list[str]]:
    edges: dict[str, set[str]] = {}
    display: dict[str, str] = {}
    by_function: dict[str, list[LockSite]] = {}
    for site in sites:
        display.setdefault(site.lock_key, site.lock_expr)
        by_function.setdefault(site.function, []).append(site)
    for function_sites in by_function.values():
        ordered = sorted(function_sites, key=lambda s: (s.line, s.span_lines))
        for outer in ordered:
            for inner in ordered:
                if inner.line <= outer.line:
                    continue
                if inner.line <= outer.scope_end_line:
                    if outer.explicit_drop_line is not None and inner.line >= outer.explicit_drop_line:
                        continue
                    edges.setdefault(outer.lock_key, set()).add(inner.lock_key)

    nodes = set(edges)
    for targets in edges.values():
        nodes.update(targets)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(edges.get(node, set())):
            if nxt not in indices:
                visit(nxt)
                lowlink[node] = min(lowlink[node], lowlink[nxt])
            elif nxt in on_stack:
                lowlink[node] = min(lowlink[node], indices[nxt])
        if lowlink[node] == indices[node]:
            comp: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                comp.append(member)
                if member == node:
                    break
            if len(comp) > 1 or (len(comp) == 1 and comp[0] in edges.get(comp[0], set())):
                components.append(comp)

    for node in sorted(nodes):
        if node not in indices:
            visit(node)

    out = [sorted(display.get(key, key) for key in comp) for comp in components]
    out.sort()
    return out


class SemanticLockScope:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lsp = LspClient(self.root)

    def close(self) -> None:
        self.lsp.close()

    def __enter__(self) -> "SemanticLockScope":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _hover_with_retry(self, uri: str, line: int, character: int, timeout: float = 30.0) -> str:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            try:
                result = self.lsp.request(
                    "textDocument/hover",
                    {
                        "textDocument": {"uri": uri},
                        "position": {"line": line, "character": character},
                    },
                    timeout=5,
                )
                last = _hover_text(result)
                if last:
                    return last
            except (TimeoutError, LspError):
                pass
            time.sleep(0.25)
        return last

    def _definition(self, uri: str, line: int, character: int) -> tuple[str, dict[str, Any]] | None:
        try:
            result = self.lsp.request(
                "textDocument/definition",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
                timeout=8,
            )
        except (TimeoutError, LspError):
            return None
        return _location(result)

    def analyze(self, path: Path) -> Analysis:
        path = path.resolve()
        text = path.read_text("utf-8")
        starts = _line_starts(text)
        uri = self.lsp.open_file(path)

        normal_matches = list(ACQUIRE.finditer(text))
        if normal_matches:
            first = normal_matches[0]
            line, col = _offset_to_position(starts, first.start("guard"))
            self._hover_with_retry(uri, line, col, timeout=30)

        try:
            symbols_result = self.lsp.request(
                "textDocument/documentSymbol", {"textDocument": {"uri": uri}}, timeout=10
            )
        except Exception:
            symbols_result = []
        symbols = _flatten_function_symbols(symbols_result)
        try:
            folds = self.lsp.request(
                "textDocument/foldingRange", {"textDocument": {"uri": uri}}, timeout=10
            )
        except Exception:
            folds = []

        sites: list[LockSite] = []
        seen_origins: set[tuple[int, str]] = set()

        for match in normal_matches:
            guard_line, guard_col = _offset_to_position(starts, match.start("guard"))
            op_line, op_col = _offset_to_position(starts, match.start("op"))
            hover = self._hover_with_retry(uri, guard_line, guard_col, timeout=6)
            method_loc = self._definition(uri, op_line, op_col)
            method_uri = _definition_uri(method_loc)
            classified = _classify_lock(hover, method_uri, match.group("op"))
            if classified is None:
                continue
            family, mode = classified
            function, function_range = _function_for_line(symbols, guard_line, guard_col)
            scope_end = _scope_end_line(folds, function_range, guard_line)
            live_end, explicit_drop, last_use, awaits = _guard_lifetime(
                text,
                starts,
                match.group("guard"),
                match.end(),
                scope_end,
            )
            expr = match.group("expr")
            expr_ident = _pick_lock_identifier(expr)
            lock_loc = None
            if expr_ident:
                absolute = match.start("expr") + expr_ident.start()
                lock_line, lock_col = _offset_to_position(starts, absolute)
                lock_loc = self._definition(uri, lock_line, lock_col)
            norm_expr = _normalize_expr(expr)
            lock_key = _definition_key(lock_loc, f"{uri}#expr:{norm_expr}")
            site = LockSite(
                function=function,
                line=guard_line + 1,
                guard=match.group("guard"),
                lock_expr=norm_expr,
                lock_key=lock_key,
                mode=mode,
                family=family,
                origin="source",
                type_text=hover,
                method_definition=method_uri,
                scope_end_line=live_end,
                explicit_drop_line=explicit_drop,
                last_textual_use_line=last_use,
                awaits_while_live=awaits,
                span_lines=max(0, live_end - (guard_line + 1)),
            )
            sites.append(site)
            seen_origins.add((guard_line + 1, site.guard))

        # Simple declarative macro support. rust-analyzer performs expansion; the
        # source invocation provides the lock expression position for type and
        # identity resolution. This intentionally does not pretend to handle an
        # arbitrary procedural macro.
        for macro in MACRO_CALL.finditer(text):
            invocation_line, invocation_col = _offset_to_position(starts, macro.start("name"))
            try:
                expanded = self.lsp.request(
                    "rust-analyzer/expandMacro",
                    {
                        "textDocument": {"uri": uri},
                        "position": {"line": invocation_line, "character": invocation_col},
                    },
                    timeout=8,
                )
            except Exception:
                continue
            if isinstance(expanded, dict):
                expansion = str(expanded.get("expansion", ""))
            else:
                expansion = str(expanded or "")
            exp_match = ACQUIRE.search(expansion)
            if not exp_match:
                continue
            args_text = macro.group("args")
            args = [part.strip() for part in args_text.split(",") if part.strip()]
            if not args:
                continue
            lock_arg = args[0]
            lock_arg_ident = _pick_lock_identifier(lock_arg)
            if not lock_arg_ident:
                continue
            arg_rel = args_text.find(lock_arg)
            ident_rel = lock_arg_ident.start()
            absolute = macro.start("args") + arg_rel + ident_rel
            arg_line, arg_col = _offset_to_position(starts, absolute)
            hover = self._hover_with_retry(uri, arg_line, arg_col, timeout=6)
            classified = _classify_lock(hover, "", exp_match.group("op"))
            if classified is None:
                continue
            family, mode = classified
            guard = exp_match.group("guard")
            if (invocation_line + 1, guard) in seen_origins:
                continue
            function, function_range = _function_for_line(symbols, invocation_line, invocation_col)
            scope_end = _scope_end_line(folds, function_range, invocation_line)
            live_end, explicit_drop, last_use, awaits = _guard_lifetime(
                text,
                starts,
                guard,
                macro.end(),
                scope_end,
            )
            lock_loc = self._definition(uri, arg_line, arg_col)
            norm_expr = _normalize_expr(lock_arg)
            lock_key = _definition_key(lock_loc, f"{uri}#expr:{norm_expr}")
            sites.append(
                LockSite(
                    function=function,
                    line=invocation_line + 1,
                    guard=guard,
                    lock_expr=norm_expr,
                    lock_key=lock_key,
                    mode=mode,
                    family=family,
                    origin="macro",
                    type_text=hover,
                    method_definition="rust-analyzer/expandMacro",
                    scope_end_line=live_end,
                    explicit_drop_line=explicit_drop,
                    last_textual_use_line=last_use,
                    awaits_while_live=awaits,
                    span_lines=max(0, live_end - (invocation_line + 1)),
                )
            )

        sites.sort(key=lambda s: (s.function, s.line, s.guard, s.origin))
        cycles = _find_cycles(sites)
        findings: list[dict[str, object]] = []
        for site in sites:
            if site.awaits_while_live:
                if site.family == "sync":
                    kind, severity = "sync_lock_across_await", "critical"
                elif site.mode == "exclusive":
                    kind, severity = "exclusive_lock_across_await", "high"
                else:
                    kind, severity = "read_lock_across_await", "medium"
                findings.append(
                    {
                        "kind": kind,
                        "severity": severity,
                        "function": site.function,
                        "line": site.line,
                        "lock": site.lock_expr,
                        "awaits": site.awaits_while_live,
                        "span_lines": site.span_lines,
                        "origin": site.origin,
                    }
                )
            if site.mode == "exclusive" and site.span_lines >= 40:
                findings.append(
                    {
                        "kind": "large_exclusive_critical_section",
                        "severity": "high",
                        "function": site.function,
                        "line": site.line,
                        "lock": site.lock_expr,
                        "span_lines": site.span_lines,
                        "origin": site.origin,
                    }
                )
        for cycle in cycles:
            findings.append(
                {
                    "kind": "lock_order_cycle",
                    "severity": "critical",
                    "cycle": cycle,
                }
            )
        findings.sort(key=lambda f: json.dumps(f, sort_keys=True))
        return Analysis(lock_sites=sites, cycles=cycles, findings=findings)


def as_jsonable(analysis: Analysis, include_resolution: bool = True) -> dict[str, object]:
    if include_resolution:
        sites: list[dict[str, object]] = [asdict(site) for site in analysis.lock_sites]
    else:
        sites = []
        for site in analysis.lock_sites:
            row = asdict(site)
            row.pop("type_text", None)
            row.pop("method_definition", None)
            row.pop("lock_key", None)
            sites.append(row)
    return {
        "lock_sites": sites,
        "cycles": analysis.cycles,
        "findings": analysis.findings,
    }


def finding_kinds(analysis: Analysis, function: str) -> set[str]:
    return {
        str(item.get("kind"))
        for item in analysis.findings
        if item.get("function") == function
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("file")
    args = parser.parse_args()
    root = Path(args.root)
    path = Path(args.file)
    if not path.is_absolute():
        path = root / path
    with SemanticLockScope(root) as analyzer:
        result = analyzer.analyze(path)
    print(json.dumps(as_jsonable(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
