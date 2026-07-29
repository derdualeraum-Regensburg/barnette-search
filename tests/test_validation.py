"""Tests for the NetworkX reference validator."""

import networkx as nx

from barnette_search import ValidationResult, validate_barnette_graph
from barnette_search.validation import (
    BIPARTITE_REASON,
    CUBIC_REASON,
    PARALLEL_EDGE_REASON,
    PLANAR_REASON,
    SELF_LOOP_REASON,
    THREE_CONNECTED_REASON,
    UNDIRECTED_REASON,
)


def test_cube_graph_is_a_valid_barnette_graph() -> None:
    result = validate_barnette_graph(nx.cubical_graph())

    assert result == ValidationResult(
        valid=True,
        number_of_vertices=8,
        number_of_edges=12,
        rejection_reasons=[],
    )


def test_k4_is_rejected_as_non_bipartite() -> None:
    result = validate_barnette_graph(nx.complete_graph(4))

    assert result.valid is False
    assert result.rejection_reasons == [BIPARTITE_REASON]


def test_c6_reports_every_failed_property() -> None:
    result = validate_barnette_graph(nx.cycle_graph(6))

    assert result.valid is False
    assert result.rejection_reasons == [CUBIC_REASON, THREE_CONNECTED_REASON]


def test_disconnected_cubic_graph_is_not_three_connected() -> None:
    graph = nx.disjoint_union(nx.cubical_graph(), nx.cubical_graph())

    result = validate_barnette_graph(graph)

    assert result.number_of_vertices == 16
    assert result.number_of_edges == 24
    assert result.rejection_reasons == [THREE_CONNECTED_REASON]


def test_self_loop_is_reported_and_other_checks_still_run() -> None:
    graph = nx.cubical_graph()
    graph.add_edge(0, 0)

    result = validate_barnette_graph(graph)

    assert result.number_of_edges == 13
    assert result.rejection_reasons == [
        SELF_LOOP_REASON,
        CUBIC_REASON,
        BIPARTITE_REASON,
    ]


def test_parallel_edge_is_reported_for_a_multigraph() -> None:
    graph = nx.MultiGraph(nx.cubical_graph())
    graph.add_edge(0, 1)

    result = validate_barnette_graph(graph)

    assert result.number_of_edges == 13
    assert result.rejection_reasons == [PARALLEL_EDGE_REASON, CUBIC_REASON]


def test_multigraph_container_without_parallel_edges_can_be_valid() -> None:
    result = validate_barnette_graph(nx.MultiGraph(nx.cubical_graph()))

    assert result.valid is True
    assert result.rejection_reasons == []


def test_k33_is_rejected_as_non_planar() -> None:
    result = validate_barnette_graph(nx.complete_bipartite_graph(3, 3))

    assert result.rejection_reasons == [PLANAR_REASON]


def test_directed_graph_is_rejected_without_skipping_other_checks() -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(range(4))

    result = validate_barnette_graph(graph)

    assert result.rejection_reasons == [
        UNDIRECTED_REASON,
        CUBIC_REASON,
        THREE_CONNECTED_REASON,
    ]

