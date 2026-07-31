#!/usr/bin/env python3
"""Standalone verifier for the double-ladder packing-lift analysis package.

Only the Python standard library is used.  The verifier checks the emitted
graph/cycle/requirement data and both original and structural packing
certificates; it does not claim to re-prove completeness of the immutable
Hamiltonian universes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def edge_set(cycle: list[int]) -> set[tuple[int, int]]:
    return {
        tuple(sorted((left, right)))
        for left, right in zip(cycle, cycle[1:] + cycle[:1])
    }


def verify_manifest(root: Path) -> int:
    checked = 0
    for raw in (root / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        expected, relative = raw.split(None, 1)
        target = root / Path(relative.strip().lstrip("*").replace("/", "\\"))
        if not target.is_file():
            raise AssertionError(f"manifest target missing: {relative}")
        actual = sha256_file(target)
        if actual != expected:
            raise AssertionError(f"manifest mismatch for {relative}: {actual} != {expected}")
        checked += 1
    return checked


def verify_source_inventory(root: Path) -> int:
    inventory = read_json(root / "artifact_inventory.json")
    checked = 0
    for graph in inventory["graphs"]:
        for artifact in graph["artifacts"]:
            path = Path(artifact["path"])
            if not path.is_file():
                raise AssertionError(f"immutable source artifact missing: {path}")
            if sha256_file(path) != artifact["sha256"]:
                raise AssertionError(f"immutable source artifact changed: {path}")
            checked += 1
    for manifest in inventory["verified_manifests"]:
        if manifest["status"] != "pass":
            raise AssertionError(f"producer recorded failed source manifest: {manifest['path']}")
    return checked


def verify_requirement_pack(
    edges: list[tuple[int, int]],
    cycle_edges: list[set[tuple[int, int]]],
    cycle_keys: list[str],
    requirements: list[list[int]],
    expected_size: int,
) -> dict[str, Any]:
    if len(requirements) != expected_size:
        raise AssertionError(f"packing size {len(requirements)} != {expected_size}")
    supports = []
    for included_index, excluded_index in requirements:
        if included_index == excluded_index:
            raise AssertionError("requirement repeats its edge")
        included = edges[included_index]
        excluded = edges[excluded_index]
        support = tuple(
            index
            for index, selected in enumerate(cycle_edges)
            if included in selected and excluded not in selected
        )
        if not support:
            raise AssertionError("packing requirement has empty coverage")
        supports.append(support)
    flat = [index for support in supports for index in support]
    if len(flat) != len(set(flat)):
        raise AssertionError("packing coverage sets intersect")
    support_sizes: dict[str, int] = {}
    for support in supports:
        key = str(len(support))
        support_sizes[key] = support_sizes.get(key, 0) + 1
    uncovered = sorted(set(cycle_keys) - {cycle_keys[index] for index in flat})
    return {
        "requirement_count": len(requirements),
        "covered_cycle_count": len(flat),
        "support_size_distribution": support_sizes,
        "uncovered_cycle_classes": uncovered,
    }


def verify_graph(record: dict[str, Any]) -> dict[str, Any]:
    order = int(record["order"])
    a = int(record["a"])
    b = int(record["b"])
    edges = [tuple(map(int, edge)) for edge in record["edges"]]
    if len(edges) != 3 * order // 2 or len(set(edges)) != len(edges):
        raise AssertionError("edge list is not a simple cubic-size edge list")
    degree = [0] * order
    adjacency = [set() for _ in range(order)]
    for left, right in edges:
        if not (0 <= left < right < order):
            raise AssertionError("edge list is not normalized")
        degree[left] += 1
        degree[right] += 1
        adjacency[left].add(right)
        adjacency[right].add(left)
    if set(degree) != {3}:
        raise AssertionError("graph is not cubic")
    cycles = [list(map(int, cycle)) for cycle in record["cycles"]]
    cycle_edges = []
    for cycle in cycles:
        if len(cycle) != order or set(cycle) != set(range(order)):
            raise AssertionError("cycle is not Hamiltonian")
        selected = edge_set(cycle)
        if len(selected) != order or not selected <= set(edges):
            raise AssertionError("cycle uses a nonedge")
        cycle_edges.append(selected)
    if len({tuple(cycle) for cycle in cycles}) != len(cycles):
        raise AssertionError("cycle universe contains duplicates")
    cycle_keys = list(record["cycle_keys"])
    if len(cycle_keys) != len(cycles) or len(set(cycle_keys)) != len(cycles):
        raise AssertionError("cycle-class keys are not a bijection")
    expected_classes = {"R", "X0011", "X0101", "X1010", "X1100"}
    expected_classes |= {f"T({i},{j})" for i in range(a) for j in range(b)}
    if set(cycle_keys) != expected_classes:
        raise AssertionError("Hamiltonian cycle classification is incomplete")
    formula = ((a + 2) * (b + 2) - 1) // 2
    original = verify_requirement_pack(
        edges, cycle_edges, cycle_keys, record["original_requirements"], formula
    )
    structural = verify_requirement_pack(
        edges, cycle_edges, cycle_keys, record["structural_requirements"], formula
    )
    if structural["uncovered_cycle_classes"] != ["R", f"T({a - 2},{b - 2})"]:
        raise AssertionError("structural packing has the wrong two uncovered classes")
    return {
        "label": record["label"],
        "hash": record["canonical_graph_hash"],
        "order": order,
        "cycle_count": len(cycles),
        "original": original,
        "structural": structural,
    }


def verify_expansion(record: dict[str, Any], graph_by_label: dict[str, dict[str, Any]]) -> None:
    source = graph_by_label[record["source"]]
    target = graph_by_label[record["target"]]
    target_edges = {tuple(edge) for edge in target["edges"]}
    vertex_map = {int(left): int(right) for left, right in record["unchanged_vertex_map"]}
    paths = record["source_edge_to_target_paths"]
    if len(paths) != len(source["edges"]):
        raise AssertionError("expansion edge map is incomplete")
    for item in paths:
        source_edge = tuple(source["edges"][item["source_edge_index"]])
        target_path = [tuple(target["edges"][index]) for index in item["target_path_edge_indices"]]
        if not target_path or not set(target_path) <= target_edges:
            raise AssertionError("expansion path uses a target nonedge")
        path_vertices: dict[int, int] = {}
        for left, right in target_path:
            path_vertices[left] = path_vertices.get(left, 0) + 1
            path_vertices[right] = path_vertices.get(right, 0) + 1
        endpoints = sorted(vertex for vertex, degree in path_vertices.items() if degree == 1)
        expected = sorted(vertex_map[vertex] for vertex in source_edge)
        if endpoints != expected:
            raise AssertionError("expansion path has wrong endpoints")


def verify(root: Path, check_manifest: bool) -> dict[str, Any]:
    if check_manifest:
        manifest_entries = verify_manifest(root)
    else:
        manifest_entries = 0
    source_artifacts = verify_source_inventory(root)
    with gzip.open(root / "verification_data.json.gz", "rt", encoding="utf-8") as source:
        data = json.load(source)
    graphs = [verify_graph(record) for record in data["graphs"]]
    raw_graph_by_label = {record["label"]: record for record in data["graphs"]}
    for expansion in data["expansions"]:
        verify_expansion(expansion, raw_graph_by_label)
    return {
        "schema": "double-ladder-packing-lift-independent-verification-v1",
        "status": "pass",
        "manifest_entries_checked": manifest_entries,
        "immutable_source_artifacts_checked": source_artifacts,
        "graphs": graphs,
        "expansion_count": len(data["expansions"]),
        "scope_note": (
            "Cycle validity, class coverage, and packing disjointness are checked here. "
            "Completeness of the immutable cycle universes is inherited by hash from the "
            "pre-existing independently verified packages."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--check-manifest", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.root.resolve(), args.check_manifest)
    except Exception as error:  # verifier must fail closed
        print(f"PACKING_LIFT_VERIFICATION_FAILED: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("PACKING_LIFT_PACKAGE_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
