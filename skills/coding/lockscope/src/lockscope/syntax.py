"""Structured Rust syntax extraction.

Lock acquisitions, guard lifetimes, await points and macro invocations are read
from a concrete syntax tree, never from text patterns. The predecessor of this
module matched acquisitions with regular expressions and missed a valid
multiline Tokio acquisition — a defect that no amount of pattern tuning fixes,
because Rust is not a regular language. Semantic identity (is this really a
mutex? which one?) is not decided here; that is `semantics.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from tree_sitter import Language, Node, Parser
import tree_sitter_rust

LANGUAGE = Language(tree_sitter_rust.language())

# Method names that can produce a lock guard. A name alone proves nothing — it
# only makes a binding worth resolving semantically.
LOCK_OPS = ("lock", "lock_owned", "read", "read_owned", "write", "write_owned")

# Receiver identifiers that never name the lock itself, so they are offered to
# the semantic resolver last rather than first.
PASS_THROUGH = (
    "self", "Arc", "Rc", "Box", "Pin", "clone", "as_ref", "as_mut",
    "borrow", "borrow_mut", "get_ref", "get_mut", "deref",
)

# Calls that pass a guard-producing expression through unchanged.
GUARD_WRAPPERS = ("unwrap", "expect", "unwrap_or_else")

# Expression nodes the guard value may be wrapped in.
TRANSPARENT = ("await_expression", "try_expression", "parenthesized_expression", "reference_expression")


@dataclass(frozen=True)
class Point:
    """A zero-based position, the way an editor and the LSP count."""

    line: int
    column: int


@dataclass(frozen=True)
class Candidate:
    """One `let` binding whose value may be a lock guard."""

    guard: str
    op: str
    lock_expr: str
    line: int
    guard_point: Point
    op_point: Point
    receiver_points: tuple[tuple[str, Point], ...]
    declaration_start_byte: int
    declaration_end_byte: int
    live_end_byte: int
    live_end_line: int
    explicit_drop_line: int | None
    last_use_line: int
    awaits_while_live: int
    origin: str = "source"


@dataclass(frozen=True)
class MacroInvocation:
    """A macro call that may expand into a lock acquisition."""

    point: Point
    end_byte: int
    scope_end_byte: int
    scope_end_line: int
    identifier_points: tuple[tuple[str, Point], ...]


def parser() -> Parser:
    return Parser(LANGUAGE)


def parse(source: bytes):
    return parser().parse(source)


def text_of(source: bytes, node: Node) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def walk(node: Node) -> Iterator[Node]:
    """Every named node below `node`, parents before children."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _identifiers(node: Node) -> list[Node]:
    return [n for n in walk(node) if n.type in {"identifier", "field_identifier"}]


def _point(node: Node) -> Point:
    row, column = node.start_point
    return Point(int(row), int(column))


def enclosing_block(node: Node) -> Node | None:
    current = node.parent
    while current is not None:
        if current.type == "block":
            return current
        current = current.parent
    return None


def _bound_name(source: bytes, pattern: Node | None) -> tuple[str, Point] | None:
    """The single identifier a `let` binds, or nothing for a destructuring."""
    if pattern is None:
        return None
    names = [n for n in _identifiers(pattern) if n.type == "identifier"]
    if len(names) != 1:
        return None
    return text_of(source, names[0]), _point(names[0])


def _method_call(source: bytes, node: Node):
    """(method name, name node, receiver) for `receiver.method(...)`."""
    if node.type != "call_expression":
        return None
    function = node.child_by_field_name("function")
    if function is None or function.type != "field_expression":
        return None
    field = function.child_by_field_name("field")
    receiver = function.child_by_field_name("value")
    if field is None or receiver is None:
        return None
    return text_of(source, field), field, receiver


def find_lock_call(source: bytes, value: Node | None):
    """Follow the value-producing chain of a `let` to a lock call.

    `.await`, `.unwrap()`, `?` and parentheses are transparent. A lock call that
    only appears as an *argument* is not what the binding holds, so the search
    never wanders into argument lists.
    """

    def descend(node: Node | None):
        if node is None:
            return None
        if node.type == "call_expression":
            parts = _method_call(source, node)
            if parts is None:
                return None
            name, name_node, receiver = parts
            if name in LOCK_OPS:
                return node, name_node, receiver, name
            if name in GUARD_WRAPPERS:
                return descend(receiver)
            return None
        if node.type in TRANSPARENT:
            for child in node.named_children:
                found = descend(child)
                if found is not None:
                    return found
            return None
        if node.type == "ERROR" and len(node.named_children) == 1:
            # A single-child ERROR node happens on syntax the grammar version
            # does not know yet. Descending one level stays structural.
            return descend(node.named_children[0])
        return None

    return descend(value)


def _explicit_drop(source: bytes, block: Node, guard: str, after_byte: int) -> tuple[int, int | None]:
    """Where `drop(guard)` ends the binding, if it does."""
    best: Node | None = None
    for node in walk(block):
        if node.type != "call_expression" or node.start_byte < after_byte:
            continue
        function = node.child_by_field_name("function")
        if function is None or function.type != "identifier" or text_of(source, function) != "drop":
            continue
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            continue
        names = [text_of(source, i) for i in _identifiers(arguments) if i.type == "identifier"]
        if names == [guard] and (best is None or node.start_byte < best.start_byte):
            best = node
    if best is None:
        return block.end_byte, None
    return best.end_byte, int(best.start_point[0]) + 1


def count_awaits(root: Node, start_byte: int, end_byte: int) -> int:
    return sum(
        1 for node in walk(root)
        if node.type == "await_expression" and start_byte <= node.start_byte < end_byte
    )


def await_points(root: Node, start_byte: int, end_byte: int) -> list[Node]:
    found = [
        node for node in walk(root)
        if node.type == "await_expression" and start_byte <= node.start_byte < end_byte
    ]
    found.sort(key=lambda node: node.start_byte)
    return found


def _last_use(source: bytes, root: Node, guard: str, start_byte: int, end_byte: int, fallback: int) -> int:
    lines = [
        int(node.start_point[0]) + 1
        for node in walk(root)
        if node.type == "identifier"
        and start_byte <= node.start_byte < end_byte
        and text_of(source, node) == guard
    ]
    return max(lines) if lines else fallback


def _receiver_points(source: bytes, receiver: Node) -> tuple[tuple[str, Point], ...]:
    """Identifiers of the receiver, the ones that can name a lock first."""
    named: list[tuple[str, Point]] = []
    passthrough: list[tuple[str, Point]] = []
    for ident in _identifiers(receiver):
        entry = (text_of(source, ident), _point(ident))
        (passthrough if entry[0] in PASS_THROUGH else named).append(entry)
    return tuple(named + passthrough)


def candidates_in(source: bytes, tree=None) -> list[Candidate]:
    """Every `let` binding in `source` whose value chain ends in a lock call."""
    tree = tree if tree is not None else parse(source)
    out: list[Candidate] = []
    for node in walk(tree.root_node):
        if node.type != "let_declaration":
            continue
        bound = _bound_name(source, node.child_by_field_name("pattern"))
        value = node.child_by_field_name("value")
        if bound is None or value is None:
            continue
        lock = find_lock_call(source, value)
        if lock is None:
            continue
        _, op_node, receiver, op = lock
        block = enclosing_block(node)
        if block is None:
            continue
        guard, guard_point = bound
        live_end_byte, drop_line = _explicit_drop(source, block, guard, node.end_byte)
        out.append(
            Candidate(
                guard=guard,
                op=op,
                lock_expr="".join(text_of(source, receiver).split()),
                line=guard_point.line + 1,
                guard_point=guard_point,
                op_point=_point(op_node),
                receiver_points=_receiver_points(source, receiver),
                declaration_start_byte=node.start_byte,
                declaration_end_byte=node.end_byte,
                live_end_byte=live_end_byte,
                live_end_line=int(block.end_point[0]) + 1 if drop_line is None else drop_line,
                explicit_drop_line=drop_line,
                last_use_line=_last_use(
                    source, block, guard, node.end_byte, live_end_byte, guard_point.line + 1
                ),
                awaits_while_live=count_awaits(block, node.end_byte, live_end_byte),
            )
        )
    out.sort(key=lambda c: (c.line, c.guard, c.op, c.lock_expr))
    return out


def extract_candidates(path: Path) -> list[Candidate]:
    return candidates_in(path.read_bytes())


def macro_invocations_in(source: bytes, tree=None) -> list[MacroInvocation]:
    tree = tree if tree is not None else parse(source)
    out: list[MacroInvocation] = []
    for node in walk(tree.root_node):
        if node.type != "macro_invocation":
            continue
        block = enclosing_block(node)
        if block is None:
            continue
        macro = node.child_by_field_name("macro")
        if macro is None:
            named = node.named_children
            if not named:
                continue
            macro = named[0]
        idents: list[tuple[str, Point]] = []
        passthrough: list[tuple[str, Point]] = []
        for ident in _identifiers(node):
            entry = (text_of(source, ident), _point(ident))
            (passthrough if entry[0] in PASS_THROUGH else idents).append(entry)
        out.append(
            MacroInvocation(
                point=_point(macro),
                end_byte=node.end_byte,
                scope_end_byte=block.end_byte,
                scope_end_line=int(block.end_point[0]) + 1,
                identifier_points=tuple(idents + passthrough),
            )
        )
    out.sort(key=lambda item: (item.point.line, item.point.column))
    return out


def extract_macro_invocations(path: Path) -> list[MacroInvocation]:
    return macro_invocations_in(path.read_bytes())


def acquisition_in_expansion(expansion: str) -> tuple[str, str] | None:
    """The guard and operation a macro expansion binds, if any."""
    wrapped = ("async fn __lockscope_expansion__() {\n" + expansion + "\n}").encode("utf-8")
    tree = parse(wrapped)
    for node in walk(tree.root_node):
        if node.type != "let_declaration":
            continue
        bound = _bound_name(wrapped, node.child_by_field_name("pattern"))
        value = node.child_by_field_name("value")
        lock = find_lock_call(wrapped, value) if value is not None else None
        if bound is not None and lock is not None:
            return bound[0], lock[3]
    return None


def macro_guard_lifetime(source: bytes, invocation: MacroInvocation, guard: str):
    """Lifetime of a guard a macro produced, measured in the calling scope."""
    tree = parse(source)
    start, end = invocation.end_byte, invocation.scope_end_byte
    drop_node: Node | None = None
    for node in walk(tree.root_node):
        if not (start <= node.start_byte < end) or node.type != "call_expression":
            continue
        function = node.child_by_field_name("function")
        if function is None or function.type != "identifier" or text_of(source, function) != "drop":
            continue
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            continue
        names = [text_of(source, i) for i in _identifiers(arguments) if i.type == "identifier"]
        if names == [guard] and (drop_node is None or node.start_byte < drop_node.start_byte):
            drop_node = node
    live_end_byte = drop_node.end_byte if drop_node is not None else end
    drop_line = int(drop_node.start_point[0]) + 1 if drop_node is not None else None
    return (
        drop_line if drop_line is not None else invocation.scope_end_line,
        drop_line,
        _last_use(source, tree.root_node, guard, start, live_end_byte, invocation.point.line + 1),
        count_awaits(tree.root_node, start, live_end_byte),
    )


def rust_files(root: Path, skip: Iterable[str] = ("target", ".git")) -> list[Path]:
    """Every `.rs` file under `root`, in a stable order."""
    skipped = set(skip)
    found = [
        path for path in root.rglob("*.rs")
        if not skipped.intersection(path.relative_to(root).parts)
    ]
    found.sort()
    return found


def versions() -> dict[str, str]:
    import importlib.metadata

    return {
        "tree_sitter": importlib.metadata.version("tree-sitter"),
        "tree_sitter_rust": importlib.metadata.version("tree-sitter-rust"),
    }
