"""Bounded facial-square reduction/lift audit. No census or external solver."""
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

import networkx as nx


ROOT = Path(__file__).resolve().parent


def edge(a, b):
    return tuple(sorted((a, b)))


def ladder(columns):
    graph = {edge(i, i + columns) for i in range(columns)}
    graph |= {edge(r * columns + i, r * columns + i + 1)
              for r in (0, 1) for i in range(columns - 1)}
    return graph, [0, columns - 1, columns, 2 * columns - 1]


def adjacency(graph):
    result = {}
    for a, b in graph:
        result.setdefault(a, set()).add(b)
        result.setdefault(b, set()).add(a)
    return result


def path_state(forest, vertices, ports):
    adj = adjacency(forest)
    if set(adj) != set(vertices) or any(len(adj[v]) not in ((1, 2) if v in ports else (2,)) for v in vertices):
        return None
    used = tuple(i for i, v in enumerate(ports) if len(adj[v]) == 1)
    if len(used) not in (2, 4):
        return None
    unseen, pairs = set(vertices), []
    while unseen:
        root = min(unseen)
        component, todo = {root}, [root]
        while todo:
            for v in adj[todo.pop()] - component:
                component.add(v)
                todo.append(v)
        ends = tuple(sorted(ports.index(v) for v in component if len(adj[v]) == 1))
        if len(ends) != 2:
            return None
        pairs.append(ends)
        unseen -= component
    return used, tuple(sorted(pairs))


def local_families(columns):
    graph, ports = ladder(columns)
    n = columns * 2
    result = {}
    for k in (n - 2, n - 1):
        for edges in combinations(sorted(graph), k):
            state = path_state(edges, range(n), ports)
            if state is not None:
                result.setdefault(state, []).append(frozenset(edges))
    return result


def hamiltonian_universe(graph):
    adj = adjacency(graph)
    root = min(adj)
    result = set()

    def extend(path, seen):
        if len(seen) == len(adj):
            if root in adj[path[-1]] and path[1] < path[-1]:
                result.add(frozenset(edge(a, b) for a, b in zip(path, path[1:] + [root])))
            return
        for v in sorted(adj[path[-1]] - seen):
            extend(path + [v], seen | {v})

    extend([root], {root})
    return sorted(result, key=lambda f: tuple(sorted(f)))


def requirements(graph, family):
    return {(e, f) for c in family for e in c for f in graph - c}


def prune(graph, family):
    kept = list(family)
    target = {(e, f) for e in graph for f in graph if e != f}
    for c in tuple(kept):
        trial = [d for d in kept if d != c]
        if requirements(graph, trial) == target:
            kept = trial
    return kept


def canonical_face(face):
    return min(tuple(s[i:] + s[:i]) for s in (list(face), list(reversed(face))) for i in range(len(s)))


def embedding(graph):
    obj = nx.Graph()
    obj.add_nodes_from(sorted(adjacency(graph)))
    obj.add_edges_from(sorted(graph))
    planar, emb = nx.check_planarity(obj)
    assert planar and nx.is_bipartite(obj) and nx.node_connectivity(obj) >= 3
    seen, faces = set(), []
    for u, v in sorted(emb.edges()):
        if (u, v) not in seen:
            faces.append(canonical_face(emb.traverse_face(u, v, seen)))
    return obj, {str(v): list(emb.neighbors_cw_order(v)) for v in sorted(obj)}, sorted(set(faces))


def expand(graph, square):
    # square order is u,v,y,x; maps below label the patch ports u,v,x,y.
    u, v, y, x = square
    p, q, r, s = range(max(adjacency(graph)) + 1, max(adjacency(graph)) + 5)
    old_map = {0: u, 1: v, 2: x, 3: y}
    new_map = {0: u, 1: p, 2: q, 3: v, 4: x, 5: r, 6: s, 7: y}
    old_patch = {edge(old_map[a], old_map[b]) for a, b in ladder(2)[0]}
    new_patch = {edge(new_map[a], new_map[b]) for a, b in ladder(4)[0]}
    return (graph - old_patch) | new_patch, old_map, new_map, old_patch, new_patch


def make_case(name, graph, family, universe, square, old_rotation):
    expanded, om, nm, old_patch, new_patch = expand(graph, square)
    new_obj, new_rotation, _ = embedding(expanded)
    inv = {v: k for k, v in om.items()}
    local_new = local_families(4)
    lifted, all_new = [], []
    provenance = []
    for old_index, c in enumerate(universe):
        inside = {edge(inv[a], inv[b]) for a, b in c & old_patch}
        state = path_state(inside, range(4), [0, 1, 2, 3])
        for variant in local_new[state]:
            d = (c - old_patch) | {edge(nm[a], nm[b]) for a, b in variant}
            all_new.append(frozenset(d))
            provenance.append(old_index)
            if c in family:
                lifted.append(frozenset(d))
    assert len(all_new) == len(set(all_new))
    external = graph - old_patch
    opposite = {edge(om[0], om[2]), edge(om[1], om[3])}
    bad = [e for e in sorted(external) if not any(opposite <= c and e not in c for c in family)]
    missing = {(e, f) for e in expanded for f in expanded if e != f} - requirements(expanded, lifted)
    middle = {edge(nm[1], nm[5]), edge(nm[2], nm[6])}
    assert missing == {(e, f) for e in middle for f in bad}
    repairs, rest = [], set(missing)
    while rest:
        d = min(all_new, key=lambda c: (-len(requirements(expanded, [c]) & rest), tuple(sorted(c))))
        newly = requirements(expanded, [d]) & rest
        assert newly, 'full universe fails to repair'
        repairs.append(d)
        rest -= newly
    chosen = prune(expanded, sorted(set(lifted + repairs), key=lambda c: tuple(sorted(c))))
    special = (tuple(range(4)), ((0, 2), (1, 3)))
    t = sum(path_state({edge(inv[a], inv[b]) for a, b in c & old_patch}, range(4), [0, 1, 2, 3]) == special
            for c in family)
    record = {'name': name, 'old_edges': sorted(graph), 'new_edges': sorted(expanded),
              'old_rotation': old_rotation, 'new_rotation': new_rotation,
              'square': square, 'old_map': [om[i] for i in range(4)], 'new_map': [nm[i] for i in range(8)],
              'old_cycles': [sorted(c) for c in universe],
              'old_selected_indices': [i for i, c in enumerate(universe) if c in family],
              'new_cycles': [sorted(c) for c in all_new], 'new_parent_indices': provenance,
              'lifted_indices': [i for i, c in enumerate(all_new) if c in lifted],
              'repair_indices': [all_new.index(c) for c in repairs],
              'selected_indices': [all_new.index(c) for c in chosen],
              'bad_exterior_edges': bad, 'uncovered_requirements': sorted(missing),
              'double_rung_state_count': t,
              'new_graph6_labelled': nx.to_graph6_bytes(new_obj, header=False).decode().strip(),
              'exact_new_hsep_claimed': False, 'repair_minimum_claimed': bool(missing) and len(repairs) == 1}
    assert len(lifted) == len(family) + 2 * t
    return record


def main():
    start = perf_counter()
    source = ROOT.parent / 'four_port_step1_20260917' / 'certificate_02.json'
    base = json.loads(source.read_bytes())
    double = frozenset(tuple(e) for e in base['graph_edges'])
    dc = [frozenset(tuple(e) for e in c) for c in base['cycles']]
    cube = frozenset(edge(v, v ^ (1 << bit)) for v in range(8) for bit in range(3))
    prism = frozenset({edge(r * 6 + i, r * 6 + (i + 1) % 6) for r in (0, 1) for i in range(6)}
                      | {edge(i, i + 6) for i in range(6)})
    rows = []
    folder = ROOT / 'examples'
    folder.mkdir(exist_ok=True)
    for name, graph, supplied in [('cube', cube, None), ('prism6', prism, None),
                                  ('D33', double, [dc[i] for i in base['selected_indices']])]:
        universe = hamiltonian_universe(graph)
        family = supplied if supplied is not None else prune(graph, universe)
        assert requirements(graph, family) == {(e, f) for e in graph for f in graph if e != f}
        _, rotation, faces = embedding(graph)
        for face_index, face in enumerate(f for f in faces if len(f) == 4):
            for orientation in (0, 1):
                square = list(face[orientation:] + face[:orientation])
                key = f'{name}_f{face_index:02}_o{orientation}'
                record = make_case(key, graph, family, universe, square, rotation)
                path = folder / (key + '.json')
                path.write_text(json.dumps(record, separators=(',', ':')) + '\n', encoding='utf-8')
                rows.append({'name': key, 'file': path.relative_to(ROOT).as_posix(),
                             'sha256': sha256(path.read_bytes()).hexdigest(), 'old_order': len(adjacency(graph)),
                             'new_order': len(adjacency(graph)) + 4, 'old_family': len(family),
                             't': record['double_rung_state_count'], 'saturated_lifts': len(record['lifted_indices']),
                             'missing': len(record['uncovered_requirements']), 'repairs': len(record['repair_indices']),
                             'final_upper': len(record['selected_indices']),
                             'target_B': (len(adjacency(graph)) + 4) * (len(adjacency(graph)) + 12) // 32})
    profile = [{'state': st, 'old_count': len(local_families(2)[st]), 'new_count': len(local_families(4)[st])}
               for st in sorted(local_families(2))]
    report = {'command': 'python artifacts/square_reduction_20260918/analyze.py',
              'python': sys.version, 'platform': platform.platform(), 'networkx': nx.__version__,
              'random_seed': None, 'random_choices': False, 'solver': 'deterministic enumeration and greedy upper covers',
              'runtime_seconds': perf_counter() - start, 'local_profile': profile,
              'source_certificate': source.relative_to(ROOT.parent.parent).as_posix(),
              'source_certificate_sha256': sha256(source.read_bytes()).hexdigest(),
              'producer_sha256': sha256(Path(__file__).read_bytes()).hexdigest(), 'examples': rows}
    (ROOT / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'cases': len(rows), 'failed_saturated_lifts': sum(r['missing'] > 0 for r in rows),
                      'D33': [r for r in rows if r['name'].startswith('D33')]}, indent=2))


if __name__ == '__main__':
    main()
