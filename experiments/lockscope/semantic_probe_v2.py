#!/usr/bin/env python3
"""LockScope semantic probe amendment A1.

The preregistered first run proved that guard hover text + method-definition URI
was insufficient to classify Tokio aliases on rust-analyzer 1.97.1. This module
keeps every expected case unchanged and amends only evidence collection:
receiver `typeDefinition` and method hover are added, and versioned Cargo
registry paths such as `/tokio-1.47.1/` are recognized.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import semantic_probe as base

LockSite = base.LockSite
Analysis = base.Analysis
as_jsonable = base.as_jsonable
finding_kinds = base.finding_kinds


def _classify(evidence: str, op: str) -> tuple[str, str] | None:
    text = evidence.lower().replace("\\", "/")
    is_tokio = (
        "tokio::sync" in text
        or "/tokio-" in text
        or "/tokio/src/sync/" in text
    )
    is_parking = (
        "parking_lot" in text
        or "/parking_lot-" in text
        or "/lock_api-" in text
    )
    is_std = (
        "std::sync" in text
        or "/library/std/src/sync/" in text
        or "/std/src/sync/" in text
    )
    if is_tokio:
        family = "async"
    elif is_parking or is_std:
        family = "sync"
    else:
        return None
    mode = "read" if op in {"read", "read_owned"} else "exclusive"
    return family, mode


class SemanticLockScope(base.SemanticLockScope):
    def _type_definition(self, uri: str, line: int, character: int):
        try:
            result = self.lsp.request(
                "textDocument/typeDefinition",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
                timeout=8,
            )
        except (TimeoutError, base.LspError):
            return None
        return base._location(result)

    def analyze(self, path: Path) -> Analysis:
        path = path.resolve()
        text = path.read_text("utf-8")
        starts = base._line_starts(text)
        uri = self.lsp.open_file(path)
        normal_matches = list(base.ACQUIRE.finditer(text))

        # Readiness gate: a known syntactic candidate must eventually acquire
        # semantic method/receiver evidence. Empty evidence is never treated as
        # a clean file.
        if normal_matches:
            first = normal_matches[0]
            line, col = base._offset_to_position(starts, first.start("op"))
            self._hover_with_retry(uri, line, col, timeout=30)

        try:
            symbols_result = self.lsp.request(
                "textDocument/documentSymbol", {"textDocument": {"uri": uri}}, timeout=10
            )
        except Exception:
            symbols_result = []
        symbols = base._flatten_function_symbols(symbols_result)
        try:
            folds = self.lsp.request(
                "textDocument/foldingRange", {"textDocument": {"uri": uri}}, timeout=10
            )
        except Exception:
            folds = []

        sites: list[LockSite] = []
        seen_origins: set[tuple[int, str]] = set()
        classified_candidates = 0

        for match in normal_matches:
            guard_line, guard_col = base._offset_to_position(starts, match.start("guard"))
            op_line, op_col = base._offset_to_position(starts, match.start("op"))
            guard_hover = self._hover_with_retry(uri, guard_line, guard_col, timeout=6)
            op_hover = self._hover_with_retry(uri, op_line, op_col, timeout=6)
            method_loc = self._definition(uri, op_line, op_col)
            method_uri = base._definition_uri(method_loc)

            expr = match.group("expr")
            expr_ident = base._pick_lock_identifier(expr)
            lock_loc = None
            type_loc = None
            expr_hover = ""
            if expr_ident:
                absolute = match.start("expr") + expr_ident.start()
                lock_line, lock_col = base._offset_to_position(starts, absolute)
                lock_loc = self._definition(uri, lock_line, lock_col)
                type_loc = self._type_definition(uri, lock_line, lock_col)
                expr_hover = self._hover_with_retry(uri, lock_line, lock_col, timeout=4)

            evidence = "\n".join(
                [
                    guard_hover,
                    op_hover,
                    expr_hover,
                    method_uri,
                    base._definition_uri(type_loc),
                ]
            )
            classified = _classify(evidence, match.group("op"))
            if classified is None:
                continue
            classified_candidates += 1
            family, mode = classified
            function, function_range = base._function_for_line(symbols, guard_line, guard_col)
            scope_end = base._scope_end_line(folds, function_range, guard_line)
            live_end, explicit_drop, last_use, awaits = base._guard_lifetime(
                text, starts, match.group("guard"), match.end(), scope_end
            )
            norm_expr = base._normalize_expr(expr)
            lock_key = base._definition_key(lock_loc, f"{uri}#expr:{norm_expr}")
            site = LockSite(
                function=function,
                line=guard_line + 1,
                guard=match.group("guard"),
                lock_expr=norm_expr,
                lock_key=lock_key,
                mode=mode,
                family=family,
                origin="source",
                type_text=evidence,
                method_definition=method_uri or base._definition_uri(type_loc),
                scope_end_line=live_end,
                explicit_drop_line=explicit_drop,
                last_textual_use_line=last_use,
                awaits_while_live=awaits,
                span_lines=max(0, live_end - (guard_line + 1)),
            )
            sites.append(site)
            seen_origins.add((guard_line + 1, site.guard))

        for macro in base.MACRO_CALL.finditer(text):
            invocation_line, invocation_col = base._offset_to_position(starts, macro.start("name"))
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
            expansion = str(expanded.get("expansion", "")) if isinstance(expanded, dict) else str(expanded or "")
            exp_match = base.ACQUIRE.search(expansion)
            if not exp_match:
                continue
            args_text = macro.group("args")
            args = [part.strip() for part in args_text.split(",") if part.strip()]
            if not args:
                continue
            lock_arg = args[0]
            ident = base._pick_lock_identifier(lock_arg)
            if not ident:
                continue
            arg_rel = args_text.find(lock_arg)
            absolute = macro.start("args") + arg_rel + ident.start()
            arg_line, arg_col = base._offset_to_position(starts, absolute)
            hover = self._hover_with_retry(uri, arg_line, arg_col, timeout=6)
            lock_loc = self._definition(uri, arg_line, arg_col)
            type_loc = self._type_definition(uri, arg_line, arg_col)
            evidence = "\n".join([hover, base._definition_uri(type_loc)])
            classified = _classify(evidence, exp_match.group("op"))
            if classified is None:
                continue
            family, mode = classified
            guard = exp_match.group("guard")
            if (invocation_line + 1, guard) in seen_origins:
                continue
            function, function_range = base._function_for_line(symbols, invocation_line, invocation_col)
            scope_end = base._scope_end_line(folds, function_range, invocation_line)
            live_end, explicit_drop, last_use, awaits = base._guard_lifetime(
                text, starts, guard, macro.end(), scope_end
            )
            norm_expr = base._normalize_expr(lock_arg)
            lock_key = base._definition_key(lock_loc, f"{uri}#expr:{norm_expr}")
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
                    type_text=evidence,
                    method_definition=base._definition_uri(type_loc) or "rust-analyzer/expandMacro",
                    scope_end_line=live_end,
                    explicit_drop_line=explicit_drop,
                    last_textual_use_line=last_use,
                    awaits_while_live=awaits,
                    span_lines=max(0, live_end - (invocation_line + 1)),
                )
            )

        # A file with syntactic candidates but zero semantic candidates is an
        # analyzer failure, not evidence of safety. This prevents the exact
        # false-clean behavior observed in run 1.
        if normal_matches and classified_candidates == 0:
            raise base.LspError(
                f"semantic readiness failure: {len(normal_matches)} acquisition candidates, zero classified"
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
