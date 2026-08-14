#!/usr/bin/env python3

import time
from pathlib import Path

import lsp_semantic_feasibility as base


def scan_edges(client: base.LspClient, files: list[Path], src: Path) -> set[str]:
    edges: set[str] = set()
    for path in files:
        origin = base.module_name(path.resolve(), src)
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines()):
            for match in base.IDENT.finditer(line):
                target_path = base.location_path(client.definition(path, line_no, match.start()))
                if target_path is None or not target_path.is_relative_to(src):
                    continue
                target = base.module_name(target_path, src)
                if target != origin and target != "__root__":
                    edges.add(f"{origin}->{target}")
    return edges


def semantic_internal_edges(root: Path, crate: str = "domain") -> list[str]:
    src = (root / crate / "src").resolve()
    files = sorted(src.rglob("*.rs"))
    client = base.LspClient(root)
    try:
        for path in files:
            client.open_document(path)

        # initialize completes before rust-analyzer necessarily finishes loading
        # Cargo metadata. This fixture always contains audit->value and policy->value,
        # so an empty graph is a reliable not-ready signal rather than a valid result.
        deadline = time.monotonic() + 15.0
        while True:
            edges = scan_edges(client, files, src)
            if edges:
                return sorted(edges)
            if time.monotonic() >= deadline:
                raise RuntimeError("rust-analyzer never produced the known baseline semantic edges")
            time.sleep(0.2)
    finally:
        client.close()


base.semantic_internal_edges = semantic_internal_edges

if __name__ == "__main__":
    raise SystemExit(base.main())
