"""Independent exact backtracking for edge-constrained Hamiltonian cycles."""

from __future__ import annotations

from collections.abc import Hashable, Iterable

import networkx as nx

from .graph_io import NetworkXGraph
from .hamiltonian import verify_hamiltonian_cycle
from .validation import _has_parallel_edges


Edge = tuple[Hashable, Hashable]


def _require_graph(graph: object) -> NetworkXGraph:
    if not isinstance(
        graph, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)
    ):
        raise TypeError("graph must be a NetworkX graph object")
    defects: list[str] = []
    if graph.is_directed():
        defects.append("directed")
    if nx.number_of_selfloops(graph):
        defects.append("contains self-loops")
    if _has_parallel_edges(graph):
        defects.append("contains parallel edges")
    if defects:
        raise ValueError(
            "constrained backtracking requires an undirected simple graph; "
            f"input is {', '.join(defects)}"
        )
    return graph


def _normalize(
    graph: NetworkXGraph,
    raw_edges: Iterable[Edge],
    rank: dict[Hashable, int],
    name: str,
) -> tuple[Edge, ...]:
    result: set[Edge] = set()
    for raw_edge in raw_edges:
        try:
            left, right = raw_edge
        except (TypeError, ValueError) as error:
            raise ValueError(f"every {name} edge must contain two endpoints") from error
        if left not in rank or right not in rank:
            raise ValueError(f"{name} edge {raw_edge!r} contains an unknown vertex")
        if not graph.has_edge(left, right):
            raise ValueError(f"{name} edge {raw_edge!r} is not in the graph")
        result.add((left, right) if rank[left] < rank[right] else (right, left))
    return tuple(sorted(result, key=lambda edge: (rank[edge[0]], rank[edge[1]])))


def _edge_set(cycle: tuple[Hashable, ...]) -> set[frozenset[Hashable]]:
    return {
        frozenset((left, right)) for left, right in zip(cycle, cycle[1:])
    }


def find_constrained_hamiltonian_cycle(
    graph: NetworkXGraph,
    required_edges: Iterable[Edge] = (),
    forbidden_edges: Iterable[Edge] = (),
) -> tuple[Hashable, ...] | None:
    """Return an exact constrained cycle using independent depth-first search.

    The search fixes the first node and one reversal orientation. Pruning uses
    only necessary conditions: remaining degree availability, connectivity of
    unvisited vertices, endpoint continuation, and the impossibility of adding
    a missing required edge after one endpoint has become internal to the path.
    """
    checked = _require_graph(graph)
    nodes = tuple(checked.nodes())
    rank = {vertex: index for index, vertex in enumerate(nodes)}
    required = _normalize(checked, required_edges, rank, "required")
    forbidden = _normalize(checked, forbidden_edges, rank, "forbidden")
    overlap = set(required) & set(forbidden)
    if overlap:
        raise ValueError(
            f"edges cannot be both required and forbidden: {tuple(overlap)!r}"
        )
    if len(nodes) < 3:
        return None

    required_keys = {frozenset(edge) for edge in required}
    forbidden_keys = {frozenset(edge) for edge in forbidden}
    required_degree = {vertex: 0 for vertex in nodes}
    for left, right in required:
        required_degree[left] += 1
        required_degree[right] += 1
    if any(degree > 2 for degree in required_degree.values()):
        return None

    adjacency = {
        vertex: frozenset(
            neighbor
            for neighbor in checked.neighbors(vertex)
            if frozenset((vertex, neighbor)) not in forbidden_keys
        )
        for vertex in nodes
    }
    if any(len(adjacency[vertex]) < 2 for vertex in nodes):
        return None
    available_graph = nx.Graph()
    available_graph.add_nodes_from(nodes)
    available_graph.add_edges_from(
        (vertex, neighbor)
        for vertex in nodes
        for neighbor in adjacency[vertex]
        if rank[vertex] < rank[neighbor]
    )
    if not nx.is_connected(available_graph) or not nx.is_biconnected(available_graph):
        return None

    start = nodes[0]
    path = [start]
    visited = {start}
    selected: set[frozenset[Hashable]] = set()
    failed: set[
        tuple[
            Hashable,
            frozenset[Hashable],
            Hashable | None,
            frozenset[frozenset[Hashable]],
        ]
    ] = set()

    def connected(vertices: set[Hashable]) -> bool:
        if not vertices:
            return True
        reached = {next(iter(vertices))}
        pending = list(reached)
        while pending:
            vertex = pending.pop()
            for neighbor in adjacency[vertex] & vertices:
                if neighbor not in reached:
                    reached.add(neighbor)
                    pending.append(neighbor)
        return reached == vertices

    def feasible(current: Hashable) -> bool:
        internal = visited - {start, current}
        for edge in required_keys - selected:
            left, right = tuple(edge)
            if left in internal or right in internal:
                return False
            if left in visited and right in visited and {left, right} != {start, current}:
                return False

        for vertex in nodes:
            selected_incident = {
                edge for edge in selected if vertex in edge
            }
            potential = set(selected_incident)
            for neighbor in adjacency[vertex]:
                if neighbor not in internal:
                    potential.add(frozenset((vertex, neighbor)))
            if len(potential) < 2:
                return False

        unvisited = set(nodes) - visited
        if unvisited:
            if not (adjacency[current] & unvisited):
                return False
            if not (adjacency[start] & unvisited):
                return False
            if not connected(unvisited):
                return False
        return True

    def search(current: Hashable) -> tuple[Hashable, ...] | None:
        first = path[1] if len(path) > 1 else None
        state = (
            current,
            frozenset(visited),
            first,
            frozenset(required_keys & selected),
        )
        if state in failed:
            return None

        if len(path) == len(nodes):
            closing = frozenset((current, start))
            if start not in adjacency[current]:
                failed.add(state)
                return None
            if first is not None and rank[first] >= rank[current]:
                failed.add(state)
                return None
            completed_edges = selected | {closing}
            if not required_keys <= completed_edges:
                failed.add(state)
                return None
            cycle = tuple(path + [start])
            if not verify_hamiltonian_cycle(checked, cycle):
                raise RuntimeError("backtracking produced an invalid certificate")
            if not required_keys <= _edge_set(cycle) or forbidden_keys & _edge_set(cycle):
                raise RuntimeError("backtracking certificate violates constraints")
            return cycle

        if not feasible(current):
            failed.add(state)
            return None
        candidates = adjacency[current] - visited
        ordered = sorted(
            candidates,
            key=lambda neighbor: (
                frozenset((current, neighbor)) not in required_keys,
                rank[neighbor],
            ),
        )
        for neighbor in ordered:
            edge = frozenset((current, neighbor))
            path.append(neighbor)
            visited.add(neighbor)
            selected.add(edge)
            answer = search(neighbor)
            if answer is not None:
                return answer
            selected.remove(edge)
            visited.remove(neighbor)
            path.pop()
        failed.add(state)
        return None

    return search(start)
