"""NetworkX-based reference validation for Barnette graphs."""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .graph_io import GraphInput, NetworkXGraph, load_graph

UNDIRECTED_REASON = "graph is directed; Barnette graphs must be undirected"
SELF_LOOP_REASON = "graph contains a self-loop; Barnette graphs must be simple"
PARALLEL_EDGE_REASON = (
    "graph contains parallel edges; Barnette graphs must be simple"
)
CUBIC_REASON = "graph is not cubic; every vertex must have degree 3"
BIPARTITE_REASON = "graph is not bipartite"
PLANAR_REASON = "graph is not planar"
THREE_CONNECTED_REASON = "graph is not 3-vertex-connected"


@dataclass(slots=True)
class ValidationResult:
    """The outcome and diagnostics from validating one graph."""

    valid: bool
    number_of_vertices: int
    number_of_edges: int
    rejection_reasons: list[str]


def _has_parallel_edges(graph: NetworkXGraph) -> bool:
    """Return whether a NetworkX multigraph has repeated endpoint pairs."""
    if not graph.is_multigraph():
        return False

    if graph.is_directed():
        pairs = ((u, v) for u, v in graph.edges())
    else:
        pairs = (frozenset((u, v)) for u, v in graph.edges())

    seen: set[object] = set()
    for pair in pairs:
        if pair in seen:
            return True
        seen.add(pair)
    return False


def _is_three_vertex_connected(graph: NetworkXGraph) -> bool:
    """Check 3-connectivity on the original undirected graph object.

    Directed inputs fail this undirected property explicitly. NetworkX accepts
    both ``Graph`` and ``MultiGraph`` objects for the remaining operations, so
    no simple-graph projection is needed.
    """
    if graph.is_directed() or graph.number_of_nodes() < 4:
        return False
    if not nx.is_connected(graph):
        return False
    return nx.node_connectivity(graph) >= 3


def validate_barnette_graph(source: GraphInput) -> ValidationResult:
    """Validate every defining property of a Barnette graph.

    All applicable checks run, even after earlier failures. The vertex and edge
    counts describe the loaded input graph; multiedges and self-loops are
    included in NetworkX's edge count.

    Predicates are evaluated on the original NetworkX object, not on a cleaned
    replacement. Cubicity uses NetworkX degree, so loops contribute twice and
    parallel edges contribute with multiplicity; directed inputs use total
    in-degree plus out-degree. NetworkX bipartiteness ignores edge direction and
    multiplicity but rejects a loop. Its planarity test explicitly tests the
    underlying loop-free simple skeleton, because direction, loops, and parallel
    copies do not change topological planarity. Three-vertex-connectivity is
    evaluated directly for undirected ``Graph`` and ``MultiGraph`` inputs;
    directed inputs fail that undirected property without being projected.
    """
    graph = load_graph(source)
    reasons: list[str] = []

    if graph.is_directed():
        reasons.append(UNDIRECTED_REASON)
    if nx.number_of_selfloops(graph) > 0:
        reasons.append(SELF_LOOP_REASON)
    if _has_parallel_edges(graph):
        reasons.append(PARALLEL_EDGE_REASON)

    if any(degree != 3 for _, degree in graph.degree()):
        reasons.append(CUBIC_REASON)

    if not nx.is_bipartite(graph):
        reasons.append(BIPARTITE_REASON)
    if not nx.check_planarity(graph)[0]:
        reasons.append(PLANAR_REASON)

    if not _is_three_vertex_connected(graph):
        reasons.append(THREE_CONNECTED_REASON)

    return ValidationResult(
        valid=not reasons,
        number_of_vertices=graph.number_of_nodes(),
        number_of_edges=graph.number_of_edges(),
        rejection_reasons=reasons,
    )
