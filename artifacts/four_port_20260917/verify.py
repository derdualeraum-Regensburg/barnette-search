"""Self-contained four-port verifier; independent global matching enumeration.

Usage: python verify.py certificate.json
Only the Python standard library is needed. No constructor/project imports.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(raw):
    edges = frozenset(tuple(e) for e in raw)
    require(len(edges) == len(raw) and all(len(e) == 2 and e[0] < e[1] for e in edges),
            'invalid or duplicate edges')
    return edges


def adjacency(edges):
    out = {}
    for u, v in edges:
        out.setdefault(u, set()).add(v)
        out.setdefault(v, set()).add(u)
    return out


def connected(vertices, edges):
    neighbours = {v: set() for v in vertices}
    for u, v in edges:
        neighbours[u].add(v)
        neighbours[v].add(u)
    seen = {min(vertices)}
    todo = list(seen)
    while todo:
        for v in neighbours[todo.pop()] - seen:
            seen.add(v)
            todo.append(v)
    return seen == set(vertices)


def hamiltonian(graph, cycle):
    adj = adjacency(cycle)
    return (cycle <= graph and set(adj) == set(adjacency(graph))
            and all(len(row) == 2 for row in adj.values()) and connected(adj, cycle))


def global_universe(graph):
    adj = adjacency(graph)
    require(all(len(row) == 3 for row in adj.values()), 'output not cubic')
    result = set()

    def visit(unmatched, matching):
        if not unmatched:
            cycle = graph - matching
            if hamiltonian(graph, cycle):
                result.add(frozenset(cycle))
            return
        v = min(unmatched)
        for u in sorted(adj[v] & unmatched):
            visit(unmatched - {u, v}, matching | {tuple(sorted((u, v)))})

    visit(set(adj), set())
    return result


def check_forest(graph, ports, forest, raw_state):
    used, pairing = raw_state
    require(len(used) in (2, 4) and list(used) == sorted(set(used))
            and set(used) <= set(range(4)), 'bad used-port set')
    require(forest <= graph, 'forest uses non-edges')
    adj = adjacency(forest)
    require(set(adj) == set(adjacency(graph)), 'forest not spanning')
    endpoints = {ports[i] for i in used}
    require(all(len(row) == (1 if v in endpoints else 2) for v, row in adj.items()),
            'forest degree mismatch')
    # Walk each path from its end, rejecting repeated vertices and extra cycles.
    visited = set()
    actual = []
    for start in sorted(endpoints):
        if start in visited:
            continue
        previous, current = None, start
        while True:
            require(current not in visited, 'forest has cycle')
            visited.add(current)
            following = adj[current] - {previous}
            if not following:
                break
            require(len(following) == 1, 'branch in forest')
            previous, current = current, next(iter(following))
        actual.append(tuple(sorted((ports.index(start), ports.index(current)))))
    require(visited == set(adj), 'forest has isolated cycle component')
    require(tuple(sorted(actual)) == tuple(tuple(p) for p in pairing), 'pairing mismatch')


def requirements(graph, family):
    # Explicit requirements, independently of the producer's edge-union selection.
    return {(e, f) for c in family for e in c for f in graph - c}


def check(record):
    graphs = [decode(g) for g in record['graphs']]
    ports = record['ports']
    vertices = [sorted(adjacency(g)) for g in graphs]
    maps = [{v: i for i, v in enumerate(vertices[0])},
            {v: len(vertices[0]) + i for i, v in enumerate(vertices[1])}]
    for g, pp in zip(graphs, ports):
        require(len(pp) == 4 and len(set(pp)) == 4 and set(pp) <= set(adjacency(g)), 'bad ports')
        require(all(len(ns) == (2 if v in pp else 3) for v, ns in adjacency(g).items()),
                'invalid fragment degrees')
    cut = [tuple(sorted((maps[0][ports[0][i]], maps[1][ports[1][i]]))) for i in range(4)]
    require(cut == [tuple(e) for e in record['cut_edges']], 'cut mismatch')
    graph = decode(record['output_edges'])
    expected = set(cut) | {tuple(sorted((maps[s][u], maps[s][v])))
                           for s in (0, 1) for u, v in graphs[s]}
    require(graph == expected, 'output graph mismatch')
    groups = []
    for s in (0, 1):
        grouped = {}
        for row in record['states'][s]:
            st = (tuple(row['state'][0]), tuple(tuple(p) for p in row['state'][1]))
            require(st not in grouped, 'duplicate state')
            fs = [decode(f) for f in row['forests']]
            require(fs and len(fs) == len(set(fs)), 'empty or duplicate state forests')
            for f in fs:
                check_forest(graphs[s], ports[s], f, st)
            ids = row['cover_indices']
            require(len(ids) == len(set(ids)) and all(0 <= i < len(fs) for i in ids), 'bad cover index')
            require(set().union(*(fs[i] for i in ids)) == set().union(*fs), 'cover loses edge union')
            limit = len(vertices[s]) // 2 - 1 + len(st[0]) // 2
            require(1 <= len(ids) <= min(len(fs), limit), 'cover size exceeds bound')
            grouped[st] = fs, set(ids)
        groups.append(grouped)
    expected_full, expected_reduced = set(), set()
    blocks = []
    for a, (aa, ua) in sorted(groups[0].items()):
        for b, (bb, vb) in sorted(groups[1].items()):
            if a[0] != b[0]:
                continue
            # Determine compatibility from actual connected glued cycles, not the state formula.
            compatible = None
            for i, first in enumerate(aa):
                for j, second in enumerate(bb):
                    cycle = frozenset({tuple(sorted((maps[s][u], maps[s][v])))
                                      for s, f in enumerate((first, second)) for u, v in f}
                                     | {cut[k] for k in a[0]})
                    good = hamiltonian(graph, cycle)
                    if compatible is None:
                        compatible = good
                    require(good == compatible, 'connectivity not determined by state')
                    if good:
                        expected_full.add(cycle)
                        if i in ua or j in vb:
                            expected_reduced.add(cycle)
            if compatible:
                blocks.append({'left_state': a, 'right_state': b,
                               'a': len(aa), 'b': len(bb), 'p': len(ua), 'q': len(vb)})
    require(json.dumps(blocks) == json.dumps(record['blocks']), 'block metadata mismatch')
    full = [decode(c) for c in record['full_cycles']]
    reduced = [decode(c) for c in record['reduced_cycles']]
    require(len(full) == len(set(full)) and set(full) == expected_full, 'full family mismatch')
    require(len(reduced) == len(set(reduced)) and set(reduced) == expected_reduced, 'reduced family mismatch')
    require(len(full) == sum(b['a'] * b['b'] for b in blocks), 'full count mismatch')
    require(len(reduced) == sum(b['p'] * b['b'] + b['a'] * b['q'] - b['p'] * b['q'] for b in blocks),
            'refined count mismatch')
    covered = requirements(graph, full)
    require(covered == requirements(graph, reduced), 'lost separation requirement')
    require(record['local_separation_criterion'] == (len(covered) == len(graph) * (len(graph) - 1)),
            'local separation criterion disagrees with direct global check')
    universe = global_universe(graph)
    require(set(full) <= universe, 'invalid global cycle')
    if record['complete_universe_claimed']:
        require(set(full) == universe, 'complete-universe claim fails')
    require(record['exact_hsep_claimed'] is False, 'unsupported exact hsep claim')
    return {'verified': True, 'vertices': len(adjacency(graph)), 'full_count': len(full),
            'reduced_count': len(reduced), 'hamiltonian_cycles': len(universe),
            'covered_requirements': len(covered), 'requirements': len(graph) * (len(graph) - 1),
            'separating': len(covered) == len(graph) * (len(graph) - 1), 'exact_hsep_claimed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('certificate', type=Path)
    args = parser.parse_args()
    raw = args.certificate.read_bytes()
    result = check(json.loads(raw))
    result['certificate_sha256'] = sha256(raw).hexdigest()
    print(json.dumps(result, indent=2))
