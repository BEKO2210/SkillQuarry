#!/usr/bin/env python3
"""LockScope v2 semantic engine: tree-sitter syntax + rust-analyzer semantics."""
from __future__ import annotations

import json
from pathlib import Path

import semantic_probe as base
import syntax_ast as syntax

LockSite = base.LockSite
Analysis = base.Analysis
as_jsonable = base.as_jsonable
finding_kinds = base.finding_kinds


def _classify(evidence: str, op: str) -> tuple[str, str] | None:
    text = evidence.lower().replace("\\", "/")
    is_tokio = "tokio::sync" in text or "/tokio-" in text or "/tokio/src/sync/" in text
    is_parking = "parking_lot" in text or "/parking_lot-" in text or "/lock_api-" in text
    is_std = "std::sync" in text or "/library/std/src/sync/" in text or "/std/src/sync/" in text
    if is_tokio:
        family = "async"
    elif is_parking or is_std:
        family = "sync"
    else:
        return None
    mode = "read" if op in {"read", "read_owned"} else "exclusive"
    return family, mode


def _point_tuple(point: syntax.Point) -> tuple[int, int]:
    return point.line, point.column


def _macro_lifetime(path: Path, invocation: syntax.MacroInvocation, guard: str) -> tuple[int, int | None, int, int]:
    source = path.read_bytes()
    tree = syntax.parser().parse(source)
    start = invocation.end_byte
    end = invocation.scope_end_byte
    drop_node = None
    awaits = []
    uses = []
    for node in syntax._walk(tree.root_node):
        if node.start_byte < start or node.start_byte >= end:
            continue
        if node.type == "await_expression":
            awaits.append(node)
        if node.type == "identifier" and source[node.start_byte:node.end_byte].decode("utf-8", errors="replace") == guard:
            uses.append(node)
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "identifier":
                continue
            if source[fn.start_byte:fn.end_byte] != b"drop":
                continue
            args = node.child_by_field_name("arguments")
            if args is None:
                continue
            names = [
                source[i.start_byte:i.end_byte].decode("utf-8", errors="replace")
                for i in syntax._ident_nodes(args)
                if i.type == "identifier"
            ]
            if names == [guard] and (drop_node is None or node.start_byte < drop_node.start_byte):
                drop_node = node
    live_end_byte = drop_node.end_byte if drop_node is not None else end
    live_awaits = sum(1 for node in awaits if node.start_byte < live_end_byte)
    drop_line = int(drop_node.start_point[0]) + 1 if drop_node is not None else None
    live_end_line = drop_line if drop_line is not None else invocation.scope_end_line
    last_use_line = max(
        [int(node.start_point[0]) + 1 for node in uses if node.start_byte < live_end_byte]
        or [invocation.point.line + 1]
    )
    return live_end_line, drop_line, last_use_line, live_awaits


class SemanticLockScope(base.SemanticLockScope):
    def _type_definition(self, uri: str, line: int, character: int):
        try:
            result = self.lsp.request(
                "textDocument/typeDefinition",
                {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}},
                timeout=8,
            )
        except (TimeoutError, base.LspError):
            return None
        return base._location(result)

    def _resolve_receiver(self, uri: str, points: tuple[tuple[str, syntax.Point], ...], op: str):
        fallback = None
        for name, point in reversed(points):
            line, col = _point_tuple(point)
            hover = self._hover_with_retry(uri, line, col, timeout=4)
            definition = self._definition(uri, line, col)
            type_definition = self._type_definition(uri, line, col)
            evidence = "\n".join([hover, base._definition_uri(definition), base._definition_uri(type_definition)])
            item = (name, hover, definition, type_definition, evidence)
            if fallback is None:
                fallback = item
            if _classify(evidence, op) is not None:
                return item
        return fallback or ("<unknown>", "", None, None, "")

    def analyze(self, path: Path) -> Analysis:
        path = path.resolve()
        uri = self.lsp.open_file(path)
        candidates = syntax.extract_candidates(path)

        if candidates:
            first = candidates[0]
            self._hover_with_retry(uri, first.op_point.line, first.op_point.column, timeout=30)

        try:
            symbols_result = self.lsp.request(
                "textDocument/documentSymbol", {"textDocument": {"uri": uri}}, timeout=10
            )
        except Exception:
            symbols_result = []
        symbols = base._flatten_function_symbols(symbols_result)

        sites: list[LockSite] = []
        classified_candidates = 0

        for cand in candidates:
            guard_hover = self._hover_with_retry(uri, cand.guard_point.line, cand.guard_point.column, timeout=5)
            op_hover = self._hover_with_retry(uri, cand.op_point.line, cand.op_point.column, timeout=5)
            method_loc = self._definition(uri, cand.op_point.line, cand.op_point.column)
            method_uri = base._definition_uri(method_loc)
            _, expr_hover, lock_loc, type_loc, receiver_evidence = self._resolve_receiver(
                uri, cand.receiver_ident_points, cand.op
            )
            evidence = "\n".join(
                [guard_hover, op_hover, expr_hover, method_uri, base._definition_uri(type_loc), receiver_evidence]
            )
            classified = _classify(evidence, cand.op)
            if classified is None:
                continue
            classified_candidates += 1
            family, mode = classified
            function, _ = base._function_for_line(symbols, cand.guard_point.line, cand.guard_point.column)
            lock_key = base._definition_key(lock_loc, f"{uri}#expr:{cand.lock_expr}")
            sites.append(
                LockSite(
                    function=function,
                    line=cand.line,
                    guard=cand.guard,
                    lock_expr=cand.lock_expr,
                    lock_key=lock_key,
                    mode=mode,
                    family=family,
                    origin="source",
                    type_text=evidence,
                    method_definition=method_uri or base._definition_uri(type_loc),
                    scope_end_line=cand.live_end_line,
                    explicit_drop_line=cand.explicit_drop_line,
                    last_textual_use_line=cand.last_use_line,
                    awaits_while_live=cand.awaits_while_live,
                    span_lines=max(0, cand.live_end_line - cand.line),
                )
            )

        for inv in syntax.extract_macro_invocations(path):
            try:
                expanded = self.lsp.request(
                    "rust-analyzer/expandMacro",
                    {
                        "textDocument": {"uri": uri},
                        "position": {"line": inv.point.line, "character": inv.point.column},
                    },
                    timeout=8,
                )
            except Exception:
                continue
            expansion = str(expanded.get("expansion", "")) if isinstance(expanded, dict) else str(expanded or "")
            acquisition = syntax.parse_expansion_acquisition(expansion)
            if acquisition is None:
                continue
            guard, op = acquisition
            chosen = None
            for name, point in inv.identifier_points:
                line, col = _point_tuple(point)
                hover = self._hover_with_retry(uri, line, col, timeout=4)
                definition = self._definition(uri, line, col)
                type_loc = self._type_definition(uri, line, col)
                evidence = "\n".join([hover, base._definition_uri(definition), base._definition_uri(type_loc)])
                classified = _classify(evidence, op)
                if classified is not None:
                    chosen = (name, definition, type_loc, evidence, classified)
                    break
            if chosen is None:
                continue
            name, lock_loc, type_loc, evidence, (family, mode) = chosen
            function, _ = base._function_for_line(symbols, inv.point.line, inv.point.column)
            live_end, drop_line, last_use, awaits = _macro_lifetime(path, inv, guard)
            sites.append(
                LockSite(
                    function=function,
                    line=inv.point.line + 1,
                    guard=guard,
                    lock_expr=name,
                    lock_key=base._definition_key(lock_loc, f"{uri}#macro:{name}"),
                    mode=mode,
                    family=family,
                    origin="macro",
                    type_text=evidence,
                    method_definition=base._definition_uri(type_loc) or "rust-analyzer/expandMacro",
                    scope_end_line=live_end,
                    explicit_drop_line=drop_line,
                    last_textual_use_line=last_use,
                    awaits_while_live=awaits,
                    span_lines=max(0, live_end - (inv.point.line + 1)),
                )
            )

        if candidates and classified_candidates == 0:
            raise base.LspError(
                f"semantic readiness failure: {len(candidates)} structured acquisition candidates, zero classified"
            )

        sites.sort(key=lambda site: (site.function, site.line, site.guard, site.origin))
        cycles = base._find_cycles(sites)
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
            findings.append({"kind": "lock_order_cycle", "severity": "critical", "cycle": cycle})
        findings.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return Analysis(lock_sites=sites, cycles=cycles, findings=findings)
