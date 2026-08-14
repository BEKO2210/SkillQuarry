"""A small rust-analyzer client.

Only the requests LockScope needs are implemented: hover, definition, type
definition, document symbols and macro expansion. The server is started once per
workspace and kept alive, because a restart costs an entire re-index — the most
expensive thing this skill can do.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

# The server is asked to answer without a build: LockScope resolves types, it
# does not need diagnostics, and `cargo check` on every keystroke would dominate
# the runtime. Proc macros stay enabled because a macro can hide an acquisition.
INITIALIZATION_OPTIONS = {
    "checkOnSave": False,
    "cargo": {"buildScripts": {"enable": False}},
    "procMacro": {"enable": True},
}


class LspError(RuntimeError):
    """The language server refused, died, or answered with an error."""


class LspClient:
    def __init__(self, root: Path, command: str = "rust-analyzer", initialize_timeout: float = 60.0):
        self.root = root.resolve()
        try:
            self.proc = subprocess.Popen(
                [command],
                cwd=self.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise LspError(f"{command} is not installed or not on PATH") from exc
        self._next_id = 1
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._opened: set[str] = set()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
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
                    },
                },
                "initializationOptions": INITIALIZATION_OPTIONS,
            },
            timeout=initialize_timeout,
        )
        if result is None:
            raise LspError("rust-analyzer initialize returned no result")
        self.notify("initialized", {})

    # -- transport ---------------------------------------------------------

    def _read_loop(self) -> None:
        stream = self.proc.stdout
        assert stream is not None
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
        except Exception as exc:  # pragma: no cover - transport failure path
            self._messages.put({"__reader_error__": repr(exc)})

    def _send(self, payload: dict[str, Any]) -> None:
        stream = self.proc.stdin
        assert stream is not None
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        stream.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
        stream.write(data)
        stream.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _answer(self, message: dict[str, Any]) -> None:
        """Servers ask questions too; an unanswered one can stall the server."""
        method = str(message.get("method", ""))
        if method == "workspace/configuration":
            items = (message.get("params") or {}).get("items") or []
            result: Any = [None for _ in items]
        else:
            result = None
        self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def request(self, method: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"LSP request timed out: {method}")
            try:
                message = self._messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"LSP request timed out: {method}") from exc
            if "__reader_error__" in message:
                raise LspError(str(message["__reader_error__"]))
            if "id" in message and "method" in message:
                self._answer(message)
                continue
            if message.get("id") != request_id:
                # Requests are strictly sequential here, so anything else is
                # progress reporting or a stale answer.
                continue
            if "error" in message:
                raise LspError(f"{method}: {message['error']}")
            return message.get("result")

    # -- documents ---------------------------------------------------------

    def open_file(self, path: Path) -> str:
        path = path.resolve()
        uri = path.as_uri()
        if uri not in self._opened:
            self.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "rust",
                        "version": 1,
                        "text": path.read_text("utf-8"),
                    }
                },
            )
            self._opened.add(uri)
        return uri

    def close(self) -> None:
        for call in (lambda: self.request("shutdown", {}, timeout=3), lambda: self.notify("exit", {})):
            try:
                call()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a wedged server
            self.proc.kill()
            self.proc.wait(timeout=5)

    def __enter__(self) -> "LspClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# -- reading answers -------------------------------------------------------


def hover_text(result: Any) -> str:
    if not result:
        return ""
    contents = result.get("contents") if isinstance(result, dict) else result
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return str(contents.get("value", ""))
    if isinstance(contents, list):
        parts = []
        for item in contents:
            parts.append(item if isinstance(item, str) else str(item.get("value", "")))
        return "\n".join(parts)
    return str(contents)


def location(result: Any) -> tuple[str, dict[str, Any]] | None:
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


def location_uri(found: tuple[str, dict[str, Any]] | None) -> str:
    return found[0] if found else ""


def location_key(found: tuple[str, dict[str, Any]] | None, fallback: str) -> str:
    """A stable identity for the thing a definition points at.

    Two acquisitions of the same lock resolve to the same definition, which is
    what makes lock-order edges meaningful instead of name-based guesswork.
    """
    if not found:
        return fallback
    uri, rng = found
    start = rng.get("start") or {}
    return f"{uri}#{int(start.get('line', 0))}:{int(start.get('character', 0))}"


def function_symbols(result: Any) -> list[tuple[str, dict[str, Any]]]:
    """Flatten the document symbol tree to (name, range) for functions."""
    out: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(result, list):
        return out
    for item in result:
        if not isinstance(item, dict):
            continue
        kind = int(item.get("kind", 0) or 0)
        rng = item.get("range") or (item.get("location") or {}).get("range")
        if kind in {6, 12} and isinstance(rng, dict):  # method, function
            out.append((str(item.get("name", "<unknown>")), rng))
        out.extend(function_symbols(item.get("children")))
    return out


def contains(rng: dict[str, Any], line: int, character: int = 0) -> bool:
    start, end = rng.get("start") or {}, rng.get("end") or {}
    start_line, start_col = int(start.get("line", -1)), int(start.get("character", 0))
    end_line, end_col = int(end.get("line", -1)), int(end.get("character", 0))
    if line < start_line or line > end_line:
        return False
    if line == start_line and character < start_col:
        return False
    if line == end_line and character > end_col:
        return False
    return True


def enclosing_function(symbols: list[tuple[str, dict[str, Any]]], line: int, character: int) -> str:
    """The innermost function containing a position, or a stable placeholder."""
    best: tuple[str, int] | None = None
    for name, rng in symbols:
        if not contains(rng, line, character):
            continue
        size = int((rng.get("end") or {}).get("line", 0)) - int((rng.get("start") or {}).get("line", 0))
        if best is None or size < best[1]:
            best = (name, size)
    return best[0] if best else "<module>"


def toolchain_versions(command: str = "rust-analyzer") -> dict[str, str]:
    """Version strings of the Rust tools, for the report envelope."""
    out: dict[str, str] = {}
    for key, argv in (
        ("rustc", ["rustc", "--version"]),
        ("cargo", ["cargo", "--version"]),
        ("rust_analyzer", [command, "--version"]),
    ):
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
            out[key] = result.stdout.strip() or result.stderr.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            out[key] = "not available"
    return out
