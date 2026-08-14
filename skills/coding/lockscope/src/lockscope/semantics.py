"""Semantic resolution through rust-analyzer.

This is the layer that answers "is this actually a lock, and which one". It sits
behind the `Resolver` shape the engine expects, so the analysis can also be
driven by recorded answers in tests without a language server in the loop.

One server serves the whole workspace: initialising rust-analyzer is by far the
most expensive step, and restarting it per file was the single largest avoidable
cost in the research prototype. Answers are cached per (file, position), because
the same identifier is asked about once per candidate it appears in.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import lsp, syntax


@dataclass
class Timings:
    """Where the wall clock went, reported with the results."""

    server_start: float = 0.0
    warmup: float = 0.0
    resolution: float = 0.0
    macro_expansion: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "server_start_seconds": round(self.server_start, 3),
            "warmup_seconds": round(self.warmup, 3),
            "resolution_seconds": round(self.resolution, 3),
            "macro_expansion_seconds": round(self.macro_expansion, 3),
        }


class RustAnalyzerResolver:
    """Resolves types, definitions and macro expansions for one workspace."""

    def __init__(self, root: Path, command: str = "rust-analyzer", warmup_timeout: float = 90.0):
        self.root = root.resolve()
        self.command = command
        self.warmup_timeout = warmup_timeout
        self.timings = Timings()
        started = time.monotonic()
        self.client = lsp.LspClient(self.root, command=command)
        self.timings.server_start = time.monotonic() - started
        self._hover: dict[tuple[str, int, int], str] = {}
        self._definition: dict[tuple[str, int, int], Any] = {}
        self._type_definition: dict[tuple[str, int, int], Any] = {}
        self._symbols: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._warm: set[str] = set()
        self._loaded = False

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "RustAnalyzerResolver":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _uri(self, path: Path) -> str:
        return self.client.open_file(path)

    def wait_until_loaded(self) -> bool:
        """Block until the workspace is loaded, or the warm-up budget runs out.

        Asking a cold server is worse than asking a slow one: it answers
        immediately, with nothing, and a lock silently stops being a lock. The
        server reports `No workspaces` until `cargo metadata` has been read, so
        that string is the readiness signal — the first three cases of the
        fixture were resolved as "not a lock" without this wait.
        """
        if self._loaded:
            return True
        started = time.monotonic()
        deadline = started + self.warmup_timeout
        while time.monotonic() < deadline:
            try:
                status = str(self.client.request("rust-analyzer/analyzerStatus", {}, timeout=10) or "")
            except (TimeoutError, lsp.LspError):
                status = ""
            if status and "No workspaces" not in status:
                self._loaded = True
                break
            time.sleep(0.5)
        self.timings.warmup += time.monotonic() - started
        return self._loaded

    def warm_up(self, path: Path, point: syntax.Point) -> None:
        """Wait for the workspace, then for this file to answer with real types."""
        self.wait_until_loaded()
        uri = self._uri(path)
        if uri in self._warm:
            return
        started = time.monotonic()
        self._hover_text(uri, point.line, point.column, timeout=self.warmup_timeout)
        self.timings.warmup += time.monotonic() - started
        self._warm.add(uri)

    # -- primitive queries -------------------------------------------------

    def _hover_text(self, uri: str, line: int, column: int, timeout: float = 5.0) -> str:
        key = (uri, line, column)
        if key in self._hover:
            return self._hover[key]
        deadline = time.monotonic() + timeout
        text = ""
        while True:
            try:
                result = self.client.request(
                    "textDocument/hover",
                    {"textDocument": {"uri": uri}, "position": {"line": line, "character": column}},
                    timeout=min(5.0, max(1.0, timeout)),
                )
                text = lsp.hover_text(result)
            except (TimeoutError, lsp.LspError):
                text = ""
            if text or time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        # An empty hover means "not analysed yet", not "nothing there". Caching
        # it would turn a slow answer into a permanent wrong one — that is how
        # the first three fixture cases stopped being locks.
        if text:
            self._hover[key] = text
        return text

    def _resolve(self, kind: str, uri: str, line: int, column: int):
        cache = self._definition if kind == "definition" else self._type_definition
        key = (uri, line, column)
        if key in cache:
            return cache[key]
        try:
            result = self.client.request(
                f"textDocument/{kind}",
                {"textDocument": {"uri": uri}, "position": {"line": line, "character": column}},
                timeout=8,
            )
            found = lsp.location(result)
        except (TimeoutError, lsp.LspError):
            found = None
        cache[key] = found
        return found

    def _evidence_at(self, uri: str, point: syntax.Point) -> str:
        hover = self._hover_text(uri, point.line, point.column)
        definition = self._resolve("definition", uri, point.line, point.column)
        type_definition = self._resolve("typeDefinition", uri, point.line, point.column)
        return "\n".join([hover, lsp.location_uri(definition), lsp.location_uri(type_definition)])

    # -- the Resolver shape ------------------------------------------------

    def evidence_for(
        self,
        path: Path,
        points: tuple[tuple[str, syntax.Point], ...],
        op: str,
        op_point: syntax.Point | None = None,
    ) -> str:
        """Evidence about the acquisition: the method first, then the receiver.

        The method being called is the strongest evidence available. `lock` on a
        `tokio::sync::Mutex` is defined in tokio's own source, and asking where
        it is defined answers the question directly — while the receiver of
        `Arc::clone(&state).lock_owned()` only ever resolves to `Arc`.

        Receiver identifiers are the fallback, in the order the extractor
        offered them: names that can be the lock first, pass-through names like
        `Arc` or `clone` last, because those describe the container and not the
        thing being locked.
        """
        from .engine import classify  # local import keeps the module graph acyclic

        uri = self._uri(path)
        if op_point is not None:
            self.warm_up(path, op_point)
        elif points:
            self.warm_up(path, points[0][1])
        started = time.monotonic()
        collected: list[str] = []
        try:
            candidates = list(points)
            if op_point is not None:
                candidates.insert(0, (op, op_point))
            for _, point in candidates:
                evidence = self._evidence_at(uri, point)
                collected.append(evidence)
                if classify(evidence, op) is not None:
                    return evidence
            return "\n".join(collected)
        finally:
            self.timings.resolution += time.monotonic() - started

    def function_at(self, path: Path, point: syntax.Point) -> str:
        uri = self._uri(path)
        if uri not in self._symbols:
            try:
                result = self.client.request(
                    "textDocument/documentSymbol", {"textDocument": {"uri": uri}}, timeout=15
                )
            except (TimeoutError, lsp.LspError):
                result = []
            self._symbols[uri] = lsp.function_symbols(result)
        return lsp.enclosing_function(self._symbols[uri], point.line, point.column)

    def definition_key(self, path: Path, points: tuple[tuple[str, syntax.Point], ...], fallback: str) -> str:
        """Identity of the lock itself, so two acquisitions can be compared."""
        uri = self._uri(path)
        from .engine import classify

        for _, point in points:
            evidence = self._evidence_at(uri, point)
            if classify(evidence, "lock") is None and classify(evidence, "read") is None:
                continue
            found = self._resolve("definition", uri, point.line, point.column)
            if found:
                return lsp.location_key(found, fallback)
        if points:
            point = points[0][1]
            found = self._resolve("definition", uri, point.line, point.column)
            if found:
                return lsp.location_key(found, fallback)
        return fallback

    def expand_macro(self, path: Path, point: syntax.Point) -> str:
        uri = self._uri(path)
        started = time.monotonic()
        try:
            result = self.client.request(
                "rust-analyzer/expandMacro",
                {"textDocument": {"uri": uri}, "position": {"line": point.line, "character": point.column}},
                timeout=10,
            )
        except (TimeoutError, lsp.LspError):
            return ""
        finally:
            self.timings.macro_expansion += time.monotonic() - started
        if isinstance(result, dict):
            return str(result.get("expansion", ""))
        return str(result or "")


class RecordedResolver:
    """A resolver backed by literal answers.

    Used by tests that need to pin classification, ordering and finding
    behaviour without a language server, and by `--replay` for reproducing a
    reported analysis on a machine that has no Rust toolchain.
    """

    def __init__(self, evidence: dict[str, str], functions: dict[int, str] | None = None,
                 keys: dict[str, str] | None = None, expansions: dict[int, str] | None = None):
        self.evidence = evidence
        self.functions = functions or {}
        self.keys = keys or {}
        self.expansions = expansions or {}

    def evidence_for(
        self, path: Path, points: tuple[tuple[str, syntax.Point], ...], op: str,
        op_point: syntax.Point | None = None,
    ) -> str:
        for name, _ in points:
            if name in self.evidence:
                return self.evidence[name]
        return ""

    def function_at(self, path: Path, point: syntax.Point) -> str:
        return self.functions.get(point.line, "<module>")

    def definition_key(self, path: Path, points: tuple[tuple[str, syntax.Point], ...], fallback: str) -> str:
        for name, _ in points:
            if name in self.keys:
                return self.keys[name]
        return fallback

    def expand_macro(self, path: Path, point: syntax.Point) -> str:
        return self.expansions.get(point.line, "")
