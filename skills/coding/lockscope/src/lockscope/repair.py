"""One conservative repair: acquire the lock after the independent await.

The transformation is deliberately narrow. If a guard is taken, then an await
happens that does not use the guard, the acquisition moves to just after that
await. Everything else — reordering locks, splitting critical sections, swapping
a std mutex for an async one — is left to a human, because those change
behaviour and this program cannot prove they are safe.

Both the acquisition and the await are located in the syntax tree. The research
prototype matched them with regular expressions and could only ever repair the
shapes its pattern happened to cover.

Why the acquisition is *moved* rather than a `drop(guard)` inserted: on the
pinned toolchain, an explicit `drop` of a `std::sync::MutexGuard` does not make
a spawned future `Send`, while ending the guard's lexical scope does. The
compiler probes in the test suite record that behaviour instead of assuming it.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from . import syntax

# Statements whose presence between the acquisition and the await make the move
# a control-flow rewrite rather than a dependency motion. Refused, not guessed.
BRANCHING = {
    "if_expression", "match_expression", "for_expression", "while_expression",
    "loop_expression", "return_expression", "break_expression", "continue_expression",
    "let_else", "closure_expression", "async_block", "unsafe_block", "try_expression",
}


@dataclass(frozen=True)
class Repair:
    """A single acquisition motion, described in terms a reviewer can check."""

    file: str
    guard: str
    from_line: int
    to_line: int
    acquisition: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Refusal:
    """Why an obvious-looking repair was not made."""

    file: str
    guard: str
    line: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _statement_of(node) -> Any:
    """The statement a node belongs to, within its block."""
    current = node
    while current.parent is not None and current.parent.type != "block":
        current = current.parent
    return current if current.parent is not None else None


def _uses_guard(source: bytes, node, guard: str) -> bool:
    return any(
        child.type == "identifier" and syntax.text_of(source, child) == guard
        for child in syntax.walk(node)
    )


def _crosses_branch(node) -> bool:
    return any(child.type in BRANCHING for child in syntax.walk(node))


def _find_motion(source: bytes, path_name: str):
    """The first safe motion: (declaration node, statement to move after, Repair).

    Returns `(None, None, None, refusals)` when nothing can be moved safely.
    """
    tree = syntax.parse(source)
    refusals: list[Refusal] = []

    for candidate in syntax.candidates_in(source, tree):
        if candidate.awaits_while_live == 0:
            continue

        declaration = _node_at(tree.root_node, candidate.declaration_start_byte, "let_declaration")
        block = syntax.enclosing_block(declaration) if declaration is not None else None
        if declaration is None or block is None:
            refusals.append(Refusal(path_name, candidate.guard, candidate.line,
                                    "acquisition is not a plain statement in a block"))
            continue

        statements = [child for child in block.named_children]
        try:
            position = statements.index(declaration)
        except ValueError:
            refusals.append(Refusal(path_name, candidate.guard, candidate.line,
                                    "acquisition is nested inside another expression"))
            continue

        # Walk forward while the statements neither use the guard nor branch,
        # remembering the last one that awaits. That is where the lock is taken.
        target: int | None = None
        blocked: str | None = None
        for index in range(position + 1, len(statements)):
            statement = statements[index]
            if _uses_guard(source, statement, candidate.guard):
                break
            if _crosses_branch(statement):
                blocked = "an await inside branching control flow"
                break
            if syntax.count_awaits(statement, statement.start_byte, statement.end_byte):
                target = index
        if target is None:
            refusals.append(Refusal(
                path_name, candidate.guard, candidate.line,
                blocked or "no independent await between the acquisition and the guard's first use",
            ))
            continue

        moved_after = statements[target]
        found = Repair(
            file=path_name,
            guard=candidate.guard,
            from_line=candidate.line,
            to_line=int(moved_after.end_point[0]) + 1,
            acquisition=" ".join(syntax.text_of(source, declaration).split()),
            reason=(
                f"guard `{candidate.guard}` was held across "
                f"{candidate.awaits_while_live} independent await point(s)"
            ),
        )
        return declaration, moved_after, found, refusals
    return None, None, None, refusals


def plan(source: bytes, path_name: str = "<source>") -> tuple[Repair | None, list[Refusal]]:
    """The repair that would be made, without touching anything."""
    _, _, found, refusals = _find_motion(source, path_name)
    return found, refusals


def _node_at(root, start_byte: int, node_type: str):
    for node in syntax.walk(root):
        if node.start_byte == start_byte and node.type == node_type:
            return node
    return None


def _move(source: bytes, declaration, after) -> bytes:
    """Cut the acquisition statement out and paste it after `after`."""
    start = _line_start(source, declaration.start_byte)
    end = _line_end(source, declaration.end_byte)
    statement = source[start:end]
    indent = _indent_of(source, after.start_byte)
    body = source[:start] + source[end:]

    # Deleting the acquisition shifts everything behind it.
    shift = end - start
    insert_at = _line_end(source, after.end_byte)
    insert_at = insert_at - shift if insert_at > start else insert_at
    text = statement.strip()
    return body[:insert_at] + indent + text + b"\n" + body[insert_at:]


def _line_start(source: bytes, byte: int) -> int:
    found = source.rfind(b"\n", 0, byte)
    return 0 if found == -1 else found + 1


def _line_end(source: bytes, byte: int) -> int:
    found = source.find(b"\n", byte)
    return len(source) if found == -1 else found + 1


def _indent_of(source: bytes, byte: int) -> bytes:
    start = _line_start(source, byte)
    indent = bytearray()
    for char in source[start:]:
        if char in (0x20, 0x09):
            indent.append(char)
        else:
            break
    return bytes(indent)


def repair_source(source: bytes, path_name: str = "<source>") -> tuple[bytes, Repair | None, list[Refusal]]:
    """The repaired bytes, the repair that was made, and what was refused."""
    declaration, after, found, refusals = _find_motion(source, path_name)
    if found is None:
        return source, None, refusals
    repaired = _move(source, declaration, after)
    if b"unsafe" in repaired and b"unsafe" not in source:
        raise RuntimeError("repair would introduce unsafe; refusing")
    return repaired, found, refusals


def repair_file(path: Path, name: str | None = None) -> tuple[Repair | None, list[Refusal]]:
    """Rewrite `path` in place if one safe motion exists."""
    original = path.read_bytes()
    repaired, found, refusals = repair_source(original, name or path.name)
    if found is None:
        return None, refusals
    if _parses_worse(original, repaired):
        raise RuntimeError("repair produced a file the Rust grammar rejects; refusing to write")
    path.write_bytes(repaired)
    return found, refusals


def _parses_worse(before: bytes, after: bytes) -> bool:
    """Guard against a rewrite that damages the file's syntax."""
    def errors(source: bytes) -> int:
        return sum(1 for node in syntax.walk(syntax.parse(source).root_node)
                   if node.type == "ERROR" or node.is_missing)

    return errors(after) > errors(before)
