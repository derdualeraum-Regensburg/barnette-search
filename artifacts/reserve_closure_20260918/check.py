"""Standard-library checks of the symbolic square-reserve transfer rules.

No project/producer imports. Local covers are independently enumerated by
all edge subsets. The optional finite regression reads the prior certificates.
"""
from hashlib import sha256
from itertools import combinations
import gzip
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parent
OLD = {'a': (0, 1), 'b': (2, 3), 'c': (0, 2), 'd': (1, 3)}
NEW = {'up': (0, 1), 'pq': (1, 2), 'qv': (2, 3), 'xr': (4, 5),
       'rs': (5, 6), 'sy': (6, 7), 'c': (0, 4), 'pr': (1, 5),
       'qs': (2, 6), 'd': (3, 7)}
TABLE = {
    'bcd': [{'c', 'd', 'pq', 'pr', 'qs', 'sy', 'xr'}],
    'ab': [{'pq', 'qv', 'rs', 'sy', 'up', 'xr'}],
    'cd': [{'d', 'pq', 'qs', 'rs', 'up', 'xr'},
           {'pr', 'qs', 'qv', 'sy', 'up', 'xr'},
           {'c', 'pq', 'pr', 'qv', 'rs', 'sy'}],
    'abd': [{'d', 'pq', 'qv', 'rs', 'sy', 'up', 'xr'}],
    'abc': [{'c', 'pq', 'qv', 'rs', 'sy', 'up', 'xr'}],
    'acd': [{'c', 'd', 'pr', 'qs', 'qv', 'rs', 'up'}],
}
FORCE = {'bcd': ('b', 'a'), 'ab': ('t2', 'd'), 'cd': ('t2', 'a'),
         'abd': ('d', 'c'), 'abc': ('c', 'd'), 'acd': ('a', 'b')}
CELLS = [({'up', 'xr', 'c', 'pr'}, [('up', 'xr'), ('c', 'pr')]),
         ({'pq', 'rs', 'pr', 'qs'}, [('pq', 'rs'), ('pr', 'qs')]),
         ({'qv', 'sy', 'qs', 'd'}, [('qv', 'sy'), ('qs', 'd')])]
PROXY = {'up': 'a', 'qv': 'a', 'rs': 'a', 'pq': 'b', 'xr': 'b', 'sy': 'b'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def state(names, edges, n, ports):
    adj = {v: set() for v in range(n)}
    for name in names:
        u, v = edges[name]
        adj[u].add(v)
        adj[v].add(u)
    if any(len(adj[v]) not in ({1, 2} if v in ports else {2}) for v in adj):
        return None
    used = {v for v in ports if len(adj[v]) == 1}
    if len(used) not in (2, 4):
        return None
    remaining, pairs = set(adj), []
    while remaining:
        seen, stack = {min(remaining)}, [min(remaining)]
        while stack:
            for v in adj[stack.pop()] - seen:
                seen.add(v)
                stack.append(v)
        ends = used & seen
        if len(ends) != 2:
            return None
        pairs.append(tuple(sorted(ports.index(v) for v in ends)))
        remaining -= seen
    return tuple(sorted(ports.index(v) for v in used)), tuple(sorted(pairs))


def covers(edges, n, ports):
    found = {}
    for size in range(len(edges) + 1):
        for names in combinations(sorted(edges), size):
            s = state(names, edges, n, ports)
            if s is not None:
                found.setdefault(s, set()).add(frozenset(names))
    return found


def local_checks(table=None):
    table = TABLE if table is None else table
    old = covers(OLD, 4, [0, 1, 2, 3])
    new = covers(NEW, 8, [0, 3, 4, 7])
    require(len(old) == len(new) == 6 and set(old) == set(new), 'state inventory')
    require(set(table) == {''.join(sorted(next(iter(rows)))) for rows in old.values()}, 'old table inventory')
    augmented = {}
    for key, rows in table.items():
        s = state(key, OLD, 4, [0, 1, 2, 3])
        require(old[s] == {frozenset(key)}, 'old cover mismatch')
        require({frozenset(r) for r in rows} == new[s] and len(rows) == len(new[s]), 'new cover mismatch')
        augmented[key] = set(key) | {f't{i}' for i in s[0]}
    for key, (a, b) in FORCE.items():
        require([k for k in table if a in augmented[k] and b not in augmented[k]] == [key], 'forcing rule')
    local_count = 0
    for square, pairs in CELLS:
        for pair in pairs:
            for forbidden in sorted(set(NEW) - square):
                require(any(set(pair) <= row and forbidden not in row for rows in table.values() for row in rows), 'new-square local witness')
                local_count += 1
            source_pair = {'a', 'b'} if set(pair) <= set(PROXY) else {'c', 'd'}
            for key, rows in table.items():
                if source_pair <= set(key):
                    require(any(set(pair) <= row for row in rows), 'new-square exterior rule')
    for key, rows in table.items():
        for f, proxy in PROXY.items():
            if proxy not in key:
                require(any(f not in row for row in rows), 'avoidance proxy')
        for proxy in ('c', 'd'):
            if proxy not in key:
                require(all('pr' not in row and 'qs' not in row for row in rows), 'rung avoidance')
        if key != 'cd':
            require(all((row & {'c', 'd'}) == (set(key) & {'c', 'd'}) for row in rows), 'retained sides')
    # A surviving adjacent square containing c (or d) cannot have its
    # opposite edge in a global cycle of special state cd: its four edges
    # would then be an isolated cycle. Check the local forced 4-cycle.
    for side, endpoints in [('c', (0, 2)), ('d', (1, 3))]:
        u, v = endpoints
        cycle = {(u, v), (u, 4), (v, 5), (4, 5)}
        degree = {z: sum(z in e for e in cycle) for z in (u, v, 4, 5)}
        require(set(degree.values()) == {2}, 'closed adjacent square')
    return {'old_states': 6, 'new_covers': 8, 'new_square_local_requirements': local_count,
            'forcing_rules': len(FORCE), 'symbolic_rules_passed': True}


def face_edges(face):
    return {tuple(sorted((face[i], face[(i + 1) % len(face)]))) for i in range(len(face))}


def compress_reserve(graph, faces, family, core):
    """Construct the reserve in section 6; no minimum-size claim."""
    family = sorted(set(map(frozenset, family)), key=lambda c: tuple(sorted(c)))
    core = set(map(frozenset, core))
    require(core <= set(family), 'core not in available family')
    chosen = set()
    for face in faces:
        if len(face) != 4:
            continue
        sides = [tuple(sorted((face[i], face[(i + 1) % 4]))) for i in range(4)]
        for i in (0, 1):
            pair = {sides[i], sides[i + 2]}
            eligible = [c for c in family if pair <= c]
            require(bool(eligible), 'no joint witness')
            initial = eligible[0]
            chosen.add(initial)
            for f in sorted((graph - set(sides)) & initial):
                witness = next((c for c in eligible if f not in c), None)
                require(witness is not None, 'reserve unavailable')
                chosen.add(witness)
    return chosen - core


def trace(rotation):
    rotation = {int(v): ns for v, ns in rotation.items()}
    darts = {(u, v) for u, ns in rotation.items() for v in ns}
    faces = []
    while darts:
        start = current = min(darts)
        face = []
        while True:
            require(current in darts, 'bad rotation')
            darts.remove(current)
            u, v = current
            face.append(u)
            row = rotation[v]
            current = (v, row[(row.index(u) + 1) % len(row)])
            if current == start:
                break
        faces.append(face)
    return faces


def mapping(record, square, pair, forbidden):
    om, nm = record['old_map'], record['new_map']
    old_names = {k: tuple(sorted((om[a], om[b]))) for k, (a, b) in OLD.items()}
    new_names = {k: tuple(sorted((nm[a], nm[b]))) for k, (a, b) in NEW.items()}
    inv = {e: k for k, e in new_names.items()}
    old_edges = {tuple(e) for e in record['old_edges']}
    old_patch = set(old_names.values())
    new_patch = set(new_names.values())
    sq = face_edges(square)
    pair = set(pair)
    if sq <= new_patch:
        pair_names = {inv[e] for e in pair}
        if forbidden not in new_patch:
            positive = 'ab' if pair_names <= set(PROXY) else 'cd'
            return tuple(old_names[k] for k in positive) + (forbidden,), 'new-exterior'
        for key in sorted(TABLE):
            if any(pair_names <= row and inv[forbidden] not in row for row in TABLE[key]):
                positive, negative = FORCE[key]
                def resolve(name):
                    if name in old_names:
                        return old_names[name]
                    vertex = om[int(name[1])]
                    choices = [e for e in old_edges - old_patch if vertex in e]
                    require(len(choices) == 1, 'port edge')
                    return choices[0]
                return (resolve(positive), resolve(negative)), 'new-local'
        raise ValueError('no forcing rule for new square')
    require(sq <= old_edges and not sq & {old_names['a'], old_names['b']}, 'unclassified face')
    if forbidden in old_edges:
        return tuple(sorted(pair)) + (forbidden,), 'retained-old'
    name = inv[forbidden]
    if name in PROXY:
        proxy = old_names[PROXY[name]]
    else:
        require(name in ('pr', 'qs'), 'unknown new edge')
        proxy = next((old_names[k] for k in ('c', 'd') if old_names[k] not in sq), None)
        require(proxy is not None, 'unchanged square contains both retained sides')
    return tuple(sorted(pair)) + (proxy,), 'retained-new'


def regression(record):
    oc = [set(map(tuple, c)) for c in record['old_cycles']]
    nc = [set(map(tuple, c)) for c in record['new_cycles']]
    old_edges, new_edges = set(map(tuple, record['old_edges'])), set(map(tuple, record['new_edges']))
    old_faces = trace(record['old_rotation'])
    old_triples = set()
    for face in old_faces:
        if len(face) == 4:
            es = [tuple(sorted((face[i], face[(i + 1) % 4]))) for i in range(4)]
            for i in (0, 1):
                for f in old_edges - set(es):
                    old_triples.add(tuple(sorted((es[i], es[i + 2]))) + (f,))
    counts = {}
    for face in trace(record['new_rotation']):
        if len(face) != 4:
            continue
        es = [tuple(sorted((face[i], face[(i + 1) % 4]))) for i in range(4)]
        for i in (0, 1):
            pair = {es[i], es[i + 2]}
            for f in sorted(new_edges - set(es)):
                source, kind = mapping(record, face, pair, f)
                if len(source) == 3:
                    require(tuple(sorted(source[:2])) + (source[2],) in old_triples, 'source is not a reserve requirement')
                else:
                    require(len(source) == 2 and source[0] != source[1] and set(source) <= old_edges, 'source is not a separation requirement')
                parents = {p for c, p in zip(nc, record['new_parent_indices']) if pair <= c and f not in c}
                support = {j for j, c in enumerate(oc) if set(source[:-1]) <= c and source[-1] not in c}
                require(bool(support) and support <= parents, 'symbolic witness implication fails')
                counts[kind] = counts.get(kind, 0) + 1
    return counts


def main():
    start = perf_counter()
    local = local_checks()
    source = ROOT.parent / 'reserve_induction_20260918/certificates.json.gz'
    records = json.loads(gzip.decompress(source.read_bytes()))
    rows = [{'name': r['name'], 'checks': regression(r)} for r in records]
    report = {'local': local, 'marked_expansions': len(rows), 'rows': rows,
              'source_sha256': sha256(source.read_bytes()).hexdigest(),
              'checker_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'command': 'python -I artifacts/reserve_closure_20260918/check.py',
              'python': sys.version, 'platform': platform.platform(), 'seed': None,
              'solver': 'none; exhaustive local subsets and explicit witness implications',
              'runtime_seconds': perf_counter() - start}
    (ROOT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'local': local, 'marked_expansions': len(rows),
                      'witness_implications': sum(sum(r['checks'].values()) for r in rows),
                      'runtime_seconds': report['runtime_seconds']}, indent=2))


if __name__ == '__main__':
    main()
