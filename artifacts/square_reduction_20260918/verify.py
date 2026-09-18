"""Independent standard-library verifier for the square-lift certificates.

Checks planar rotation systems, bipartiteness and 3-connectivity, independently
enumerates global cycles by perfect matchings, and checks every requirement.
"""
import argparse
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from time import perf_counter


def require(ok, message):
    if not ok:
        raise ValueError(message)


def decode(raw):
    result = frozenset(tuple(e) for e in raw)
    require(len(result) == len(raw) and all(len(e) == 2 and e[0] < e[1] for e in result), 'bad edges')
    return result


def adjacent(graph):
    out = {}
    for a, b in graph:
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out


def connected(graph, deleted=()):
    adj = adjacent(graph)
    remaining = set(adj) - set(deleted)
    if not remaining:
        return False
    seen, todo = {min(remaining)}, [min(remaining)]
    while todo:
        for v in (adj[todo.pop()] & remaining) - seen:
            seen.add(v)
            todo.append(v)
    return seen == remaining


def canonical(cycle):
    return min(tuple(seq[i:] + seq[:i]) for seq in (list(cycle), list(reversed(cycle))) for i in range(len(seq)))


def barnette(graph, raw_rotation):
    adj = adjacent(graph)
    require(all(len(row) == 3 for row in adj.values()) and len(adj) >= 4, 'not cubic')
    require(connected(graph), 'disconnected graph')
    colors = {min(adj): 0}
    todo = list(colors)
    while todo:
        v = todo.pop()
        for w in adj[v]:
            if w not in colors:
                colors[w] = 1 - colors[v]
                todo.append(w)
            require(colors[w] != colors[v], 'not bipartite')
    for size in (1, 2):
        require(all(connected(graph, deleted) for deleted in combinations(sorted(adj), size)), 'not 3-connected')
    rotation = {int(v): ns for v, ns in raw_rotation.items()}
    require(set(rotation) == set(adj), 'rotation vertex mismatch')
    require(all(len(ns) == len(set(ns)) and set(ns) == adj[v] for v, ns in rotation.items()), 'bad rotation')
    remaining = {(u, v) for u in adj for v in adj[u]}
    faces = []
    while remaining:
        start = min(remaining)
        dart, face = start, []
        while True:
            require(dart in remaining, 'invalid face permutation')
            remaining.remove(dart)
            u, v = dart
            face.append(u)
            row = rotation[v]
            dart = (v, row[(row.index(u) + 1) % len(row)])
            if dart == start:
                break
        faces.append(canonical(face))
    require(len(adj) - len(graph) + len(faces) == 2, 'rotation is not planar')
    return set(faces)


def cycle_universe(graph):
    adj = adjacent(graph)
    result = set()

    def visit(unmatched, matching):
        if not unmatched:
            cycle = graph - matching
            if connected(cycle):
                result.add(frozenset(cycle))
            return
        v = min(unmatched)
        for w in sorted(adj[v] & unmatched):
            visit(unmatched - {v, w}, matching | {tuple(sorted((v, w)))})

    visit(set(adj), set())
    return result


def state(forest, vertices, ports):
    adj = adjacent(forest)
    require(set(adj) == set(vertices), 'local cover not spanning')
    used = tuple(i for i, v in enumerate(ports) if len(adj[v]) == 1)
    require(len(used) in (2, 4), 'wrong used ports')
    ends = {ports[i] for i in used}
    require(all(len(row) == (1 if v in ends else 2) for v, row in adj.items()), 'local degree failure')
    seen, pairs = set(), []
    for root in sorted(ends):
        if root in seen:
            continue
        last, v = None, root
        while True:
            require(v not in seen, 'local cycle')
            seen.add(v)
            following = adj[v] - {last}
            if not following:
                break
            require(len(following) == 1, 'local branch')
            last, v = v, next(iter(following))
        pairs.append(tuple(sorted((ports.index(root), ports.index(v)))))
    require(seen == set(vertices), 'hidden local cycle')
    return used, tuple(sorted(pairs))


def uncovered(graph, family):
    return {(e, f) for e in graph for f in graph if e != f
            and not any(e in c and f not in c for c in family)}


def checked_indices(indices, count):
    require(len(indices) == len(set(indices)) and all(isinstance(i, int) and 0 <= i < count for i in indices),
            'bad family indices')
    return set(indices)


def check(record):
    old, new = decode(record['old_edges']), decode(record['new_edges'])
    old_faces = barnette(old, record['old_rotation'])
    new_faces = barnette(new, record['new_rotation'])
    om, nm = record['old_map'], record['new_map']
    require(len(om) == len(set(om)) == 4 and len(nm) == len(set(nm)) == 8, 'bad patch maps')
    require([nm[i] for i in (0, 3, 4, 7)] == om, 'corner maps disagree')
    require(record['square'] == [om[i] for i in (0, 1, 3, 2)], 'square order mismatch')
    require(canonical(record['square']) in old_faces, 'old square not facial')
    e = lambda a, b: tuple(sorted((a, b)))
    a, b, c, d = e(om[0], om[1]), e(om[2], om[3]), e(om[0], om[2]), e(om[1], om[3])
    old_patch = frozenset((a, b, c, d))
    new_patch = frozenset({e(nm[i], nm[i + 1]) for i in (0, 1, 2, 4, 5, 6)}
                          | {e(nm[i], nm[i + 4]) for i in range(4)})
    require({uv for uv in old if set(uv) <= set(om)} == old_patch, 'old patch not induced square')
    require({uv for uv in new if set(uv) <= set(nm)} == new_patch, 'new patch not induced strip')
    require(new == (old - old_patch) | new_patch, 'replacement mismatch')
    require(set(nm) - set(om) == set(adjacent(new)) - set(adjacent(old)), 'inserted vertex mismatch')
    for i in range(3):
        require(canonical([nm[i], nm[i + 1], nm[i + 5], nm[i + 4]]) in new_faces,
                'strip cells not facial')
    # The reduction criterion needs just these two diagonal checks once G is Barnette.
    require(connected(old, [om[0], om[3]]) and connected(old, [om[1], om[2]]), 'diagonal connectivity fails')
    old_cycles, new_cycles = [[decode(row) for row in record[key]] for key in ('old_cycles', 'new_cycles')]
    require(len(old_cycles) == len(set(old_cycles)) and set(old_cycles) == cycle_universe(old), 'old cycle universe mismatch')
    require(len(new_cycles) == len(set(new_cycles)) and set(new_cycles) == cycle_universe(new), 'new cycle universe mismatch')
    selected_old = checked_indices(record['old_selected_indices'], len(old_cycles))
    family = [old_cycles[i] for i in selected_old]
    require(not uncovered(old, family), 'old family not separating')
    external = old - old_patch
    parents = record['new_parent_indices']
    require(len(parents) == len(new_cycles), 'parent metadata length')
    for cycle, parent in zip(new_cycles, parents):
        require(isinstance(parent, int) and 0 <= parent < len(old_cycles), 'invalid parent')
        old_cycle = old_cycles[parent]
        require(cycle & external == old_cycle & external, 'outside incidences changed')
        require(state(cycle & new_patch, nm, om) == state(old_cycle & old_patch, om, om),
                'boundary pairing changed')
    for i, cycle in enumerate(old_cycles):
        expected = 3 if cycle & old_patch == {c, d} else 1
        require(parents.count(i) == expected, 'wrong number of local lifts')
    lift_ids = checked_indices(record['lifted_indices'], len(new_cycles))
    require(lift_ids == {i for i, p in enumerate(parents) if p in selected_old}, 'not all selected-parent lifts retained')
    lifts = [new_cycles[i] for i in lift_ids]
    t = sum(cycle & old_patch == {c, d} for cycle in family)
    require(t == record['double_rung_state_count'] and len(lifts) == len(family) + 2 * t, 'lift count mismatch')
    bad = {f for f in external if not any({c, d} <= cycle and f not in cycle for cycle in family)}
    require(bad == decode(record['bad_exterior_edges']), 'joint avoidance metadata mismatch')
    missing = uncovered(new, lifts)
    middle = {e(nm[1], nm[5]), e(nm[2], nm[6])}
    require(missing == {(g, f) for g in middle for f in bad}, 'exact missing-requirement theorem fails')
    require(missing == {(tuple(x), tuple(y)) for x, y in record['uncovered_requirements']}, 'missing metadata mismatch')
    repair_ids = checked_indices(record['repair_indices'], len(new_cycles))
    require(not uncovered(new, [new_cycles[i] for i in lift_ids | repair_ids]), 'repair certificate fails')
    if record['repair_minimum_claimed']:
        require(missing and len(repair_ids) == 1, 'unsupported repair minimum')
    chosen = checked_indices(record['selected_indices'], len(new_cycles))
    require(chosen <= lift_ids | repair_ids, 'final family not obtained by pruning')
    require(not uncovered(new, [new_cycles[i] for i in chosen]), 'final upper certificate fails')
    require(record['exact_new_hsep_claimed'] is False, 'unsupported exact hsep claim')
    n = len(adjacent(new))
    data = [ord(ch) - 63 for ch in record['new_graph6_labelled']]
    require(data and data[0] == n < 63 and len(data) == 1 + (n * (n - 1) // 2 + 5) // 6
            and all(0 <= v < 64 for v in data), 'invalid graph6')
    bits = [(value >> i) & 1 for value in data[1:] for i in range(5, -1, -1)]
    positions = [(u, v) for v in range(n) for u in range(v)]
    require(set(adjacent(new)) == set(range(n)), 'graph6 labels not consecutive')
    require({uv for uv, bit in zip(positions, bits) if bit} == new
            and not any(bits[len(positions):]), 'graph6 does not match')
    return {'verified': True, 'old_order': len(adjacent(old)), 'new_order': n,
            'old_family': len(family), 'saturated_lifts': len(lifts), 't': t,
            'uncovered': len(missing), 'bad_exterior_edges': sorted(bad),
            'repairs': len(repair_ids), 'final_upper': len(chosen),
            'repair_parent_selected': [parents[i] in selected_old for i in sorted(repair_ids)],
            'new_hamiltonian_cycles': len(new_cycles), 'exact_new_hsep_claimed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('certificates', nargs='+', type=Path)
    args = parser.parse_args()
    start, rows = perf_counter(), []
    for path in args.certificates:
        raw = path.read_bytes()
        row = check(json.loads(raw))
        row.update(file=path.name, sha256=sha256(raw).hexdigest())
        rows.append(row)
    print(json.dumps({'results': rows, 'runtime_seconds': perf_counter() - start}, indent=2))
