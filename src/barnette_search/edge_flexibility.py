"""Exhaustive same-face ordered edge-flexibility analysis.

The deterministic greedy cover solves one uncovered ordered pair, then uses the
returned cycle to certify every still-uncovered pair whose required edge is in
that cycle and whose forbidden edge is absent. Face duplication is retained as
provenance while each ordered edge pair is analyzed only once.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import networkx as nx

from .constrained_hamiltonian import find_constrained_hamiltonian_cycle
from .constrained_hamiltonian_sat import (
    ConstrainedHamiltonianSatResult,
    ConstrainedHamiltonianSatSession,
    Edge,
)
from .hamiltonian import verify_hamiltonian_cycle
from .planar_code import EmbeddedPlanarGraph, certificate_hash


EdgePair = tuple[Edge, Edge]


@dataclass(frozen=True, slots=True)
class EdgePairRecord:
    """Face provenance and witness assignment for one ordered pair."""

    required_edge: Edge
    forbidden_edge: Edge
    face_indices: tuple[int, ...]
    witness_certificate_hash: str | None
    directly_queried_by_sat: bool
    backtracking_satisfiable: bool | None


@dataclass(frozen=True, slots=True)
class WitnessRecord:
    """One Hamiltonian cycle in the greedy set cover."""

    trigger_required_edge: Edge
    trigger_forbidden_edge: Edge
    cycle: tuple[Hashable, ...]
    certificate_hash: str
    newly_covered_pairs: int


@dataclass(frozen=True, slots=True)
class SatCallRecord:
    """One constrained SAT call made by the greedy cover."""

    required_edge: Edge
    forbidden_edge: Edge
    satisfiable: bool
    runtime_seconds: float
    subtour_iterations: int
    subtour_constraints: int
    certificate_hash: str | None


@dataclass(frozen=True, slots=True)
class EdgeFlexibilityResult:
    """Complete result for one embedded graph."""

    complete_property_holds: bool
    candidate_requires_review: bool
    total_ordered_same_face_edge_pairs: int
    number_of_sat_calls: int
    number_of_distinct_witness_cycles: int
    witness_cover_ratio: float
    ordered_pairs_per_witness: float
    total_sat_time_seconds: float
    maximum_single_query_sat_time_seconds: float
    subtour_iterations: int
    subtour_constraints: int
    hardest_ordered_pair: EdgePair | None
    face_size_multiset: tuple[int, ...]
    failed_ordered_pair: EdgePair | None
    pair_records: tuple[EdgePairRecord, ...]
    witnesses: tuple[WitnessRecord, ...]
    sat_calls: tuple[SatCallRecord, ...]
    backtracking_queries: int
    backtracking_agreements: int
    backtracking_runtime_seconds: float
    candidate_report_directory: str | None


def _normalize_edge(
    left: Hashable, right: Hashable, rank: dict[Hashable, int]
) -> Edge:
    return (left, right) if rank[left] < rank[right] else (right, left)


def _rotation_faces(
    graph: nx.Graph, rotation: Sequence[Sequence[Hashable]]
) -> tuple[tuple[Hashable, ...], ...]:
    nodes = tuple(graph.nodes())
    if len(rotation) != len(nodes):
        raise ValueError("rotation system does not have one row per graph vertex")
    rows = {vertex: tuple(rotation[index]) for index, vertex in enumerate(nodes)}
    unused = {(vertex, neighbor) for vertex in nodes for neighbor in rows[vertex]}
    faces: list[tuple[Hashable, ...]] = []
    while unused:
        start = min(
            unused,
            key=lambda dart: (nodes.index(dart[0]), nodes.index(dart[1])),
        )
        dart = start
        boundary: list[Hashable] = []
        while True:
            if dart not in unused:
                if dart != start:
                    raise ValueError("rotation system has an invalid facial walk")
                break
            unused.remove(dart)
            left, right = dart
            boundary.append(left)
            neighbors = rows[right]
            if left not in neighbors:
                raise ValueError("rotation-system adjacency is not symmetric")
            position = neighbors.index(left)
            dart = (right, neighbors[(position - 1) % len(neighbors)])
        faces.append(tuple(boundary))
    return tuple(faces)


def _faces_from_embedding(
    graph: nx.Graph,
    embedding: EmbeddedPlanarGraph | nx.PlanarEmbedding | Sequence[Sequence[Hashable]],
) -> tuple[tuple[Hashable, ...], ...]:
    if isinstance(embedding, EmbeddedPlanarGraph):
        return tuple(tuple(face) for face in embedding.faces)
    if isinstance(embedding, nx.PlanarEmbedding):
        seen: set[tuple[Hashable, Hashable]] = set()
        faces: list[tuple[Hashable, ...]] = []
        rank = {vertex: index for index, vertex in enumerate(graph.nodes())}
        darts = sorted(
            (
                (vertex, neighbor)
                for vertex in graph.nodes()
                for neighbor in embedding.neighbors_cw_order(vertex)
            ),
            key=lambda dart: (rank[dart[0]], rank[dart[1]]),
        )
        for left, right in darts:
            if (left, right) not in seen:
                faces.append(
                    tuple(embedding.traverse_face(left, right, mark_half_edges=seen))
                )
        return tuple(faces)
    return _rotation_faces(graph, embedding)


def _pair_provenance(
    graph: nx.Graph, faces: tuple[tuple[Hashable, ...], ...]
) -> tuple[tuple[EdgePair, tuple[int, ...]], ...]:
    rank = {vertex: index for index, vertex in enumerate(graph.nodes())}
    edge_order = tuple(
        sorted(
            {
                _normalize_edge(left, right, rank)
                for left, right in graph.edges()
            },
            key=lambda edge: (rank[edge[0]], rank[edge[1]]),
        )
    )
    edge_rank = {edge: index for index, edge in enumerate(edge_order)}
    provenance: dict[EdgePair, list[int]] = {}
    for face_index, face in enumerate(faces):
        if len(face) < 3:
            raise ValueError("faces must have boundary length at least three")
        face_edges: list[Edge] = []
        for left, right in zip(face, face[1:] + face[:1]):
            if left not in rank or right not in rank or not graph.has_edge(left, right):
                raise ValueError("embedding face contains a non-edge or unknown vertex")
            edge = _normalize_edge(left, right, rank)
            if edge not in face_edges:
                face_edges.append(edge)
        for required in face_edges:
            for forbidden in face_edges:
                if required != forbidden:
                    provenance.setdefault((required, forbidden), []).append(face_index)
    return tuple(
        sorted(
            (
                (pair, tuple(face_indices))
                for pair, face_indices in provenance.items()
            ),
            key=lambda item: (
                edge_rank[item[0][0]],
                edge_rank[item[0][1]],
            ),
        )
    )


def _cycle_edge_keys(cycle: tuple[Hashable, ...]) -> set[frozenset[Hashable]]:
    return {
        frozenset((left, right)) for left, right in zip(cycle, cycle[1:])
    }


def _cycle_satisfies_pair(cycle: tuple[Hashable, ...], pair: EdgePair) -> bool:
    selected = _cycle_edge_keys(cycle)
    required, forbidden = pair
    return frozenset(required) in selected and frozenset(forbidden) not in selected


def _candidate_identity(graph: nx.Graph, pair: EdgePair) -> str:
    rank = {vertex: index for index, vertex in enumerate(graph.nodes())}
    edges = sorted(
        (sorted((rank[left], rank[right])) for left, right in graph.edges())
    )
    required, forbidden = pair
    payload = {
        "edges": edges,
        "required": sorted((rank[required[0]], rank[required[1]])),
        "forbidden": sorted((rank[forbidden[0]], rank[forbidden[1]])),
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def _save_candidate_evidence(
    graph: nx.Graph,
    faces: tuple[tuple[Hashable, ...], ...],
    pair: EdgePair,
    primary_session: ConstrainedHamiltonianSatSession,
    primary_result: ConstrainedHamiltonianSatResult,
    output_directory: Path,
    backtracking_cycle: tuple[Hashable, ...] | None = None,
) -> tuple[Path, ConstrainedHamiltonianSatResult, tuple[Hashable, ...] | None]:
    identity = _candidate_identity(graph, pair)
    candidate_directory = output_directory / identity
    candidate_directory.mkdir(parents=True, exist_ok=True)
    required, forbidden = pair
    primary_session.export_dimacs(
        candidate_directory / "primary_constrained.cnf",
        required_edges=(required,),
        forbidden_edges=(forbidden,),
    )

    with ConstrainedHamiltonianSatSession(graph, solver="minisat22") as independent:
        independent_result = independent.solve(
            required_edges=(required,), forbidden_edges=(forbidden,)
        )
        independent.export_dimacs(
            candidate_directory / "independent_constrained.cnf",
            required_edges=(required,),
            forbidden_edges=(forbidden,),
        )
    if independent_result.cycle is not None:
        if not verify_hamiltonian_cycle(graph, independent_result.cycle):
            raise RuntimeError("independent SAT engine returned an invalid cycle")
        if not _cycle_satisfies_pair(independent_result.cycle, pair):
            raise RuntimeError("independent SAT cycle violates constraints")

    if backtracking_cycle is None:
        backtracking_cycle = find_constrained_hamiltonian_cycle(
            graph, required_edges=(required,), forbidden_edges=(forbidden,)
        )
    if backtracking_cycle is not None:
        if not verify_hamiltonian_cycle(graph, backtracking_cycle):
            raise RuntimeError("independent backtracking returned an invalid cycle")
        if not _cycle_satisfies_pair(backtracking_cycle, pair):
            raise RuntimeError("independent backtracking cycle violates constraints")

    nodes = tuple(graph.nodes())
    rank = {vertex: index for index, vertex in enumerate(nodes)}
    graph_record = {
        "node_labels_repr": [repr(vertex) for vertex in nodes],
        "edges": sorted(
            sorted((rank[left], rank[right])) for left, right in graph.edges()
        ),
        "faces": [[rank[vertex] for vertex in face] for face in faces],
    }
    (candidate_directory / "graph_and_embedding.json").write_text(
        json.dumps(graph_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = {
        "classification": "candidate only; manual review required",
        "required_edge": required,
        "forbidden_edge": forbidden,
        "primary_sat": asdict(primary_result),
        "independent_sat": asdict(independent_result),
        "independent_backtracking_cycle": backtracking_cycle,
        "engines_agree": (
            primary_result.satisfiable
            == independent_result.satisfiable
            == (backtracking_cycle is not None)
        ),
    }
    (candidate_directory / "candidate_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=repr) + "\n",
        encoding="utf-8",
    )
    return candidate_directory, independent_result, backtracking_cycle


def analyze_same_face_edge_flexibility(
    graph: nx.Graph,
    embedding: EmbeddedPlanarGraph | nx.PlanarEmbedding | Sequence[Sequence[Hashable]],
    *,
    cross_check_backtracking: bool | None = None,
    candidate_output_directory: Path | None = None,
) -> EdgeFlexibilityResult:
    """Exhaustively certify all ordered, distinct, cofacial edge pairs."""
    faces = _faces_from_embedding(graph, embedding)
    provenance_items = _pair_provenance(graph, faces)
    provenance = dict(provenance_items)
    ordered_pairs = tuple(pair for pair, _ in provenance_items)
    uncovered = set(ordered_pairs)
    pair_witness: dict[EdgePair, str] = {}
    queried_pairs: set[EdgePair] = set()
    witnesses: list[WitnessRecord] = []
    sat_calls: list[SatCallRecord] = []
    failed_pair: EdgePair | None = None
    candidate_directory: Path | None = None
    candidate_requires_review = False
    total_sat_time = 0.0
    maximum_sat_time = 0.0
    hardest_pair: EdgePair | None = None
    subtour_iterations = 0

    candidate_root = candidate_output_directory or Path(
        "edge_flexibility_candidates"
    )
    with ConstrainedHamiltonianSatSession(graph) as session:
        while uncovered:
            pair = next(pair for pair in ordered_pairs if pair in uncovered)
            required, forbidden = pair
            queried_pairs.add(pair)
            result = session.solve(
                required_edges=(required,), forbidden_edges=(forbidden,)
            )
            total_sat_time += result.runtime_seconds
            subtour_iterations += result.subtour_iterations
            if result.runtime_seconds > maximum_sat_time:
                maximum_sat_time = result.runtime_seconds
                hardest_pair = pair
            witness_hash = certificate_hash(result.cycle)
            sat_calls.append(
                SatCallRecord(
                    required_edge=required,
                    forbidden_edge=forbidden,
                    satisfiable=result.satisfiable,
                    runtime_seconds=result.runtime_seconds,
                    subtour_iterations=result.subtour_iterations,
                    subtour_constraints=result.subtour_constraints,
                    certificate_hash=witness_hash,
                )
            )
            if result.cycle is None:
                failed_pair = pair
                candidate_requires_review = True
                candidate_directory, _, _ = _save_candidate_evidence(
                    graph,
                    faces,
                    pair,
                    session,
                    result,
                    candidate_root,
                )
                break
            if not verify_hamiltonian_cycle(graph, result.cycle):
                raise RuntimeError("greedy witness is not a Hamiltonian cycle")
            if not _cycle_satisfies_pair(result.cycle, pair):
                raise RuntimeError("greedy witness violates its trigger pair")
            assert witness_hash is not None
            certified = tuple(
                candidate
                for candidate in ordered_pairs
                if candidate in uncovered
                and _cycle_satisfies_pair(result.cycle, candidate)
            )
            if pair not in certified:
                raise RuntimeError("SAT witness did not certify its own query")
            for certified_pair in certified:
                pair_witness[certified_pair] = witness_hash
            uncovered.difference_update(certified)
            witnesses.append(
                WitnessRecord(
                    trigger_required_edge=required,
                    trigger_forbidden_edge=forbidden,
                    cycle=result.cycle,
                    certificate_hash=witness_hash,
                    newly_covered_pairs=len(certified),
                )
            )
        cumulative_subtour_constraints = session.cumulative_subtour_constraints

        perform_backtracking = (
            graph.number_of_nodes() <= 24
            if cross_check_backtracking is None
            else cross_check_backtracking
        )
        backtracking_outcomes: dict[EdgePair, bool] = {}
        backtracking_queries = 0
        backtracking_agreements = 0
        backtracking_time = 0.0
        if perform_backtracking and failed_pair is None:
            for pair in ordered_pairs:
                required, forbidden = pair
                started = perf_counter()
                cycle = find_constrained_hamiltonian_cycle(
                    graph,
                    required_edges=(required,),
                    forbidden_edges=(forbidden,),
                )
                backtracking_time += perf_counter() - started
                backtracking_queries += 1
                satisfiable = cycle is not None
                backtracking_outcomes[pair] = satisfiable
                sat_satisfiable = pair in pair_witness
                if cycle is not None and (
                    not verify_hamiltonian_cycle(graph, cycle)
                    or not _cycle_satisfies_pair(cycle, pair)
                ):
                    raise RuntimeError(
                        "constrained backtracking returned an invalid witness"
                    )
                if satisfiable == sat_satisfiable:
                    backtracking_agreements += 1
                    continue
                candidate_requires_review = True
                failed_pair = pair
                trigger_result = session.solve(
                    required_edges=(required,), forbidden_edges=(forbidden,)
                )
                candidate_directory, _, _ = _save_candidate_evidence(
                    graph,
                    faces,
                    pair,
                    session,
                    trigger_result,
                    candidate_root,
                    backtracking_cycle=cycle,
                )
                break

    total_pairs = len(ordered_pairs)
    witness_count = len(witnesses)
    pair_records = tuple(
        EdgePairRecord(
            required_edge=pair[0],
            forbidden_edge=pair[1],
            face_indices=provenance[pair],
            witness_certificate_hash=pair_witness.get(pair),
            directly_queried_by_sat=pair in queried_pairs,
            backtracking_satisfiable=backtracking_outcomes.get(pair),
        )
        for pair in ordered_pairs
    )
    property_holds = not uncovered and failed_pair is None
    return EdgeFlexibilityResult(
        complete_property_holds=property_holds,
        candidate_requires_review=candidate_requires_review,
        total_ordered_same_face_edge_pairs=total_pairs,
        number_of_sat_calls=len(sat_calls),
        number_of_distinct_witness_cycles=witness_count,
        witness_cover_ratio=(witness_count / total_pairs if total_pairs else 0.0),
        ordered_pairs_per_witness=(
            total_pairs / witness_count if witness_count else 0.0
        ),
        total_sat_time_seconds=total_sat_time,
        maximum_single_query_sat_time_seconds=maximum_sat_time,
        subtour_iterations=subtour_iterations,
        subtour_constraints=cumulative_subtour_constraints,
        hardest_ordered_pair=hardest_pair,
        face_size_multiset=tuple(sorted(map(len, faces))),
        failed_ordered_pair=failed_pair,
        pair_records=pair_records,
        witnesses=tuple(witnesses),
        sat_calls=tuple(sat_calls),
        backtracking_queries=backtracking_queries,
        backtracking_agreements=backtracking_agreements,
        backtracking_runtime_seconds=backtracking_time,
        candidate_report_directory=(
            str(candidate_directory) if candidate_directory is not None else None
        ),
    )
