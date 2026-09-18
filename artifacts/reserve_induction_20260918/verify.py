"""Standalone standard-library verifier for reserve-induction certificates.

Square-validation routines are copied from the preceding square audit (same
repository, MIT), to avoid imports from the producer or project package.

Checks planar rotation systems, bipartiteness and 3-connectivity, independently
enumerates global cycles by perfect matchings, and checks every requirement.
"""
import argparse
import base64
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import platform
import sys
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


def reserve_requirements(graph, faces):
    requirements = set()
    for face in faces:
        if len(face) != 4:
            continue
        sides = [tuple(sorted((face[i], face[(i + 1) % 4]))) for i in range(4)]
        for i in (0, 1):
            a, b = sorted((sides[i], sides[i + 2]))
            requirements.update((a, b, f) for f in graph - set(sides))
    return requirements


def absent_triples(requirements, family):
    return {r for r in requirements if not any(r[0] in c and r[1] in c and r[2] not in c for c in family)}


def decode_triples(raw):
    triples = {tuple(tuple(e) for e in r) for r in raw}
    require(len(triples) == len(raw) and all(len(r) == 3 for r in triples), 'bad triple list')
    return triples


def universal_obstructions(old, faces, oc, nc, parents, required):
    constraints = {(a, b) for a in old for b in old if a != b}
    constraints |= reserve_requirements(old, faces)
    supports = {frozenset(i for i, cycle in enumerate(oc)
                          if set(r[:-1]) <= cycle and r[-1] not in cycle) for r in constraints}
    require(all(supports), 'empty old mandatory support')
    # This verifier uses explicit sets, independently of the producer's masks.
    minimal = [s for s in supports if not any(t < s for t in supports)]
    failed = set()
    for r in required:
        forbidden = {p for c, p in zip(nc, parents) if {r[0], r[1]} <= c and r[2] not in c}
        if not any(s <= forbidden for s in minimal):
            failed.add(r)
    return failed


def verify_reserve(record):
    summary = check(record)
    old, new = decode(record['old_edges']), decode(record['new_edges'])
    old_faces = barnette(old, record['old_rotation'])
    new_faces = barnette(new, record['new_rotation'])
    oc = [decode(c) for c in record['old_cycles']]
    nc = [decode(c) for c in record['new_cycles']]
    core = checked_indices(record['old_selected_indices'], len(oc))
    reserve = checked_indices(record['source_reserve_indices'], len(oc))
    require(not core & reserve, 'source core and reserve overlap')
    require(not absent_triples(reserve_requirements(old, old_faces), [oc[i] for i in core | reserve]),
            'source reserve fails')
    available = checked_indices(record['available_lift_indices'], len(nc))
    require(available == {i for i, p in enumerate(record['new_parent_indices']) if p in core | reserve},
            'reservoir lift inventory mismatch')
    required = reserve_requirements(new, new_faces)
    missing = absent_triples(required, [nc[i] for i in available])
    require(missing == decode_triples(record['closure_missing']), 'closure deficit mismatch')
    require(absent_triples(required, nc) == decode_triples(record['full_universe_missing']),
            'full universe deficit mismatch')
    universal = universal_obstructions(old, old_faces, oc, nc, record['new_parent_indices'], required)
    require(universal == decode_triples(record['universal_closure_obstructions']), 'universal closure mismatch')
    next_core = checked_indices(record['budget_selected_indices'], len(nc))
    require(next_core <= available, 'budget core uses unavailable parent')
    require(not uncovered(new, [nc[i] for i in next_core]), 'budget core fails separation')
    next_reserve = checked_indices(record['next_reserve_indices'], len(nc))
    require(next_reserve <= available, 'next reserve uses unavailable parent')
    require(not next_core & next_reserve, 'next core and reserve overlap')
    require(not absent_triples(required, [nc[i] for i in next_core | next_reserve]), 'next reserve fails')
    # Independently test the new one-step reserve lemma: each needed old
    # reserve parent has a lift using both middle rungs and the same exterior.
    u, v, x, y = record['old_map']
    nm = record['new_map']
    e = lambda a, b: tuple(sorted((a, b)))
    opposite = {e(u, x), e(v, y)}
    patch = opposite | {e(u, v), e(x, y)}
    outside = old - patch
    bad = {f for f in outside if not any(opposite <= oc[i] and f not in oc[i] for i in core)}
    useful = {i for i in reserve if opposite <= oc[i] and any(f not in oc[i] for f in bad)}
    middle = {e(nm[1], nm[5]), e(nm[2], nm[6])}
    repairs = []
    for p in sorted(useful):
        eligible = [i for i, parent in enumerate(record['new_parent_indices']) if parent == p and middle <= nc[i]]
        require(bool(eligible), 'no simultaneous-rung lift')
        repairs.append(nc[eligible[0]])
    require(not uncovered(new, [nc[i] for i in record['lifted_indices']] + repairs), 'reserve lemma repair fails')
    n = len(adjacent(new))
    summary.update(name=record['name'], source_reserve=len(reserve), next_reserve=len(next_reserve),
                   next_reserve_from_available=next_reserve <= available,
                   closure_missing=len(missing), budget_core_upper=len(next_core), target_B=n * (n + 8) // 32,
                   universal_closure_obstructions=len(universal),
                   reserve_lemma_repairs=len(repairs))
    return summary


def check_source(source):
    graph = source['graph']
    edges = decode(graph['edges'])
    rotation = graph['rotation_system']
    faces = barnette(edges, {str(i): row for i, row in enumerate(rotation)})
    require(set(adjacent(edges)) == set(range(len(rotation))), 'source labels')
    require(faces == {canonical(f) for f in graph['faces']}, 'source faces')
    n = len(rotation)
    require(n == graph['graph_order'] < 63, 'source order')
    values = [ord(c) - 63 for c in graph['graph6']]
    require(values and values[0] == n and all(0 <= v < 64 for v in values), 'source graph6 header')
    bits = [(v >> k) & 1 for v in values[1:] for k in range(5, -1, -1)]
    positions = [(a, b) for b in range(n) for a in range(b)]
    require(len(values) == 1 + (len(positions) + 5) // 6, 'source graph6 length')
    require({p for p, bit in zip(positions, bits) if bit} == edges and not any(bits[len(positions):]), 'source graph6 edges')
    pc = base64.b64decode(graph['planar_code_base64'], validate=True)
    expected = b'>>planar_code<<' + bytes([n]) + b''.join(bytes([v + 1 for v in row] + [0]) for row in rotation)
    require(pc == expected and sha256(pc).hexdigest() == graph['planar_code_sha256'], 'source planar code')
    return edges, faces


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    start = perf_counter()
    manifest = args.root / 'SHA256SUMS.txt'
    for line in manifest.read_text(encoding='ascii').splitlines():
        digest, name = line.split('  ', 1)
        require(sha256((args.root / name).read_bytes()).hexdigest() == digest, 'manifest mismatch: ' + name)
    inputs = json.loads((args.root / 'inputs.json').read_bytes())['graphs']
    cases = json.loads(gzip.decompress((args.root / 'certificates.json.gz').read_bytes()))
    expected, actual = set(), set()
    source_edges, outside_by_faces = [], []
    for gi, source in enumerate(inputs):
        edges, faces = check_source(source)
        source_edges.append(edges)
        n = len(adjacent(edges))
        patterns = [sorted([4] * (a + b) + [a + 3] * 2 + [b + 3] * 2)
                    for a in range(1, n, 2) for b in range(a, n, 2) if 2 * (a + b) + 4 == n]
        if sorted(map(len, faces)) not in patterns:
            outside_by_faces.append(gi)
        for face in faces:
            if len(face) == 4:
                sides = [tuple(sorted((face[i], face[(i + 1) % 4]))) for i in range(4)]
                for i in (0, 1):
                    expected.add((gi, canonical(face), tuple(sorted((sides[i], sides[i + 2])))))
    rows = []
    for record in cases:
        gi = record['input_index']
        require(isinstance(gi, int) and 0 <= gi < len(inputs), 'source index')
        require(decode(record['old_edges']) == source_edges[gi], 'source edges mismatch')
        source_primal = {frozenset(tuple(sorted((p[i], p[(i + 1) % len(p)]))) for i in range(len(p)))
                         for p in inputs[gi]['primal_cycles']}
        require({decode(record['old_cycles'][i]) for i in record['old_selected_indices']} == source_primal,
                'source primal mismatch')
        u, v, y, x = record['square']
        sides = tuple(sorted((tuple(sorted((u, x))), tuple(sorted((v, y))))))
        key = (gi, canonical(record['square']), sides)
        require(key not in actual, 'duplicate marked case')
        actual.add(key)
        rows.append(verify_reserve(record))
    require(actual == expected, 'marked-square coverage incomplete')
    require(len(inputs) == 15 and len(rows) == 206, 'bounded audit inventory')
    report = {'verified': True, 'graphs': len(inputs), 'marked_expansions': len(rows),
              'outside_double_ladders_by_face_lengths': outside_by_faces,
              'universal_closure_failures': sum(bool(r['universal_closure_obstructions']) for r in rows),
              'command': 'python -I artifacts/reserve_induction_20260918/verify.py --report artifacts/reserve_induction_20260918/verification.json',
              'python': sys.version, 'platform': platform.platform(),
              'verifier_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'runtime_seconds': perf_counter() - start, 'rows': rows}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
