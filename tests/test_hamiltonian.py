"""Tests for the exact Hamiltonian-cycle reference routines."""

from collections.abc import Hashable
from itertools import permutations

import networkx as nx
import pytest

from barnette_search import find_hamiltonian_cycle, verify_hamiltonian_cycle


def _assert_finds_verified_cycle(graph: nx.Graph) -> tuple[Hashable, ...]:
    cycle = find_hamiltonian_cycle(graph)

    assert cycle is not None
    assert isinstance(cycle, tuple)
    assert cycle[0] == next(iter(graph))
    assert cycle[-1] == cycle[0]
    assert verify_hamiltonian_cycle(graph, cycle)

    rank = {vertex: index for index, vertex in enumerate(graph)}
    assert rank[cycle[1]] < rank[cycle[-2]]
    return cycle


@pytest.mark.parametrize(
    "graph",
    [
        pytest.param(nx.cubical_graph(), id="cube"),
        pytest.param(nx.complete_bipartite_graph(3, 3), id="k33"),
        pytest.param(nx.cycle_graph(6), id="c6"),
    ],
)
def test_hamiltonian_graphs_return_verified_cycles(graph: nx.Graph) -> None:
    _assert_finds_verified_cycle(graph)


def test_petersen_graph_is_non_hamiltonian() -> None:
    assert find_hamiltonian_cycle(nx.petersen_graph()) is None


def test_solver_matches_permutation_oracle_through_six_vertices() -> None:
    for graph in nx.graph_atlas_g():
        nodes = tuple(graph)
        if len(nodes) > 6:
            continue

        expected = False
        if len(nodes) >= 3:
            start = nodes[0]
            expected = any(
                all(
                    graph.has_edge(left, right)
                    for left, right in zip(
                        (start, *middle, start),
                        (start, *middle, start)[1:],
                    )
                )
                for middle in permutations(nodes[1:])
            )

        cycle = find_hamiltonian_cycle(graph)
        assert (cycle is not None) is expected
        if cycle is not None:
            assert verify_hamiltonian_cycle(graph, cycle)


def test_disconnected_graph_is_non_hamiltonian() -> None:
    graph = nx.disjoint_union(nx.cycle_graph(3), nx.cycle_graph(3))

    assert find_hamiltonian_cycle(graph) is None


def test_graph_with_bridge_is_non_hamiltonian() -> None:
    graph = nx.barbell_graph(3, 0)

    assert nx.has_bridges(graph)
    assert find_hamiltonian_cycle(graph) is None


@pytest.mark.parametrize(
    "graph",
    [
        pytest.param(nx.Graph(), id="empty"),
        pytest.param(nx.empty_graph(1), id="one-vertex"),
        pytest.param(nx.path_graph(2), id="two-vertex"),
    ],
)
def test_fewer_than_three_vertices_have_no_simple_cycle(graph: nx.Graph) -> None:
    assert find_hamiltonian_cycle(graph) is None


def test_solver_handles_mixed_hashable_node_types() -> None:
    nodes: list[Hashable] = ["start", 1, ("node", 2), frozenset({3})]
    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from(zip(nodes, nodes[1:] + nodes[:1]))

    _assert_finds_verified_cycle(graph)


def test_simple_multigraph_container_is_accepted() -> None:
    graph = nx.MultiGraph(nx.cycle_graph(6))

    cycle = find_hamiltonian_cycle(graph)

    assert cycle is not None
    assert verify_hamiltonian_cycle(graph, cycle)


def test_finder_does_not_mutate_the_graph() -> None:
    graph = nx.cubical_graph()
    nodes_before = list(graph.nodes(data=True))
    edges_before = list(graph.edges(data=True))

    _assert_finds_verified_cycle(graph)

    assert list(graph.nodes(data=True)) == nodes_before
    assert list(graph.edges(data=True)) == edges_before


def _looped_cycle() -> nx.Graph:
    graph = nx.cycle_graph(6)
    graph.add_edge(0, 0)
    return graph


def _parallel_cycle() -> nx.MultiGraph:
    graph = nx.MultiGraph(nx.cycle_graph(6))
    graph.add_edge(0, 1)
    return graph


@pytest.mark.parametrize(
    ("graph", "message"),
    [
        pytest.param(nx.DiGraph(nx.cycle_graph(6)), "directed", id="directed"),
        pytest.param(_looped_cycle(), "self-loops", id="self-loop"),
        pytest.param(_parallel_cycle(), "parallel edges", id="parallel-edge"),
    ],
)
def test_invalid_graph_domains_are_rejected(
    graph: nx.Graph, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        find_hamiltonian_cycle(graph)
    with pytest.raises(ValueError, match=message):
        verify_hamiltonian_cycle(graph, ())


def test_multidigraph_reports_all_domain_violations() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(0, 0)
    graph.add_edge(0, 0)

    with pytest.raises(ValueError) as error:
        find_hamiltonian_cycle(graph)

    message = str(error.value)
    assert "directed" in message
    assert "self-loops" in message
    assert "parallel edges" in message


def test_non_networkx_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="NetworkX"):
        find_hamiltonian_cycle({0: [1], 1: [0]})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "cycle",
    [
        pytest.param(None, id="absent"),
        pytest.param((0, 1, 2, 3, 4, 5), id="wrong-length"),
        pytest.param((0, 1, 2, 3, 4, 5, 1), id="not-closed"),
        pytest.param((0, 1, 2, 3, 4, 4, 0), id="duplicate-and-missing"),
        pytest.param((0, 2, 1, 3, 4, 5, 0), id="non-edge"),
        pytest.param((0, 1, 2, 3, 4, 99, 0), id="unknown-vertex"),
        pytest.param((0, 1, 2, 3, 4, [], 0), id="unhashable-vertex"),
    ],
)
def test_verifier_rejects_invalid_certificates(cycle: object) -> None:
    assert not verify_hamiltonian_cycle(nx.cycle_graph(6), cycle)  # type: ignore[arg-type]


def test_verifier_accepts_both_cycle_orientations() -> None:
    graph = nx.cycle_graph(6)

    assert verify_hamiltonian_cycle(graph, (0, 1, 2, 3, 4, 5, 0))
    assert verify_hamiltonian_cycle(graph, (0, 5, 4, 3, 2, 1, 0))


def test_verifier_rejects_two_vertex_edge_traversal() -> None:
    assert not verify_hamiltonian_cycle(nx.path_graph(2), (0, 1, 0))
