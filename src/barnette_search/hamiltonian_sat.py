"""Independent exact SAT reference solver for Hamiltonian cycles.

Each undirected input edge has one primary Boolean variable. PySAT sequential
counter encodings require exactly two selected incident edges at every vertex,
so each model is a spanning 2-factor and may initially contain several cycles.

For every proper selected-edge component ``S``, the solver incrementally adds
``sum(delta(S)) >= 2``. Every Hamiltonian cycle crosses every nonempty proper
vertex cut at least twice, so these subtour constraints cannot remove a
Hamiltonian cycle. They do remove the current disconnected 2-factor, whose
selected cut contains no edges. Solving and refinement continue until one
spanning cycle is found or the formula becomes unsatisfiable.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import Any

import networkx as nx

from .graph_io import NetworkXGraph
from .hamiltonian import verify_hamiltonian_cycle
from .validation import _has_parallel_edges

_SOLVER_KEY = "g3"
_SOLVER_NAME = "Glucose3"


@dataclass(frozen=True, slots=True)
class HamiltonianSatResult:
    """Result and encoding statistics from the exact SAT solver."""

    satisfiable: bool
    cycle: tuple[Hashable, ...] | None
    solver_name: str
    number_of_edge_variables: int
    number_of_variables: int
    number_of_clauses: int
    number_of_subtour_iterations: int
    number_of_subtour_constraints: int


def _load_pysat() -> tuple[Any, Any, Any]:
    """Load optional PySAT components only when SAT solving is requested."""
    try:
        from pysat.card import CardEnc, EncType
        from pysat.solvers import Solver
    except ImportError as error:
        raise ImportError(
            "SAT support requires python-sat; install barnette-search[sat]"
        ) from error
    return CardEnc, EncType, Solver


def _require_simple_undirected_graph(graph: object) -> NetworkXGraph:
    """Enforce the SAT solver's finite, undirected, simple input domain."""
    if not isinstance(
        graph, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)
    ):
        raise TypeError("graph must be a NetworkX graph object")

    violations: list[str] = []
    if graph.is_directed():
        violations.append("directed")
    if nx.number_of_selfloops(graph) > 0:
        violations.append("contains self-loops")
    if _has_parallel_edges(graph):
        violations.append("contains parallel edges")
    if violations:
        details = ", ".join(violations)
        raise ValueError(
            "SAT Hamiltonian-cycle solving requires an undirected simple graph; "
            f"input is {details}"
        )
    return graph


def _negative_result(
    *,
    number_of_edge_variables: int,
    number_of_variables: int,
    number_of_clauses: int,
    number_of_subtour_iterations: int = 0,
    number_of_subtour_constraints: int = 0,
) -> HamiltonianSatResult:
    """Construct a negative structured result with consistent metadata."""
    return HamiltonianSatResult(
        satisfiable=False,
        cycle=None,
        solver_name=_SOLVER_NAME,
        number_of_edge_variables=number_of_edge_variables,
        number_of_variables=number_of_variables,
        number_of_clauses=number_of_clauses,
        number_of_subtour_iterations=number_of_subtour_iterations,
        number_of_subtour_constraints=number_of_subtour_constraints,
    )


def _selected_components(
    graph: NetworkXGraph,
    edges: tuple[tuple[Hashable, Hashable], ...],
    model: list[int],
) -> tuple[tuple[tuple[Hashable, Hashable], ...], list[set[Hashable]]]:
    """Extract selected primary edges and all their connected components."""
    number_of_edges = len(edges)
    selected_variables = {
        literal for literal in model if 0 < literal <= number_of_edges
    }
    selected_edges = tuple(
        edge
        for variable, edge in enumerate(edges, start=1)
        if variable in selected_variables
    )

    selected_graph = nx.Graph()
    selected_graph.add_nodes_from(graph.nodes())
    selected_graph.add_edges_from(selected_edges)
    if any(degree != 2 for _, degree in selected_graph.degree()):
        raise RuntimeError("SAT model violates an encoded degree constraint")

    components = [
        set(component) for component in nx.connected_components(selected_graph)
    ]
    return selected_edges, components


def _cycle_from_edges(
    graph: NetworkXGraph,
    selected_edges: tuple[tuple[Hashable, Hashable], ...],
) -> tuple[Hashable, ...]:
    """Traverse a connected selected 2-factor in deterministic orientation."""
    nodes = tuple(graph.nodes())
    rank = {vertex: index for index, vertex in enumerate(nodes)}
    adjacency: dict[Hashable, set[Hashable]] = {vertex: set() for vertex in nodes}
    for left, right in selected_edges:
        adjacency[left].add(right)
        adjacency[right].add(left)

    start = nodes[0]
    first = min(adjacency[start], key=rank.__getitem__)
    cycle: list[Hashable] = [start, first]
    previous, current = start, first
    while current != start:
        successors = adjacency[current] - {previous}
        if len(successors) != 1:
            raise RuntimeError("selected edges do not form one simple cycle")
        following = next(iter(successors))
        cycle.append(following)
        previous, current = current, following
        if len(cycle) > len(nodes) + 1:
            raise RuntimeError("selected-edge traversal did not close")
    return tuple(cycle)


def solve_hamiltonian_cycle_sat(graph: NetworkXGraph) -> HamiltonianSatResult:
    """Solve exactly with incremental SAT and return detailed statistics.

    PySAT is optional and loaded by this function. Materialized NetworkX graphs
    are finite; directed graphs, self-loops, and actual parallel edges are
    rejected. A ``MultiGraph`` container without those defects is accepted.
    """
    checked_graph = _require_simple_undirected_graph(graph)
    CardEnc, EncType, Solver = _load_pysat()

    nodes = tuple(checked_graph.nodes())
    edges = tuple(checked_graph.edges())
    number_of_edge_variables = len(edges)

    if len(nodes) < 3:
        return _negative_result(
            number_of_edge_variables=number_of_edge_variables,
            number_of_variables=number_of_edge_variables,
            number_of_clauses=0,
        )
    if not nx.is_connected(checked_graph):
        return _negative_result(
            number_of_edge_variables=number_of_edge_variables,
            number_of_variables=number_of_edge_variables,
            number_of_clauses=0,
        )
    if any(degree < 2 for _, degree in checked_graph.degree()):
        return _negative_result(
            number_of_edge_variables=number_of_edge_variables,
            number_of_variables=number_of_edge_variables,
            number_of_clauses=0,
        )

    incident_variables: dict[Hashable, list[int]] = {
        vertex: [] for vertex in nodes
    }
    for variable, (left, right) in enumerate(edges, start=1):
        incident_variables[left].append(variable)
        incident_variables[right].append(variable)

    clauses: list[list[int]] = []
    top_variable = number_of_edge_variables
    for vertex in nodes:
        encoding = CardEnc.equals(
            lits=incident_variables[vertex],
            bound=2,
            top_id=top_variable,
            encoding=EncType.seqcounter,
        )
        clauses.extend(encoding.clauses)
        top_variable = max(top_variable, encoding.nv)

    number_of_clauses = len(clauses)
    number_of_subtour_iterations = 0
    number_of_subtour_constraints = 0
    seen_subtour_cuts: set[frozenset[int]] = set()

    with Solver(name=_SOLVER_KEY, bootstrap_with=clauses) as solver:
        while solver.solve():
            model = solver.get_model()
            if model is None:
                raise RuntimeError("SAT solver returned no model after SAT")
            selected_edges, components = _selected_components(
                checked_graph, edges, model
            )

            if len(components) == 1:
                cycle = _cycle_from_edges(checked_graph, selected_edges)
                if not verify_hamiltonian_cycle(checked_graph, cycle):
                    raise RuntimeError("SAT solver produced an invalid cycle")
                return HamiltonianSatResult(
                    satisfiable=True,
                    cycle=cycle,
                    solver_name=_SOLVER_NAME,
                    number_of_edge_variables=number_of_edge_variables,
                    number_of_variables=top_variable,
                    number_of_clauses=number_of_clauses,
                    number_of_subtour_iterations=number_of_subtour_iterations,
                    number_of_subtour_constraints=number_of_subtour_constraints,
                )

            new_subtour_constraints = 0
            for component in components:
                cut_variables = [
                    variable
                    for variable, (left, right) in enumerate(edges, start=1)
                    if (left in component) != (right in component)
                ]
                cut_key = frozenset(cut_variables)
                if cut_key in seen_subtour_cuts:
                    continue
                seen_subtour_cuts.add(cut_key)

                if len(cut_variables) < 2:
                    # The at-least-two constraint is impossible. An empty clause
                    # is its exact CNF representation; CardEnc rejects this bound.
                    cut_clauses = [[]]
                    new_top_variable = top_variable
                else:
                    encoding = CardEnc.atleast(
                        lits=cut_variables,
                        bound=2,
                        top_id=top_variable,
                        encoding=EncType.seqcounter,
                    )
                    cut_clauses = encoding.clauses
                    new_top_variable = max(top_variable, encoding.nv)
                for clause in cut_clauses:
                    solver.add_clause(clause)
                number_of_clauses += len(cut_clauses)
                top_variable = new_top_variable
                number_of_subtour_constraints += 1
                new_subtour_constraints += 1

            if new_subtour_constraints == 0:
                raise RuntimeError("SAT refinement produced no new subtour cut")
            number_of_subtour_iterations += 1

    return _negative_result(
        number_of_edge_variables=number_of_edge_variables,
        number_of_variables=top_variable,
        number_of_clauses=number_of_clauses,
        number_of_subtour_iterations=number_of_subtour_iterations,
        number_of_subtour_constraints=number_of_subtour_constraints,
    )


def find_hamiltonian_cycle_sat(
    graph: NetworkXGraph,
) -> tuple[Hashable, ...] | None:
    """Return an exact SAT-derived Hamiltonian cycle, or ``None``."""
    return solve_hamiltonian_cycle_sat(graph).cycle
