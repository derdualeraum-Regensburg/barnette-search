"""Regenerate a bounded deterministic audit; never starts a graph census."""
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

import networkx as nx

from construct import compose, cube_fragment, ladder
from verify import check


def main():
    start = perf_counter()
    root = Path(__file__).resolve().parent
    folder = root / 'examples'
    folder.mkdir(exist_ok=True)
    rows = []
    cases = [('ladder2_ladder2', ladder(2), ladder(2), False),
             ('ladder3_ladder4', ladder(3), ladder(4), False),
             ('ladder4_ladder4', ladder(4), ladder(4), False),
             ('cube_fragment_ladder4', cube_fragment(), ladder(4), False),
             ('ladder4_cube_fragment_thin', ladder(4), cube_fragment(), True)]
    for name, left, right, thin in cases:
        for index, permutation in enumerate(permutations(range(4))):
            record = compose(left, right, permutation, thin=thin)
            result = check(record)
            graph = nx.Graph()
            graph.add_nodes_from(sorted({v for e in record['output_edges'] for v in e}))
            graph.add_edges_from(record['output_edges'])
            graph6 = nx.to_graph6_bytes(graph, header=False).decode().strip()
            assert set(nx.from_graph6_bytes(graph6.encode()).edges()) == set(map(tuple, record['output_edges']))
            record['graph6_labelled'] = graph6
            path = folder / f'{name}_{index:02}.json'
            path.write_text(json.dumps(record, separators=(',', ':')) + '\n', encoding='utf-8')
            result.update({'file': path.relative_to(root).as_posix(),
                           'sha256': sha256(path.read_bytes()).hexdigest(),
                           'barnette': nx.is_bipartite(graph) and nx.check_planarity(graph)[0]
                                       and nx.node_connectivity(graph) >= 3,
                           'complete_local_families': not thin})
            rows.append(result)
    report = {'python': sys.version, 'platform': platform.platform(), 'networkx': nx.__version__,
              'command': 'python artifacts/four_port_20260917/build_examples.py',
              'random_seed': None, 'randomness': False, 'solver': None,
              'runtime_seconds': perf_counter() - start,
              'source_sha256': {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))},
              'scope': '120 labelled examples, not isomorphism classes; upper certificates only',
              'examples': rows}
    (root / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    files = sorted([*root.glob('*.py'), root / 'results.json', *folder.glob('*.json')])
    (root / 'SHA256SUMS.txt').write_text(''.join(
        f'{sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\n' for p in files), encoding='utf-8')
    print(json.dumps({'examples': len(rows), 'barnette': sum(r['barnette'] for r in rows),
                      'strict_refinements': sum(r['reduced_count'] < r['full_count'] for r in rows),
                      'separating': sum(r['separating'] for r in rows),
                      'runtime_seconds': report['runtime_seconds']}, indent=2))


if __name__ == '__main__':
    main()
