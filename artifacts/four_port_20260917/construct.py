"""Bounded four-port experiments, using exhaustive local edge subsets.

No solver, randomness, optimality claim, or census reconstruction.
"""
from itertools import combinations


def edge(u, v):
    return tuple(sorted((u, v)))


def ladder(columns):
    edges = {edge(r * columns + i, r * columns + i + 1)
             for r in (0, 1) for i in range(columns - 1)}
    edges |= {edge(i, columns + i) for i in range(columns)}
    return sorted(edges), [0, columns - 1, columns, 2 * columns - 1]


def cube_fragment():
    edges = {edge(v, v ^ (1 << bit)) for v in range(8) for bit in range(3)}
    edges -= {(0, 1), (6, 7)}
    return sorted(edges), [0, 1, 6, 7]


def state(edges, ports, forest):
    vertices = set(v for e in edges for v in e)
    neighbours = {v: set() for v in vertices}
    if not set(forest) <= set(map(tuple, edges)):
        return None
    for u, v in forest:
        neighbours[u].add(v)
        neighbours[v].add(u)
    if any(len(ns) not in ((1, 2) if v in ports else (2,))
           for v, ns in neighbours.items()):
        return None
    used = tuple(i for i, v in enumerate(ports) if len(neighbours[v]) == 1)
    if len(used) not in (2, 4):
        return None
    unseen = set(vertices)
    pairs = []
    while unseen:
        todo = [min(unseen)]
        component = set(todo)
        while todo:
            for v in neighbours[todo.pop()] - component:
                component.add(v)
                todo.append(v)
        ends = tuple(sorted(ports.index(v) for v in component if len(neighbours[v]) == 1))
        if len(ends) != 2:
            return None
        pairs.append(ends)
        unseen -= component
    return used, tuple(sorted(pairs))


def local_forests(edges, ports):
    n = len({v for e in edges for v in e})
    result = []
    for size in (n - 2, n - 1):
        for subset in combinations(map(tuple, edges), size):
            if state(edges, ports, subset) is not None:
                result.append(frozenset(subset))
    return sorted(result, key=lambda f: tuple(sorted(f)))


def compatible(left, right):
    return left[0] == right[0] and (len(left[0]) == 2 or left[1] != right[1])


def union_cover(family):
    """Deterministic edge-union cover; a feasible upper bound, never a minimum claim."""
    chosen = [0]
    missing = set().union(*family) - family[0]
    while missing:
        i = min(range(len(family)), key=lambda j: (-len(missing & family[j]), j))
        chosen.append(i)
        missing -= family[i]
    return chosen


def local_separation_criterion(graphs, groups):
    """The note's local-and-cross-edge criterion, without building global cycles."""
    active = [{a for a in groups[s] if any(compatible(a, b) for b in groups[1 - s])}
              for s in (0, 1)]
    for s in (0, 1):
        ground = {('edge', *e) for e in graphs[s]} | {('cut', i) for i in range(4)}
        family = [{('edge', *e) for e in f} | {('cut', i) for i in a[0]}
                  for a in active[s] for f in groups[s][a]]
        if not all(any(e in f and g not in f for f in family)
                   for e in ground for g in ground if e != g):
            return False
    for e in graphs[0]:
        for f in graphs[1]:
            for reverse in (False, True):
                if not any(compatible(a, b)
                           and any((e in x) != reverse for x in groups[0][a])
                           and any((f in y) == reverse for y in groups[1][b])
                           for a in active[0] for b in active[1]):
                    return False
    return True


def compose(left, right, permutation=(0, 1, 2, 3), thin=False):
    graphs = [list(map(tuple, left[0])), list(map(tuple, right[0]))]
    ports = [left[1], [right[1][i] for i in permutation]]
    universes = [local_forests(g, p) for g, p in zip(graphs, ports)]
    families = [f[::2] if thin else f for f in universes]
    vertices = [sorted({v for e in g for v in e}) for g in graphs]
    maps = [{v: i for i, v in enumerate(vertices[0])},
            {v: len(vertices[0]) + i for i, v in enumerate(vertices[1])}]
    cut = [edge(maps[0][ports[0][i]], maps[1][ports[1][i]]) for i in range(4)]
    output = sorted(set(cut) | {edge(maps[s][u], maps[s][v])
                               for s in (0, 1) for u, v in graphs[s]})
    groups = []
    for s in (0, 1):
        grouped = {}
        for f in families[s]:
            grouped.setdefault(state(graphs[s], ports[s], f), []).append(f)
        groups.append(grouped)
    covers = [{st: union_cover(fs) for st, fs in grouped.items()} for grouped in groups]
    full, reduced, profiles = [], [], []
    for a in sorted(groups[0]):
        for b in sorted(groups[1]):
            if not compatible(a, b):
                continue
            aa, bb = groups[0][a], groups[1][b]
            ua, vb = covers[0][a], covers[1][b]
            profiles.append({'left_state': a, 'right_state': b,
                             'a': len(aa), 'b': len(bb), 'p': len(ua), 'q': len(vb)})
            for i, first in enumerate(aa):
                for j, second in enumerate(bb):
                    cycle = sorted({edge(maps[s][u], maps[s][v])
                                    for s, forest in enumerate((first, second)) for u, v in forest}
                                   | {cut[k] for k in a[0]})
                    full.append(cycle)
                    if i in ua or j in vb:
                        reduced.append(cycle)
    states = [[{'state': st, 'forests': [sorted(f) for f in grouped[st]],
                'cover_indices': covers[s][st]} for st in sorted(grouped)]
              for s, grouped in enumerate(groups)]
    return {'graphs': graphs, 'ports': ports, 'states': states, 'output_edges': output,
            'cut_edges': cut, 'blocks': profiles, 'full_cycles': full, 'reduced_cycles': reduced,
            'complete_universe_claimed': not thin, 'exact_hsep_claimed': False,
            'local_separation_criterion': local_separation_criterion(graphs, groups)}
