"""Independent finite regression checks for the quantitative splice lemma."""
import copy
from itertools import permutations
from pathlib import Path
import runpy
import re

import pytest

ROOT = Path(__file__).parents[1] / "artifacts" / "splice_lemma_20260917"
C = runpy.run_path(str(ROOT / "construct.py"))
V = runpy.run_path(str(ROOT / "verify.py"))


def test_manuscript_cube_table_is_a_separating_family_in_each_stated_state():
    """Check the actual printed witnesses, including their omitted-port labels."""
    source = (ROOT.parents[1] / "paper" / "sections" / "quantitative_splice.tex").read_text(
        encoding="utf-8"
    )
    table = source.split("omitted edge at 0", 1)[1].split(r"\end{array}", 1)[0]
    rows = re.findall(r"0([134])&([0-7]{8}),\\quad([0-7]{8})", table)
    assert len(rows) == 3
    cycles = []
    for omitted, first, second in rows:
        for sequence in (first, second):
            vertices = list(map(int, sequence))
            assert sorted(vertices) == list(range(8))
            cycle = frozenset(
                tuple(sorted(pair))
                for pair in zip(vertices, vertices[1:] + vertices[:1])
            )
            assert (0, int(omitted)) not in cycle
            cycles.append(cycle)
    cube = frozenset(C["prism"](4))
    V["family_check"](cube, cycles)
    assert set(cycles) == V["cycles_by_matchings"](cube)


@pytest.mark.parametrize("left,right", [(4, 4), (4, 6), (6, 6), (8, 8)])
@pytest.mark.parametrize("permutation", tuple(permutations(range(3))))
def test_every_port_bijection(left, right, permutation):
    graph = C["prism"](right)
    ports = sorted(v for e in graph if 0 in e for v in e if v != 0)
    cert = C["compose"](C["prism"](left), graph, 0, 0, [ports[i] for i in permutation])
    result = V["check"](cert)
    assert result["verified"] and result["reduced_upper_bound"] <= result["product_upper_bound"]


def test_edge_cover_refinement_is_strict():
    cert = C["compose"](C["prism"](8), C["prism"](8), 0, 0)
    result = V["check"](cert)
    assert (result["product_upper_bound"], result["reduced_upper_bound"]) == (44, 40)


def test_state_subfamily_cannot_be_empty():
    cert = C["compose"](C["prism"](4), C["prism"](4), 0, 0)
    cert["state_cover_indices"][0][0] = ()
    with pytest.raises(ValueError, match="does not cover"):
        V["check"](cert)


def test_cycle_tampering_is_rejected():
    cert = copy.deepcopy(C["compose"](C["prism"](4), C["prism"](4), 0, 0))
    cert["reduced_cycles"][0] = cert["reduced_cycles"][0][1:]
    with pytest.raises(ValueError, match="invalid Hamiltonian"):
        V["check"](cert)


def test_nonseparating_hamiltonian_graph_is_rejected():
    k4 = tuple((a, b) for a in range(4) for b in range(a + 1, 4))
    with pytest.raises(ValueError, match="no Hamiltonian separating family"):
        C["compose"](k4, C["prism"](4), 0, 0)


def test_supplied_family_may_be_proper_subset_of_universe():
    graph = C["compose"](C["prism"](4), C["prism"](4), 0, 0)["output_edges"]
    family = list(C["cycles_by_paths"](graph))
    for cycle in tuple(family):
        candidate = [c for c in family if c != cycle]
        if C["separating"](graph, candidate):
            family = candidate
    assert len(family) < len(C["cycles_by_paths"](graph))
    cube = C["prism"](4)
    cert = C["compose"](graph, cube, 0, 0, supplied_families=[family, C["cycles_by_paths"](cube)])
    assert cert["input_universes_complete"] == [False, True]
    assert V["check"](cert)["verified"]
