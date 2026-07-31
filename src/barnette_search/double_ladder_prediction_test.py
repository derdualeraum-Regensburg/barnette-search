"""Prospective exact tests for three square-expanded double ladders.

The construction starts from the immutable certified D(9,7) record and only
applies the already certified four-vertex expansion.  Complete Hamiltonian
universes are cross-checked by path backtracking and by independently
enumerating perfect matchings of the cubic graph.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import base64
import gzip
import json
from pathlib import Path
from time import perf_counter
import tracemalloc
from typing import Any, Iterable, Iterator, Mapping, Sequence

import networkx as nx

from .barnie_sequence import deterministic_greedy_cover, greedy_packing_lower_bound
from .hsep_order36 import (
    enumerate_hamiltonian_cycles,
    solve_packing_lower_bound,
    solve_set_cover,
    verify_cover_edges,
)
from .ladder_analysis import (
    barnette_properties,
    canonicalize_embedding,
    detect_quadrilateral_structures,
    edge_to_faces,
    graph_from_rotation,
    normalized_edge,
)
from .planar_code import encode_planar_code


Edge = tuple[int, int]
ModelVertex = tuple[str, int, int]

SOURCE_HASH = "2f96ada16c46cd2bd038b97d5af44f46ed14522cba1edf3fa041d66e02107bcc"
PREDICTIONS = (
    ("D(9,9)", 9, 9, 40, 86, 60, "B"),
    ("D(11,9)", 11, 9, 44, 104, 71, "A"),
    ("D(11,11)", 11, 11, 48, 126, 84, "B"),
)


@dataclass(frozen=True)
class ConstructedGraph:
    label: str
    a: int
    b: int
    rotation: tuple[tuple[int, ...], ...]
    graph_hash: str
    model_by_vertex: dict[int, ModelVertex]

    @property
    def graph(self) -> nx.Graph:
        return graph_from_rotation(self.rotation)

    @property
    def edges(self) -> tuple[Edge, ...]:
        return tuple(sorted(normalized_edge(*edge) for edge in self.graph.edges()))


def canonical_json_bytes(value: Any) -> bytes:
    """Return the project's deterministic, human-readable JSON encoding."""
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def deterministic_gzip(data: bytes) -> bytes:
    """Compress bytes with fixed metadata."""
    stream = BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as target:
        target.write(data)
    return stream.getvalue()


def normalize_cycle(cycle: Iterable[int]) -> tuple[int, ...]:
    """Remove rotation and reversal choices from an undirected cycle."""
    body = tuple(cycle)
    if len(body) > 1 and body[0] == body[-1]:
        body = body[:-1]
    if len(body) != len(set(body)):
        raise ValueError("cycle repeats a vertex")
    minimum = min(body)
    position = body.index(minimum)
    forward = body[position:] + body[:position]
    reversed_body = tuple(reversed(body))
    position = reversed_body.index(minimum)
    backward = reversed_body[position:] + reversed_body[:position]
    return min(forward, backward)


def cycle_edges(cycle: Sequence[int]) -> frozenset[Edge]:
    return frozenset(
        normalized_edge(left, right)
        for left, right in zip(cycle, cycle[1:] + cycle[:1])
    )


def verify_cycle(edges: Sequence[Edge], order: int, cycle: Sequence[int]) -> bool:
    return (
        len(cycle) == order
        and set(cycle) == set(range(order))
        and len(set(cycle)) == order
        and cycle_edges(cycle) <= set(edges)
    )


def enumerate_via_perfect_matchings(
    edges: Sequence[Edge], order: int
) -> tuple[tuple[int, ...], ...]:
    """Independently enumerate Hamilton cycles as connected 2-factor complements.

    In a cubic graph, deleting a perfect matching leaves degree two at every
    vertex.  It is a Hamiltonian cycle exactly when that 2-factor is connected.
    The matching recursion is therefore an exhaustive and independent
    completeness check for the path-based enumerator.
    """
    adjacency = [set() for _ in range(order)]
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    if any(len(row) != 3 for row in adjacency):
        raise ValueError("perfect-matching Hamilton enumeration requires cubicity")
    edge_set = set(edges)
    cycles: set[tuple[int, ...]] = set()

    def visit(unmatched: frozenset[int], matching: tuple[Edge, ...]) -> None:
        if not unmatched:
            complement = edge_set - set(matching)
            two_adjacency = [set() for _ in range(order)]
            for left, right in complement:
                two_adjacency[left].add(right)
                two_adjacency[right].add(left)
            if any(len(row) != 2 for row in two_adjacency):
                raise RuntimeError("perfect-matching complement is not 2-regular")
            path = [0]
            previous: int | None = None
            current = 0
            while True:
                candidates = two_adjacency[current] - ({previous} if previous is not None else set())
                if previous is None:
                    following = min(candidates)
                else:
                    following = next(iter(candidates))
                if following == 0:
                    break
                path.append(following)
                previous, current = current, following
                if len(path) > order:
                    raise RuntimeError("2-factor traversal did not close")
            if len(path) == order:
                cycles.add(normalize_cycle(path))
            return

        vertex = min(unmatched)
        for neighbor in sorted(adjacency[vertex] & set(unmatched)):
            visit(
                unmatched - {vertex, neighbor},
                matching + (normalized_edge(vertex, neighbor),),
            )

    visit(frozenset(range(order)), ())
    return tuple(sorted(cycles))


def _rotation_from_graph(graph: nx.Graph) -> tuple[tuple[int, ...], ...]:
    planar, embedding = nx.check_planarity(graph)
    if not planar:
        raise ValueError("square expansion produced a nonplanar graph")
    nodes = sorted(graph)
    if nodes != list(range(len(nodes))):
        raise ValueError("construction graph labels must be contiguous integers")
    return tuple(tuple(embedding.neighbors_cw_order(vertex)) for vertex in nodes)


def _canonical_constructed(
    label: str,
    a: int,
    b: int,
    graph: nx.Graph,
    model_by_original: Mapping[int, ModelVertex],
) -> tuple[ConstructedGraph, dict[int, int]]:
    canonical = canonicalize_embedding(_rotation_from_graph(graph))
    original_to_canonical = {
        original: canonical_vertex
        for original, canonical_vertex in enumerate(canonical["original_to_canonical"])
    }
    model = {
        original_to_canonical[original]: tuple(model_by_original[original])
        for original in sorted(model_by_original)
    }
    result = ConstructedGraph(
        label=label,
        a=a,
        b=b,
        rotation=tuple(tuple(row) for row in canonical["rotation_system"]),
        graph_hash=str(canonical["canonical_graph_hash"]),
        model_by_vertex=model,
    )
    return result, original_to_canonical


def load_certified_source(ladder_family_path: Path) -> ConstructedGraph:
    """Load and recheck the immutable certified D(9,7) source."""
    data = json.loads(ladder_family_path.read_text(encoding="utf-8"))
    matches = [
        record
        for record in data["graphs"]
        if record.get("canonical_graph_hash") == SOURCE_HASH
    ]
    if len(matches) != 1:
        raise ValueError("certified D(9,7) source record is missing or duplicated")
    record = matches[0]
    double_ladder = record["double_ladder"]
    parameters = double_ladder["parameters"]
    if parameters != {"first_ladder_length": 9, "second_ladder_length": 7}:
        raise ValueError("certified source does not have D(9,7) parameters")
    rotation = tuple(
        tuple(map(int, row)) for row in record["canonical_embedding"]["rotation_system"]
    )
    canonical = canonicalize_embedding(rotation)
    if canonical["canonical_graph_hash"] != SOURCE_HASH:
        raise ValueError("certified source canonical hash mismatch")
    if tuple(tuple(row) for row in canonical["rotation_system"]) != rotation:
        raise ValueError("certified source embedding is not in canonical form")
    model = {
        int(vertex): (str(value[0]), int(value[1]), int(value[2]))
        for vertex, value in double_ladder["canonical_vertex_to_model"]
    }
    if set(model) != set(range(36)):
        raise ValueError("certified source model mapping is incomplete")
    return ConstructedGraph("D(9,7)", 9, 7, rotation, SOURCE_HASH, model)


def _model_inverse(model_by_vertex: Mapping[int, ModelVertex]) -> dict[ModelVertex, int]:
    inverse = {model: vertex for vertex, model in model_by_vertex.items()}
    if len(inverse) != len(model_by_vertex):
        raise ValueError("model mapping is not injective")
    return inverse


def forward_square_expansion(
    source: ConstructedGraph,
    *,
    target_label: str,
    target_a: int,
    target_b: int,
    ladder_name: str,
) -> tuple[ConstructedGraph, dict[str, Any]]:
    """Lengthen one ladder by two through one certified square insertion.

    The chosen source cell is always cell zero.  Its two opposite rail edges
    are replaced by length-three paths and the corresponding new vertices are
    joined by two rungs.  No target edge list is supplied or consulted.
    """
    expected_a = source.a + (2 if ladder_name == "A" else 0)
    expected_b = source.b + (2 if ladder_name == "B" else 0)
    if (target_a, target_b) != (expected_a, expected_b):
        raise ValueError("target parameters do not match one square expansion")
    graph = source.graph.copy()
    source_model = dict(source.model_by_vertex)
    inverse = _model_inverse(source_model)
    removed = tuple(
        sorted(
            normalized_edge(
                inverse[(ladder_name, 0, rail)],
                inverse[(ladder_name, 1, rail)],
            )
            for rail in (0, 1)
        )
    )
    source_faces = tuple(tuple(face) for face in canonicalize_embedding(source.rotation)["faces"])
    incidence = edge_to_faces(source_faces)
    common_faces = sorted(set(incidence[removed[0]]) & set(incidence[removed[1]]))
    if len(common_faces) != 1 or len(source_faces[common_faces[0]]) != 4:
        raise ValueError("chosen rail edges are not opposite edges of one quadrilateral face")

    graph.remove_edges_from(removed)
    target_model_original = {
        vertex: (
            name,
            column + 2 if name == ladder_name and column >= 1 else column,
            rail,
        )
        for vertex, (name, column, rail) in source_model.items()
    }
    next_vertex = graph.number_of_nodes()
    inserted_original: dict[tuple[int, int], int] = {}
    for column in (1, 2):
        for rail in (0, 1):
            inserted_original[(column, rail)] = next_vertex
            target_model_original[next_vertex] = (ladder_name, column, rail)
            graph.add_node(next_vertex)
            next_vertex += 1
    old_left = {rail: inverse[(ladder_name, 0, rail)] for rail in (0, 1)}
    old_right = {rail: inverse[(ladder_name, 1, rail)] for rail in (0, 1)}
    inserted_edges_original: list[Edge] = []
    for rail in (0, 1):
        path = (
            old_left[rail],
            inserted_original[(1, rail)],
            inserted_original[(2, rail)],
            old_right[rail],
        )
        inserted_edges_original.extend(
            normalized_edge(left, right) for left, right in zip(path, path[1:])
        )
    inserted_edges_original.extend(
        normalized_edge(inserted_original[(column, 0)], inserted_original[(column, 1)])
        for column in (1, 2)
    )
    graph.add_edges_from(inserted_edges_original)

    target, old_to_canonical = _canonical_constructed(
        target_label, target_a, target_b, graph, target_model_original
    )
    inserted_target = sorted(old_to_canonical[value] for value in inserted_original.values())
    unchanged_mapping = [[vertex, old_to_canonical[vertex]] for vertex in range(len(source.rotation))]
    inserted_target_edges = sorted(
        normalized_edge(old_to_canonical[left], old_to_canonical[right])
        for left, right in inserted_edges_original
    )
    mapped_removed = sorted(
        normalized_edge(old_to_canonical[left], old_to_canonical[right])
        for left, right in removed
    )
    reconstructed_edges = {
        normalized_edge(old_to_canonical[left], old_to_canonical[right])
        for left, right in source.edges
    }
    reconstructed_edges.difference_update(mapped_removed)
    reconstructed_edges.update(inserted_target_edges)
    target_edges = set(target.edges)
    if reconstructed_edges != target_edges:
        raise RuntimeError("forward reconstruction does not equal canonical target")

    target_faces = tuple(tuple(face) for face in canonicalize_embedding(target.rotation)["faces"])
    affected_source = sorted(set(incidence[removed[0]]) | set(incidence[removed[1]]))
    affected_target = [
        index for index, face in enumerate(target_faces) if set(face) & set(inserted_target)
    ]
    boundary = []
    inserted_original_set = set(inserted_original.values())
    for original in sorted(inserted_original_set):
        outside = [neighbor for neighbor in graph[original] if neighbor not in inserted_original_set]
        if len(outside) != 1:
            raise RuntimeError("inserted square vertex does not have one boundary terminal")
        terminal_original = outside[0]
        boundary.append(
            {
                "inserted_vertex": old_to_canonical[original],
                "target_terminal": old_to_canonical[terminal_original],
                "source_terminal": terminal_original,
            }
        )
    source_hash = source.graph_hash
    target_hash = target.graph_hash
    target_planar_code = encode_planar_code(target.rotation)
    target_graph6 = nx.to_graph6_bytes(target.graph, header=False).decode("ascii").strip()
    reduced_edges = target_edges - set(inserted_target_edges)
    reduced_edges.difference_update(
        edge for edge in tuple(reduced_edges) if set(edge) & set(inserted_target)
    )
    reduced_edges.update(mapped_removed)
    mapped_source_edges = {
        normalized_edge(old_to_canonical[left], old_to_canonical[right])
        for left, right in source.edges
    }
    certificate = {
        "schema": "double-ladder-forward-square-expansion-v1",
        "operation": "two-edge facial square expansion",
        "source_label": source.label,
        "target_label": target.label,
        "source_parameters": {"a": source.a, "b": source.b},
        "target_parameters": {"a": target.a, "b": target.b},
        "source_order": len(source.rotation),
        "target_order": len(target.rotation),
        "source_canonical_hash": source_hash,
        "target_canonical_hash": target_hash,
        "source_canonical_edge_list": [list(edge) for edge in source.edges],
        "source_rotation_system": [list(row) for row in source.rotation],
        "selected_ladder": ladder_name,
        "selected_cell": 0,
        "deleted_edges_source_labels": [list(edge) for edge in removed],
        "deleted_edges_target_labels": [list(edge) for edge in mapped_removed],
        "inserted_vertices_target_labels": inserted_target,
        "inserted_edges_target_labels": [list(edge) for edge in inserted_target_edges],
        "boundary_terminals": boundary,
        "unchanged_source_to_target": unchanged_mapping,
        "affected_faces_before": [
            {
                "face_index": index,
                "vertices": list(source_faces[index]),
                "size": len(source_faces[index]),
            }
            for index in affected_source
        ],
        "affected_faces_after": [
            {
                "face_index": index,
                "vertices": list(target_faces[index]),
                "size": len(target_faces[index]),
            }
            for index in affected_target
        ],
        "source_boundary_rotations": {
            str(vertex): list(source.rotation[vertex])
            for edge in removed
            for vertex in edge
        },
        "target_affected_rotations": {
            str(vertex): list(target.rotation[vertex])
            for vertex in sorted(
                set(inserted_target)
                | {item["target_terminal"] for item in boundary}
            )
        },
        "target_canonical_edge_list": [list(edge) for edge in target.edges],
        "target_graph6": target_graph6,
        "target_planar_code_base64": base64.b64encode(target_planar_code).decode("ascii"),
        "target_planar_code_sha256": sha256(target_planar_code).hexdigest(),
        "checks": {
            "source_edges_are_disjoint": not bool(set(removed[0]) & set(removed[1])),
            "source_edges_are_opposite_quadrilateral_rails": True,
            "inserted_vertex_count": len(inserted_target) == 4,
            "deleted_edge_count": len(removed) == 2,
            "inserted_edge_count": len(inserted_target_edges) == 8,
            "reconstruction_edge_set_equals_target": reconstructed_edges == target_edges,
            "inverse_reduction_equals_mapped_source": reduced_edges == mapped_source_edges,
            "target_barnette_properties": barnette_properties(target.graph),
        },
    }
    return target, certificate


def construct_prediction_chain(ladder_family_path: Path) -> tuple[list[ConstructedGraph], list[dict[str, Any]]]:
    source = load_certified_source(ladder_family_path)
    targets: list[ConstructedGraph] = []
    certificates: list[dict[str, Any]] = []
    current = source
    for label, a, b, _order, _cycles, _hsep, ladder in PREDICTIONS:
        current, certificate = forward_square_expansion(
            current,
            target_label=label,
            target_a=a,
            target_b=b,
            ladder_name=ladder,
        )
        targets.append(current)
        certificates.append(certificate)
    return targets, certificates


def graph_record(graph: ConstructedGraph) -> dict[str, Any]:
    nx_graph = graph.graph
    edges = graph.edges
    faces = tuple(tuple(face) for face in canonicalize_embedding(graph.rotation)["faces"])
    structures = detect_quadrilateral_structures(graph.rotation)
    properties = barnette_properties(nx_graph)
    order = len(graph.rotation)
    edge_count = len(edges)
    cap_sizes = sorted(size for size in map(len, faces) if size != 4)
    expected_caps = sorted((graph.a + 3, graph.a + 3, graph.b + 3, graph.b + 3))
    ladder_lengths = sorted(item["face_count"] for item in structures["ladders"])
    expected_ladders = sorted((graph.a, graph.b))
    checks = {
        **properties,
        "order": order == 2 * (graph.a + graph.b) + 4,
        "edge_count": edge_count == 3 * order // 2,
        "euler_identity": order - edge_count + len(faces) == 2,
        "face_dart_arithmetic": sum(map(len, faces)) == 2 * edge_count,
        "quadrilateral_face_count": sum(len(face) == 4 for face in faces) == graph.a + graph.b,
        "strict_ladder_lengths": ladder_lengths == expected_ladders,
        "cap_face_signature": cap_sizes == expected_caps,
        "model_parameters": sorted(
            max(column for name, column, _rail in graph.model_by_vertex.values() if name == ladder)
            for ladder in ("A", "B")
        ) == expected_ladders,
    }
    if not all(checks.values()):
        failed = sorted(key for key, value in checks.items() if not value)
        raise RuntimeError(f"{graph.label} failed Barnette/structure checks: {failed}")
    planar_code = encode_planar_code(graph.rotation)
    graph6 = nx.to_graph6_bytes(nx_graph, header=False).decode("ascii").strip()
    return {
        "schema": "double-ladder-prediction-graph-v1",
        "label": graph.label,
        "parameters": {"a": graph.a, "b": graph.b},
        "order": order,
        "edge_count": edge_count,
        "canonical_graph_hash": graph.graph_hash,
        "canonical_edge_list": [list(edge) for edge in edges],
        "rotation_system": [list(row) for row in graph.rotation],
        "faces": [list(face) for face in faces],
        "face_size_multiset": sorted(map(len, faces)),
        "quadrilateral_face_count": graph.a + graph.b,
        "cap_face_signature": expected_caps,
        "strict_ladder_lengths": expected_ladders,
        "quadrilateral_component_signature": structures["quadrilateral_component_signature"],
        "model_vertex_labels": [
            [vertex, list(graph.model_by_vertex[vertex])]
            for vertex in sorted(graph.model_by_vertex)
        ],
        "graph6": graph6,
        "planar_code_base64": base64.b64encode(planar_code).decode("ascii"),
        "planar_code_sha256": sha256(planar_code).hexdigest(),
        "validation": checks,
    }


def enumerate_complete_universe(
    graph: ConstructedGraph,
) -> tuple[tuple[tuple[int, ...], ...], dict[str, Any]]:
    """Run and compare both complete enumeration methods."""
    tracemalloc.start()
    started = perf_counter()
    backtracking = tuple(
        sorted(normalize_cycle(cycle) for cycle in enumerate_hamiltonian_cycles(graph.edges, len(graph.rotation)))
    )
    backtracking_seconds = perf_counter() - started
    matching_started = perf_counter()
    matching = enumerate_via_perfect_matchings(graph.edges, len(graph.rotation))
    matching_seconds = perf_counter() - matching_started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if len(backtracking) != len(set(backtracking)):
        raise RuntimeError("path enumerator emitted a duplicate normalized cycle")
    if backtracking != matching:
        raise RuntimeError("Hamiltonian enumeration methods disagree")
    if not all(verify_cycle(graph.edges, len(graph.rotation), cycle) for cycle in backtracking):
        raise RuntimeError("Hamiltonian enumerator emitted an invalid cycle")
    return backtracking, {
        "backtracking_method": "deterministic anchored Hamiltonian path DFS",
        "perfect_matching_method": "exhaustive perfect matchings with connected 2-factor complements",
        "backtracking_runtime_seconds": backtracking_seconds,
        "perfect_matching_runtime_seconds": matching_seconds,
        "total_runtime_seconds": perf_counter() - started,
        "peak_python_memory_bytes": peak,
        "independent_agreement": True,
        "complete_cycle_count": len(backtracking),
    }


def connector_edges(graph: ConstructedGraph) -> tuple[Edge, ...]:
    inverse = _model_inverse(graph.model_by_vertex)
    return (
        normalized_edge(inverse[("A", 0, 0)], inverse[("B", 0, 0)]),
        normalized_edge(inverse[("A", 0, 1)], inverse[("B", graph.b, 0)]),
        normalized_edge(inverse[("A", graph.a, 0)], inverse[("B", 0, 1)]),
        normalized_edge(inverse[("A", graph.a, 1)], inverse[("B", graph.b, 1)]),
    )


def classify_cycles(
    graph: ConstructedGraph, universe: Sequence[Sequence[int]]
) -> dict[str, Any]:
    inverse = _model_inverse(graph.model_by_vertex)
    connectors = connector_edges(graph)
    records = []
    counts: Counter[str] = Counter()
    turn_pairs: set[tuple[int, int]] = set()
    failures: list[dict[str, Any]] = []
    for cycle_index, cycle in enumerate(universe):
        selected = cycle_edges(cycle)
        connector_bits = "".join("1" if edge in selected else "0" for edge in connectors)
        ladder_bits = []
        turns: list[int | None] = []
        valid_turns = True
        for name, length in (("A", graph.a), ("B", graph.b)):
            rungs = [
                normalized_edge(inverse[(name, column, 0)], inverse[(name, column, 1)])
                for column in range(length + 1)
            ]
            rails = [
                [
                    normalized_edge(inverse[(name, column, rail)], inverse[(name, column + 1, rail)])
                    for column in range(length)
                ]
                for rail in (0, 1)
            ]
            rung_bits = "".join("1" if edge in selected else "0" for edge in rungs)
            rail_bits = [
                "".join("1" if edge in selected else "0" for edge in rail)
                for rail in rails
            ]
            candidates = [
                position
                for position in range(length)
                if rail_bits[0][position] == rail_bits[1][position] == "0"
                and rung_bits[position : position + 2] == "11"
            ]
            turns.append(candidates[0] if len(candidates) == 1 else None)
            valid_turns &= len(candidates) == 1
            ladder_bits.append(
                {"name": name, "rung_bits": rung_bits, "rail_bits": rail_bits}
            )
        if connector_bits == "1111" and all(set(item["rung_bits"]) <= {"0"} for item in ladder_bits):
            classification = "all_rails"
            turns = [None, None]
        elif connector_bits == "1111" and valid_turns:
            classification = "paired_cell_turns"
            turn_pairs.add((int(turns[0]), int(turns[1])))
        elif connector_bits.count("1") == 2:
            classification = "two_connector_exception"
            turns = [None, None]
        else:
            classification = "unclassified"
            failures.append({"cycle_index": cycle_index, "cycle": list(cycle), "connector_bits": connector_bits})
        counts[classification] += 1
        records.append(
            {
                "cycle_index": cycle_index,
                "classification": classification,
                "connector_bits": connector_bits,
                "turn_cells": turns,
                "model_ladder_bits": ladder_bits,
            }
        )
    expected_pairs = {(left, right) for left in range(graph.a) for right in range(graph.b)}
    checks = {
        "every_cycle_classified_once": not failures,
        "unique_all_rails_cycle": counts["all_rails"] == 1,
        "all_turn_pairs_once": counts["paired_cell_turns"] == graph.a * graph.b and turn_pairs == expected_pairs,
        "four_connector_exceptions": counts["two_connector_exception"] == 4,
        "class_counts_sum_to_universe": sum(counts.values()) == len(universe),
    }
    return {
        "schema": "double-ladder-cycle-classification-v1",
        "graph": graph.label,
        "canonical_graph_hash": graph.graph_hash,
        "connector_edges": [list(edge) for edge in connectors],
        "counts": dict(sorted(counts.items())),
        "expected_counts": {
            "all_rails": 1,
            "paired_cell_turns": graph.a * graph.b,
            "two_connector_exception": 4,
        },
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
        "counterexamples": failures,
        "cycle_records": records,
    }


def exact_hsep_certificate(
    graph: ConstructedGraph,
    universe: Sequence[Sequence[int]],
    predicted_hsep: int,
) -> dict[str, Any]:
    """Find matching primal and packing certificates over a complete universe."""
    started = perf_counter()
    tracemalloc.start()
    selected = solve_set_cover(graph.edges, universe, predicted_hsep)
    if selected is None:
        raise RuntimeError(f"{graph.label} has no separating cover at frozen bound {predicted_hsep}")
    primal = tuple(universe[index] for index in selected)
    complete, covered = verify_cover_edges(graph.edges, primal)
    if not complete:
        raise RuntimeError("SAT-derived primal certificate does not separate all requirements")
    greedy_packing = greedy_packing_lower_bound(graph.edges, universe)
    if len(greedy_packing) == len(primal):
        packing = greedy_packing
        method = "deterministic_support_disjoint_packing"
    else:
        packing = solve_packing_lower_bound(graph.edges, universe, len(primal))
        method = "deterministic_sat_packing"
    exact = len(primal) if packing is not None and len(packing) == len(primal) else None
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "schema": "double-ladder-exact-hsep-certificate-v1",
        "graph": graph.label,
        "canonical_graph_hash": graph.graph_hash,
        "complete_hamiltonian_cycle_count": len(universe),
        "predicted_hsep": predicted_hsep,
        "hsep_lower_bound": len(packing) if packing is not None else len(greedy_packing),
        "hsep_upper_bound": len(primal),
        "exact_hsep": exact,
        "proof_status": "exact_primal_packing" if exact is not None else "interval_missing_matching_lower_certificate",
        "primal_cycle_indices": list(selected),
        "primal_cycles": [list(cycle) for cycle in primal],
        "primal_cycle_count": len(primal),
        "packing_requirements": [list(requirement) for requirement in (packing or greedy_packing)],
        "packing_requirement_count": len(packing or greedy_packing),
        "lower_bound_method": method if packing is not None else "greedy_packing_only",
        "covered_ordered_edge_pairs": covered,
        "required_ordered_edge_pairs": len(graph.edges) * (len(graph.edges) - 1),
        "runtime_seconds": perf_counter() - started,
        "peak_python_memory_bytes": peak,
    }


def universe_payload(
    graph: ConstructedGraph,
    universe: Sequence[Sequence[int]],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "double-ladder-complete-hamiltonian-universe-v1",
        "graph": graph.label,
        "canonical_graph_hash": graph.graph_hash,
        "cycle_representation": "lexicographically least rotation and reversal; start is vertex 0; no repeated closing vertex",
        "complete_cycle_count": len(universe),
        "cycles": [list(cycle) for cycle in universe],
        "enumeration": dict(metadata),
    }
