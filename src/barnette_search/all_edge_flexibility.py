"""Exact Hamiltonian flexibility for all ordered pairs of graph edges."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from .flexibility_common import (
    ConstraintDetail,
    FlexibilityConstraint,
    WitnessDetail,
    graph_context,
    greedy_analyze,
)


Edge = tuple[Hashable, Hashable]
EdgePair = tuple[Edge, Edge]


@dataclass(frozen=True, slots=True)
class AllEdgePairFlexibilityResult:
    """Compact or detailed result for all ordered distinct edge pairs."""

    graph_order: int
    edge_count: int
    canonical_graph_hash: str
    face_size_multiset: tuple[int, ...]
    total_ordered_edge_pairs: int
    number_of_constrained_sat_calls: int
    number_of_witness_cycles: int
    witness_cover_ratio: float
    average_pairs_certified_per_witness: float
    maximum_pairs_certified_by_one_witness: int
    total_sat_wall_time_seconds: float
    median_query_time_seconds: float
    p95_query_time_seconds: float
    p99_query_time_seconds: float
    maximum_query_time_seconds: float
    hardest_ordered_pair: EdgePair | None
    total_subtour_iterations: int
    total_subtour_constraints: int
    property_satisfied: bool
    candidate_requires_review: bool
    candidate_report_path: str | None
    backtracking_queries: int
    backtracking_agreements: int
    backtracking_runtime_seconds: float
    pair_details: tuple[ConstraintDetail, ...] | None
    witnesses: tuple[WitnessDetail, ...] | None


def analyze_all_edge_pair_flexibility(
    graph: nx.Graph,
    *,
    retain_pair_details: bool = False,
    retain_witness_cycles: bool = False,
    cross_check_backtracking: bool = False,
    candidate_output_directory: Path | None = None,
    compress_candidates: bool = False,
) -> AllEdgePairFlexibilityResult:
    """Test every ordered pair of distinct undirected graph edges exactly."""
    context = graph_context(graph)
    constraints = tuple(
        FlexibilityConstraint(
            key=(required, forbidden),
            required_edges=(required,),
            forbidden_edges=(forbidden,),
        )
        for required in context.edges
        for forbidden in context.edges
        if required != forbidden
    )
    core = greedy_analyze(
        graph,
        context,
        constraints,
        analysis_name="all_edge_pairs",
        retain_details=retain_pair_details,
        retain_witness_cycles=retain_witness_cycles,
        cross_check_backtracking=cross_check_backtracking,
        candidate_output_directory=(
            candidate_output_directory
            or Path("results") / "flexibility_candidates"
        ),
        compress_candidates=compress_candidates,
    )
    return AllEdgePairFlexibilityResult(
        graph_order=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        canonical_graph_hash=context.canonical_graph_hash,
        face_size_multiset=context.face_size_multiset,
        total_ordered_edge_pairs=core.total_constraints,
        number_of_constrained_sat_calls=core.number_of_sat_calls,
        number_of_witness_cycles=core.number_of_witness_cycles,
        witness_cover_ratio=core.witness_cover_ratio,
        average_pairs_certified_per_witness=core.average_constraints_per_witness,
        maximum_pairs_certified_by_one_witness=(
            core.maximum_constraints_by_one_witness
        ),
        total_sat_wall_time_seconds=core.total_sat_wall_time_seconds,
        median_query_time_seconds=core.median_query_time_seconds,
        p95_query_time_seconds=core.p95_query_time_seconds,
        p99_query_time_seconds=core.p99_query_time_seconds,
        maximum_query_time_seconds=core.maximum_query_time_seconds,
        hardest_ordered_pair=core.hardest_constraint,
        total_subtour_iterations=core.total_subtour_iterations,
        total_subtour_constraints=core.total_subtour_constraints,
        property_satisfied=core.property_satisfied,
        candidate_requires_review=core.candidate_requires_review,
        candidate_report_path=core.candidate_report_path,
        backtracking_queries=core.backtracking_queries,
        backtracking_agreements=core.backtracking_agreements,
        backtracking_runtime_seconds=core.backtracking_runtime_seconds,
        pair_details=core.constraint_details,
        witnesses=core.witness_details,
    )
