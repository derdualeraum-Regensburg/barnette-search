"""Finite state-table proof checks and independently verified square lifts."""
from itertools import combinations
import json
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[1] / 'artifacts' / 'square_reduction_20260918'
C = runpy.run_path(str(ROOT / 'analyze.py'))
V = runpy.run_path(str(ROOT / 'verify.py'))
FILES = sorted((ROOT / 'examples').glob('*.json'))


def central():
    return json.loads((ROOT / 'examples' / 'D33_f01_o0.json').read_text())


@pytest.mark.parametrize('path', FILES, ids=lambda p: p.stem)
def test_certified_expansions(path):
    result = V['check'](json.loads(path.read_text()))
    assert result['new_order'] == result['old_order'] + 4
    if result['old_order'] >= 12:
        n = result['new_order']
        assert result['final_upper'] <= n * (n + 8) // 32


@pytest.mark.parametrize('columns', [2, 4])
def test_local_table_exhaustively_against_independent_path_walker(columns):
    graph, ports = C['ladder'](columns)
    expected = C['local_families'](columns)
    observed = {}
    for size in (2 * columns - 2, 2 * columns - 1):
        for edges in combinations(sorted(graph), size):
            try:
                state = V['state'](edges, range(2 * columns), ports)
            except ValueError:
                continue
            observed.setdefault(state, set()).add(frozenset(edges))
    assert observed == {s: set(fs) for s, fs in expected.items()}
    assert len(observed) == 6
    assert sorted(map(len, observed.values())) == ([1] * 6 if columns == 2 else [1, 1, 1, 1, 1, 3])


def test_every_old_local_state_is_forced_by_an_ordered_requirement():
    groups = C['local_families'](2)
    augmented = {s: set(fs[0]) | {('port', i) for i in s[0]} for s, fs in groups.items()}
    ground = set().union(*augmented.values())
    forced = set()
    for e in ground:
        for f in ground - {e}:
            support = [s for s, row in augmented.items() if e in row and f not in row]
            if len(support) == 1:
                forced.add(support[0])
    assert forced == set(groups)


def test_proxy_table_and_only_joint_inclusion_obstruction():
    old, new = C['local_families'](2), C['local_families'](4)
    proxies = {(0, 1): (0, 1), (2, 3): (0, 1), (5, 6): (0, 1),
               (1, 2): (2, 3), (4, 5): (2, 3), (6, 7): (2, 3),
               (0, 4): (0, 2), (3, 7): (1, 3)}
    for state, rows in old.items():
        original = rows[0]
        for edge, proxy in proxies.items():
            assert any((edge in f) == (proxy in original) for f in new[state])
        for middle in ((1, 5), (2, 6)):
            assert any(middle in f for f in new[state]) == ({(0, 2), (1, 3)} <= original)
            if (0, 2) not in original:
                assert any(middle not in f for f in new[state])
    augmented = [set(f) | {('port', i) for i in s[0]} for s, fs in new.items() for f in fs]
    ground = set().union(*augmented)
    assert all(any(e in row and f not in row for row in augmented) for e in ground for f in ground - {e})


def test_central_obstruction_and_one_cycle_repair():
    record = central()
    result = V['check'](record)
    assert (result['old_family'], result['t'], result['saturated_lifts'], result['uncovered'],
            result['repairs'], result['final_upper']) == (12, 2, 16, 4, 1, 17)
    assert result['repair_parent_selected'] == [False]
    source = json.loads((ROOT.parent / 'four_port_step1_20260917' / 'certificate_02.json').read_text())
    parent = record['new_parent_indices'][record['repair_indices'][0]]
    assert record['old_cycles'][parent] == source['cycles'][6]


def test_missing_repair_is_rejected():
    record = central()
    record['repair_indices'] = []
    with pytest.raises(ValueError, match='repair certificate fails'):
        V['check'](record)


def test_false_joint_avoidance_claim_is_rejected():
    record = central()
    record['bad_exterior_edges'] = []
    with pytest.raises(ValueError, match='joint avoidance metadata'):
        V['check'](record)


def test_incomplete_global_universe_is_rejected():
    record = central()
    record['new_cycles'].pop()
    with pytest.raises(ValueError, match='new cycle universe mismatch'):
        V['check'](record)


def test_false_parent_is_rejected():
    record = central()
    record['new_parent_indices'][0] = (record['new_parent_indices'][0] + 1) % len(record['old_cycles'])
    with pytest.raises(ValueError, match='outside incidences changed|boundary pairing changed'):
        V['check'](record)


def test_nonplanar_rotation_is_rejected():
    record = central()
    record['new_rotation']['0'].reverse()
    with pytest.raises(ValueError, match='rotation is not planar'):
        V['check'](record)


def test_unsupported_exact_hsep_claim_is_rejected():
    record = central()
    record['exact_new_hsep_claimed'] = True
    with pytest.raises(ValueError, match='unsupported exact hsep'):
        V['check'](record)
