"""Tests for combinatorial ladder detection and square expansion."""

from __future__ import annotations

import networkx as nx

from barnette_search.hsep_order36 import enumerate_hamiltonian_cycles
from barnette_search.ladder_analysis import (
    barnette_properties,
    canonicalize_embedding,
    detect_quadrilateral_structures,
    double_ladder_cycle_formula,
    double_ladder_graph,
    empirical_double_ladder_hsep,
    graph_from_rotation,
    square_reduction_certificates,
)


def _rotation(graph: nx.Graph):
    graph = nx.convert_node_labels_to_integers(graph, ordering="sorted")
    planar, embedding = nx.check_planarity(graph)
    assert planar
    return tuple(
        tuple(embedding.neighbors_cw_order(vertex))
        for vertex in range(graph.number_of_nodes())
    )


def test_double_ladder_has_two_strict_face_chains() -> None:
    rotation = _rotation(double_ladder_graph(5, 3))
    structures = detect_quadrilateral_structures(rotation)
    assert sorted(item["face_count"] for item in structures["ladders"]) == [3, 5]
    assert not structures["exceptional_quadrilateral_components"]
    assert all(item["induced"] and not item["additional_chords"] for item in structures["ladders"])


def test_embedding_normalization_removes_labels_and_reflection() -> None:
    rotation = _rotation(double_ladder_graph(5, 3))
    relabel = {index: len(rotation) - 1 - index for index in range(len(rotation))}
    reflected_relabelled = tuple(
        tuple(relabel[neighbor] for neighbor in reversed(rotation[index]))
        for index in reversed(range(len(rotation)))
    )
    first = canonicalize_embedding(rotation)
    second = canonicalize_embedding(reflected_relabelled)
    assert first["rotation_system"] == second["rotation_system"]
    assert first["canonical_graph_hash"] == second["canonical_graph_hash"]


def test_fixed_square_reduction_recovers_shorter_double_ladder() -> None:
    source = canonicalize_embedding(_rotation(double_ladder_graph(5, 3)))
    target = canonicalize_embedding(_rotation(double_ladder_graph(5, 5)))
    certificates = square_reduction_certificates(
        source["rotation_system"],
        target["rotation_system"],
        source_hash=source["canonical_graph_hash"],
        target_hash=target["canonical_graph_hash"],
    )
    assert certificates
    certificate = next(
        item
        for item in certificates
        if item["source_expanded_face"]["expanded_edges_are_detected_ladder_rails"]
    )
    assert certificate["source_expanded_face"]["expanded_edges_are_opposite"]
    assert certificate["source_expanded_face"]["expanded_edges_are_detected_ladder_rails"]
    assert certificate["canonical_hash_matches_source"]
    assert certificate["reconstruction_edge_set_matches_target"]
    assert all(certificate["reduced_barnette_properties"].values())


def test_double_ladder_cycle_and_certified_range_hsep_formulas() -> None:
    graph = nx.convert_node_labels_to_integers(double_ladder_graph(3, 3), ordering="sorted")
    cycles = tuple(enumerate_hamiltonian_cycles(tuple(sorted(graph.edges())), 16))
    assert len(cycles) == double_ladder_cycle_formula(3, 3) == 14
    assert empirical_double_ladder_hsep(3, 3) == 12
    assert empirical_double_ladder_hsep(9, 7) == 49
    assert all(barnette_properties(graph).values())
    assert graph_from_rotation(_rotation(graph)).number_of_edges() == 24
