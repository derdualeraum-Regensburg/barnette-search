"""Exact Hamiltonian flexibility for every canonical three-edge path."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from .flexibility_common import (
    ConstraintDetail,
    FlexibilityConstraint,
    GraphContext,
    WitnessDetail,
    graph_context,
    greedy_analyze,
)


ThreeEdgePath = tuple[Hashable, Hashable, Hashable, Hashable]


@dataclass(frozen=True, slots=True)
class ThreeEdgePathFlexibilityResult:
    """Compact or detailed result for all canonical three-edge paths."""

    graph_order: int
    edge_count: int
    canonical_graph_hash: str
    face_size_multiset: tuple[int, ...]
    number_of_distinct_three_edge_paths: int
    number_of_constrained_sat_calls: int
    number_of_witness_cycles: int
    witness_cover_ratio: float
    average_paths_certified_per_witness: float
    maximum_paths_certified_by_one_witness: int
    total_sat_wall_time_seconds: float
    median_query_time_seconds: float
    p95_query_time_seconds: float
    p99_query_time_seconds: float
    maximum_query_time_seconds: float
    hardest_path: ThreeEdgePath | None
    total_subtour_iterations: int
    total_subtour_constraints: int
    property_satisfied: bool
    candidate_requires_review: bool
    candidate_report_path: str | None
    backtracking_queries: int
    backtracking_agreements: int
    backtracking_runtime_seconds: float
    path_details: tuple[ConstraintDetail, ...] | None
    witnesses: tuple[WitnessDetail, ...] | None


def _enumerate_three_edge_paths(
    graph: nx.Graph, context: GraphContext
) -> tuple[ThreeEdgePath, ...]:
    """Enumerate using a precomputed graph context."""
    nodes = context.nodes
    edges = context.edges
    rank = {vertex: index for index, vertex in enumerate(nodes)}
    paths: set[ThreeEdgePath] = set()
    for middle_left, middle_right in edges:
        left_neighbors = sorted(
            (v for v in graph.neighbors(middle_left) if v != middle_right),
            key=rank.__getitem__,
        )
        right_neighbors = sorted(
            (v for v in graph.neighbors(middle_right) if v != middle_left),
            key=rank.__getitem__,
        )
        for outer_left in left_neighbors:
            for outer_right in right_neighbors:
                path = (outer_left, middle_left, middle_right, outer_right)
                if len(set(path)) != 4:
                    continue
                reverse = tuple(reversed(path))
                canonical = min(
                    (path, reverse),
                    key=lambda candidate: tuple(rank[v] for v in candidate),
                )
                paths.add(canonical)
    return tuple(
        sorted(paths, key=lambda path: tuple(rank[vertex] for vertex in path))
    )


def enumerate_three_edge_paths(graph: nx.Graph) -> tuple[ThreeEdgePath, ...]:
    """Enumerate simple length-three paths, deduplicating reversal."""
    context = graph_context(graph)
    return _enumerate_three_edge_paths(graph, context)


def analyze_three_edge_path_flexibility(
    graph: nx.Graph,
    *,
    retain_path_details: bool = False,
    retain_witness_cycles: bool = False,
    cross_check_backtracking: bool = False,
    candidate_output_directory: Path | None = None,
    compress_candidates: bool = False,
) -> ThreeEdgePathFlexibilityResult:
    """Test every simple canonical length-three path exactly."""
    context = graph_context(graph)
    paths = _enumerate_three_edge_paths(graph, context)
    rank = {vertex: index for index, vertex in enumerate(context.nodes)}

    def edge(left: Hashable, right: Hashable) -> tuple[Hashable, Hashable]:
        return (left, right) if rank[left] < rank[right] else (right, left)

    constraints = tuple(
        FlexibilityConstraint(
            key=path,
            required_edges=(edge(path[1], path[2]),),
            forbidden_edges=(edge(path[0], path[1]), edge(path[2], path[3])),
        )
        for path in paths
    )
    core = greedy_analyze(
        graph,
        context,
        constraints,
        analysis_name="three_edge_paths",
        retain_details=retain_path_details,
        retain_witness_cycles=retain_witness_cycles,
        cross_check_backtracking=cross_check_backtracking,
        candidate_output_directory=(
            candidate_output_directory
            or Path("results") / "flexibility_candidates"
        ),
        compress_candidates=compress_candidates,
    )
    return ThreeEdgePathFlexibilityResult(
        graph_order=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        canonical_graph_hash=context.canonical_graph_hash,
        face_size_multiset=context.face_size_multiset,
        number_of_distinct_three_edge_paths=core.total_constraints,
        number_of_constrained_sat_calls=core.number_of_sat_calls,
        number_of_witness_cycles=core.number_of_witness_cycles,
        witness_cover_ratio=core.witness_cover_ratio,
        average_paths_certified_per_witness=(
            core.average_constraints_per_witness
        ),
        maximum_paths_certified_by_one_witness=(
            core.maximum_constraints_by_one_witness
        ),
        total_sat_wall_time_seconds=core.total_sat_wall_time_seconds,
        median_query_time_seconds=core.median_query_time_seconds,
        p95_query_time_seconds=core.p95_query_time_seconds,
        p99_query_time_seconds=core.p99_query_time_seconds,
        maximum_query_time_seconds=core.maximum_query_time_seconds,
        hardest_path=core.hardest_constraint,
        total_subtour_iterations=core.total_subtour_iterations,
        total_subtour_constraints=core.total_subtour_constraints,
        property_satisfied=core.property_satisfied,
        candidate_requires_review=core.candidate_requires_review,
        candidate_report_path=core.candidate_report_path,
        backtracking_queries=core.backtracking_queries,
        backtracking_agreements=core.backtracking_agreements,
        backtracking_runtime_seconds=core.backtracking_runtime_seconds,
        path_details=core.constraint_details,
        witnesses=core.witness_details,
    )
