"""Explicit proof rules for square-reserve preservation."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'artifacts/reserve_closure_20260918'
V = runpy.run_path(str(ROOT / 'check.py'))
CASES = json.loads(gzip.decompress((ROOT.parent / 'reserve_induction_20260918/certificates.json.gz').read_bytes()))


def test_complete_local_proof_table():
    result = V['local_checks']()
    assert result == {'old_states': 6, 'new_covers': 8, 'new_square_local_requirements': 36,
                      'forcing_rules': 6, 'symbolic_rules_passed': True}


@pytest.mark.parametrize('record', CASES, ids=lambda r: r['name'])
def test_explicit_general_witness_rules_on_certified_graph(record):
    counts = V['regression'](record)
    assert counts['new-local'] == 36
    assert all(counts[k] > 0 for k in ('new-exterior', 'retained-old', 'retained-new'))
    graph = set(map(tuple, record['new_edges']))
    cycles = [frozenset(map(tuple, c)) for c in record['new_cycles']]
    family = {cycles[i] for i in record['available_lift_indices']}
    core = {cycles[i] for i in record['budget_selected_indices']}
    faces = V['trace'](record['new_rotation'])
    reserve = V['compress_reserve'](graph, faces, family, core)
    n = len(record['new_rotation'])
    squares = [face for face in faces if len(face) == 4]
    assert reserve <= family and not reserve & core
    assert len(reserve) <= 2 * len(squares) * (n - 1) <= (n + 4) * (n - 1)
    for face in squares:
        sides = [tuple(sorted((face[i], face[(i + 1) % 4]))) for i in range(4)]
        for i in (0, 1):
            for f in graph - set(sides):
                assert any({sides[i], sides[i + 2]} <= c and f not in c for c in core | reserve)


def test_missing_special_variant_rejected():
    table = deepcopy(V['TABLE'])
    table['cd'].pop()
    with pytest.raises(ValueError, match='new cover mismatch'):
        V['local_checks'](table)


def test_extra_local_edge_rejected():
    table = deepcopy(V['TABLE'])
    table['abc'][0].add('d')
    with pytest.raises(ValueError, match='new cover mismatch'):
        V['local_checks'](table)


def test_wrong_parent_rejected():
    record = deepcopy(CASES[0])
    record['new_parent_indices'] = [0] * len(record['new_cycles'])
    with pytest.raises(ValueError, match='symbolic witness implication fails'):
        V['regression'](record)


def test_wrong_proxy_rejected(monkeypatch):
    monkeypatch.setitem(V['PROXY'], 'up', 'b')
    with pytest.raises(ValueError, match='avoidance proxy'):
        V['local_checks']()


def test_reserve_compression_counting_on_every_local_state():
    for old in V['TABLE']:
        assert 4 - len(old) <= 2
    for n in range(8, 101, 2):
        external = 3 * n // 2 - 4
        initially_avoided_at_least = n // 2 - 2
        assert 1 + external - initially_avoided_at_least == n - 1
        assert 2 * (n // 2 + 2) * (n - 1) == (n + 4) * (n - 1)


def test_compression_rejects_unavailable_core():
    with pytest.raises(ValueError, match='core not in available family'):
        V['compress_reserve'](set(), [], [], [frozenset({(0, 1)})])


def test_compression_rejects_absent_joint_witness():
    with pytest.raises(ValueError, match='no joint witness'):
        V['compress_reserve'](V['face_edges']([0, 1, 2, 3]), [[0, 1, 2, 3]], [], [])
