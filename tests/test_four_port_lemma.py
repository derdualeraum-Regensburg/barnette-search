"""Independent finite checks of four-port connectivity and separation preservation."""
import copy
from itertools import combinations, permutations
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'artifacts' / 'four_port_20260917'
C = runpy.run_path(str(AUDIT / 'construct.py'))
V = runpy.run_path(str(AUDIT / 'verify.py'))
L = runpy.run_path(str(AUDIT / 'lift_repair.py'))


@pytest.mark.parametrize('pair', [(2, 2), (3, 4), (4, 4), (0, 4)])
@pytest.mark.parametrize('permutation', tuple(permutations(range(4))))
def test_all_port_bijections_against_independent_global_enumeration(pair, permutation):
    left = C['cube_fragment']() if pair[0] == 0 else C['ladder'](pair[0])
    result = V['check'](C['compose'](left, C['ladder'](pair[1]), permutation))
    assert result['verified']
    assert result['reduced_count'] <= result['full_count']


@pytest.mark.parametrize('permutation', tuple(permutations(range(4))))
def test_incomplete_local_families_preserve_exactly_their_covered_requirements(permutation):
    record = C['compose'](C['ladder'](4), C['cube_fragment'](), permutation, thin=True)
    assert V['check'](record)['verified']


def test_nine_states_and_twelve_compatible_ordered_blocks():
    states = [(s, (s,)) for s in combinations(range(4), 2)]
    states += [((0, 1, 2, 3), p) for p in
               (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2)))]
    assert len(states) == 9
    assert sum(C['compatible'](a, b) for a in states for b in states) == 12
    for state in states[6:]:
        assert not C['compatible'](state, state)


def test_same_pairing_glues_to_two_cycles_not_one():
    first = {(0, 1), (2, 3)}
    second = {(4, 5), (6, 7)}
    cut = {(i, i + 4) for i in range(4)}
    cycle = frozenset(first | second | cut)
    graph = frozenset(cycle | {(0, 3), (1, 2), (4, 7), (5, 6)})
    assert not V['hamiltonian'](graph, cycle)


def test_empty_cover_rejected():
    record = C['compose'](C['ladder'](4), C['ladder'](4))
    record['states'][0][0]['cover_indices'] = []
    with pytest.raises(ValueError, match='cover loses'):
        V['check'](record)


def test_wrong_pairing_rejected():
    record = copy.deepcopy(C['compose'](C['ladder'](4), C['ladder'](4)))
    row = record['states'][0][0]
    row['state'] = (row['state'][0], ((0, 0),))
    with pytest.raises(ValueError, match='pairing mismatch'):
        V['check'](record)


def test_damaged_global_cycle_rejected():
    record = C['compose'](C['ladder'](4), C['ladder'](4))
    record['reduced_cycles'][0] = record['reduced_cycles'][0][:-1]
    with pytest.raises(ValueError, match='reduced family mismatch'):
        V['check'](record)


def test_full_port_only_cycles_cannot_separate_cut_edges():
    record = C['compose'](C['ladder'](3), C['ladder'](3))
    cut = frozenset(record['cut_edges'])
    cycles = [frozenset(c) for c in record['full_cycles'] if cut <= frozenset(c)]
    assert cycles
    covered = V['requirements'](frozenset(record['output_edges']), cycles)
    assert not any((e, f) in covered for e in cut for f in cut if e != f)


def test_budget_must_allow_for_existing_slack():
    h = lambda a, b: ((a + 2) * (b + 2) - 1) // 2
    bound = lambda n: n * (n + 8) // 32
    growth = h(5, 15) - h(3, 15)
    delta = bound(44) - bound(40)
    assert (growth, delta) == (17, 11)
    assert growth > delta
    assert growth <= delta + bound(40) - h(3, 15)


@pytest.mark.parametrize('outside,inside', [(2, 2), (2, 4), (4, 2)])
def test_lift_and_repair_has_independently_valid_witnesses(outside, inside):
    old = C['compose'](C['ladder'](outside), C['ladder'](inside))
    new = C['compose'](C['ladder'](outside), C['ladder'](inside + 2))
    assert V['check'](old)['separating'] and V['check'](new)['separating']
    result = L['lift_and_repair'](old, new)
    lifts = [V['decode'](c) for c in result['lift_cycles']]
    repairs = [V['decode'](c) for c in result['repair_cycles']]
    graph = V['decode'](new['output_edges'])
    universe = V['global_universe'](graph)
    assert set(lifts + repairs) <= universe
    assert len(V['requirements'](graph, lifts + repairs)) == len(graph) * (len(graph) - 1)
    # Independently compare incidence on every unchanged exterior edge and cut label.
    outside_edges = set(map(tuple, old['graphs'][0]))
    def signature(record, c):
        return c & outside_edges, tuple(tuple(e) in c for e in record['cut_edges'])
    for c in map(V['decode'], old['reduced_cycles']):
        assert any(signature(old, c) == signature(new, d) for d in lifts)
    assert result['upper_bound'] <= result['old_count'] + len(repairs)


def test_missing_lifts_are_not_assumed_to_exist():
    old = C['compose'](C['ladder'](2), C['ladder'](2))
    new = C['compose'](C['ladder'](2), C['ladder'](4))
    new['reduced_cycles'] = []
    with pytest.raises(ValueError, match='no compatible lift'):
        L['lift_and_repair'](old, new)


def test_nonseparating_source_cannot_start_induction():
    old = C['compose'](C['ladder'](3), C['ladder'](2))
    new = C['compose'](C['ladder'](3), C['ladder'](4))
    with pytest.raises(ValueError, match='old family is not separating'):
        L['lift_and_repair'](old, new)
