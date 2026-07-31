#!/usr/bin/env python3
"""Standard-library verifier for the prospective double-ladder package."""

from __future__ import annotations

import argparse
import base64
from collections import Counter, deque
from hashlib import sha256
import gzip
from itertools import combinations
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence


Edge = tuple[int, int]


def edge(left: int, right: int) -> Edge:
    return (left, right) if left < right else (right, left)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def adjacency_from_edges(edges: Sequence[Edge], order: int) -> list[set[int]]:
    adjacency = [set() for _ in range(order)]
    if len(edges) != len(set(edges)):
        raise ValueError("duplicate canonical edge")
    for left, right in edges:
        if not (0 <= left < right < order):
            raise ValueError("edge is not normalized or in range")
        adjacency[left].add(right)
        adjacency[right].add(left)
    return adjacency


def connected(adjacency: Sequence[set[int]], removed: set[int] | None = None) -> bool:
    removed = removed or set()
    remaining = [vertex for vertex in range(len(adjacency)) if vertex not in removed]
    if not remaining:
        return True
    reached = {remaining[0]}
    pending = [remaining[0]]
    while pending:
        vertex = pending.pop()
        for neighbor in adjacency[vertex] - removed:
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    return len(reached) == len(remaining)


def three_connected(adjacency: Sequence[set[int]]) -> bool:
    vertices = range(len(adjacency))
    return all(
        connected(adjacency, set(removed))
        for size in (0, 1, 2)
        for removed in combinations(vertices, size)
    )


def bipartite(adjacency: Sequence[set[int]]) -> bool:
    colors: dict[int, int] = {}
    for start in range(len(adjacency)):
        if start in colors:
            continue
        colors[start] = 0
        pending = deque([start])
        while pending:
            vertex = pending.popleft()
            for neighbor in adjacency[vertex]:
                if neighbor not in colors:
                    colors[neighbor] = 1 - colors[vertex]
                    pending.append(neighbor)
                elif colors[neighbor] == colors[vertex]:
                    return False
    return True


def trace_faces(rotation: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    rows = tuple(tuple(map(int, row)) for row in rotation)
    unused = {(left, right) for left, row in enumerate(rows) for right in row}
    faces = []
    while unused:
        start = min(unused)
        dart = start
        face = []
        while True:
            if dart not in unused:
                if dart != start:
                    raise ValueError("rotation does not define facial walks")
                break
            unused.remove(dart)
            left, right = dart
            face.append(left)
            row = rows[right]
            position = row.index(left)
            dart = (right, row[(position - 1) % len(row)])
        faces.append(tuple(face))
    return tuple(faces)


def canonical_hash(rotation: Sequence[Sequence[int]]) -> str:
    rows = tuple(tuple(map(int, row)) for row in rotation)
    candidates = []
    for root in range(len(rows)):
        for first in rows[root]:
            for direction in (1, -1):
                labels = {root: 0, first: 1}
                parents = {root: first, first: root}
                vertices = [root, first]
                code = []
                position = 0
                while position < len(vertices):
                    vertex = vertices[position]
                    neighbors = rows[vertex]
                    anchor = neighbors.index(parents[vertex])
                    ordered = tuple(
                        neighbors[(anchor + direction * offset) % len(neighbors)]
                        for offset in range(len(neighbors))
                    )
                    for neighbor in ordered:
                        if neighbor not in labels:
                            labels[neighbor] = len(labels)
                            parents[neighbor] = vertex
                            vertices.append(neighbor)
                    code.append(tuple(labels[neighbor] for neighbor in ordered))
                    position += 1
                candidates.append(tuple(code))
    payload = json.dumps(min(candidates), separators=(",", ":")).encode("ascii")
    return sha256(payload).hexdigest()


def parse_planar_code(data: bytes) -> tuple[tuple[int, ...], ...]:
    header = b">>planar_code<<"
    if not data.startswith(header):
        raise ValueError("planar_code header missing")
    position = len(header)
    if position >= len(data):
        raise ValueError("planar_code graph missing")
    order = data[position]
    position += 1
    rows = []
    for _vertex in range(order):
        row = []
        while True:
            if position >= len(data):
                raise ValueError("truncated planar_code")
            value = data[position]
            position += 1
            if value == 0:
                break
            row.append(value - 1)
        rows.append(tuple(row))
    if position != len(data):
        raise ValueError("planar_code contains trailing records")
    return tuple(rows)


def parse_graph6(text: str) -> tuple[int, set[Edge]]:
    data = text.strip().encode("ascii")
    if not data or data[0] == 126:
        raise ValueError("verifier supports only short graph6 order encoding")
    order = data[0] - 63
    bits = []
    for value in data[1:]:
        number = value - 63
        if not 0 <= number < 64:
            raise ValueError("invalid graph6 character")
        bits.extend((number >> shift) & 1 for shift in range(5, -1, -1))
    needed = order * (order - 1) // 2
    if len(bits) < needed:
        raise ValueError("truncated graph6")
    edges = set()
    position = 0
    for right in range(1, order):
        for left in range(right):
            if bits[position]:
                edges.add((left, right))
            position += 1
    return order, edges


def cycle_edges(cycle: Sequence[int]) -> frozenset[Edge]:
    return frozenset(edge(left, right) for left, right in zip(cycle, cycle[1:] + cycle[:1]))


def normalize_cycle(cycle: Sequence[int]) -> tuple[int, ...]:
    body = tuple(cycle)
    minimum = min(body)
    position = body.index(minimum)
    forward = body[position:] + body[:position]
    reverse = tuple(reversed(body))
    position = reverse.index(minimum)
    backward = reverse[position:] + reverse[:position]
    return min(forward, backward)


def enumerate_via_matchings(edges: Sequence[Edge], order: int) -> tuple[tuple[int, ...], ...]:
    adjacency = adjacency_from_edges(edges, order)
    if any(len(row) != 3 for row in adjacency):
        raise ValueError("matching enumeration requires a cubic graph")
    all_edges = set(edges)
    cycles: set[tuple[int, ...]] = set()

    def visit(unmatched: frozenset[int], matching: tuple[Edge, ...]) -> None:
        if not unmatched:
            complement = all_edges - set(matching)
            rows = adjacency_from_edges(sorted(complement), order)
            if any(len(row) != 2 for row in rows):
                raise ValueError("matching complement is not 2-regular")
            path = [0]
            previous = None
            current = 0
            while True:
                choices = rows[current] - ({previous} if previous is not None else set())
                following = min(choices) if previous is None else next(iter(choices))
                if following == 0:
                    break
                path.append(following)
                previous, current = current, following
                if len(path) > order:
                    raise ValueError("2-factor did not close")
            if len(path) == order:
                cycles.add(normalize_cycle(path))
            return
        vertex = min(unmatched)
        for neighbor in sorted(adjacency[vertex] & set(unmatched)):
            visit(unmatched - {vertex, neighbor}, matching + (edge(vertex, neighbor),))

    visit(frozenset(range(order)), ())
    return tuple(sorted(cycles))


def verify_graph(directory: Path) -> tuple[dict[str, Any], tuple[Edge, ...], tuple[tuple[int, ...], ...]]:
    record = read_json(directory / "graph.json")
    order = int(record["order"])
    edges = tuple(tuple(map(int, item)) for item in record["canonical_edge_list"])
    adjacency = adjacency_from_edges(edges, order)
    rotation = tuple(tuple(map(int, row)) for row in record["rotation_system"])
    if len(rotation) != order:
        raise ValueError("rotation order mismatch")
    for vertex, row in enumerate(rotation):
        if set(row) != adjacency[vertex] or len(row) != len(set(row)):
            raise ValueError("rotation adjacency mismatch")
    faces = trace_faces(rotation)
    if [list(face) for face in faces] != record["faces"]:
        raise ValueError("stored face list mismatch")
    if order - len(edges) + len(faces) != 2 or sum(map(len, faces)) != 2 * len(edges):
        raise ValueError("Euler or facial dart arithmetic failed")
    if canonical_hash(rotation) != record["canonical_graph_hash"]:
        raise ValueError("canonical graph hash mismatch")
    if any(len(row) != 3 for row in adjacency):
        raise ValueError("graph is not cubic")
    if not bipartite(adjacency) or not three_connected(adjacency):
        raise ValueError("bipartiteness or 3-connectivity failed")
    planar = (directory / "planar_code").read_bytes()
    if sha256(planar).hexdigest() != record["planar_code_sha256"]:
        raise ValueError("planar_code hash mismatch")
    if parse_planar_code(planar) != rotation:
        raise ValueError("planar_code rotation mismatch")
    graph6_order, graph6_edges = parse_graph6((directory / "graph6").read_text(encoding="ascii"))
    if graph6_order != order or graph6_edges != set(edges):
        raise ValueError("graph6 mismatch")
    if sorted(map(len, faces)) != record["face_size_multiset"]:
        raise ValueError("face-size multiset mismatch")
    a = int(record["parameters"]["a"])
    b = int(record["parameters"]["b"])
    if order != 2 * (a + b) + 4:
        raise ValueError("double-ladder order formula mismatch")
    if sum(len(face) == 4 for face in faces) != a + b:
        raise ValueError("quadrilateral face count mismatch")
    if sorted(len(face) for face in faces if len(face) != 4) != sorted((a + 3, a + 3, b + 3, b + 3)):
        raise ValueError("cap-face signature mismatch")
    return record, edges, faces


def verify_expansion(directory: Path, target_edges: Sequence[Edge]) -> None:
    cert = read_json(directory / "expansion_certificate.json")
    source_edges = {tuple(map(int, item)) for item in cert["source_canonical_edge_list"]}
    mapping = {int(left): int(right) for left, right in cert["unchanged_source_to_target"]}
    if set(mapping) != {vertex for edge_value in source_edges for vertex in edge_value}:
        raise ValueError("expansion unchanged mapping is incomplete")
    reconstructed = {edge(mapping[left], mapping[right]) for left, right in source_edges}
    deleted = {tuple(map(int, item)) for item in cert["deleted_edges_target_labels"]}
    inserted = {tuple(map(int, item)) for item in cert["inserted_edges_target_labels"]}
    reconstructed.difference_update(deleted)
    reconstructed.update(inserted)
    if reconstructed != set(target_edges):
        raise ValueError("expansion reconstruction does not equal target")
    inserted_vertices = set(map(int, cert["inserted_vertices_target_labels"]))
    if len(inserted_vertices) != 4:
        raise ValueError("expansion did not insert four vertices")
    reduced = {value for value in target_edges if not (set(value) & inserted_vertices)}
    reduced.update(deleted)
    mapped_source = {edge(mapping[left], mapping[right]) for left, right in source_edges}
    if reduced != mapped_source:
        raise ValueError("inverse square reduction does not recover source")
    source_rotation = tuple(tuple(map(int, row)) for row in cert["source_rotation_system"])
    if canonical_hash(source_rotation) != cert["source_canonical_hash"]:
        raise ValueError("expansion source hash mismatch")


def verify_classification(
    directory: Path,
    record: dict[str, Any],
    universe: Sequence[Sequence[int]],
) -> None:
    stored = read_json(directory / "structural_cycle_classes.json")
    model = {
        int(vertex): (str(value[0]), int(value[1]), int(value[2]))
        for vertex, value in record["model_vertex_labels"]
    }
    inverse = {value: vertex for vertex, value in model.items()}
    a = int(record["parameters"]["a"])
    b = int(record["parameters"]["b"])
    connectors = (
        edge(inverse[("A", 0, 0)], inverse[("B", 0, 0)]),
        edge(inverse[("A", 0, 1)], inverse[("B", b, 0)]),
        edge(inverse[("A", a, 0)], inverse[("B", 0, 1)]),
        edge(inverse[("A", a, 1)], inverse[("B", b, 1)]),
    )
    recomputed = []
    counts: Counter[str] = Counter()
    pairs = set()
    for cycle_index, cycle in enumerate(universe):
        selected = cycle_edges(cycle)
        connector_bits = "".join("1" if item in selected else "0" for item in connectors)
        ladder_bits = []
        turns = []
        valid = True
        for name, length in (("A", a), ("B", b)):
            rungs = [edge(inverse[(name, column, 0)], inverse[(name, column, 1)]) for column in range(length + 1)]
            rails = [[edge(inverse[(name, column, rail)], inverse[(name, column + 1, rail)]) for column in range(length)] for rail in (0, 1)]
            rung_bits = "".join("1" if item in selected else "0" for item in rungs)
            rail_bits = ["".join("1" if item in selected else "0" for item in row) for row in rails]
            candidates = [position for position in range(length) if rail_bits[0][position] == rail_bits[1][position] == "0" and rung_bits[position:position + 2] == "11"]
            turns.append(candidates[0] if len(candidates) == 1 else None)
            valid &= len(candidates) == 1
            ladder_bits.append({"name": name, "rung_bits": rung_bits, "rail_bits": rail_bits})
        if connector_bits == "1111" and all(set(item["rung_bits"]) <= {"0"} for item in ladder_bits):
            classification = "all_rails"
            turns = [None, None]
        elif connector_bits == "1111" and valid:
            classification = "paired_cell_turns"
            pairs.add((turns[0], turns[1]))
        elif connector_bits.count("1") == 2:
            classification = "two_connector_exception"
            turns = [None, None]
        else:
            raise ValueError(f"unclassified cycle {cycle_index}")
        counts[classification] += 1
        recomputed.append({
            "cycle_index": cycle_index,
            "classification": classification,
            "connector_bits": connector_bits,
            "turn_cells": turns,
            "model_ladder_bits": ladder_bits,
        })
    if recomputed != stored["cycle_records"]:
        raise ValueError("stored structural cycle records mismatch")
    if dict(sorted(counts.items())) != stored["counts"]:
        raise ValueError("stored structural counts mismatch")
    if counts != Counter({"paired_cell_turns": a * b, "two_connector_exception": 4, "all_rails": 1}):
        raise ValueError("structural class formula mismatch")
    if pairs != {(left, right) for left in range(a) for right in range(b)}:
        raise ValueError("turn-position pair coverage mismatch")


def verify_hsep(
    directory: Path,
    edges: Sequence[Edge],
    universe: Sequence[Sequence[int]],
) -> tuple[int, int]:
    primal = read_json(directory / "primal_hsep_certificate.json")
    lower = read_json(directory / "lower_bound_certificate.json")
    edge_indexes = {value: index for index, value in enumerate(edges)}
    all_indexes = set(range(len(edges)))
    covered = set()
    primal_cycles = tuple(tuple(map(int, cycle)) for cycle in primal["primal_cycles"])
    universe_set = set(universe)
    for cycle in primal_cycles:
        if cycle not in universe_set:
            raise ValueError("primal cycle is absent from complete universe")
        selected = {edge_indexes[value] for value in cycle_edges(cycle)}
        covered.update((include, exclude) for include in selected for exclude in all_indexes - selected)
    requirements = {(include, exclude) for include in all_indexes for exclude in all_indexes if include != exclude}
    if covered != requirements:
        raise ValueError("primal family misses ordered edge-pair requirements")
    packing = tuple(tuple(map(int, item)) for item in lower["packing_requirements"])
    if len(packing) != len(set(packing)):
        raise ValueError("packing repeats a requirement")
    if any(include == exclude or include not in all_indexes or exclude not in all_indexes for include, exclude in packing):
        raise ValueError("invalid packing requirement index")
    for cycle in universe:
        selected = {edge_indexes[value] for value in cycle_edges(cycle)}
        if sum(include in selected and exclude not in selected for include, exclude in packing) > 1:
            raise ValueError("one Hamiltonian cycle covers two packing requirements")
    if len(primal_cycles) != len(packing):
        raise ValueError("primal and packing bounds do not match")
    return len(primal_cycles), len(requirements)


def verify_manifest(directory: Path, *, recursive: bool) -> int:
    manifest = directory / "SHA256SUMS.txt"
    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        value, relative = line.split("  ", 1)
        path = directory / Path(relative)
        if not path.is_file() or digest(path) != value:
            raise ValueError(f"manifest mismatch: {relative}")
        entries.append(relative)
    expected_paths = directory.rglob("*") if recursive else directory.glob("*")
    expected = sorted(
        path.relative_to(directory).as_posix()
        for path in expected_paths
        if path.is_file() and path != directory / "SHA256SUMS.txt"
    )
    if sorted(entries) != expected:
        raise ValueError("manifest path inventory mismatch")
    return len(entries)


def verify_package(root: Path, check_manifest: bool) -> dict[str, Any]:
    lock_hash = digest(root / "prediction_lock.json")
    lock = read_json(root / "prediction_lock.json")
    report_hash = None
    for line in (root / "PREDICTION_LOCK.md").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("`e8ba"):
            report_hash = line.strip().strip("`")
    if report_hash != lock_hash:
        raise ValueError("prediction lock SHA-256 mismatch")
    expected = {item["graph"]: item for item in lock["predictions"]}
    graph_results = []
    for directory in (root / "D_9_9", root / "D_11_9", root / "D_11_11"):
        record, edges, _faces = verify_graph(directory)
        verify_expansion(directory, edges)
        with gzip.open(directory / "hamiltonian_cycles.json.gz", "rt", encoding="utf-8") as source:
            universe_record = json.load(source)
        universe = tuple(tuple(map(int, cycle)) for cycle in universe_record["cycles"])
        if len(universe) != universe_record["complete_cycle_count"] or len(universe) != len(set(universe)):
            raise ValueError("cycle universe count or uniqueness mismatch")
        for cycle in universe:
            if len(cycle) != record["order"] or set(cycle) != set(range(record["order"])) or cycle_edges(cycle) > set(edges):
                raise ValueError("invalid Hamiltonian cycle")
            if normalize_cycle(cycle) != cycle:
                raise ValueError("non-normalized Hamiltonian cycle")
        independent = enumerate_via_matchings(edges, int(record["order"]))
        if independent != universe:
            raise ValueError("perfect-matching completeness enumeration disagrees")
        verify_classification(directory, record, universe)
        exact_hsep, requirements = verify_hsep(directory, edges, universe)
        prediction = expected[record["label"]]
        if len(universe) != prediction["predicted_hamiltonian_cycles"]:
            raise ValueError("Hamiltonian-cycle prediction failed")
        if exact_hsep != prediction["predicted_hsep"]:
            raise ValueError("hsep prediction failed")
        local_manifest_entries = verify_manifest(directory, recursive=False) if check_manifest else None
        graph_results.append({
            "graph": record["label"],
            "canonical_graph_hash": record["canonical_graph_hash"],
            "order": record["order"],
            "hamiltonian_cycle_count": len(universe),
            "exact_hsep": exact_hsep,
            "ordered_edge_pair_requirements": requirements,
            "construction": "pass",
            "barnette_properties": "pass",
            "complete_universe": "pass",
            "structural_classification": "pass",
            "primal_certificate": "pass",
            "lower_certificate": "pass",
            "local_manifest_entries": local_manifest_entries,
            "status": "pass",
        })
    global_entries = verify_manifest(root, recursive=True) if check_manifest else None
    return {
        "schema": "double-ladder-independent-verification-v1",
        "standard_library_only": True,
        "prediction_lock_sha256": lock_hash,
        "manifest_checked": check_manifest,
        "global_manifest_entries": global_entries,
        "graphs": graph_results,
        "all_passed": True,
        "scope": "graph-specific only; no M_B claim",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--check-manifest", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = verify_package(args.root.resolve(), args.check_manifest)
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if args.output:
        args.output.write_bytes(payload)
    else:
        sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
