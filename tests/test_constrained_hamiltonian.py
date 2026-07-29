"""Cross-tests for the independent constrained exact solvers."""

import networkx as nx
import pytest

from barnette_search.constrained_hamiltonian import (
    find_constrained_hamiltonian_cycle,
)
from barnette_search.constrained_hamiltonian_sat import (
    solve_constrained_hamiltonian_cycle_sat,
)
from barnette_search.hamiltonian import verify_hamiltonian_cycle


def _edge_keys(cycle: tuple[object, ...]) -> set[frozenset[object]]:
    return {
        frozenset((left, right)) for left, right in zip(cycle, cycle[1:])
    }


def _assert_constraints(
    graph: nx.Graph,
    cycle: tuple[object, ...],
    required: tuple[tuple[object, object], ...],
    forbidden: tuple[tuple[object, object], ...],
) -> None:
    assert verify_hamiltonian_cycle(graph, cycle)
    selected = _edge_keys(cycle)
    assert all(frozenset(edge) in selected for edge in required)
    assert all(frozenset(edge) not in selected for edge in forbidden)


@pytest.mark.parametrize(
    ("required", "forbidden", "expected"),
    [
        (((0, 1),), (), True),
        ((), ((0, 1),), True),
        (((0, 1), (5, 6)), ((0, 3), (1, 7)), True),
        (((0, 1), (0, 3), (0, 4)), (), False),
    ],
)
def test_handcrafted_cube_constraints(
    required: tuple[tuple[int, int], ...],
    forbidden: tuple[tuple[int, int], ...],
    expected: bool,
) -> None:
    graph = nx.cubical_graph()
    sat = solve_constrained_hamiltonian_cycle_sat(graph, required, forbidden)
    backtracking = find_constrained_hamiltonian_cycle(graph, required, forbidden)
    assert sat.satisfiable is expected
    assert (backtracking is not None) is expected
    for cycle in (sat.cycle, backtracking):
        if cycle is not None:
            _assert_constraints(graph, cycle, required, forbidden)


@pytest.mark.parametrize("solver", ["sat", "backtracking"])
@pytest.mark.parametrize("constraint_kind", ["required", "forbidden"])
def test_constraint_edge_must_exist(solver: str, constraint_kind: str) -> None:
    graph = nx.cycle_graph(5)
    required = ((0, 2),) if constraint_kind == "required" else ()
    forbidden = ((0, 2),) if constraint_kind == "forbidden" else ()
    function = (
        solve_constrained_hamiltonian_cycle_sat
        if solver == "sat"
        else find_constrained_hamiltonian_cycle
    )
    with pytest.raises(ValueError, match="not in the graph"):
        function(graph, required, forbidden)


@pytest.mark.parametrize(
    "function",
    [solve_constrained_hamiltonian_cycle_sat, find_constrained_hamiltonian_cycle],
)
def test_contradictory_requirements_are_rejected(function) -> None:
    with pytest.raises(ValueError, match="both required and forbidden"):
        function(nx.cycle_graph(5), ((0, 1),), ((1, 0),))


def test_nonconsecutive_heterogeneous_labels() -> None:
    labels = {0: "start", 1: 20, 2: ("v", 2), 3: -7, 4: "last", 5: 99}
    graph = nx.relabel_nodes(nx.cycle_graph(6), labels)
    required = (("start", 20),)
    sat = solve_constrained_hamiltonian_cycle_sat(graph, required)
    backtracking = find_constrained_hamiltonian_cycle(graph, required)
    assert sat.cycle is not None
    assert backtracking is not None
    _assert_constraints(graph, sat.cycle, required, ())
    _assert_constraints(graph, backtracking, required, ())


def test_cycle_graph_forbidden_edge_is_unsatisfiable() -> None:
    graph = nx.cycle_graph(6)
    sat = solve_constrained_hamiltonian_cycle_sat(graph, forbidden_edges=((0, 1),))
    backtracking = find_constrained_hamiltonian_cycle(
        graph, forbidden_edges=((0, 1),)
    )
    assert not sat.satisfiable
    assert sat.cycle is None
    assert backtracking is None
