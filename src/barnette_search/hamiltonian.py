"""Exact reference routines for Hamiltonian cycles.

The finder uses depth-first backtracking from the first node in NetworkX
insertion order. Fixing that node removes rotational symmetry. Of the two
orientations of a cycle, only the one whose second node has lower insertion
rank than its penultimate node is retained, removing reversal symmetry without
comparing potentially heterogeneous node labels.

The pruning rules below are necessary conditions for a completion and therefore
preserve completeness:

* A Hamiltonian graph with at least three vertices is connected, has minimum
  degree at least two, and is biconnected.
* After fixing a partial path, its endpoint needs an unvisited successor and the
  start needs an unvisited closing neighbor.
* Every unvisited vertex still needs two available cycle neighbors.
* The subgraph induced by the unvisited vertices must be connected, because
  those vertices would form one consecutive segment of any completion.
* Failed states are cached by endpoint, visited set, and first path vertex. The
  future suffix depends only on those values; the order of unavailable internal
  path vertices cannot change whether a completion exists.

This is an exponential-time reference algorithm intended for small graphs.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable

import networkx as nx

from .graph_io import NetworkXGraph
from .validation import _has_parallel_edges


def _require_simple_undirected_graph(graph: object) -> NetworkXGraph:
    """Return *graph* after enforcing the solver's input domain."""
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
            "Hamiltonian-cycle routines require an undirected simple graph; "
            f"input is {details}"
        )
    return graph


def _is_connected_subset(
    vertices: set[Hashable], adjacency: dict[Hashable, frozenset[Hashable]]
) -> bool:
    """Check connectivity of an induced vertex subset without graph conversion."""
    if not vertices:
        return True

    start = next(iter(vertices))
    reached = {start}
    pending = [start]
    while pending:
        vertex = pending.pop()
        for neighbor in adjacency[vertex] & vertices:
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    return reached == vertices


def find_hamiltonian_cycle(
    graph: NetworkXGraph,
) -> tuple[Hashable, ...] | None:
    """Return one exact Hamiltonian cycle, or ``None`` when none exists.

    Inputs must be materialized, undirected, structurally simple NetworkX
    graphs. A ``MultiGraph`` container is accepted when it has no actual loops
    or repeated endpoint pair. Invalid graph domains raise ``ValueError`` (or
    ``TypeError`` for non-NetworkX objects).
    """
    checked_graph = _require_simple_undirected_graph(graph)
    nodes = tuple(checked_graph.nodes())
    number_of_nodes = len(nodes)

    # Simple undirected cycles have at least three distinct vertices.
    if number_of_nodes < 3:
        return None
    if not nx.is_connected(checked_graph):
        return None
    if any(degree < 2 for _, degree in checked_graph.degree()):
        return None
    if not nx.is_biconnected(checked_graph):
        return None

    rank = {vertex: index for index, vertex in enumerate(nodes)}
    adjacency = {
        vertex: frozenset(checked_graph.neighbors(vertex)) for vertex in nodes
    }
    all_nodes = set(nodes)
    start = nodes[0]
    path: list[Hashable] = [start]
    visited: set[Hashable] = {start}
    failed_states: set[tuple[Hashable, frozenset[Hashable], Hashable]] = set()

    def residual_is_feasible(current: Hashable) -> bool:
        """Apply necessary conditions to the unfinished path."""
        remaining = all_nodes - visited
        first = path[1]

        if not remaining:
            return start in adjacency[current] and rank[first] < rank[current]

        if not adjacency[current] & remaining:
            return False

        # The eventual closing vertex must also select the canonical orientation.
        if not any(
            rank[first] < rank[vertex]
            for vertex in adjacency[start] & remaining
        ):
            return False

        available = remaining | {start, current}
        if any(
            len(adjacency[vertex] & available) < 2 for vertex in remaining
        ):
            return False

        return _is_connected_subset(remaining, adjacency)

    def search(current: Hashable) -> tuple[Hashable, ...] | None:
        if len(path) == number_of_nodes:
            if start in adjacency[current] and rank[path[1]] < rank[current]:
                return tuple(path) + (start,)
            return None

        first = path[1] if len(path) > 1 else start
        state = (current, frozenset(visited), first)
        if state in failed_states:
            return None

        candidates = adjacency[current] - visited
        ordered_candidates = sorted(
            candidates,
            key=lambda vertex: (len(adjacency[vertex] - visited), rank[vertex]),
        )
        for candidate in ordered_candidates:
            visited.add(candidate)
            path.append(candidate)
            if residual_is_feasible(candidate):
                cycle = search(candidate)
                if cycle is not None:
                    return cycle
            path.pop()
            visited.remove(candidate)

        failed_states.add(state)
        return None

    return search(start)


def verify_hamiltonian_cycle(
    graph: NetworkXGraph, cycle: Iterable[Hashable] | None
) -> bool:
    """Independently verify a Hamiltonian-cycle certificate.

    Invalid graph domains raise the same exceptions as the finder. Malformed or
    absent certificates return ``False``.
    """
    checked_graph = _require_simple_undirected_graph(graph)
    if cycle is None or checked_graph.number_of_nodes() < 3:
        return False

    try:
        certificate = tuple(cycle)
    except TypeError:
        return False

    number_of_nodes = checked_graph.number_of_nodes()
    if len(certificate) != number_of_nodes + 1:
        return False
    if not (
        certificate[0] is certificate[-1]
        or certificate[0] == certificate[-1]
    ):
        return False

    graph_nodes = set(checked_graph.nodes())
    try:
        if any(vertex not in graph_nodes for vertex in certificate):
            return False
        body = certificate[:-1]
        if len(set(body)) != number_of_nodes or set(body) != graph_nodes:
            return False
    except TypeError:
        return False

    return all(
        checked_graph.has_edge(left, right)
        for left, right in zip(certificate, certificate[1:])
    )
