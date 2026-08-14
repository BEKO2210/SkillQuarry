#!/usr/bin/env python3
"""Validate every skill manifest against registry/schema.json. Standard library only.

The repository refuses third-party runtime dependencies, so this implements the
subset of JSON Schema the manifest schema actually uses — type, required,
properties, additionalProperties, enum, pattern, const, numeric bounds, string
lengths, array bounds and uniqueItems — and nothing else. An unknown keyword in
the schema is an error rather than a silently skipped check.

It then applies the rules a schema cannot express: the manifest must match its
location on disk, and every file it points at must exist.

    python3 tools/validate_skills.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"""^\s*(?:__version__|version)\s*[:=]\s*["'](?P<version>[^"']+)["']""", re.MULTILINE)
SCHEMA_PATH = REPO / "registry" / "schema.json"
SKILLS_DIR = REPO / "skills"
WORKFLOW_DIR = REPO / ".github" / "workflows"

SUPPORTED_KEYWORDS = {
    "$schema", "$id", "title", "description", "type", "required", "properties",
    "additionalProperties", "enum", "const", "pattern", "minimum", "maximum",
    "minLength", "maxLength", "items", "minItems", "maxItems", "uniqueItems",
}

TYPE_MAP: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return isinstance(value, TYPE_MAP[expected])


def validate(value: Any, schema: dict[str, Any], where: str = "$") -> list[str]:
    """Return every schema violation found in `value`, as human-readable strings."""
    unknown = set(schema) - SUPPORTED_KEYWORDS
    if unknown:
        return [f"{where}: schema uses unsupported keywords: {', '.join(sorted(unknown))}"]

    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type and not _type_matches(value, expected_type):
        return [f"{where}: expected {expected_type}, found {type(value).__name__}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{where}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} is not one of {schema['enum']}")

    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{where}: {value!r} does not match {schema['pattern']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{where}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{where}: longer than {schema['maxLength']} characters")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{where}: above maximum {schema['maximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{where}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and len(value) != len({json.dumps(item, sort_keys=True) for item in value}):
            errors.append(f"{where}: items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors += validate(item, item_schema, f"{where}[{index}]")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in value:
                errors.append(f"{where}: missing required field {field!r}")
        if schema.get("additionalProperties") is False:
            for field in value:
                if field not in properties:
                    errors.append(f"{where}: unknown field {field!r}")
        for field, subschema in properties.items():
            if field in value:
                errors += validate(value[field], subschema, f"{where}.{field}")

    return errors


def _referenced_files(manifest: dict[str, Any], directory: Path) -> list[tuple[str, Path]]:
    """Paths the manifest promises exist, with the base each one is relative to."""
    references: list[tuple[str, Path]] = []
    for key in ("research",):
        if manifest.get(key):
            references.append((f"{key}: {manifest[key]}", directory / manifest[key]))
    for key in ("banner",):
        if manifest.get(key):
            references.append((f"{key}: {manifest[key]}", REPO / manifest[key]))
    if manifest.get("icon"):
        references.append((f"icon: {manifest['icon']}", (directory / manifest["icon"]).resolve()))
    entrypoints = manifest.get("entrypoints", {})
    for key in ("skill", "install", "uninstall"):
        if entrypoints.get(key):
            references.append((f"entrypoints.{key}: {entrypoints[key]}", directory / entrypoints[key]))
    report = manifest.get("tests", {}).get("report")
    if report:
        references.append((f"tests.report: {report}", directory / report))
    return references


def declared_versions(directory: Path) -> dict[str, str]:
    """Versions the skill states about itself outside the manifest.

    A skill that says 1.0.0 in its manifest and 0.9.0 in its package metadata has
    already lied to somebody; the registry must not have to guess which is true.
    """
    found: dict[str, str] = {}
    candidates = [directory / "pyproject.toml", *sorted(directory.glob("src/*/core.py")),
                  *sorted(directory.glob("src/*/runner.py"))]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        match = VERSION_PATTERN.search(candidate.read_text("utf-8"))
        if match:
            found[candidate.relative_to(directory).as_posix()] = match.group("version")
    return found


def check_security(manifest: dict[str, Any], relative: str) -> list[str]:
    """A skill that can run commands must say so in machine-readable form."""
    shell = (manifest.get("permissions") or {}).get("shell", "none")
    runs_commands = shell.strip().lower() not in {"", "none"}
    security = manifest.get("security")
    if runs_commands and not security:
        return [f"{relative}: permissions.shell is {shell!r}, so a `security` block is required"]
    if not security:
        return []
    errors: list[str] = []
    if runs_commands and security.get("runs_external_commands") is not True:
        errors.append(f"{relative}: permissions.shell describes commands, but security.runs_external_commands is false")
    threat_model = security.get("threat_model")
    if threat_model and not (REPO / relative).parent.joinpath(threat_model).exists():
        errors.append(f"{relative}: security.threat_model {threat_model} does not exist")
    return errors


def load_all_manifests() -> dict[str, dict[str, Any]]:
    found = {}
    for path in sorted(SKILLS_DIR.glob("*/*/skill.json")):
        try:
            found[path.parent.name] = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    return found


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("-")[0].split(".")[:3])


def check_relations(manifests: dict[str, dict[str, Any]]) -> list[str]:
    """Dependencies must resolve, satisfy their minimum, and form no cycle.

    A dependency graph that only works by accident is worse than none: the client
    installs in this order, so a cycle would loop and a missing name would fail
    halfway through someone's machine.
    """
    errors: list[str] = []
    for name, manifest in sorted(manifests.items()):
        for entry in manifest.get("dependencies") or []:
            target = str(entry.get("name"))
            if target == name:
                errors.append(f"{name}: depends on itself")
                continue
            if target not in manifests:
                errors.append(f"{name}: depends on {target!r}, which is not in this quarry")
                continue
            minimum = entry.get("minimum_version")
            if minimum and _version_tuple(str(manifests[target]["version"])) < _version_tuple(minimum):
                errors.append(
                    f"{name}: needs {target} >= {minimum}, but the quarry has {manifests[target]['version']}"
                )
        for partner in manifest.get("composes_with") or []:
            if partner not in manifests:
                errors.append(f"{name}: composes_with names {partner!r}, which is not in this quarry")
            elif partner == name:
                errors.append(f"{name}: composes_with names itself")

    # Cycle detection over the dependency edges.
    colour: dict[str, int] = {}

    def visit(node: str, trail: list[str]) -> None:
        colour[node] = 1
        for entry in manifests.get(node, {}).get("dependencies") or []:
            target = str(entry.get("name"))
            if target not in manifests:
                continue
            if colour.get(target) == 1:
                cycle = " -> ".join(trail + [node, target])
                errors.append(f"dependency cycle: {cycle}")
            elif colour.get(target, 0) == 0:
                visit(target, trail + [node])
        colour[node] = 2

    for name in sorted(manifests):
        if colour.get(name, 0) == 0:
            visit(name, [])
    return errors


def install_order(manifests: dict[str, dict[str, Any]], name: str) -> list[str]:
    """Dependencies first, then the skill itself. Assumes the graph is valid."""
    order: list[str] = []
    seen: set[str] = set()

    def walk(current: str) -> None:
        if current in seen or current not in manifests:
            return
        seen.add(current)
        for entry in manifests[current].get("dependencies") or []:
            walk(str(entry.get("name")))
        order.append(current)

    walk(name)
    return order


def check_layout(manifest: dict[str, Any], path: Path) -> list[str]:
    """Rules about the world outside the JSON document itself."""
    directory = path.parent
    relative = directory.relative_to(REPO).as_posix()
    errors: list[str] = []
    if manifest.get("name") != directory.name:
        errors.append(f"{relative}: name {manifest.get('name')!r} does not match the directory name")
    if manifest.get("category") != directory.parent.name:
        errors.append(f"{relative}: category {manifest.get('category')!r} does not match the directory {directory.parent.name!r}")
    for label, target in _referenced_files(manifest, directory):
        if not target.exists():
            errors.append(f"{relative}: {label} does not exist")
    workflow = manifest.get("workflow") or f"{manifest.get('name')}-tests.yml"
    if not (WORKFLOW_DIR / workflow).exists():
        errors.append(f"{relative}: CI workflow .github/workflows/{workflow} does not exist")
    for required_doc in ("README.md", "SKILL.md"):
        if not (directory / required_doc).exists():
            errors.append(f"{relative}: {required_doc} is required by the skill specification")
    for source, version in declared_versions(directory).items():
        if version != manifest.get("version"):
            errors.append(
                f"{relative}: {source} declares version {version!r}, manifest says {manifest.get('version')!r}"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    manifests = sorted(SKILLS_DIR.glob("*/*/skill.json"))
    if not manifests:
        print("validate_skills: no manifests found under skills/*/*/skill.json", file=sys.stderr)
        return 2

    relation_errors = check_relations(load_all_manifests())
    for error in relation_errors:
        print(f"FAIL relations: {error}", file=sys.stderr)

    failures = 1 if relation_errors else 0
    for path in manifests:
        relative = path.relative_to(REPO).as_posix()
        try:
            manifest = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"FAIL {relative}: unreadable: {exc}", file=sys.stderr)
            failures += 1
            continue
        errors = (
            validate(manifest, schema, relative)
            + check_layout(manifest, path)
            + check_security(manifest, relative)
        )
        if errors:
            failures += 1
            print(f"FAIL {relative}", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(f"ok   {relative}")

    if failures:
        print(f"validate_skills: {failures} of {len(manifests)} manifests are invalid", file=sys.stderr)
        return 1
    print(f"validate_skills: {len(manifests)} manifests valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
