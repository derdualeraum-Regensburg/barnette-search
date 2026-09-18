"""Bounded exact analysis of four existing 16-vertex four-port examples.

No existing solver/validator is modified; no census is generated.
"""
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

import networkx as nx


ROOT = Path(__file__).resolve().parent
INPUT = ROOT.parent / 'four_port_20260917' / 'examples'


def decode(raw):
    return frozenset(tuple(e) for e in raw)


def demands(graph, cycle):
    return {(e, f) for e in cycle for f in graph - cycle}


def union_minimum(family):
    target = set().union(*family)
    for size in range(1, len(family) + 1):
        for chosen in combinations(range(len(family)), size):
            if set().union(*(family[i] for i in chosen)) == target:
                return size
    raise ValueError('empty local family')


def double_ladder_33():
    # Vertices 0..7 are A_i^r=2*i+r; 8..15 are B_j^r=8+2*j+r.
    edges = set()
    for offset in (0, 8):
        edges |= {(offset + 2 * i, offset + 2 * i + 1) for i in range(4)}
        edges |= {(offset + 2 * i + r, offset + 2 * (i + 1) + r)
                  for i in range(3) for r in (0, 1)}
    return edges | {(0, 8), (1, 14), (6, 9), (7, 15)}


def main():
    start = perf_counter()
    summaries = []
    for index in (2, 10, 13, 21):
        source = INPUT / f'ladder4_ladder4_{index:02}.json'
        raw = source.read_bytes()
        old = json.loads(raw)
        graph = decode(old['output_edges'])
        cycles = [decode(c) for c in old['full_cycles']]
        covers = [demands(graph, c) for c in cycles]
        requirements = [(e, f) for e in sorted(graph) for f in sorted(graph) if e != f]
        supports = {r: [i for i, covered in enumerate(covers) if r in covered] for r in requirements}
        mandatory = sorted({ids[0] for ids in supports.values() if len(ids) == 1})
        assert set().union(*(covers[i] for i in mandatory)) == set(requirements)
        private = [{'cycle_index': i, 'requirement': next(r for r in requirements if supports[r] == [i])}
                   for i in mandatory]
        omitted = sorted(set(range(len(cycles))) - set(mandatory))
        replacement_covers = []
        for i in omitted:
            found = None
            for size in range(1, len(mandatory) + 1):
                found = next((ids for ids in combinations(mandatory, size)
                              if covers[i] <= set().union(*(covers[j] for j in ids))), None)
                if found is not None:
                    break
            replacement_covers.append({'omitted_index': i, 'witness_indices': found})
        # Reconstruct pair provenance using the source fragment labels and forests.
        blocks = []
        for block in old['blocks']:
            rows = [next(row for row in old['states'][s] if row['state'] == block[key])
                    for s, key in enumerate(('left_state', 'right_state'))]
            fs = [[decode(f) for f in row['forests']] for row in rows]
            matrix = []
            for a in fs[0]:
                row = []
                for b in fs[1]:
                    global_b = {(u + 8, v + 8) for u, v in b}
                    state_cut = {tuple(old['cut_edges'][i]) for i in block['left_state'][0]}
                    row.append(cycles.index(a | global_b | state_cut))
                matrix.append(row)
            p, q = map(union_minimum, fs)
            a, b = map(len, fs)
            blocks.append({'states': [block['left_state'], block['right_state']],
                           'cycle_index_matrix': matrix, 'a': a, 'b': b, 'p_min': p, 'q_min': q,
                           'rectangle_minimum': p * b + a * q - p * q,
                           'selected_count': sum(i in mandatory for row in matrix for i in row)})
        graph_nx = nx.Graph(sorted(graph))
        target = nx.Graph(sorted(double_ladder_33()))
        matcher = nx.algorithms.isomorphism.GraphMatcher(graph_nx, target)
        assert matcher.is_isomorphic()
        record = {'source_file': source.relative_to(ROOT.parent.parent).as_posix(),
                  'source_sha256': sha256(raw).hexdigest(), 'graph_edges': sorted(graph),
                  'graph6_labelled': old['graph6_labelled'],
                  'cycles': [sorted(c) for c in cycles], 'selected_indices': mandatory,
                  'private_requirements': private, 'omitted_indices': omitted,
                  'replacement_covers': replacement_covers,
                  'prior_selected_indices': [i for i, c in enumerate(cycles)
                                             if c in [decode(f) for f in old['reduced_cycles']]],
                  'ports': old['ports'], 'cut_edges': old['cut_edges'], 'blocks': blocks,
                  'double_ladder_33_map': [matcher.mapping[v] for v in range(16)],
                  'claim': {'hsep': 12, 'unique_minimum_family': True,
                            'minimum_with_state_union_rectangles': 13}}
        path = ROOT / f'certificate_{index:02}.json'
        path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        summaries.append({'certificate': path.name, 'sha256': sha256(path.read_bytes()).hexdigest(),
                          'full_cycles': len(cycles), 'upper': len(mandatory),
                          'private_requirement_lower': len(private),
                          'minimum_with_state_union_rectangles': sum(b['rectangle_minimum'] for b in blocks),
                          'omitted_indices': omitted})
    report = {'command': 'python artifacts/four_port_step1_20260917/analyze.py',
              'python': sys.version, 'platform': platform.platform(), 'networkx': nx.__version__,
              'solver': 'exhaustive finite subsets; no external optimization solver',
              'random_seed': None, 'random_choices': False, 'runtime_seconds': perf_counter() - start,
              'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'scope': 'four labelled representations, one isomorphism class D(3,3)',
              'certificates': summaries}
    (ROOT / 'analysis.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
