"""Independent exact verifier for the 16-vertex diagnosis (standard library only).

Enumerates Hamiltonian cycles by vertex-path DFS; checks upper, lower, block
obstruction, graph6 identity and an explicit D(3,3) isomorphism certificate.
"""
import argparse
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from time import perf_counter


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(raw):
    edges = frozenset(tuple(e) for e in raw)
    require(len(edges) == len(raw) and all(len(e) == 2 and e[0] < e[1] for e in edges),
            'invalid edges')
    return edges


def neighbours(edges):
    result = {}
    for u, v in edges:
        result.setdefault(u, set()).add(v)
        result.setdefault(v, set()).add(u)
    return result


def complete_cycles(graph):
    adjacency = neighbours(graph)
    start = min(adjacency)
    found = set()

    def extend(path, used):
        last = path[-1]
        if len(used) == len(adjacency):
            if start in adjacency[last] and path[1] < last:
                found.add(frozenset(tuple(sorted(pair)) for pair in zip(path, path[1:] + [start])))
            return
        for v in sorted(adjacency[last] - used):
            extend(path + [v], used | {v})

    extend([start], {start})
    return found


def coverage(graph, cycles):
    return {(e, f) for e in graph for f in graph if e != f
            and any(e in c and f not in c for c in cycles)}


def boundary_state(forest, ports):
    adjacency = neighbours(forest)
    require(len(adjacency) == 8, 'nonspanning fragment')
    used = tuple(i for i, v in enumerate(ports) if len(adjacency[v]) == 1)
    require(len(used) in (2, 4), 'invalid terminal set')
    require(all(len(row) == (1 if v in {ports[i] for i in used} else 2)
                for v, row in adjacency.items()), 'invalid path-cover degrees')
    unseen = set(adjacency)
    pairs = []
    while unseen:
        root = min(unseen)
        component, pending = {root}, [root]
        while pending:
            for v in adjacency[pending.pop()] - component:
                component.add(v)
                pending.append(v)
        ends = sorted(ports.index(v) for v in component if len(adjacency[v]) == 1)
        require(len(ends) == 2, 'cycle component in fragment')
        pairs.append(tuple(ends))
        unseen -= component
    return used, tuple(sorted(pairs))


def minimum_union_cover(forests):
    target = frozenset().union(*forests)
    # Exhaustive negative certificates for every smaller size are tiny here.
    for size in range(1, len(forests) + 1):
        if any(frozenset().union(*chosen) == target for chosen in combinations(forests, size)):
            return size
    raise ValueError('empty union-cover family')


def check(record):
    graph = decode(record['graph_edges'])
    require(set(neighbours(graph)) == set(range(16)), 'wrong graph order')
    require(all(len(ns) == 3 for ns in neighbours(graph).values()), 'noncubic graph')
    # Decode the small-order graph6 record independently.
    data = [ord(c) - 63 for c in record['graph6_labelled']]
    require(len(data) == 21 and data[0] == 16 and all(0 <= c < 64 for c in data), 'bad graph6 encoding')
    bits = [(c >> j) & 1 for c in data[1:] for j in range(5, -1, -1)]
    positions = [(u, v) for v in range(16) for u in range(v)]
    require({e for e, bit in zip(positions, bits) if bit} == graph, 'graph6 disagrees with edges')
    mapping = record['double_ladder_33_map']
    require(sorted(mapping) == list(range(16)), 'isomorphism map not bijective')
    target = set()
    for offset in (0, 8):
        for v in range(8):
            if v % 2 == 0:
                target.add((offset + v, offset + v + 1))
            if v < 6:
                target.add((offset + v, offset + v + 2))
    target.update(((0, 8), (1, 14), (6, 9), (7, 15)))
    require({tuple(sorted((mapping[u], mapping[v]))) for u, v in graph} == target,
            'isomorphism certificate fails')
    cycles = [decode(c) for c in record['cycles']]
    require(len(cycles) == len(set(cycles)) and set(cycles) == complete_cycles(graph),
            'cycle universe is incomplete or invalid')
    indices = record['selected_indices']
    require(len(indices) == len(set(indices)) and all(0 <= i < len(cycles) for i in indices),
            'bad selection')
    all_requirements = {(e, f) for e in graph for f in graph if e != f}
    require(coverage(graph, [cycles[i] for i in indices]) == all_requirements, 'upper certificate fails')
    private = record['private_requirements']
    require(sorted(row['cycle_index'] for row in private) == sorted(indices), 'lower witness count mismatch')
    seen = set()
    for row in private:
        e, f = map(tuple, row['requirement'])
        require((e, f) in all_requirements and (e, f) not in seen, 'invalid lower requirement')
        seen.add((e, f))
        support = [i for i, c in enumerate(cycles) if e in c and f not in c]
        require(support == [row['cycle_index']], 'lower requirement does not force its cycle')
    omitted = record['omitted_indices']
    require(set(omitted) == set(range(len(cycles))) - set(indices) and len(omitted) == 2,
            'omission metadata fails')
    replacements = record['replacement_covers']
    require(sorted(row['omitted_index'] for row in replacements) == sorted(omitted), 'replacement metadata fails')
    for row in replacements:
        chosen = row['witness_indices']
        require(chosen and len(set(chosen)) == len(chosen) and set(chosen) <= set(indices),
                'invalid replacement witnesses')
        needed = coverage(graph, [cycles[row['omitted_index']]])
        require(needed <= coverage(graph, [cycles[i] for i in chosen]), 'replacement loses requirements')
    prior = record['prior_selected_indices']
    require(len(prior) == len(set(prior)) == 13 and set(prior) <= set(range(len(cycles))),
            'bad prior family')
    require(coverage(graph, [cycles[i] for i in prior]) == all_requirements, 'prior family fails')
    require(set(indices) < set(prior), 'new family not a strict pruning')
    ports = record['ports']
    require(len(ports) == 2 and all(len(p) == len(set(p)) == 4 for p in ports), 'bad ports')
    cut = decode(record['cut_edges'])
    require(cut == {tuple(sorted((ports[0][i], ports[1][i] + 8))) for i in range(4)}, 'cut mismatch')
    require(cut == {e for e in graph if e[0] < 8 <= e[1]}, 'incorrect cut')
    grouped = {}
    for i, cycle in enumerate(cycles):
        first = frozenset(e for e in cycle if e[1] < 8)
        second = frozenset((u - 8, v - 8) for u, v in cycle if u >= 8)
        states = boundary_state(first, ports[0]), boundary_state(second, ports[1])
        grouped.setdefault(states, []).append((i, first, second))
    require(len(record['blocks']) == len(grouped), 'block count mismatch')
    block_seen = set()
    rectangle_minimum = 0
    for block in record['blocks']:
        states = tuple((tuple(s[0]), tuple(tuple(pair) for pair in s[1])) for s in block['states'])
        require(states in grouped and states not in block_seen, 'invalid or repeated block')
        block_seen.add(states)
        rows = grouped[states]
        left = sorted({x[1] for x in rows}, key=lambda f: tuple(sorted(f)))
        right = sorted({x[2] for x in rows}, key=lambda f: tuple(sorted(f)))
        pairs = {(x[1], x[2]): x[0] for x in rows}
        require(len(pairs) == len(left) * len(right), 'not a full compatible product')
        matrix = [[pairs[a, b] for b in right] for a in left]
        require(matrix == block['cycle_index_matrix'], 'cycle matrix disagrees with projections')
        a, b = len(left), len(right)
        p, q = minimum_union_cover(left), minimum_union_cover(right)
        require((a, b, p, q) == (block['a'], block['b'], block['p_min'], block['q_min']),
                'state union-cover optimum mismatch')
        cost = p * b + a * q - p * q
        require(cost == block['rectangle_minimum'], 'rectangle count mismatch')
        require(sum(i in indices for i, _, _ in rows) == block['selected_count'], 'block selection mismatch')
        rectangle_minimum += cost
    claim = record['claim']
    require(len(indices) == len(private) == claim['hsep'] == 12, 'exact claim mismatch')
    require(claim['unique_minimum_family'] is True, 'uniqueness metadata mismatch')
    require(rectangle_minimum == claim['minimum_with_state_union_rectangles'] == 13,
            'rectangle minimum claim mismatch')
    return {'verified': True, 'order': 16, 'hamiltonian_cycles': len(cycles),
            'upper': len(indices), 'lower': len(private), 'exact_hsep': len(indices),
            'unique_minimum_family': True, 'minimum_with_state_union_rectangles': rectangle_minimum,
            'ordered_requirements': len(all_requirements), 'isomorphic_to': 'D(3,3)'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('certificates', nargs='+', type=Path)
    args = parser.parse_args()
    start = perf_counter()
    results = []
    for path in args.certificates:
        raw = path.read_bytes()
        result = check(json.loads(raw))
        result.update(file=path.name, sha256=sha256(raw).hexdigest())
        results.append(result)
    print(json.dumps({'results': results, 'runtime_seconds': perf_counter() - start}, indent=2))
