#!/usr/bin/env python3
"""Standard-library verifier for the double-ladder primal-lift package."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


EXCEPTIONS = ("X0011", "X1100", "X0101", "X1010")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def cycle_edges(cycle: list[int]) -> frozenset[tuple[int, int]]:
    return frozenset(
        tuple(sorted((left, right)))
        for left, right in zip(cycle, cycle[1:] + cycle[:1])
    )


def parse_turn(key: str) -> tuple[int, int] | None:
    if not key.startswith("T("):
        return None
    left, right = key[2:-1].split(",")
    return int(left), int(right)


def symbolic_family(a: int, b: int) -> tuple[str, ...]:
    turns = [
        f"T({i},{j})"
        for i in range(a)
        for j in range(b)
        if i in (0, a - 1)
        or j in (0, b - 1)
        or (0 < i < a - 1 and 0 < j < b - 1 and (i + j) % 2 == 1)
    ]
    return (*EXCEPTIONS, *turns)


def symbolic_incidence(
    edge: list[Any], cycle_key: str, a: int, b: int
) -> bool:
    turn = parse_turn(cycle_key)
    if turn is not None:
        i, j = turn
        if edge[0] == "C":
            return True
        coordinate = i if edge[0] == "A" else j
        if edge[1] == "rail":
            return coordinate != edge[2]
        return coordinate in (edge[2] - 1, edge[2])
    if edge[0] == "C":
        return cycle_key[1:][edge[1]] == "1"
    ladder, kind = edge[:2]
    if cycle_key == "X0011":
        if ladder == "A":
            return kind == "rail" or (kind == "rung" and edge[2] == 0)
        return kind == "rung" or (kind == "rail" and edge[3] == edge[2] % 2)
    if cycle_key == "X1100":
        if ladder == "A":
            return kind == "rail" or (kind == "rung" and edge[2] == a)
        return kind == "rung" or (kind == "rail" and edge[3] != edge[2] % 2)
    if cycle_key == "X0101":
        if ladder == "A":
            return kind == "rung" or (kind == "rail" and edge[3] == edge[2] % 2)
        return kind == "rail" or (kind == "rung" and edge[2] == 0)
    if cycle_key != "X1010":
        raise AssertionError(f"unexpected cycle key {cycle_key}")
    if ladder == "A":
        return kind == "rung" or (kind == "rail" and edge[3] != edge[2] % 2)
    return kind == "rail" or (kind == "rung" and edge[2] == b)


def verify_manifest(root: Path) -> int:
    checked = 0
    for raw in (root / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        expected, relative = raw.split(None, 1)
        target = root / Path(relative.strip().lstrip("*").replace("/", "\\"))
        if not target.is_file() or sha256_file(target) != expected:
            raise AssertionError(f"manifest failure: {relative}")
        checked += 1
    return checked


def verify_sources(root: Path) -> int:
    inventory = read_json(root / "source_inventory.json")
    checked = 0
    for artifact in inventory["artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise AssertionError(f"immutable source changed: {path}")
        checked += 1
    if any(item["status"] != "pass" for item in inventory["manifest_checks"]):
        raise AssertionError("producer recorded a failed immutable manifest")
    return checked


def verify_graph(record: dict[str, Any]) -> dict[str, Any]:
    a, b, order = record["a"], record["b"], record["order"]
    edges = [tuple(edge) for edge in record["edges"]]
    if len(edges) != 3 * order // 2 or len(set(edges)) != len(edges):
        raise AssertionError("bad edge count or duplicate edge")
    degree = [0] * order
    for left, right in edges:
        if not (0 <= left < right < order):
            raise AssertionError("edge list is not normalized")
        degree[left] += 1
        degree[right] += 1
    if set(degree) != {3}:
        raise AssertionError("graph is not cubic")
    cycles = [list(map(int, cycle)) for cycle in record["cycles"]]
    cycle_edge_sets = []
    for cycle in cycles:
        if len(cycle) != order or set(cycle) != set(range(order)):
            raise AssertionError("non-Hamiltonian cycle")
        selected = cycle_edges(cycle)
        if len(selected) != order or not selected <= set(edges):
            raise AssertionError("cycle uses a nonedge")
        cycle_edge_sets.append(selected)
    keys = list(record["cycle_keys"])
    expected_universe = {"R", *EXCEPTIONS} | {
        f"T({i},{j})" for i in range(a) for j in range(b)
    }
    if len(keys) != len(cycles) or set(keys) != expected_universe:
        raise AssertionError("cycle classification mismatch")
    expected_family = set(symbolic_family(a, b))
    formula = ((a + 2) * (b + 2) - 1) // 2
    if len(expected_family) != formula:
        raise AssertionError("symbolic cardinality mismatch")
    original = tuple(record["original_primal_indices"])
    symbolic = tuple(record["symbolic_primal_indices"])
    if len(original) != formula or set(original) != set(symbolic):
        raise AssertionError("stored primal is not the symbolic family")
    if {keys[index] for index in symbolic} != expected_family:
        raise AssertionError("selected structural classes mismatch")

    signatures = []
    for edge_index, edge in enumerate(edges):
        signature = frozenset(
            ordinal
            for ordinal, cycle_index in enumerate(symbolic)
            if edge in cycle_edge_sets[cycle_index]
        )
        symbolic_edge = record["symbolic_edges"][edge_index]
        formula_signature = frozenset(
            ordinal
            for ordinal, cycle_index in enumerate(symbolic)
            if symbolic_incidence(symbolic_edge, keys[cycle_index], a, b)
        )
        if signature != formula_signature:
            raise AssertionError(f"symbolic incidence mismatch on edge {edge_index}")
        signatures.append(signature)
    if len(set(signatures)) != len(edges):
        raise AssertionError("edge signatures are not distinct")
    for left in range(len(edges)):
        for right in range(left + 1, len(edges)):
            if signatures[left] <= signatures[right] or signatures[right] <= signatures[left]:
                raise AssertionError(f"signature containment: {left},{right}")
    ordered_covered = sum(
        bool(signatures[left] - signatures[right])
        for left in range(len(edges))
        for right in range(len(edges))
        if left != right
    )
    if ordered_covered != len(edges) * (len(edges) - 1):
        raise AssertionError("not every ordered edge pair is separated")
    return {
        "label": record["label"],
        "hash": record["canonical_graph_hash"],
        "cycle_count": len(cycles),
        "primal_size": formula,
        "edge_count": len(edges),
        "ordered_requirements_verified": ordered_covered,
    }


def injected_key(key: str, axis: str) -> str:
    turn = parse_turn(key)
    if turn is None:
        return key
    i, j = turn
    if axis == "A" and i > 0:
        i += 2
    if axis == "B" and j > 0:
        j += 2
    return f"T({i},{j})"


def verify_lift(
    record: dict[str, Any], graph_by_label: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    source = graph_by_label[record["source"]]
    target = graph_by_label[record["target"]]
    axis = record["axis"]
    source_keys = {
        source["cycle_keys"][index] for index in source["symbolic_primal_indices"]
    }
    target_keys = {
        target["cycle_keys"][index] for index in target["symbolic_primal_indices"]
    }
    mapped = {injected_key(key, axis) for key in source_keys}
    if not mapped <= target_keys:
        raise AssertionError("structural primal nesting fails")
    new = target_keys - mapped
    expected = source["a"] + 2 if axis == "B" else source["b"] + 2
    if len(new) != expected or set(record["new_target_cycle_classes"]) != new:
        raise AssertionError("lifting increment mismatch")

    paths = {
        item["source_edge_index"]: tuple(item["target_path_edge_indices"])
        for item in record["source_edge_to_target_paths"]
    }
    source_edge_index = {tuple(edge): index for index, edge in enumerate(source["edges"])}
    source_cycle_edges = [
        frozenset(source_edge_index[edge] for edge in cycle_edges(cycle))
        for cycle in source["cycles"]
    ]
    target_edge_index = {tuple(edge): index for index, edge in enumerate(target["edges"])}
    target_cycle_lookup = {
        frozenset(target_edge_index[edge] for edge in cycle_edges(cycle)): index
        for index, cycle in enumerate(target["cycles"])
    }
    target_selected = set(target["symbolic_primal_indices"])
    direct = {}
    for cycle_index in source["symbolic_primal_indices"]:
        mapped_edges = frozenset(
            target_edge
            for source_edge in source_cycle_edges[cycle_index]
            for target_edge in paths[source_edge]
        )
        target_cycle = target_cycle_lookup.get(mapped_edges)
        if target_cycle is not None and target_cycle in target_selected:
            direct[cycle_index] = target_cycle
    if len(direct) != record["literal_direct_geometric_lift_count"]:
        raise AssertionError("direct geometric lift count mismatch")
    repaired = {
        source["cycle_keys"][index]
        for index in source["symbolic_primal_indices"]
        if index not in direct
    }
    if repaired != set(record["locally_repaired_source_cycle_classes"]):
        raise AssertionError("local repair class list mismatch")
    if len(repaired) != expected:
        raise AssertionError("unexpected repair count")
    return {
        "transition": f"{record['source']} -> {record['target']}",
        "direct_lifts": len(direct),
        "local_repairs": len(repaired),
        "new_cycles": len(new),
    }


def verify(root: Path, check_manifest: bool) -> dict[str, Any]:
    manifest_entries = verify_manifest(root) if check_manifest else 0
    source_count = verify_sources(root)
    with gzip.open(root / "verification_data.json.gz", "rt", encoding="utf-8") as source:
        data = json.load(source)
    graphs = [verify_graph(record) for record in data["graphs"]]
    by_label = {record["label"]: record for record in data["graphs"]}
    lifts = [verify_lift(record, by_label) for record in data["lifts"]]
    return {
        "schema": "double-ladder-primal-lift-independent-verification-v1",
        "status": "pass",
        "manifest_entries_checked": manifest_entries,
        "immutable_source_artifacts_checked": source_count,
        "graphs": graphs,
        "lifts": lifts,
        "scope_note": (
            "All finite cycles, signatures, ordered edge-pair separations and literal lift "
            "counts are recomputed. Completeness of the immutable cycle universes is inherited "
            "by source hash."
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
    except Exception as error:
        print(f"PRIMAL_LIFT_VERIFICATION_FAILED: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("PRIMAL_LIFT_PACKAGE_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
