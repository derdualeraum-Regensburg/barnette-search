"""Bounded reserve-closure experiment; no exact optimization claims."""
import gzip
from itertools import combinations
from math import comb
from hashlib import sha256
import json
from pathlib import Path
import platform
import runpy
import sys
from time import perf_counter

import networkx as nx

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
HELPER = ROOT.parent / 'square_reduction_20260918' / 'analyze.py'
A = runpy.run_path(str(HELPER))


def snapshot():
    source = REPO / 'results/release-v0.9.0-repro/barnette-recalculated-certificates-v0.9.0/barnie-sequence'
    rows, sources, counts = [], {}, []
    for n in (8, 12, 14, 16, 18, 20):
        gp = source / f'order_{n:02}' / 'graph_certificates.jsonl.gz'
        ep = gp.with_name('exact_certificates.jsonl.gz')
        with gzip.open(gp, 'rt') as stream:
            graphs = [json.loads(line) for line in stream]
        with gzip.open(ep, 'rt') as stream:
            exact = {r['canonical_graph_hash']: r for r in map(json.loads, stream)}
        counts.append(len(graphs))
        sources[str(n)] = {p.name: sha256(p.read_bytes()).hexdigest() for p in (gp, ep)}
        rows.extend({'graph': g, 'primal_cycles': exact[g['canonical_graph_hash']]['primal_cycles']} for g in graphs)
    assert counts == [1, 1, 1, 2, 2, 8]
    (ROOT / 'inputs.json').write_text(json.dumps({'source_release': 'v0.9.0', 'source_hashes': sources,
                                              'graphs': rows}, indent=2) + '\n', encoding='utf-8')


def triples(graph, faces):
    result = set()
    for face in faces:
        if len(face) != 4:
            continue
        patch = {A['edge'](face[i], face[(i + 1) % 4]) for i in range(4)}
        for o in (0, 1):
            u, v, y, x = face[o:] + face[:o]
            c, d = sorted((A['edge'](u, x), A['edge'](v, y)))
            result.update((c, d, f) for f in graph - patch)
    return result


def deficits(required, family):
    return {r for r in required if not any(r[0] in c and r[1] in c and r[2] not in c for c in family)}


def reserve(required, core, universe):
    missing, selected = deficits(required, core), []
    while missing:
        cycle = min(universe, key=lambda c: (-sum(a in c and b in c and f not in c for a, b, f in missing), tuple(sorted(c))))
        covered = {r for r in missing if r[0] in cycle and r[1] in cycle and r[2] not in cycle}
        if not covered:
            break
        selected.append(cycle)
        missing -= covered
    return selected, missing


def closure_obstructions(old, faces, universe, new_cycles, parents, required):
    """Universal over all separating, square-robust old subfamilies.

    A target support must contain the support of at least one old mandatory
    requirement. Otherwise its complement satisfies every old requirement.
    """
    constraints = [(e, f) for e in sorted(old) for f in sorted(old) if e != f]
    constraints += sorted(triples(old, faces))
    supports = set()
    for r in constraints:
        supports.add(sum(1 << i for i, c in enumerate(universe)
                         if all(e in c for e in r[:-1]) and r[-1] not in c))
    assert 0 not in supports
    minimal = [s for s in sorted(supports, key=lambda s: (s.bit_count(), s))
               if not any(t != s and t & s == t for t in supports)]
    failed = []
    for r in sorted(required):
        support = 0
        for c, p in zip(new_cycles, parents):
            if r[0] in c and r[1] in c and r[2] not in c:
                support |= 1 << p
        if not any(s & support == s for s in minimal):
            failed.append(r)
    return failed


def main():
    start = perf_counter()
    if '--snapshot' in sys.argv:
        snapshot()
    data = json.loads((ROOT / 'inputs.json').read_text(encoding='utf-8'))
    cases, sources = [], []
    for gi, source in enumerate(data['graphs']):
        graph = frozenset(tuple(e) for e in source['graph']['edges'])
        universe = A['hamiltonian_universe'](graph)
        core = [frozenset(A['edge'](p[i], p[(i + 1) % len(p)]) for i in range(len(p))) for p in source['primal_cycles']]
        _, rotation, faces = A['embedding'](graph)
        extra, impossible = reserve(triples(graph, faces), core, universe)
        assert not impossible
        sources.append({'input_index': gi, 'core': len(core), 'reserve': len(extra), 'cycles': len(universe)})
        for fi, face in enumerate(f for f in faces if len(f) == 4):
            for o in (0, 1):
                record = A['make_case'](f'g{gi:02}_f{fi:02}_o{o}', graph, core, universe, list(face[o:] + face[:o]), rotation)
                new = frozenset(tuple(e) for e in record['new_edges'])
                nc = [frozenset(tuple(e) for e in c) for c in record['new_cycles']]
                _, _, nf = A['embedding'](new)
                available_parents = {i for i, c in enumerate(universe) if c in core or c in extra}
                available = [i for i, p in enumerate(record['new_parent_indices']) if p in available_parents]
                required = triples(new, nf)
                closure_missing = deficits(required, [nc[i] for i in available])
                full_missing = deficits(required, nc)
                universal_missing = closure_obstructions(graph, faces, universe, nc, record['new_parent_indices'], required)
                # Repairs must come from the stored reservoir, not an unrelated
                # parent in the full universe used by the earlier diagnostic.
                pool = [nc[i] for i in record['lifted_indices']]
                missing_pairs = {(e, f) for e in new for f in new if e != f} - A['requirements'](new, pool)
                while missing_pairs:
                    repair = min((nc[i] for i in available), key=lambda c: (-len(A['requirements'](new, [c]) & missing_pairs), tuple(sorted(c))))
                    covered = A['requirements'](new, [repair]) & missing_pairs
                    assert covered
                    pool.append(repair)
                    missing_pairs -= covered
                next_core = A['prune'](new, sorted(set(pool), key=lambda c: tuple(sorted(c))))
                new_order = len(A['adjacency'](new))
                budget = new_order * (new_order + 8) // 32
                budget_ids = [nc.index(c) for c in next_core]
                if new_order >= 20 and new_order % 4 == 0 and len(next_core) > budget:
                    # A bounded feasibility search, never an exact hsep claim.
                    assert comb(len(available), budget) <= 2000000, 'bounded search limit'
                    for ids in combinations(available, budget):
                        trial = [nc[i] for i in ids]
                        if len(A['requirements'](new, trial)) == len(new) * (len(new) - 1):
                            budget_ids = list(ids)
                            next_core = trial
                            break
                next_reserve, _ = reserve(required, next_core, [nc[i] for i in available])
                record.update(input_index=gi, source_reserve_indices=[universe.index(c) for c in extra],
                              available_lift_indices=available, closure_missing=sorted(closure_missing),
                              full_universe_missing=sorted(full_missing),
                              universal_closure_obstructions=universal_missing,
                              budget_selected_indices=budget_ids,
                              next_reserve_indices=[nc.index(c) for c in next_reserve])
                cases.append(record)
    raw = (json.dumps(cases, separators=(',', ':')) + '\n').encode()
    (ROOT / 'certificates.json.gz').write_bytes(gzip.compress(raw, mtime=0))
    rows = [{'name': c['name'], 'order': len(c['old_rotation']), 'core': len(c['old_selected_indices']),
             'reserve': len(c['source_reserve_indices']), 'closure_missing': len(c['closure_missing']),
             'full_universe_missing': len(c['full_universe_missing']), 'next_core_upper': len(c['selected_indices']),
             'budget_core_upper': len(c['budget_selected_indices']),
             'universal_closure_obstructions': len(c['universal_closure_obstructions']),
             'next_reserve': len(c['next_reserve_indices']),
             'target_B': (len(c['new_rotation']) * (len(c['new_rotation']) + 8)) // 32} for c in cases]
    report = {'command': 'python artifacts/reserve_induction_20260918/analyze.py', 'python': sys.version,
              'platform': platform.platform(), 'networkx': nx.__version__, 'random_seed': None,
              'solver': 'complete DFS enumeration; deterministic greedy reserve; no optimality claimed',
              'runtime_seconds': perf_counter() - start, 'sources': sources, 'cases': rows,
              'hashes': {p.name: sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), HELPER, ROOT / 'inputs.json', ROOT / 'certificates.json.gz')}}
    (ROOT / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'graphs': len(sources), 'cases': len(cases),
                      'closure_failures': sum(bool(c['closure_missing']) for c in cases),
                      'universe_failures': sum(bool(c['full_universe_missing']) for c in cases),
                      'universal_closure_failures': sum(bool(c['universal_closure_obstructions']) for c in cases),
                      'budget_misses_n_ge_16_mod4': [r['name'] for r in rows if r['order'] >= 16 and r['order'] % 4 == 0 and r['budget_core_upper'] > r['target_B']]}, indent=2))


if __name__ == '__main__':
    main()
