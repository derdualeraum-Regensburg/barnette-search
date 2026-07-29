"""Tests for the independent exact SAT Hamiltonian-cycle solver."""

from collections.abc import Hashable

import networkx as nx
import pytest

pytest.importorskip("pysat")

from barnette_search import (  # noqa: E402
    find_hamiltonian_cycle,
    find_hamiltonian_cycle_sat,
    solve_hamiltonian_cycle_sat,
    verify_hamiltonian_cycle,
)


def _assert_sat_cycle(graph: nx.Graph) -> tuple[Hashable, ...]:
    result = solve_hamiltonian_cycle_sat(graph)

    assert result.satisfiable is True
    assert result.cycle is not None
    assert result.satisfiable == (result.cycle is not None)
    assert result.solver_name == "Glucose3"
    assert result.number_of_edge_variables == graph.number_of_edges()
    assert result.number_of_variables >= result.number_of_edge_variables
    assert result.number_of_clauses > 0
    assert verify_hamiltonian_cycle(graph, result.cycle)
    return result.cycle


@pytest.mark.parametrize(
    "graph",
    [
        pytest.param(nx.cubical_graph(), id="cube"),
        pytest.param(nx.complete_bipartite_graph(3, 3), id="k33"),
        pytest.param(nx.cycle_graph(6), id="c6"),
    ],
)
def test_known_hamiltonian_graphs(graph: nx.Graph) -> None:
    _assert_sat_cycle(graph)


def test_cycle_only_api_returns_a_verified_cycle() -> None:
    graph = nx.cubical_graph()

    cycle = find_hamiltonian_cycle_sat(graph)

    assert cycle is not None
    assert verify_hamiltonian_cycle(graph, cycle)


def test_petersen_graph_requires_subtour_elimination() -> None:
    result = solve_hamiltonian_cycle_sat(nx.petersen_graph())

    assert result.satisfiable is False
    assert result.cycle is None
    assert result.number_of_subtour_iterations > 0
    assert result.number_of_subtour_constraints > 0


def test_disconnected_graph_is_non_hamiltonian() -> None:
    graph = nx.disjoint_union(nx.cycle_graph(3), nx.cycle_graph(3))

    result = solve_hamiltonian_cycle_sat(graph)

    assert result.satisfiable is False
    assert result.cycle is None


@pytest.mark.parametrize(
    "graph",
    [
        pytest.param(nx.barbell_graph(3, 0), id="two-triangles"),
        pytest.param(nx.barbell_graph(4, 0), id="two-k4s"),
    ],
)
def test_bridge_graphs_have_forced_disconnected_first_models(
    graph: nx.Graph,
) -> None:
    result = solve_hamiltonian_cycle_sat(graph)

    assert nx.has_bridges(graph)
    assert result.satisfiable is False
    assert result.cycle is None
    assert result.number_of_subtour_iterations == 1
    assert result.number_of_subtour_constraints >= 1


@pytest.mark.parametrize(
    "graph",
    [
        pytest.param(nx.Graph(), id="empty"),
        pytest.param(nx.empty_graph(1), id="one-vertex"),
        pytest.param(nx.path_graph(2), id="two-vertex"),
        pytest.param(nx.path_graph(6), id="degree-below-two"),
    ],
)
def test_explicit_non_hamiltonian_edge_cases(graph: nx.Graph) -> None:
    result = solve_hamiltonian_cycle_sat(graph)

    assert result.satisfiable is False
    assert result.cycle is None
    assert result.number_of_subtour_iterations == 0
    assert result.number_of_subtour_constraints == 0


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
        find_hamiltonian_cycle_sat(graph)


def test_non_networkx_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="NetworkX"):
        find_hamiltonian_cycle_sat({0: [1], 1: [0]})  # type: ignore[arg-type]


def test_simple_multigraph_container_is_accepted() -> None:
    graph = nx.MultiGraph(nx.cycle_graph(6))

    cycle = find_hamiltonian_cycle_sat(graph)

    assert cycle is not None
    assert verify_hamiltonian_cycle(graph, cycle)


def test_nonconsecutive_node_labels_are_supported() -> None:
    labels = {
        vertex: f"node-{10 * vertex + 7}" for vertex in range(8)
    }
    graph = nx.relabel_nodes(
        nx.cubical_graph(), labels
    )

    cycle = _assert_sat_cycle(graph)

    assert set(cycle[:-1]) == set(graph)


def test_sat_solver_does_not_call_backtracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import barnette_search.hamiltonian as backtracking_module
    import barnette_search.hamiltonian_sat as sat_module

    def unexpected_call(graph: nx.Graph) -> None:
        raise AssertionError("SAT solver called the backtracking implementation")

    monkeypatch.setattr(
        backtracking_module, "find_hamiltonian_cycle", unexpected_call
    )
    assert not hasattr(sat_module, "find_hamiltonian_cycle")
    _assert_sat_cycle(nx.cycle_graph(6))


def test_sat_and_backtracking_agree_on_graph_atlas_through_seven_vertices() -> None:
    for atlas_index, graph in enumerate(nx.graph_atlas_g()):
        backtracking_cycle = find_hamiltonian_cycle(graph)
        sat_cycle = find_hamiltonian_cycle_sat(graph)
        context = f"atlas index {atlas_index}, edges={list(graph.edges())}"

        assert (sat_cycle is not None) == (
            backtracking_cycle is not None
        ), context
        if sat_cycle is not None:
            assert verify_hamiltonian_cycle(graph, sat_cycle), context


_RANDOM_CASES: tuple[tuple[int, int], ...] = (
    (8, 1),
    (8, 7),
    (9, 12),
    (9, 1),
    (10, 46),
    (10, 7),
    (11, 22),
    (11, 7),
    (12, 10),
    (12, 1),
)


@pytest.mark.parametrize(("number_of_vertices", "seed"), _RANDOM_CASES)
def test_sat_and_backtracking_agree_on_deterministic_random_graphs(
    number_of_vertices: int, seed: int
) -> None:
    graph = nx.gnp_random_graph(number_of_vertices, 0.32, seed=seed)

    backtracking_cycle = find_hamiltonian_cycle(graph)
    sat_cycle = find_hamiltonian_cycle_sat(graph)

    assert nx.is_connected(graph)
    assert min(dict(graph.degree()).values()) >= 2
    assert nx.is_biconnected(graph)
    assert (sat_cycle is not None) == (backtracking_cycle is not None)
    if sat_cycle is not None:
        assert verify_hamiltonian_cycle(graph, sat_cycle)
