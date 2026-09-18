"""Focused tests for the prospective double-ladder construction pipeline."""

import pytest

import networkx as nx

from barnette_search.double_ladder_prediction_test import (
    construct_prediction_chain,
    enumerate_via_perfect_matchings,
    graph_record,
    normalize_cycle,
)
from barnette_search.ladder_analysis import double_ladder_graph
from barnette_search.paths import results_root


LADDER_FAMILY = results_root() / "barnie-sequence" / "ladder-analysis" / "ladder_family.json"


def test_cycle_normalization_removes_orientation_and_start() -> None:
    assert normalize_cycle((2, 3, 0, 1)) == (0, 1, 2, 3)
    assert normalize_cycle((2, 1, 0, 3, 2)) == (0, 1, 2, 3)


def test_perfect_matching_enumerator_reproduces_small_family_count() -> None:
    graph = nx.convert_node_labels_to_integers(double_ladder_graph(3, 3), ordering="sorted")
    edges = tuple(sorted((min(left, right), max(left, right)) for left, right in graph.edges()))
    universe = enumerate_via_perfect_matchings(edges, graph.number_of_nodes())
    assert len(universe) == 14


def test_prediction_chain_uses_three_valid_square_expansions() -> None:
    if not LADDER_FAMILY.exists():
        pytest.skip("external ladder-family package not configured; set BARNETTE_RESULTS_ROOT")
    graphs, certificates = construct_prediction_chain(LADDER_FAMILY)
    assert [(graph.a, graph.b, len(graph.rotation)) for graph in graphs] == [
        (9, 9, 40),
        (11, 9, 44),
        (11, 11, 48),
    ]
    assert len({graph.graph_hash for graph in graphs}) == 3
    for graph, certificate in zip(graphs, certificates):
        assert all(graph_record(graph)["validation"].values())
        assert certificate["checks"]["reconstruction_edge_set_equals_target"]
        assert certificate["checks"]["inverse_reduction_equals_mapped_source"]
        assert all(certificate["checks"]["target_barnette_properties"].values())
