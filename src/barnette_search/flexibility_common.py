"""Shared exact machinery for stronger Hamiltonian-flexibility analyses."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import asdict, dataclass
import gzip
import json
import math
from pathlib import Path
from statistics import mean, median
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
from .planar_code import (
    EmbeddedPlanarGraph,
    canonical_graph_hash,
    certificate_hash,
    encode_planar_code,
)


@dataclass(frozen=True, slots=True)
class GraphContext:
    """Deterministic edge, embedding, and identity data for one graph."""

    nodes: tuple[Hashable, ...]
    edges: tuple[Edge, ...]
    faces: tuple[tuple[Hashable, ...], ...]
    rotation_system: tuple[tuple[Hashable, ...], ...]
    canonical_graph_hash: str
    face_size_multiset: tuple[int, ...]
    indexed_planar_code: bytes


@dataclass(frozen=True, slots=True)
class FlexibilityConstraint:
    """One deterministic required/forbidden edge query."""

    key: Any
    required_edges: tuple[Edge, ...]
    forbidden_edges: tuple[Edge, ...]


@dataclass(frozen=True, slots=True)
class ConstraintDetail:
    """Optional full mapping from a constraint to its greedy witness."""

    key: Any
    required_edges: tuple[Edge, ...]
    forbidden_edges: tuple[Edge, ...]
    witness_certificate_hash: str | None
    directly_queried: bool


@dataclass(frozen=True, slots=True)
class WitnessDetail:
    """Optional full witness-cover entry."""

    trigger_key: Any
    certificate_hash: str
    newly_certified_constraints: int
    cycle: tuple[Hashable, ...] | None


@dataclass(frozen=True, slots=True)
class GreedyAnalysisResult:
    """Generic exact greedy-cover result consumed by public analyzers."""

    property_satisfied: bool
    candidate_requires_review: bool
    total_constraints: int
    number_of_sat_calls: int
    number_of_witness_cycles: int
    witness_cover_ratio: float
    average_constraints_per_witness: float
    maximum_constraints_by_one_witness: int
    total_sat_wall_time_seconds: float
    median_query_time_seconds: float
    p95_query_time_seconds: float
    p99_query_time_seconds: float
    maximum_query_time_seconds: float
    hardest_constraint: Any | None
    total_subtour_iterations: int
    total_subtour_constraints: int
    backtracking_queries: int
    backtracking_agreements: int
    backtracking_runtime_seconds: float
    failed_constraint: Any | None
    candidate_report_path: str | None
    constraint_details: tuple[ConstraintDetail, ...] | None
    witness_details: tuple[WitnessDetail, ...] | None


def percentile(values: Iterable[float], probability: float) -> float:
    """Return a deterministic linearly interpolated percentile."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def distribution(values: Iterable[float]) -> dict[str, float]:
    """Return publication-oriented distribution statistics."""
    materialized = tuple(values)
    if not materialized:
        return {
            "minimum": 0.0,
            "median": 0.0,
            "mean": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "maximum": 0.0,
        }
    return {
        "minimum": min(materialized),
        "median": median(materialized),
        "mean": mean(materialized),
        "p95": percentile(materialized, 0.95),
        "p99": percentile(materialized, 0.99),
        "maximum": max(materialized),
    }


def graph_context(graph: nx.Graph) -> GraphContext:
    """Construct deterministic abstract identity and sphere embedding data."""
    planar, embedding = nx.check_planarity(graph)
    if not planar:
        raise ValueError("flexibility analysis requires a planar graph")
    nodes = tuple(graph.nodes())
    rank = {vertex: index for index, vertex in enumerate(nodes)}
    edges = tuple(
        sorted(
            (
                (left, right) if rank[left] < rank[right] else (right, left)
                for left, right in graph.edges()
            ),
            key=lambda edge: (rank[edge[0]], rank[edge[1]]),
        )
    )
    rotation = tuple(
        tuple(embedding.neighbors_cw_order(vertex)) for vertex in nodes
    )
    seen: set[tuple[Hashable, Hashable]] = set()
    faces: list[tuple[Hashable, ...]] = []
    for left in nodes:
        for right in rotation[rank[left]]:
            if (left, right) not in seen:
                faces.append(
                    tuple(embedding.traverse_face(left, right, mark_half_edges=seen))
                )

    indexed_graph = nx.Graph()
    indexed_graph.add_nodes_from(range(len(nodes)))
    indexed_graph.add_edges_from((rank[left], rank[right]) for left, right in edges)
    indexed_rotation = tuple(
        tuple(rank[neighbor] for neighbor in rotation[index])
        for index in range(len(nodes))
    )
    indexed_faces = tuple(
        tuple(rank[vertex] for vertex in face) for face in faces
    )
    embedded = EmbeddedPlanarGraph(
        graph=indexed_graph,
        rotation_system=indexed_rotation,
        faces=indexed_faces,
    )
    return GraphContext(
        nodes=nodes,
        edges=edges,
        faces=tuple(faces),
        rotation_system=rotation,
        canonical_graph_hash=canonical_graph_hash(embedded),
        face_size_multiset=tuple(sorted(map(len, faces))),
        indexed_planar_code=encode_planar_code(indexed_rotation),
    )


def cycle_edge_set(cycle: tuple[Hashable, ...]) -> set[frozenset[Hashable]]:
    """Return the unordered edges selected by a closed cycle."""
    return {
        frozenset((left, right)) for left, right in zip(cycle, cycle[1:])
    }


def cycle_satisfies(
    cycle: tuple[Hashable, ...], constraint: FlexibilityConstraint
) -> bool:
    """Independently check every required and forbidden edge."""
    selected = cycle_edge_set(cycle)
    return all(
        frozenset(edge) in selected for edge in constraint.required_edges
    ) and all(
        frozenset(edge) not in selected for edge in constraint.forbidden_edges
    )


def _write_json(path: Path, value: Any, *, compress: bool) -> Path:
    target = path.with_suffix(path.suffix + ".gz") if compress else path
    opener = gzip.open if compress else open
    with opener(target, "wt", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, indent=2, sort_keys=True, default=repr)
        output.write("\n")
    return target


def _export_dimacs(
    session: ConstrainedHamiltonianSatSession,
    path: Path,
    constraint: FlexibilityConstraint,
    *,
    compress: bool,
) -> Path:
    session.export_dimacs(
        path,
        required_edges=constraint.required_edges,
        forbidden_edges=constraint.forbidden_edges,
    )
    if not compress:
        return path
    target = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as source, gzip.open(target, "wb") as output:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            output.write(block)
    path.unlink()
    return target


def save_candidate_review(
    graph: nx.Graph,
    context: GraphContext,
    analysis_name: str,
    constraint: FlexibilityConstraint,
    primary_session: ConstrainedHamiltonianSatSession,
    primary_result: ConstrainedHamiltonianSatResult,
    output_directory: Path,
    *,
    compress: bool,
    backtracking_cycle: tuple[Hashable, ...] | None = None,
) -> Path:
    """Persist independently checked evidence without classifying a result."""
    key_digest = certificate_hash(
        tuple(range(len(context.nodes))) + (0,)
    ) or "identity"
    directory = (
        output_directory
        / analysis_name
        / f"{context.canonical_graph_hash[:20]}-{key_digest[:8]}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    primary_cnf = _export_dimacs(
        primary_session,
        directory / "primary_constrained.cnf",
        constraint,
        compress=compress,
    )
    with ConstrainedHamiltonianSatSession(graph, solver="minisat22") as independent:
        independent_result = independent.solve(
            required_edges=constraint.required_edges,
            forbidden_edges=constraint.forbidden_edges,
        )
        independent_cnf = _export_dimacs(
            independent,
            directory / "minisat22_constrained.cnf",
            constraint,
            compress=compress,
        )
    if independent_result.cycle is not None and (
        not verify_hamiltonian_cycle(graph, independent_result.cycle)
        or not cycle_satisfies(independent_result.cycle, constraint)
    ):
        raise RuntimeError("MiniSat22 returned an invalid constrained certificate")
    if backtracking_cycle is None:
        backtracking_cycle = find_constrained_hamiltonian_cycle(
            graph,
            required_edges=constraint.required_edges,
            forbidden_edges=constraint.forbidden_edges,
        )
    if backtracking_cycle is not None and (
        not verify_hamiltonian_cycle(graph, backtracking_cycle)
        or not cycle_satisfies(backtracking_cycle, constraint)
    ):
        raise RuntimeError("independent backtracking returned an invalid certificate")

    rank = {vertex: index for index, vertex in enumerate(context.nodes)}
    graph_record = {
        "canonical_graph_hash": context.canonical_graph_hash,
        "node_labels": [repr(vertex) for vertex in context.nodes],
        "edges": [
            [rank[left], rank[right]] for left, right in context.edges
        ],
        "edge_variable_mapping": [
            {
                "variable": variable,
                "edge": [rank[left], rank[right]],
                "original_labels": [repr(left), repr(right)],
            }
            for variable, (left, right) in enumerate(context.edges, start=1)
        ],
        "rotation_system": [
            [rank[neighbor] for neighbor in row]
            for row in context.rotation_system
        ],
        "faces": [
            [rank[vertex] for vertex in face] for face in context.faces
        ],
        "constraint": asdict(constraint),
    }
    graph_path = _write_json(
        directory / "graph_embedding_and_labels.json",
        graph_record,
        compress=compress,
    )
    solver_log = {
        "classification": "candidate only; independent manual review required",
        "analysis": analysis_name,
        "constraint": asdict(constraint),
        "primary_glucose3_result": asdict(primary_result),
        "independent_minisat22_result": asdict(independent_result),
        "independent_backtracking_cycle": backtracking_cycle,
        "engines_agree": (
            primary_result.satisfiable
            == independent_result.satisfiable
            == (backtracking_cycle is not None)
        ),
        "native_solver_logs": (
            "PySAT exposes structured results but no textual proof log in this "
            "configuration. Exact CNFs and all returned models are retained."
        ),
        "files": {
            "primary_dimacs": primary_cnf.name,
            "minisat22_dimacs": independent_cnf.name,
            "graph_embedding": graph_path.name,
        },
    }
    _write_json(directory / "candidate_report.json", solver_log, compress=compress)
    return directory


def greedy_analyze(
    graph: nx.Graph,
    context: GraphContext,
    constraints: tuple[FlexibilityConstraint, ...],
    *,
    analysis_name: str,
    retain_details: bool,
    retain_witness_cycles: bool,
    cross_check_backtracking: bool,
    candidate_output_directory: Path,
    compress_candidates: bool,
) -> GreedyAnalysisResult:
    """Run a deterministic exact witness cover for arbitrary edge constraints."""
    uncovered = set(range(len(constraints)))
    witness_for: dict[int, str] = {}
    queried: set[int] = set()
    witnesses: list[WitnessDetail] = []
    query_times: list[float] = []
    hardest: Any | None = None
    maximum_time = -1.0
    subtour_iterations = 0
    failed_index: int | None = None
    candidate_path: Path | None = None
    backtracking_queries = 0
    backtracking_agreements = 0
    backtracking_time = 0.0

    with ConstrainedHamiltonianSatSession(graph) as session:
        while uncovered:
            index = min(uncovered)
            constraint = constraints[index]
            queried.add(index)
            result = session.solve(
                required_edges=constraint.required_edges,
                forbidden_edges=constraint.forbidden_edges,
            )
            query_times.append(result.runtime_seconds)
            subtour_iterations += result.subtour_iterations
            if result.runtime_seconds > maximum_time:
                maximum_time = result.runtime_seconds
                hardest = constraint.key
            if result.cycle is None:
                failed_index = index
                candidate_path = save_candidate_review(
                    graph,
                    context,
                    analysis_name,
                    constraint,
                    session,
                    result,
                    candidate_output_directory,
                    compress=compress_candidates,
                )
                break
            if not verify_hamiltonian_cycle(graph, result.cycle):
                raise RuntimeError("SAT witness failed independent verification")
            if not cycle_satisfies(result.cycle, constraint):
                raise RuntimeError("SAT witness failed independent constraint checks")
            witness_hash = certificate_hash(result.cycle)
            if witness_hash is None:
                raise RuntimeError("closed SAT witness has no certificate hash")
            certified = tuple(
                candidate
                for candidate in sorted(uncovered)
                if cycle_satisfies(result.cycle, constraints[candidate])
            )
            if index not in certified:
                raise RuntimeError("witness did not certify its trigger constraint")
            for candidate in certified:
                witness_for[candidate] = witness_hash
            uncovered.difference_update(certified)
            witnesses.append(
                WitnessDetail(
                    trigger_key=constraint.key,
                    certificate_hash=witness_hash,
                    newly_certified_constraints=len(certified),
                    cycle=result.cycle if retain_witness_cycles else None,
                )
            )

        if cross_check_backtracking and failed_index is None:
            for index, constraint in enumerate(constraints):
                started = perf_counter()
                cycle = find_constrained_hamiltonian_cycle(
                    graph,
                    required_edges=constraint.required_edges,
                    forbidden_edges=constraint.forbidden_edges,
                )
                backtracking_time += perf_counter() - started
                backtracking_queries += 1
                if cycle is not None and (
                    not verify_hamiltonian_cycle(graph, cycle)
                    or not cycle_satisfies(cycle, constraint)
                ):
                    raise RuntimeError(
                        "backtracking witness failed independent checks"
                    )
                sat_answer = index in witness_for
                if (cycle is not None) == sat_answer:
                    backtracking_agreements += 1
                    continue
                failed_index = index
                rerun = session.solve(
                    required_edges=constraint.required_edges,
                    forbidden_edges=constraint.forbidden_edges,
                )
                candidate_path = save_candidate_review(
                    graph,
                    context,
                    analysis_name,
                    constraint,
                    session,
                    rerun,
                    candidate_output_directory,
                    compress=compress_candidates,
                    backtracking_cycle=cycle,
                )
                break
        subtour_constraints = session.cumulative_subtour_constraints

    total = len(constraints)
    witness_count = len(witnesses)
    details = None
    if retain_details:
        details = tuple(
            ConstraintDetail(
                key=constraint.key,
                required_edges=constraint.required_edges,
                forbidden_edges=constraint.forbidden_edges,
                witness_certificate_hash=witness_for.get(index),
                directly_queried=index in queried,
            )
            for index, constraint in enumerate(constraints)
        )
    return GreedyAnalysisResult(
        property_satisfied=not uncovered and failed_index is None,
        candidate_requires_review=failed_index is not None,
        total_constraints=total,
        number_of_sat_calls=len(query_times),
        number_of_witness_cycles=witness_count,
        witness_cover_ratio=(witness_count / total if total else 0.0),
        average_constraints_per_witness=(
            total / witness_count if witness_count else 0.0
        ),
        maximum_constraints_by_one_witness=max(
            (witness.newly_certified_constraints for witness in witnesses),
            default=0,
        ),
        total_sat_wall_time_seconds=sum(query_times),
        median_query_time_seconds=percentile(query_times, 0.5),
        p95_query_time_seconds=percentile(query_times, 0.95),
        p99_query_time_seconds=percentile(query_times, 0.99),
        maximum_query_time_seconds=max(query_times, default=0.0),
        hardest_constraint=hardest,
        total_subtour_iterations=subtour_iterations,
        total_subtour_constraints=subtour_constraints,
        backtracking_queries=backtracking_queries,
        backtracking_agreements=backtracking_agreements,
        backtracking_runtime_seconds=backtracking_time,
        failed_constraint=(
            constraints[failed_index].key if failed_index is not None else None
        ),
        candidate_report_path=(str(candidate_path) if candidate_path else None),
        constraint_details=details,
        witness_details=(
            tuple(witnesses)
            if retain_details or retain_witness_cycles
            else None
        ),
    )
