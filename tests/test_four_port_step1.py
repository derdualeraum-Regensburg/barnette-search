"""Exact small-case certificates and rejection of damaged proof objects."""
import copy
import json
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[1] / 'artifacts' / 'four_port_step1_20260917'
V = runpy.run_path(str(ROOT / 'verify.py'))


def certificate(index=2):
    return json.loads((ROOT / f'certificate_{index:02}.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('index', [2, 10, 13, 21])
def test_exact_certificates_and_rectangle_obstruction(index):
    result = V['check'](certificate(index))
    assert (result['upper'], result['lower'], result['minimum_with_state_union_rectangles']) == (12, 12, 13)
    assert result['isomorphic_to'] == 'D(3,3)'
    assert result['unique_minimum_family']


def test_one_entire_state_block_is_removed():
    record = certificate()
    counts = sorted((b['a'] * b['b'], b['selected_count']) for b in record['blocks'])
    assert counts == [(1, 0), (1, 1), (1, 1), (1, 1), (1, 1), (9, 8)]
    big = next(b for b in record['blocks'] if b['a'] == 3)
    assert (big['p_min'], big['q_min']) == (2, 2)
    assert big['cycle_index_matrix'] == [[2, 3, 4], [5, 6, 7], [8, 9, 10]]
    assert record['omitted_indices'] == [1, 6]
    local = [frozenset(tuple(e) for e in record['cycles'][i] if e[1] < 8)
             for i in (2, 5, 8)]
    assert all(len(f) == 6 for f in local)
    assert len(frozenset().union(*local)) == 10


@pytest.mark.parametrize('omitted', [1, 6])
def test_deleted_cycle_requirements_survive_simultaneous_deletion(omitted):
    record = certificate()
    graph = V['decode'](record['graph_edges'])
    cycles = [V['decode'](c) for c in record['cycles']]
    kept = [cycles[i] for i in record['selected_indices']]
    assert V['coverage'](graph, [cycles[omitted]]) <= V['coverage'](graph, kept)


def test_incomplete_cycle_universe_rejected():
    record = certificate()
    record['cycles'].pop()
    with pytest.raises(ValueError, match='universe is incomplete'):
        V['check'](record)


def test_missing_mandatory_cycle_rejected():
    record = certificate()
    record['selected_indices'].remove(0)
    with pytest.raises(ValueError, match='upper certificate fails'):
        V['check'](record)


def test_false_private_requirement_rejected():
    record = certificate()
    record['private_requirements'][0]['requirement'] = copy.deepcopy(record['private_requirements'][1]['requirement'])
    with pytest.raises(ValueError, match='does not force'):
        V['check'](record)


def test_false_local_union_cover_minimum_rejected():
    record = certificate()
    next(b for b in record['blocks'] if b['a'] == 3)['p_min'] = 1
    with pytest.raises(ValueError, match='union-cover optimum'):
        V['check'](record)


def test_false_rectangle_minimum_rejected():
    record = certificate()
    record['claim']['minimum_with_state_union_rectangles'] = 12
    with pytest.raises(ValueError, match='rectangle minimum claim'):
        V['check'](record)


def test_inadequate_replacement_family_rejected():
    record = certificate()
    record['replacement_covers'][0]['witness_indices'] = [0]
    with pytest.raises(ValueError, match='replacement loses'):
        V['check'](record)


def test_false_isomorphism_rejected():
    record = certificate()
    mapping = record['double_ladder_33_map']
    mapping[0], mapping[1] = mapping[1], mapping[0]
    with pytest.raises(ValueError, match='isomorphism certificate fails'):
        V['check'](record)


def test_changed_graph6_edge_rejected():
    record = certificate()
    old = record['graph6_labelled']
    record['graph6_labelled'] = old[:-1] + chr(((ord(old[-1]) - 63) ^ 1) + 63)
    with pytest.raises(ValueError, match='graph6 disagrees'):
        V['check'](record)
