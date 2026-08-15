"""A minimal Chrome DevTools Protocol client, standard library only.

Taken from this repository's HitMap research branch
(research/hitmap-ux-skill, reviewed there), because Chrome's own
--screenshot/--virtual-time path hangs on macOS CI runners while the DevTools
protocol answers reliably on every platform.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any

BROWSER_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome")


class CDPError(RuntimeError):
    pass


def find_browser(explicit: str | None = None) -> str | None:
    if explicit:
        p = Path(explicit)
        return str(p) if p.is_file() else which(explicit)
    env = os.environ.get("HITMAP_BROWSER")
    if env:
        p = Path(env)
        return str(p) if p.is_file() else which(env)
    for name in BROWSER_NAMES:
        path = which(name)
        if path:
            return path
    return None


@dataclass
class BrowserProcess:
    process: subprocess.Popen[str]
    devtools_base: str
    user_data_dir: tempfile.TemporaryDirectory[str]

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.user_data_dir.cleanup()


def launch_browser(binary: str) -> BrowserProcess:
    # ignore_cleanup_errors: Chrome may still be flushing its profile when the
    # process exits; a leftover file in a temp dir is not worth a traceback.
    profile = tempfile.TemporaryDirectory(prefix="hitmap-chrome-", ignore_cleanup_errors=True)
    proc = subprocess.Popen(
        [
            binary,
            "--headless=new",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile.name}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            # macOS: without a mock keychain a real Chrome waits on a
            # permission dialog no headless run can answer.
            "--use-mock-keychain",
            "--password-store=basic",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            *(["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []),
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stderr is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        line = proc.stderr.readline()
        if "DevTools listening on ws://" in line:
            ws_url = line.split("DevTools listening on ", 1)[1].strip()
            parsed = urllib.parse.urlparse(ws_url)
            return BrowserProcess(proc, f"http://{parsed.hostname}:{parsed.port}", profile)
        if proc.poll() is not None:
            break
    proc.kill()
    profile.cleanup()
    raise CDPError("browser did not expose a DevTools endpoint within 10 seconds")


class WebSocket:
    def __init__(self, url: str, timeout: float = 10.0):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws":
            raise CDPError("only ws:// DevTools endpoints are supported")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = self._read_http_headers()
        if not response.startswith("HTTP/1.1 101"):
            self.close()
            raise CDPError(f"DevTools websocket handshake failed: {response.splitlines()[0] if response else 'empty response'}")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        headers = {}
        for line in response.split("\r\n")[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        if headers.get("sec-websocket-accept") != accept:
            self.close()
            raise CDPError("DevTools websocket returned an invalid accept key")

    def _read_http_headers(self) -> str:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > 65536:
                raise CDPError("oversized websocket handshake")
        return data.decode("latin1")

    def send_json(self, obj: dict[str, Any]) -> None:
        payload = json.dumps(obj, separators=(",", ":")).encode()
        mask = os.urandom(4)
        first = 0x81
        length = len(payload)
        if length < 126:
            header = bytes([first, 0x80 | length])
        elif length < 65536:
            header = bytes([first, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([first, 0x80 | 127]) + struct.pack("!Q", length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv_json(self) -> dict[str, Any]:
        while True:
            first, second = self._recv_exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            masked = bool(second & 0x80)
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise CDPError("DevTools websocket closed")
            if opcode == 0x9:
                self._send_pong(payload)
                continue
            if opcode != 0x1:
                continue
            return json.loads(payload.decode())

    def _send_pong(self, payload: bytes) -> None:
        length = len(payload)
        if length >= 126:
            raise CDPError("unexpected large ping")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes([0x8A, 0x80 | length]) + mask + masked)

    def _recv_exact(self, n: int) -> bytes:
        data = bytearray()
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise CDPError("unexpected EOF from DevTools websocket")
            data.extend(chunk)
        return bytes(data)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class CDPClient:
    def __init__(self, websocket_url: str):
        self.ws = WebSocket(websocket_url)
        self.next_id = 1

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        ident = self.next_id
        self.next_id += 1
        self.ws.send_json({"id": ident, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self.ws.recv_json()
            if msg.get("id") != ident:
                continue
            if "error" in msg:
                raise CDPError(f"{method}: {msg['error']}")
            return msg.get("result", {})
        raise CDPError(f"timeout waiting for {method}")

    def close(self) -> None:
        self.ws.close()


def new_page(devtools_base: str, url: str) -> str:
    req = urllib.request.Request(f"{devtools_base}/json/new?{urllib.parse.quote(url, safe=':/?=&%')}", method="PUT")
    with urllib.request.urlopen(req, timeout=5) as response:
        data = json.load(response)
    ws = data.get("webSocketDebuggerUrl")
    if not ws:
        raise CDPError("DevTools did not return a page websocket URL")
    return str(ws)


def evaluate(client: CDPClient, expression: str) -> Any:
    result = client.call("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    }, timeout=20)
    remote = result.get("result", {})
    if remote.get("subtype") == "error":
        raise CDPError(str(remote.get("description") or "browser evaluation failed"))
    return remote.get("value")
