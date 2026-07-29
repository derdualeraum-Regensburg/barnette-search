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


def test_oriented_cube_uses_original_directed_degrees() -> None:
    cube = nx.cubical_graph()
    graph = nx.DiGraph()
    graph.add_nodes_from(cube)
    graph.add_edges_from(cube.edges())

    result = validate_barnette_graph(graph)

    assert all(degree == 3 for _, degree in graph.degree())
    assert result.number_of_edges == 12
    assert result.rejection_reasons == [UNDIRECTED_REASON, THREE_CONNECTED_REASON]


def test_multidigraph_reports_repeated_ordered_arcs() -> None:
    cube = nx.cubical_graph()
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(cube)
    graph.add_edges_from(cube.edges())
    first_edge = next(iter(cube.edges()))
    graph.add_edge(*first_edge)

    result = validate_barnette_graph(graph)

    assert result.number_of_edges == 13
    assert result.rejection_reasons == [
        UNDIRECTED_REASON,
        PARALLEL_EDGE_REASON,
        CUBIC_REASON,
        THREE_CONNECTED_REASON,
    ]


def test_reciprocal_multidigraph_arcs_are_not_parallel() -> None:
    graph = nx.MultiDiGraph([(0, 1), (1, 0)])

    result = validate_barnette_graph(graph)

    assert result.number_of_edges == 2
    assert PARALLEL_EDGE_REASON not in result.rejection_reasons
    assert UNDIRECTED_REASON in result.rejection_reasons


def test_repeated_self_loop_is_both_a_loop_and_a_parallel_edge() -> None:
    graph = nx.MultiGraph()
    graph.add_edge(0, 0)
    graph.add_edge(0, 0)

    result = validate_barnette_graph(graph)

    assert result.number_of_edges == 2
    assert SELF_LOOP_REASON in result.rejection_reasons
    assert PARALLEL_EDGE_REASON in result.rejection_reasons


def test_parallel_multiplicity_counts_toward_cubic_degree() -> None:
    graph = nx.MultiGraph()
    graph.add_edges_from([(0, 1), (0, 1), (0, 1)])

    result = validate_barnette_graph(graph)

    assert dict(graph.degree()) == {0: 3, 1: 3}
    assert result.rejection_reasons == [
        PARALLEL_EDGE_REASON,
        THREE_CONNECTED_REASON,
    ]


def test_self_loop_counts_twice_toward_cubic_degree() -> None:
    graph = nx.Graph([(0, 0), (0, 1), (1, 1)])

    result = validate_barnette_graph(graph)

    assert dict(graph.degree()) == {0: 3, 1: 3}
    assert result.rejection_reasons == [
        SELF_LOOP_REASON,
        BIPARTITE_REASON,
        THREE_CONNECTED_REASON,
    ]


def test_non_simple_nonplanar_skeleton_is_still_nonplanar() -> None:
    graph = nx.MultiGraph(nx.complete_bipartite_graph(3, 3))
    graph.add_edge(0, 3)

    result = validate_barnette_graph(graph)

    assert result.rejection_reasons == [
        PARALLEL_EDGE_REASON,
        CUBIC_REASON,
        PLANAR_REASON,
    ]


def test_three_connectivity_uses_vertex_deletions_not_edge_multiplicity() -> None:
    graph = nx.MultiGraph(nx.cycle_graph(4))
    graph.add_edge(0, 1)
    graph.add_edge(2, 3)

    result = validate_barnette_graph(graph)

    assert all(degree == 3 for _, degree in graph.degree())
    assert result.rejection_reasons == [
        PARALLEL_EDGE_REASON,
        THREE_CONNECTED_REASON,
    ]

