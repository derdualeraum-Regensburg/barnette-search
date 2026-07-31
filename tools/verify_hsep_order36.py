#!/usr/bin/env python3
"""Standalone standard-library verifier for order-36 hsep certificates.

This file intentionally imports nothing from ``barnette_search`` and invokes no
SAT solver.  It checks graph encodings, canonical graph hashes, normalized
Hamiltonian cycles, every ordered edge-pair requirement, exact-cycle universes,
packing lower bounds, census coverage, and (optionally) SHA256SUMS.txt.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Iterable, Iterator, Sequence


ORDER = 36
EDGE_COUNT = 54
REQUIREMENTS = EDGE_COUNT * (EDGE_COUNT - 1)
GRAPH_COUNT = 15_374
BARNIE_HASH = "2f96ada16c46cd2bd038b97d5af44f46ed14522cba1edf3fa041d66e02107bcc"
HEADER = b">>planar_code<<"
SCHEMA = "barnette-hsep-order36-certificate-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_cycle(cycle: Iterable[int]) -> tuple[int, ...]:
    values = tuple(int(vertex) for vertex in cycle)
    if len(values) >= 2 and values[0] == values[-1]:
        values = values[:-1]
    if len(values) < 3 or len(set(values)) != len(values):
        raise ValueError("cycle vertices are not distinct")
    variants: list[tuple[int, ...]] = []
    for oriented in (values, tuple(reversed(values))):
        minimum = min(oriented)
        for index, vertex in enumerate(oriented):
            if vertex == minimum:
                variants.append(oriented[index:] + oriented[:index])
    return min(variants)


def parse_planar_code(data: bytes) -> tuple[tuple[int, ...], ...]:
    if not data.startswith(HEADER):
        raise ValueError("planar_code header is absent")
    position = len(HEADER)
    if position >= len(data):
        raise ValueError("planar_code has no graph record")
    order = data[position]
    position += 1
    if order == 0:
        raise ValueError("planar_code order is zero")
    rows: list[tuple[int, ...]] = []
    for _ in range(order):
        neighbors: list[int] = []
        while True:
            if position >= len(data):
                raise ValueError("planar_code is truncated")
            value = data[position]
            position += 1
            if value == 0:
                break
            if value > order:
                raise ValueError("planar_code neighbor is out of range")
            neighbors.append(value - 1)
        rows.append(tuple(neighbors))
    if position != len(data):
        raise ValueError("planar_code contains multiple records or trailing data")
    rotation = tuple(rows)
    for vertex, neighbors in enumerate(rotation):
        if vertex in neighbors or len(neighbors) != len(set(neighbors)):
            raise ValueError("planar_code graph is not simple")
        if any(vertex not in rotation[neighbor] for neighbor in neighbors):
            raise ValueError("planar_code adjacency is not symmetric")
    return rotation


def edges_from_rotation(rotation: Sequence[Sequence[int]]) -> tuple[tuple[int, int], ...]:
    return tuple(
        sorted(
            {
                (min(vertex, neighbor), max(vertex, neighbor))
                for vertex, row in enumerate(rotation)
                for neighbor in row
            }
        )
    )


def connected(rotation: Sequence[Sequence[int]], removed: frozenset[int] = frozenset()) -> bool:
    remaining = set(range(len(rotation))) - set(removed)
    if not remaining:
        return True
    start = min(remaining)
    reached = {start}
    pending = [start]
    while pending:
        vertex = pending.pop()
        for neighbor in rotation[vertex]:
            if neighbor in remaining and neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    return reached == remaining


def trace_faces(rotation: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    unused = {(u, v) for u, row in enumerate(rotation) for v in row}
    faces: list[tuple[int, ...]] = []
    while unused:
        start = min(unused)
        dart = start
        boundary: list[int] = []
        while True:
            if dart not in unused:
                if dart != start:
                    raise ValueError("rotation does not define facial walks")
                break
            unused.remove(dart)
            left, right = dart
            boundary.append(left)
            row = rotation[right]
            try:
                position = row.index(left)
            except ValueError as error:
                raise ValueError("rotation adjacency is asymmetric") from error
            dart = (right, row[(position - 1) % len(row)])
        faces.append(tuple(boundary))
    return tuple(faces)


def verify_barnette_rotation(rotation: Sequence[Sequence[int]]) -> tuple[int, ...]:
    order = len(rotation)
    if order != ORDER or any(len(row) != 3 for row in rotation):
        raise ValueError("graph is not order-36 cubic")
    if not connected(rotation):
        raise ValueError("graph is disconnected")
    color: dict[int, int] = {}
    for root in range(order):
        if root in color:
            continue
        color[root] = 0
        pending = [root]
        while pending:
            vertex = pending.pop()
            for neighbor in rotation[vertex]:
                if neighbor not in color:
                    color[neighbor] = 1 - color[vertex]
                    pending.append(neighbor)
                elif color[neighbor] == color[vertex]:
                    raise ValueError("graph is not bipartite")
    for left in range(order):
        if not connected(rotation, frozenset((left,))):
            raise ValueError("graph has a cut vertex")
        for right in range(left + 1, order):
            if not connected(rotation, frozenset((left, right))):
                raise ValueError("graph has a two-vertex cut")
    edges = edges_from_rotation(rotation)
    faces = trace_faces(rotation)
    if order - len(edges) + len(faces) != 2:
        raise ValueError("rotation is not a cellular sphere embedding")
    return tuple(sorted(map(len, faces)))


def canonical_graph_hash(rotation: Sequence[Sequence[int]]) -> str:
    candidates: list[tuple[tuple[int, ...], ...]] = []
    for root in range(len(rotation)):
        for first in rotation[root]:
            for direction in (1, -1):
                labels = {root: 0, first: 1}
                parents = {root: first, first: root}
                vertices = [root, first]
                rows: list[tuple[int, ...]] = []
                position = 0
                while position < len(vertices):
                    vertex = vertices[position]
                    neighbors = rotation[vertex]
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
                    rows.append(tuple(labels[neighbor] for neighbor in ordered))
                    position += 1
                candidates.append(tuple(rows))
    payload = json.dumps(min(candidates), separators=(",", ":")).encode("ascii")
    return sha256(payload).hexdigest()


def cycle_edges(cycle: Sequence[int], edge_index: dict[tuple[int, int], int]) -> frozenset[int]:
    selected: set[int] = set()
    for left, right in zip(cycle, cycle[1:] + cycle[:1]):
        edge = (min(left, right), max(left, right))
        if edge not in edge_index:
            raise ValueError(f"cycle contains non-edge {edge}")
        selected.add(edge_index[edge])
    return frozenset(selected)


def verify_cycles_and_cover(
    edges: Sequence[tuple[int, int]], cycles_raw: Any
) -> tuple[tuple[tuple[int, ...], ...], int]:
    if not isinstance(cycles_raw, list):
        raise ValueError("cycles is not a list")
    cycles = tuple(tuple(map(int, cycle)) for cycle in cycles_raw)
    if len(cycles) != len(set(cycles)):
        raise ValueError("cycle family contains duplicates")
    edge_index = {edge: index for index, edge in enumerate(edges)}
    all_edges = set(range(len(edges)))
    covered: set[tuple[int, int]] = set()
    for cycle in cycles:
        if len(cycle) != ORDER or set(cycle) != set(range(ORDER)):
            raise ValueError("cycle is not Hamiltonian on vertices 0..35")
        if normalize_cycle(cycle) != cycle:
            raise ValueError("cycle is not normalized")
        selected = cycle_edges(cycle, edge_index)
        if len(selected) != ORDER:
            raise ValueError("cycle does not contain 36 distinct graph edges")
        for required in selected:
            for forbidden in all_edges - selected:
                covered.add((required, forbidden))
    return cycles, len(covered)


def _connected_subset(vertices: set[int], adjacency: Sequence[frozenset[int]]) -> bool:
    if not vertices:
        return True
    start = min(vertices)
    reached = {start}
    pending = [start]
    while pending:
        vertex = pending.pop()
        for neighbor in adjacency[vertex] & vertices:
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    return reached == vertices


def enumerate_hamiltonian_cycles(
    edges: Sequence[tuple[int, int]], order: int
) -> Iterator[tuple[int, ...]]:
    mutable = [set() for _ in range(order)]
    for left, right in edges:
        mutable[left].add(right)
        mutable[right].add(left)
    adjacency = tuple(frozenset(row) for row in mutable)
    all_vertices = set(range(order))
    path = [0]
    visited = {0}

    def feasible(current: int) -> bool:
        remaining = all_vertices - visited
        first = path[1]
        if not remaining:
            return 0 in adjacency[current] and first < current
        if not adjacency[current] & remaining:
            return False
        if not any(first < vertex for vertex in adjacency[0] & remaining):
            return False
        available = remaining | {0, current}
        if any(len(adjacency[vertex] & available) < 2 for vertex in remaining):
            return False
        return _connected_subset(remaining, adjacency)

    def search(current: int) -> Iterator[tuple[int, ...]]:
        if len(path) == order:
            if 0 in adjacency[current] and path[1] < current:
                yield tuple(path)
            return
        for candidate in sorted(
            adjacency[current] - visited,
            key=lambda vertex: (len(adjacency[vertex] - visited), vertex),
        ):
            visited.add(candidate)
            path.append(candidate)
            if feasible(candidate):
                yield from search(candidate)
            path.pop()
            visited.remove(candidate)

    for first in sorted(adjacency[0]):
        visited.add(first)
        path.append(first)
        if feasible(first):
            yield from search(first)
        path.pop()
        visited.remove(first)


def verify_exact_fields(
    record: dict[str, Any], edges: Sequence[tuple[int, int]], cycles: Sequence[Sequence[int]]
) -> None:
    exact = record.get("exact_hsep")
    universe_raw = record.get("complete_hamiltonian_cycle_universe")
    packing_raw = record.get("packing_lower_bound")
    if exact is None:
        if universe_raw is not None or packing_raw is not None:
            raise ValueError("non-exact record contains incomplete exact fields")
        return
    if not isinstance(exact, int) or exact <= 0 or len(cycles) != exact:
        raise ValueError("exact hsep does not match primal cover size")
    if not isinstance(universe_raw, list) or not isinstance(packing_raw, list):
        raise ValueError("exact record lacks cycle universe or packing")
    universe, _ = verify_cycles_and_cover(edges, universe_raw)
    if tuple(sorted(universe)) != universe:
        raise ValueError("complete cycle universe is not sorted")
    independently_enumerated = tuple(sorted(enumerate_hamiltonian_cycles(edges, ORDER)))
    if independently_enumerated != universe:
        raise ValueError("stored Hamiltonian-cycle universe is not complete")
    packing = tuple(tuple(map(int, item)) for item in packing_raw)
    if len(packing) != exact or len(set(packing)) != exact:
        raise ValueError("packing size does not match exact hsep")
    if any(not (0 <= required < EDGE_COUNT and 0 <= forbidden < EDGE_COUNT and required != forbidden) for required, forbidden in packing):
        raise ValueError("packing contains an invalid requirement")
    edge_index = {edge: index for index, edge in enumerate(edges)}
    all_edges = set(range(len(edges)))
    for cycle in universe:
        selected = cycle_edges(cycle, edge_index)
        covered_packing = sum(
            required in selected and forbidden in all_edges - selected
            for required, forbidden in packing
        )
        if covered_packing > 1:
            raise ValueError("Hamiltonian cycle covers two packing requirements")


def verify_record(record: dict[str, Any], expected_index: int) -> tuple[str, int, str]:
    if record.get("schema") != SCHEMA:
        raise ValueError("certificate schema mismatch")
    if record.get("generation_index") != expected_index or record.get("plantri_rank") != expected_index + 1:
        raise ValueError("certificate rank/index mismatch")
    data = base64.b64decode(record["planar_code_base64"], validate=True)
    if sha256(data).hexdigest() != record.get("planar_code_sha256"):
        raise ValueError("planar_code SHA-256 mismatch")
    rotation = parse_planar_code(data)
    faces = verify_barnette_rotation(rotation)
    if list(faces) != record.get("face_size_multiset"):
        raise ValueError("face multiset mismatch")
    graph_hash = canonical_graph_hash(rotation)
    if graph_hash != record.get("canonical_graph_hash"):
        raise ValueError("canonical graph hash mismatch")
    edges = edges_from_rotation(rotation)
    if len(edges) != EDGE_COUNT or [list(edge) for edge in edges] != record.get("edges"):
        raise ValueError("stored edge list mismatch")
    cycles, covered = verify_cycles_and_cover(edges, record.get("cycles"))
    if len(cycles) != record.get("cover_size") or covered != REQUIREMENTS:
        raise ValueError("family does not cover all 2,862 ordered edge pairs")
    verify_exact_fields(record, edges, cycles)
    status = str(record.get("status"))
    if graph_hash == BARNIE_HASH:
        if record.get("exact_hsep") != 49 or len(cycles) != 49:
            raise ValueError("Barnie 49 lacks matching exact 49/49 certificates")
    elif len(cycles) > 48 or not status.startswith("verified_le48"):
        raise ValueError("non-Barnie graph lacks a verified cover of size at most 48")
    return graph_hash, len(cycles), status


def verify_manifest(root: Path) -> int:
    manifest = root / "SHA256SUMS.txt"
    checked = 0
    for line_number, line in enumerate(manifest.read_text(encoding="ascii").splitlines(), start=1):
        if not line:
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError(f"malformed manifest line {line_number}") from error
        path = root / Path(relative)
        if not path.is_file() or digest_file(path) != expected:
            raise ValueError(f"manifest mismatch: {relative}")
        checked += 1
    return checked


def verify_all(root: Path, *, check_manifest: bool) -> dict[str, Any]:
    started = perf_counter()
    certificate_path = root / "order36_certificates.jsonl"
    metadata = json.loads((root / "order36_metadata.json").read_text(encoding="ascii"))
    expected_digest = metadata["canonical_uncompressed_certificates_sha256"]
    actual_digest = digest_file(certificate_path)
    if actual_digest != expected_digest:
        raise ValueError("canonical certificate JSONL digest mismatch")
    hashes: set[str] = set()
    statuses: Counter[str] = Counter()
    cover_sizes: Counter[int] = Counter()
    barnie_count = 0
    count = 0
    with certificate_path.open("r", encoding="ascii") as source:
        for index, line in enumerate(source):
            if not line.endswith("\n"):
                raise ValueError("certificate JSONL has a non-terminated line")
            record = json.loads(line)
            if canonical_json(record) + "\n" != line:
                raise ValueError(f"certificate line {index + 1} is not canonical JSON")
            graph_hash, cover_size, status = verify_record(record, index)
            if graph_hash in hashes:
                raise ValueError("duplicate canonical graph hash")
            hashes.add(graph_hash)
            statuses[status] += 1
            cover_sizes[cover_size] += 1
            barnie_count += int(graph_hash == BARNIE_HASH)
            count += 1
    if count != GRAPH_COUNT or len(hashes) != GRAPH_COUNT:
        raise ValueError("certificate census does not contain 15,374 unique graphs")
    if barnie_count != 1:
        raise ValueError("Barnie canonical hash does not occur exactly once")
    manifest_files = verify_manifest(root) if check_manifest else None
    return {
        "schema": "barnette-hsep-order36-independent-verification-v1",
        "verified": True,
        "graph_count": count,
        "non_barnie_le48_count": count - 1,
        "barnie_hash": BARNIE_HASH,
        "barnie_exact_hsep": 49,
        "ordered_edge_pairs_verified_per_graph": REQUIREMENTS,
        "status_distribution": dict(sorted(statuses.items())),
        "cover_size_distribution": {str(k): v for k, v in sorted(cover_sizes.items())},
        "canonical_certificates_sha256": actual_digest,
        "manifest_files_verified": manifest_files,
        "runtime_seconds": perf_counter() - started,
        "conclusion": "BARNIE_49_UNIQUE_ORDER36_MAXIMUM",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--check-manifest", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args(argv)
    try:
        result = (
            {
                "schema": "barnette-hsep-order36-manifest-verification-v1",
                "verified": True,
                "manifest_files_verified": verify_manifest(arguments.root),
            }
            if arguments.manifest_only
            else verify_all(arguments.root, check_manifest=arguments.check_manifest)
        )
    except Exception as error:
        print(canonical_json({"verified": False, "error": str(error)}))
        return 1
    output = canonical_json(result)
    if arguments.report is not None:
        temporary = arguments.report.with_name(arguments.report.name + ".tmp")
        temporary.write_text(output + "\n", encoding="ascii", newline="\n")
        temporary.replace(arguments.report)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
