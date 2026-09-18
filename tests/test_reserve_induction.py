"""Reserve witnesses and bounded induction certificates, including corruptions."""
from copy import deepcopy
from itertools import combinations
import gzip
import json
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'artifacts/reserve_induction_20260918'
V = runpy.run_path(str(ROOT / 'verify.py'))
A = runpy.run_path(str(ROOT / 'analyze.py'))
CASES = json.loads(gzip.decompress((ROOT / 'certificates.json.gz').read_bytes()))
INPUTS = json.loads((ROOT / 'inputs.json').read_bytes())['graphs']


@pytest.mark.parametrize('record', CASES, ids=lambda r: r['name'])
def test_independent_reserve_certificate(record):
    result = V['verify_reserve'](record)
    assert result['closure_missing'] == 0
    assert result['universal_closure_obstructions'] == 0
    assert result['next_reserve_from_available']
    if result['old_order'] >= 16 and result['old_order'] % 4 == 0:
        assert result['budget_core_upper'] <= result['target_B']


@pytest.mark.parametrize('source', INPUTS)
def test_preserved_graph6_and_planar_code(source):
    V['check_source'](source)


def with_reserve():
    return deepcopy(next(c for c in CASES if c['source_reserve_indices']))


def test_missing_source_reserve_rejected():
    record = with_reserve()
    record['source_reserve_indices'] = []
    with pytest.raises(ValueError, match='source reserve fails'):
        V['verify_reserve'](record)


def test_false_closure_obstruction_rejected():
    record = deepcopy(CASES[0])
    record['closure_missing'] = [[record['new_edges'][0]] * 3]
    with pytest.raises(ValueError, match='closure deficit mismatch'):
        V['verify_reserve'](record)


def test_unavailable_lift_inventory_rejected():
    record = with_reserve()
    record['available_lift_indices'].pop()
    with pytest.raises(ValueError, match='reservoir lift inventory mismatch'):
        V['verify_reserve'](record)


def test_missing_next_reserve_rejected():
    record = deepcopy(next(c for c in CASES if c['next_reserve_indices']))
    record['next_reserve_indices'] = []
    with pytest.raises(ValueError, match='next reserve fails'):
        V['verify_reserve'](record)


def test_empty_budget_core_rejected():
    record = deepcopy(CASES[0])
    record['budget_selected_indices'] = []
    with pytest.raises(ValueError, match='budget core fails'):
        V['verify_reserve'](record)


def test_greedy_budget_miss_is_repaired_by_feasible_selection():
    record = next(c for c in CASES if c['name'] == 'g03_f05_o1')
    assert len(record['selected_indices']) == 18
    assert len(record['budget_selected_indices']) == 17
    assert V['verify_reserve'](record)['budget_core_upper'] == 17


def test_every_joint_parent_has_a_simultaneous_rung_lift():
    old = A['A']['local_families'](2)
    new = A['A']['local_families'](4)
    for state, covers in old.items():
        if {(0, 2), (1, 3)} <= covers[0]:
            assert any({(1, 5), (2, 6)} <= cover for cover in new[state])


def test_reserve_constructor_reports_impossible_requirements():
    required = {((0, 1), (2, 3), (4, 5))}
    chosen, missing = A['reserve'](required, [], [frozenset({(0, 1)})])
    assert chosen == [] and missing == required


def test_labelled_source_coverage_has_both_orientations():
    for i, source in enumerate(INPUTS):
        count = sum(len(f) == 4 for f in source['graph']['faces'])
        assert sum(c['input_index'] == i for c in CASES) == 2 * count


def test_graph6_tampering_rejected():
    source = deepcopy(INPUTS[0])
    source['graph']['graph6'] = source['graph']['graph6'][:-1] + '?'
    with pytest.raises(ValueError, match='source graph6'):
        V['check_source'](source)


def test_false_universal_obstruction_rejected():
    record = deepcopy(CASES[0])
    record['universal_closure_obstructions'] = [[record['new_edges'][0]] * 3]
    with pytest.raises(ValueError, match='universal closure mismatch'):
        V['verify_reserve'](record)


def test_support_implication_criterion_against_all_small_families():
    subsets = [{i for i in range(3) if mask & (1 << i)} for mask in range(8)]
    for size in (1, 2, 3):
        for supports in combinations(subsets[1:], size):
            for target in subsets:
                universal = all(bool(family & target) for family in subsets
                                if all(family & support for support in supports))
                assert universal == any(support <= target for support in supports)


def test_universal_checker_detects_no_target_witnesses():
    record = CASES[0]
    old = V['decode'](record['old_edges'])
    faces = V['barnette'](old, record['old_rotation'])
    universe = [V['decode'](c) for c in record['old_cycles']]
    required = V['reserve_requirements'](old, faces)
    assert required
    assert V['universal_obstructions'](old, faces, universe, [], [], required) == required
