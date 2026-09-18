"""Construct upper certificates for three-edge splices; no optimality claim.

All graphs have integer vertex labels. A cycle is a frozenset of sorted edges.
This module does not use any established project solver or verifier.
"""
from itertools import product


def edge(u, v):
    return tuple(sorted((u, v)))


def prism(length):
    if length < 3:
        raise ValueError("prism length must be at least three")
    return tuple(sorted(
        {edge(r * length + j, r * length + (j + 1) % length)
         for r in (0, 1) for j in range(length)}
        | {edge(j, length + j) for j in range(length)}
    ))


def cycles_by_paths(edges):
    """Enumerate undirected Hamilton cycles by anchored path search."""
    adjacency = {}
    for u, v in edges:
        adjacency.setdefault(u, set()).add(v)
        adjacency.setdefault(v, set()).add(u)
    start = min(adjacency)
    result = set()

    def extend(path, seen):
        last = path[-1]
        if len(seen) == len(adjacency):
            if start in adjacency[last] and path[1] < last:
                result.add(frozenset(edge(a, b) for a, b in zip(path, path[1:] + [start])))
            return
        for v in sorted(adjacency[last] - seen):
            extend(path + [v], seen | {v})

    extend([start], {start})
    return tuple(sorted(result, key=lambda c: tuple(sorted(c))))


def separating(edges, family):
    signatures = {e: {i for i, cycle in enumerate(family) if e in cycle} for e in edges}
    return all(signatures[e] - signatures[f] for e in edges for f in edges if e != f)


def state_cover(family, internal_edges):
    """Deterministic greedy edge cover inside one state; only an upper bound."""
    missing = set(internal_edges)
    chosen = []
    while missing:
        index = min(range(len(family)), key=lambda j: (-len(missing & family[j]), j))
        covered = missing & family[index]
        if not covered:
            raise ValueError("state family does not cover all internal edges")
        chosen.append(index)
        missing -= covered
    return tuple(chosen)


def compose(left, right, left_vertex, right_vertex, right_ports=None, supplied_families=None):
    left = tuple(sorted(left))
    right = tuple(sorted(right))
    universes = [cycles_by_paths(left), cycles_by_paths(right)]
    families = universes if supplied_families is None else [tuple(f) for f in supplied_families]
    for family, universe in zip(families, universes):
        if len(family) != len(set(family)) or not set(family) <= set(universe):
            raise ValueError("input family contains a duplicate or non-Hamiltonian cycle")
    for graph, family in zip((left, right), families):
        if not separating(graph, family):
            raise ValueError("input graph has no Hamiltonian separating family")
    vertices = [sorted({v for e in graph for v in e}) for graph in (left, right)]
    roots = (left_vertex, right_vertex)
    ports = [sorted(next(v for v in e if v != root) for e in graph if root in e)
             for graph, root in zip((left, right), roots)]
    if any(len(p) != 3 for p in ports):
        raise ValueError("splice vertices must have degree three")
    if right_ports is not None:
        if sorted(right_ports) != ports[1]:
            raise ValueError("right_ports is not a permutation of the neighbours")
        ports[1] = list(right_ports)
    remaining = [[v for v in vs if v != root] for vs, root in zip(vertices, roots)]
    maps = [{v: i for i, v in enumerate(remaining[0])},
            {v: len(remaining[0]) + i for i, v in enumerate(remaining[1])}]
    cut = tuple(edge(maps[0][ports[0][i]], maps[1][ports[1][i]]) for i in range(3))
    internal = [set(e for e in graph if root not in e)
                for graph, root in zip((left, right), roots)]
    output_edges = tuple(sorted(set(cut) | {
        edge(maps[s][u], maps[s][v]) for s in (0, 1) for u, v in internal[s]
    }))
    states = [[tuple(c for c in families[s] if edge(roots[s], ports[s][i]) not in c)
               for i in range(3)] for s in (0, 1)]
    covers = [[state_cover(states[s][i], internal[s]) for i in range(3)] for s in (0, 1)]
    product_family, reduced_family = [], []
    pair_records, reduced_records = [], []
    for i in range(3):
        for a, b in product(range(len(states[0][i])), range(len(states[1][i]))):
            joined = frozenset({cut[j] for j in range(3) if j != i} | {
                edge(maps[s][u], maps[s][v]) for s, c in ((0, states[0][i][a]), (1, states[1][i][b]))
                for u, v in c if roots[s] not in (u, v)
            })
            product_family.append(joined)
            pair_records.append([i, a, b])
            if a in covers[0][i] or b in covers[1][i]:
                reduced_family.append(joined)
                reduced_records.append([i, a, b])
    encode = lambda family: [sorted(c) for c in family]
    return {
        "schema": "hsep-three-edge-splice-upper-certificate-v1",
        "left_edges": left, "right_edges": right, "vertices_removed": roots,
        "input_universes_complete": [set(f) == set(u) for f, u in zip(families, universes)],
        "ports": ports, "left_family": encode(families[0]), "right_family": encode(families[1]),
        "state_sizes": [[len(c) for c in side] for side in states],
        "state_cover_indices": covers, "output_edges": output_edges, "cut_edges": cut,
        "product_cycles": encode(product_family), "reduced_cycles": encode(reduced_family),
        "product_pairs": pair_records, "reduced_pairs": reduced_records,
        "claim": "upper bounds only; neither output family is claimed optimal",
    }
