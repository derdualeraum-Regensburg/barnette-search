"""Construct a conditional lift and greedy repair from supplied cycle certificates.

Inputs should first be checked by verify.py. All counts are upper bounds.
"""


def as_family(raw):
    return tuple(frozenset(tuple(e) for e in c) for c in raw)


def covered(graph, cycles):
    return {(e, f) for c in cycles for e in c for f in graph - c}


def common_signature(record, cycle):
    # The constructor maps the common left exterior to the same 0-based labels.
    vertices = sorted({v for e in record['graphs'][0] for v in e})
    mapping = {v: i for i, v in enumerate(vertices)}
    exterior = {tuple(sorted((mapping[u], mapping[v]))) for u, v in record['graphs'][0]}
    used = tuple(i for i, e in enumerate(record['cut_edges']) if tuple(e) in cycle)
    return frozenset(exterior & cycle), used


def lift_and_repair(old, new):
    if old['graphs'][0] != new['graphs'][0] or old['ports'][0] != new['ports'][0]:
        raise ValueError('different exteriors')
    family = as_family(old['reduced_cycles'])
    old_graph = frozenset(tuple(e) for e in old['output_edges'])
    if len(covered(old_graph, family)) != len(old_graph) * (len(old_graph) - 1):
        raise ValueError('old family is not separating')
    candidates = sorted(set(as_family(new['reduced_cycles'])), key=lambda c: tuple(sorted(c)))
    chosen = []
    for c in family:
        matches = [d for d in candidates if common_signature(old, c) == common_signature(new, d)]
        if not matches:
            raise ValueError('exterior witness has no compatible lift')
        chosen.append(matches[0])
    lifts = set(chosen)
    graph = frozenset(tuple(e) for e in new['output_edges'])
    missing = {(e, f) for e in graph for f in graph if e != f} - covered(graph, lifts)
    residual_count = len(missing)
    repairs = []
    while missing:
        witness = min(candidates, key=lambda c: (-len(covered(graph, [c]) & missing), tuple(sorted(c))))
        newly = covered(graph, [witness]) & missing
        if not newly:
            raise ValueError('candidate family cannot repair residual requirements')
        repairs.append(witness)
        missing -= newly
    return {'old_count': len(family), 'lift_cycles': [sorted(c) for c in sorted(lifts, key=lambda c: tuple(sorted(c)))],
            'repair_cycles': [sorted(c) for c in repairs], 'residual_requirements': residual_count,
            'upper_bound': len(lifts) + len(repairs), 'greedy_repair_is_optimal': False}
