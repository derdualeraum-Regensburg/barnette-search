"""Independent standard-library verification of a splice certificate JSON.

Usage: python verify.py certificate.json
No imports from the constructor, NetworkX, SAT solvers, or the project package.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path


def require(value, message):
    if not value:
        raise ValueError(message)


def adjacency(edges):
    result = {}
    for u, v in edges:
        require(u < v, "edges must be distinct, sorted endpoints")
        result.setdefault(u, set()).add(v)
        result.setdefault(v, set()).add(u)
    require(all(len(row) == 3 for row in result.values()), "graph is not cubic")
    return result


def is_hamiltonian(edges, vertices):
    neighbours = {v: set() for v in vertices}
    for a, b in edges:
        if a not in neighbours or b not in neighbours:
            return False
        neighbours[a].add(b)
        neighbours[b].add(a)
    if any(len(row) != 2 for row in neighbours.values()):
        return False
    visited = {min(vertices)}
    pending = list(visited)
    while pending:
        for v in neighbours[pending.pop()] - visited:
            visited.add(v)
            pending.append(v)
    return visited == set(vertices)


def cycles_by_matchings(edges):
    """Independent exhaustive enumeration via complements of perfect matchings."""
    neighbours = adjacency(edges)
    result = set()

    def visit(unmatched, matching):
        if not unmatched:
            complement = edges - matching
            if is_hamiltonian(complement, neighbours):
                result.add(frozenset(complement))
            return
        v = min(unmatched)
        for u in sorted(neighbours[v] & unmatched):
            visit(unmatched - {u, v}, matching | {tuple(sorted((u, v)))})

    visit(set(neighbours), set())
    return result


def family_check(edges, cycles):
    require(len(cycles) == len(set(cycles)), "duplicate cycle")
    vertices = set(adjacency(edges))
    for cycle in cycles:
        require(cycle <= edges and is_hamiltonian(cycle, vertices), "invalid Hamiltonian cycle")
    # Explicit ordered-pair checking, without the producer's signature method.
    for e in edges:
        for f in edges - {e}:
            require(any(e in c and f not in c for c in cycles), "unseparated ordered edge pair")


def check(record):
    decode = lambda values: tuple(frozenset(tuple(e) for e in cycle) for cycle in values)
    graphs = [frozenset(tuple(e) for e in record[key]) for key in ("left_edges", "right_edges")]
    families = [decode(record[key]) for key in ("left_family", "right_family")]
    roots, ports = record["vertices_removed"], record["ports"]
    complete = []
    for graph, family in zip(graphs, families):
        family_check(graph, family)
        universe = cycles_by_matchings(graph)
        require(set(family) <= universe, "input family contains invalid cycle")
        complete.append(set(family) == universe)
    require(complete == record["input_universes_complete"], "input completeness metadata mismatch")
    remain = [sorted(set(adjacency(g)) - {r}) for g, r in zip(graphs, roots)]
    maps = [{v: i for i, v in enumerate(remain[0])},
            {v: len(remain[0]) + i for i, v in enumerate(remain[1])}]
    for s in (0, 1):
        require(len(ports[s]) == 3 and set(ports[s]) == adjacency(graphs[s])[roots[s]], "invalid ports")
    cut = {tuple(sorted((maps[0][ports[0][i]], maps[1][ports[1][i]]))) for i in range(3)}
    expected_edges = cut | {tuple(sorted((maps[s][u], maps[s][v])))
        for s in (0, 1) for u, v in graphs[s] if roots[s] not in (u, v)}
    edges = frozenset(tuple(e) for e in record["output_edges"])
    require(edges == expected_edges, "splice graph mismatch")
    require(cut == set(tuple(e) for e in record["cut_edges"]), "cut mismatch")
    states = [[tuple(c for c in families[s] if tuple(sorted((roots[s], ports[s][i]))) not in c)
               for i in range(3)] for s in (0, 1)]
    sizes = [[len(c) for c in side] for side in states]
    require(sizes == record["state_sizes"], "state-size mismatch")
    for s in (0, 1):
        interior = {e for e in graphs[s] if roots[s] not in e}
        for i in range(3):
            indexes = record["state_cover_indices"][s][i]
            require(len(indexes) == len(set(indexes)) and all(0 <= j < sizes[s][i] for j in indexes), "bad cover index")
            union = set().union(*(states[s][i][j] for j in indexes))
            require(interior <= union, "state subfamily does not cover internal edges")
            require(2 <= len(indexes) <= min(sizes[s][i], (len(remain[s]) + 1) // 2), "cover-size bound violated")
    product_cycles = decode(record["product_cycles"])
    reduced_cycles = decode(record["reduced_cycles"])
    family_check(edges, product_cycles)
    family_check(edges, reduced_cycles)
    require(set(reduced_cycles) <= set(product_cycles), "reduced family not a subset")
    independent_universe = cycles_by_matchings(edges)
    require(set(product_cycles) <= independent_universe, "product contains invalid cycle")
    if all(complete):
        require(set(product_cycles) == independent_universe, "product does not equal independent cycle universe")
    for key, family in (("product_pairs", product_cycles), ("reduced_pairs", reduced_cycles)):
        require(len(record[key]) == len(family), "pair-record count mismatch")
        seen_pairs = set()
        for indexes, cycle in zip(record[key], family):
            i, a, b = indexes
            require(0 <= i < 3 and 0 <= a < sizes[0][i] and 0 <= b < sizes[1][i], "invalid state pair")
            require(tuple(indexes) not in seen_pairs, "duplicate state pair")
            seen_pairs.add(tuple(indexes))
            if key == "reduced_pairs":
                require(a in record["state_cover_indices"][0][i] or b in record["state_cover_indices"][1][i], "pair outside reduced construction")
            lifted = {tuple(sorted((maps[s][u], maps[s][v]))) for s, c in ((0, states[0][i][a]), (1, states[1][i][b])) for u, v in c if roots[s] not in (u, v)}
            lifted |= {tuple(sorted((maps[0][ports[0][j]], maps[1][ports[1][j]]))) for j in range(3) if j != i}
            require(cycle == lifted, "cycle does not lift recorded state pair")
    raw = sum(sizes[0][i] * sizes[1][i] for i in range(3))
    small = 0
    for i in range(3):
        p, q = (len(record["state_cover_indices"][s][i]) for s in (0, 1))
        small += p * sizes[1][i] + sizes[0][i] * q - p * q
    require(len(product_cycles) == raw and len(reduced_cycles) == small, "cardinality formula mismatch")
    require(raw <= (len(families[0]) - 4) * (len(families[1]) - 4) + 8, "profile-free bound violated")
    return {"verified": True, "order": len(remain[0]) + len(remain[1]),
            "input_family_sizes": list(map(len, families)), "state_sizes": sizes,
            "product_upper_bound": raw, "reduced_upper_bound": small,
            "complete_output_cycle_count": len(independent_universe),
            "ordered_requirements_verified": len(edges) * (len(edges) - 1),
            "exact_hsep_claimed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("certificate", type=Path)
    args = parser.parse_args()
    payload = args.certificate.read_bytes()
    result = check(json.loads(payload))
    result["certificate_sha256"] = sha256(payload).hexdigest()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
