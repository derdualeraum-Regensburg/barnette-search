"""Exact incremental SAT solver for edge-constrained Hamiltonian cycles.

One primary Boolean variable represents every undirected edge. Sequential
cardinality encodings select exactly two incident edges at every vertex.
Required and forbidden edges are query assumptions. Subtour cuts are added to
the persistent session: every Hamiltonian cycle crosses every proper nonempty
vertex cut at least twice, so those clauses remain valid for all later queries.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import networkx as nx

from .graph_io import NetworkXGraph
from .hamiltonian import verify_hamiltonian_cycle
from .validation import _has_parallel_edges


Edge = tuple[Hashable, Hashable]


@dataclass(frozen=True, slots=True)
class ConstrainedHamiltonianSatResult:
    """A constrained decision result with per-query and cumulative SAT facts."""

    satisfiable: bool
    cycle: tuple[Hashable, ...] | None
    solver_name: str
    required_edges: tuple[Edge, ...]
    forbidden_edges: tuple[Edge, ...]
    number_of_edge_variables: int
    number_of_variables: int
    number_of_clauses: int
    subtour_iterations: int
    subtour_constraints: int
    cumulative_subtour_constraints: int
    runtime_seconds: float


def _load_pysat() -> tuple[Any, Any, Any]:
    try:
        from pysat.card import CardEnc, EncType
        from pysat.solvers import Solver
    except ImportError as error:
        raise ImportError(
            "constrained SAT support requires python-sat; "
            "install barnette-search[sat]"
        ) from error
    return CardEnc, EncType, Solver


def _require_simple_undirected_graph(graph: object) -> NetworkXGraph:
    if not isinstance(
        graph, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)
    ):
        raise TypeError("graph must be a NetworkX graph object")
    violations: list[str] = []
    if graph.is_directed():
        violations.append("directed")
    if nx.number_of_selfloops(graph):
        violations.append("contains self-loops")
    if _has_parallel_edges(graph):
        violations.append("contains parallel edges")
    if violations:
        raise ValueError(
            "constrained Hamiltonian-cycle solving requires an undirected "
            f"simple graph; input is {', '.join(violations)}"
        )
    return graph


def _edge_key(edge: Edge, rank: dict[Hashable, int]) -> Edge:
    left, right = edge
    return (left, right) if rank[left] < rank[right] else (right, left)


def _normalize_constraints(
    graph: NetworkXGraph,
    edges: Iterable[Edge],
    *,
    name: str,
    rank: dict[Hashable, int],
) -> tuple[Edge, ...]:
    normalized: set[Edge] = set()
    for raw_edge in edges:
        try:
            left, right = raw_edge
        except (TypeError, ValueError) as error:
            raise ValueError(f"every {name} edge must contain two endpoints") from error
        if left not in rank or right not in rank:
            raise ValueError(f"{name} edge {raw_edge!r} contains an unknown vertex")
        if not graph.has_edge(left, right):
            raise ValueError(f"{name} edge {raw_edge!r} is not in the graph")
        normalized.add(_edge_key((left, right), rank))
    return tuple(
        sorted(normalized, key=lambda edge: (rank[edge[0]], rank[edge[1]]))
    )


def _cycle_edges(cycle: tuple[Hashable, ...]) -> set[frozenset[Hashable]]:
    return {
        frozenset((left, right))
        for left, right in zip(cycle, cycle[1:])
    }


def _verify_constraints(
    cycle: tuple[Hashable, ...],
    required_edges: tuple[Edge, ...],
    forbidden_edges: tuple[Edge, ...],
) -> bool:
    selected = _cycle_edges(cycle)
    return all(frozenset(edge) in selected for edge in required_edges) and all(
        frozenset(edge) not in selected for edge in forbidden_edges
    )


class ConstrainedHamiltonianSatSession:
    """Incremental exact solver retaining globally valid subtour constraints."""

    _SOLVERS = {
        "glucose3": ("g3", "Glucose3"),
        "minisat22": ("m22", "MiniSat22"),
    }

    def __init__(self, graph: NetworkXGraph, *, solver: str = "glucose3") -> None:
        self.graph = _require_simple_undirected_graph(graph)
        if solver not in self._SOLVERS:
            raise ValueError(f"unsupported SAT solver: {solver}")
        solver_key, self.solver_name = self._SOLVERS[solver]
        CardEnc, EncType, Solver = _load_pysat()

        self.nodes = tuple(self.graph.nodes())
        self.rank = {vertex: index for index, vertex in enumerate(self.nodes)}
        self.edges = tuple(
            sorted(
                {
                    _edge_key((left, right), self.rank)
                    for left, right in self.graph.edges()
                },
                key=lambda edge: (self.rank[edge[0]], self.rank[edge[1]]),
            )
        )
        self.edge_variables = {
            edge: variable for variable, edge in enumerate(self.edges, start=1)
        }
        self.number_of_edge_variables = len(self.edges)
        self.number_of_variables = self.number_of_edge_variables
        self.clauses: list[list[int]] = []
        self.seen_subtour_cuts: set[frozenset[int]] = set()
        self.cumulative_subtour_constraints = 0
        self._closed = False

        incident: dict[Hashable, list[int]] = {vertex: [] for vertex in self.nodes}
        for edge, variable in self.edge_variables.items():
            left, right = edge
            incident[left].append(variable)
            incident[right].append(variable)

        if len(self.nodes) < 3 or (
            self.nodes and not nx.is_connected(self.graph)
        ):
            self.clauses.append([])
        for vertex in self.nodes:
            if len(incident[vertex]) < 2:
                self.clauses.append([])
                continue
            encoding = CardEnc.equals(
                lits=incident[vertex],
                bound=2,
                top_id=self.number_of_variables,
                encoding=EncType.seqcounter,
            )
            self.clauses.extend(map(list, encoding.clauses))
            self.number_of_variables = max(self.number_of_variables, encoding.nv)

        self._solver = Solver(name=solver_key, bootstrap_with=self.clauses)

    def _constraints(
        self,
        required_edges: Iterable[Edge],
        forbidden_edges: Iterable[Edge],
    ) -> tuple[tuple[Edge, ...], tuple[Edge, ...], list[int]]:
        required = _normalize_constraints(
            self.graph,
            required_edges,
            name="required",
            rank=self.rank,
        )
        forbidden = _normalize_constraints(
            self.graph,
            forbidden_edges,
            name="forbidden",
            rank=self.rank,
        )
        overlap = set(required) & set(forbidden)
        if overlap:
            raise ValueError(
                f"edges cannot be both required and forbidden: {tuple(overlap)!r}"
            )
        assumptions = [self.edge_variables[edge] for edge in required]
        assumptions.extend(-self.edge_variables[edge] for edge in forbidden)
        return required, forbidden, assumptions

    def _selected_edges(self, model: list[int]) -> tuple[Edge, ...]:
        selected_variables = {
            literal
            for literal in model
            if 0 < literal <= self.number_of_edge_variables
        }
        return tuple(
            edge
            for edge, variable in self.edge_variables.items()
            if variable in selected_variables
        )

    def _components(self, selected_edges: tuple[Edge, ...]) -> list[set[Hashable]]:
        selected = nx.Graph()
        selected.add_nodes_from(self.nodes)
        selected.add_edges_from(selected_edges)
        if any(degree != 2 for _, degree in selected.degree()):
            raise RuntimeError("SAT model violates an encoded degree constraint")
        return [set(component) for component in nx.connected_components(selected)]

    def _add_component_cut(self, component: set[Hashable]) -> bool:
        CardEnc, EncType, _ = _load_pysat()
        cut_variables = [
            variable
            for edge, variable in self.edge_variables.items()
            if (edge[0] in component) != (edge[1] in component)
        ]
        cut_key = frozenset(cut_variables)
        if cut_key in self.seen_subtour_cuts:
            return False
        self.seen_subtour_cuts.add(cut_key)
        if len(cut_variables) < 2:
            cut_clauses = [[]]
        else:
            encoding = CardEnc.atleast(
                lits=cut_variables,
                bound=2,
                top_id=self.number_of_variables,
                encoding=EncType.seqcounter,
            )
            cut_clauses = list(map(list, encoding.clauses))
            self.number_of_variables = max(self.number_of_variables, encoding.nv)
        for clause in cut_clauses:
            self._solver.add_clause(clause)
        self.clauses.extend(cut_clauses)
        self.cumulative_subtour_constraints += 1
        return True

    def _cycle_from_edges(self, selected_edges: tuple[Edge, ...]) -> tuple[Hashable, ...]:
        adjacency: dict[Hashable, set[Hashable]] = {
            vertex: set() for vertex in self.nodes
        }
        for left, right in selected_edges:
            adjacency[left].add(right)
            adjacency[right].add(left)
        start = self.nodes[0]
        first = min(adjacency[start], key=self.rank.__getitem__)
        cycle: list[Hashable] = [start, first]
        previous, current = start, first
        while current != start:
            following = adjacency[current] - {previous}
            if len(following) != 1:
                raise RuntimeError("selected SAT edges do not form one cycle")
            next_vertex = next(iter(following))
            cycle.append(next_vertex)
            previous, current = current, next_vertex
            if len(cycle) > len(self.nodes) + 1:
                raise RuntimeError("selected SAT cycle did not close")
        return tuple(cycle)

    def solve(
        self,
        *,
        required_edges: Iterable[Edge] = (),
        forbidden_edges: Iterable[Edge] = (),
    ) -> ConstrainedHamiltonianSatResult:
        """Solve one assumption query while retaining only global cut clauses."""
        if self._closed:
            raise RuntimeError("SAT session is closed")
        required, forbidden, assumptions = self._constraints(
            required_edges, forbidden_edges
        )
        started = perf_counter()
        iterations = 0
        added_constraints = 0
        cycle: tuple[Hashable, ...] | None = None

        while self._solver.solve(assumptions=assumptions):
            model = self._solver.get_model()
            if model is None:
                raise RuntimeError("SAT solver returned no model after SAT")
            selected_edges = self._selected_edges(model)
            components = self._components(selected_edges)
            if len(components) == 1:
                cycle = self._cycle_from_edges(selected_edges)
                if not verify_hamiltonian_cycle(self.graph, cycle):
                    raise RuntimeError("SAT solver produced an invalid certificate")
                if not _verify_constraints(cycle, required, forbidden):
                    raise RuntimeError("SAT certificate violates edge constraints")
                break
            newly_added = sum(
                self._add_component_cut(component) for component in components
            )
            if newly_added == 0:
                raise RuntimeError("SAT refinement produced no new subtour cut")
            iterations += 1
            added_constraints += newly_added

        return ConstrainedHamiltonianSatResult(
            satisfiable=cycle is not None,
            cycle=cycle,
            solver_name=self.solver_name,
            required_edges=required,
            forbidden_edges=forbidden,
            number_of_edge_variables=self.number_of_edge_variables,
            number_of_variables=self.number_of_variables,
            number_of_clauses=len(self.clauses),
            subtour_iterations=iterations,
            subtour_constraints=added_constraints,
            cumulative_subtour_constraints=self.cumulative_subtour_constraints,
            runtime_seconds=perf_counter() - started,
        )

    def export_dimacs(
        self,
        path: Path,
        *,
        required_edges: Iterable[Edge] = (),
        forbidden_edges: Iterable[Edge] = (),
    ) -> None:
        """Write the current global CNF plus exact query unit clauses."""
        _, _, assumptions = self._constraints(required_edges, forbidden_edges)
        query_clauses = self.clauses + [[literal] for literal in assumptions]
        with path.open("w", encoding="ascii", newline="\n") as output:
            output.write(
                f"p cnf {self.number_of_variables} {len(query_clauses)}\n"
            )
            for clause in query_clauses:
                output.write(" ".join(map(str, clause)) + " 0\n")

    def close(self) -> None:
        if not self._closed:
            self._solver.delete()
            self._closed = True

    def __enter__(self) -> "ConstrainedHamiltonianSatSession":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def solve_constrained_hamiltonian_cycle_sat(
    graph: NetworkXGraph,
    required_edges: Iterable[Edge] = (),
    forbidden_edges: Iterable[Edge] = (),
) -> ConstrainedHamiltonianSatResult:
    """Solve one exact edge-constrained Hamiltonian-cycle query."""
    with ConstrainedHamiltonianSatSession(graph) as session:
        return session.solve(
            required_edges=required_edges,
            forbidden_edges=forbidden_edges,
        )
