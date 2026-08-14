#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import pro_test as p
import redteam

IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


class LspClient:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.proc = subprocess.Popen(
            ["rust-analyzer"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.root,
        )
        self.next_id = 1
        self.responses = {}
        self.cv = threading.Condition()
        self.reader_error = None
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        self._initialize()

    def _send(self, message: dict) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        assert self.proc.stdin is not None
        self.proc.stdin.write(header + payload)
        self.proc.stdin.flush()

    def _read_message(self):
        assert self.proc.stdout is not None
        headers = {}
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        size = int(headers["content-length"])
        payload = self.proc.stdout.read(size)
        if len(payload) != size:
            raise RuntimeError("truncated LSP payload")
        return json.loads(payload.decode("utf-8"))

    def _read_loop(self) -> None:
        try:
            while True:
                message = self._read_message()
                if message is None:
                    return
                if "method" in message and "id" in message:
                    method = message["method"]
                    if method == "workspace/configuration":
                        items = message.get("params", {}).get("items", [])
                        result = [{} for _ in items]
                    elif method == "client/registerCapability":
                        result = None
                    elif method == "workspace/workspaceFolders":
                        result = [{"uri": self.root.as_uri(), "name": self.root.name}]
                    else:
                        result = None
                    self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})
                    continue
                if "id" in message:
                    with self.cv:
                        self.responses[message["id"]] = message
                        self.cv.notify_all()
        except Exception as exc:  # surfaced to requester
            with self.cv:
                self.reader_error = repr(exc)
                self.cv.notify_all()

    def request(self, method: str, params: dict, timeout: float = 30.0):
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        with self.cv:
            while request_id not in self.responses:
                if self.reader_error:
                    raise RuntimeError(self.reader_error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"LSP request timed out: {method}")
                self.cv.wait(remaining)
            response = self.responses.pop(request_id)
        if "error" in response:
            raise RuntimeError(f"LSP {method} failed: {response['error']}")
        return response.get("result")

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _initialize(self) -> None:
        result = self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self.root.as_uri(),
                "workspaceFolders": [{"uri": self.root.as_uri(), "name": self.root.name}],
                "capabilities": {"workspace": {"configuration": True}},
                "initializationOptions": {
                    "cargo": {"buildScripts": {"enable": False}},
                    "procMacro": {"enable": False},
                },
                "clientInfo": {"name": "morphostat-feasibility", "version": "0"},
            },
            timeout=45.0,
        )
        if not isinstance(result, dict) or "capabilities" not in result:
            raise RuntimeError("rust-analyzer initialize returned no capabilities")
        self.notify("initialized", {})

    def open_document(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": path.resolve().as_uri(),
                    "languageId": "rust",
                    "version": 1,
                    "text": text,
                }
            },
        )

    def definition(self, path: Path, line: int, character: int):
        return self.request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path.resolve().as_uri()},
                "position": {"line": line, "character": character},
            },
            timeout=20.0,
        )

    def close(self) -> None:
        try:
            self.request("shutdown", {}, timeout=10.0)
            self.notify("exit", {})
            self.proc.wait(timeout=10.0)
        except Exception:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5.0)


def uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path)).resolve()


def location_path(result) -> Path | None:
    if result is None:
        return None
    if isinstance(result, list):
        if not result:
            return None
        result = result[0]
    if not isinstance(result, dict):
        return None
    uri = result.get("uri") or result.get("targetUri")
    return uri_to_path(uri) if isinstance(uri, str) else None


def module_name(path: Path, src: Path) -> str:
    rel = path.relative_to(src)
    if rel.name == "lib.rs":
        return "__root__"
    if rel.name == "mod.rs":
        rel = rel.parent
    else:
        rel = rel.with_suffix("")
    return "::".join(rel.parts)


def semantic_internal_edges(root: Path, crate: str = "domain") -> list[str]:
    src = (root / crate / "src").resolve()
    files = sorted(src.rglob("*.rs"))
    client = LspClient(root)
    try:
        for path in files:
            client.open_document(path)
        edges = set()
        for path in files:
            origin = module_name(path.resolve(), src)
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines()):
                for match in IDENT.finditer(line):
                    target_path = location_path(client.definition(path, line_no, match.start()))
                    if target_path is None or not target_path.is_relative_to(src):
                        continue
                    target = module_name(target_path, src)
                    if target != origin and target != "__root__":
                        edges.add(f"{origin}->{target}")
        return sorted(edges)
    finally:
        client.close()


def private_helper_refactor(root: Path) -> None:
    path = root / "domain/src/policy.rs"
    p.replace(
        path,
        "pub fn apply_policy(value: DomainValue) -> DomainValue {",
        "fn identity(value: DomainValue) -> DomainValue { value }\n\npub fn apply_policy(value: DomainValue) -> DomainValue {",
    )
    p.replace(
        path,
        "DomainValue::new(value.get() + 1)",
        "DomainValue::new(identity(value).get() + 1)",
    )


def run_case(arena: Path, name: str, mutate, expect_change: bool) -> dict:
    healthy = arena / f"{name}-healthy"
    actual = arena / f"{name}-actual"
    redteam.base(healthy)
    shutil.copytree(healthy, actual)
    mutate(actual)

    healthy_edges = semantic_internal_edges(healthy)
    actual_edges = semantic_internal_edges(actual)
    detected = healthy_edges != actual_edges
    return {
        "case": name,
        "detected": detected,
        "expected_detected": expect_change,
        "healthy_edges": healthy_edges,
        "actual_edges": actual_edges,
        "pass": detected == expect_change,
    }


def main() -> int:
    version = subprocess.run(
        ["rust-analyzer", "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=20,
    ).stdout.strip()

    cases = [
        ("direct_qualified_internal_reference", redteam.direct_qualified_reference, True),
        ("crate_alias_internal_reference", redteam.crate_alias_reference, True),
        ("private_helper_control", private_helper_refactor, False),
    ]
    with tempfile.TemporaryDirectory(prefix="morphostat-lsp-") as tmp:
        arena = Path(tmp)
        results = [run_case(arena, name, mutate, expected) for name, mutate, expected in cases]

    failures = [item["case"] for item in results if not item["pass"]]
    summary = {
        "rust_analyzer_version": version,
        "cases": len(results),
        "failures": failures,
        "results": results,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
