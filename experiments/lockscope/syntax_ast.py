#!/usr/bin/env python3
"""Structured Rust syntax extraction for LockScope v2.

This module deliberately does not use regex to discover lock acquisitions,
lexical scopes, await expressions, or macro invocations. tree-sitter-rust
provides the concrete syntax tree; rust-analyzer is used later for semantic
identity/type resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tree_sitter import Language, Parser
import tree_sitter_rust

LANGUAGE = Language(tree_sitter_rust.language())
LOCK_OPS = {"lock", "lock_owned", "read", "read_owned", "write", "write_owned"}
SKIP_IDENTS = {"self", "Arc", "Rc", "Box", "Pin", "clone", "as_ref", "as_mut", "borrow", "borrow_mut", "get_ref"}


@dataclass(frozen=True)
class Point:
    line: int
    column: int


@dataclass(frozen=True)
class SyntaxCandidate:
    guard: str
    op: str
    lock_expr: str
    line: int
    guard_point: Point
    op_point: Point
    receiver_ident_points: tuple[tuple[str, Point], ...]
    declaration_end_byte: int
    live_end_byte: int
    live_end_line: int
    explicit_drop_line: int | None
    last_use_line: int
    awaits_while_live: int
    origin: str = "source"


@dataclass(frozen=True)
class MacroInvocation:
    point: Point
    scope_end_byte: int
    scope_end_line: int
    end_byte: int
    identifier_points: tuple[tuple[str, Point], ...]


def parser() -> Parser:
    return Parser(LANGUAGE)


def _text(source: bytes, node) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _walk(node) -> Iterable:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _ident_nodes(node) -> list:
    return [n for n in _walk(node) if n.type in {"identifier", "field_identifier"}]


def _point(node) -> Point:
    row, col = node.start_point
    return Point(int(row), int(col))


def _nearest_block(node):
    current = node.parent
    while current is not None:
        if current.type == "block":
            return current
        current = current.parent
    return None


def _pattern_guard(source: bytes, pattern) -> tuple[str, Point] | None:
    if pattern is None:
        return None
    idents = [n for n in _ident_nodes(pattern) if n.type == "identifier"]
    if len(idents) != 1:
        return None
    ident = idents[0]
    return _text(source, ident), _point(ident)


def _field_parts(source: bytes, call):
    if call.type != "call_expression":
        return None
    function = call.child_by_field_name("function")
    if function is None or function.type != "field_expression":
        return None
    field = function.child_by_field_name("field")
    value = function.child_by_field_name("value")
    if field is None or value is None:
        return None
    return _text(source, field), field, value


def _find_lock_call(source: bytes, value):
    # Prefer a lock call that sits on the value-producing chain. This covers
    # `.await`, `.unwrap()`, `.expect()`, parentheses and `?` without treating
    # arbitrary nested lock calls passed as arguments as the bound guard.
    wrappers = {"unwrap", "expect", "unwrap_or_else"}

    def descend(node):
        if node is None:
            return None
        if node.type == "call_expression":
            parts = _field_parts(source, node)
            if parts is not None:
                field_name, field_node, receiver = parts
                if field_name in LOCK_OPS:
                    return node, field_node, receiver, field_name
                if field_name in wrappers:
                    return descend(receiver)
            return None
        if node.type in {"await_expression", "try_expression", "parenthesized_expression", "reference_expression"}:
            for child in node.named_children:
                found = descend(child)
                if found is not None:
                    return found
            return None
        # tree-sitter versions may wrap an expression in a generic ERROR node
        # while editing. For a committed source file we only descend through a
        # single named child; this remains structural and avoids arbitrary nest search.
        if node.type == "ERROR" and len(node.named_children) == 1:
            return descend(node.named_children[0])
        return None

    return descend(value)


def _drop_end(source: bytes, block, guard: str, after_byte: int) -> tuple[int, int | None]:
    best = None
    for node in _walk(block):
        if node.type != "call_expression" or node.start_byte < after_byte:
            continue
        function = node.child_by_field_name("function")
        if function is None or function.type != "identifier" or _text(source, function) != "drop":
            continue
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            continue
        names = [_text(source, ident) for ident in _ident_nodes(arguments) if ident.type == "identifier"]
        if names == [guard] or (guard in names and len(names) == 1):
            if best is None or node.start_byte < best.start_byte:
                best = node
    if best is None:
        return block.end_byte, None
    return best.end_byte, int(best.start_point[0]) + 1


def _await_count(block, start_byte: int, end_byte: int) -> int:
    return sum(
        1
        for node in _walk(block)
        if node.type == "await_expression" and start_byte <= node.start_byte < end_byte
    )


def _last_guard_use(source: bytes, block, guard: str, start_byte: int, end_byte: int, fallback_line: int) -> int:
    lines = [
        int(node.start_point[0]) + 1
        for node in _walk(block)
        if node.type == "identifier"
        and start_byte <= node.start_byte < end_byte
        and _text(source, node) == guard
    ]
    return max(lines) if lines else fallback_line


def extract_candidates(path: Path) -> list[SyntaxCandidate]:
    source = path.read_bytes()
    tree = parser().parse(source)
    out: list[SyntaxCandidate] = []
    for node in _walk(tree.root_node):
        if node.type != "let_declaration":
            continue
        pattern = node.child_by_field_name("pattern")
        value = node.child_by_field_name("value")
        guard_info = _pattern_guard(source, pattern)
        if guard_info is None or value is None:
            continue
        lock = _find_lock_call(source, value)
        if lock is None:
            continue
        _, op_node, receiver, op = lock
        block = _nearest_block(node)
        if block is None:
            continue
        guard, guard_point = guard_info
        live_end_byte, drop_line = _drop_end(source, block, guard, node.end_byte)
        awaits = _await_count(block, node.end_byte, live_end_byte)
        last_use = _last_guard_use(source, block, guard, node.end_byte, live_end_byte, guard_point.line + 1)
        receiver_idents = []
        for ident in _ident_nodes(receiver):
            name = _text(source, ident)
            if name not in SKIP_IDENTS:
                receiver_idents.append((name, _point(ident)))
        if not receiver_idents:
            for ident in _ident_nodes(receiver):
                receiver_idents.append((_text(source, ident), _point(ident)))
        out.append(
            SyntaxCandidate(
                guard=guard,
                op=op,
                lock_expr="".join(_text(source, receiver).split()),
                line=guard_point.line + 1,
                guard_point=guard_point,
                op_point=_point(op_node),
                receiver_ident_points=tuple(receiver_idents),
                declaration_end_byte=node.end_byte,
                live_end_byte=live_end_byte,
                live_end_line=int(block.end_point[0]) + 1 if drop_line is None else drop_line,
                explicit_drop_line=drop_line,
                last_use_line=last_use,
                awaits_while_live=awaits,
            )
        )
    out.sort(key=lambda c: (c.line, c.guard, c.op, c.lock_expr))
    return out


def extract_macro_invocations(path: Path) -> list[MacroInvocation]:
    source = path.read_bytes()
    tree = parser().parse(source)
    out: list[MacroInvocation] = []
    for node in _walk(tree.root_node):
        if node.type != "macro_invocation":
            continue
        block = _nearest_block(node)
        if block is None:
            continue
        named = node.named_children
        macro_node = node.child_by_field_name("macro")
        if macro_node is None and named:
            macro_node = named[0]
        if macro_node is None:
            continue
        idents = []
        for ident in _ident_nodes(node):
            name = _text(source, ident)
            if name not in SKIP_IDENTS:
                idents.append((name, _point(ident)))
        out.append(
            MacroInvocation(
                point=_point(macro_node),
                scope_end_byte=block.end_byte,
                scope_end_line=int(block.end_point[0]) + 1,
                end_byte=node.end_byte,
                identifier_points=tuple(idents),
            )
        )
    out.sort(key=lambda item: (item.point.line, item.point.column))
    return out


def parse_expansion_acquisition(expansion: str) -> tuple[str, str] | None:
    wrapper_prefix = "async fn __lockscope_macro__() {\n"
    source = (wrapper_prefix + expansion + "\n}").encode("utf-8")
    tree = parser().parse(source)
    for node in _walk(tree.root_node):
        if node.type != "let_declaration":
            continue
        pattern = node.child_by_field_name("pattern")
        value = node.child_by_field_name("value")
        guard_info = _pattern_guard(source, pattern)
        lock = _find_lock_call(source, value) if value is not None else None
        if guard_info is not None and lock is not None:
            guard, _ = guard_info
            _, _, _, op = lock
            return guard, op
    return None


def syntax_versions() -> dict[str, str]:
    import importlib.metadata
    return {
        "tree_sitter": importlib.metadata.version("tree-sitter"),
        "tree_sitter_rust": importlib.metadata.version("tree-sitter-rust"),
    }
