"""Focused tests for the structural double-ladder packing construction."""

from pathlib import Path

from barnette_search.double_ladder_packing import (
    canonical_structural_packing,
    load_chain,
    packing_formula,
    packing_summary,
)


SEQUENCE_ROOT = Path(r"E:\barnette-results\barnie-sequence")
PREDICTION_ROOT = Path(r"E:\barnette-results\double-ladder-prediction-test")


def test_packing_formula_values_and_increments() -> None:
    assert packing_formula(9, 7) == 49
    assert packing_formula(9, 9) == 60
    assert packing_formula(11, 9) == 71
    assert packing_formula(11, 11) == 84
    assert packing_formula(9, 9) - packing_formula(9, 7) == 11
    assert packing_formula(11, 9) - packing_formula(9, 9) == 11
    assert packing_formula(11, 11) - packing_formula(11, 9) == 13


def test_structural_packings_against_certified_cycle_universes() -> None:
    if not (SEQUENCE_ROOT.exists() and PREDICTION_ROOT.exists()):
        return
    for dataset in load_chain(SEQUENCE_ROOT, PREDICTION_ROOT):
        packing = canonical_structural_packing(dataset)
        summary = packing_summary(dataset, packing)
        assert summary["packing_size"] == packing_formula(dataset.a, dataset.b)
        assert summary["coverage_sets_pairwise_disjoint"]
        assert summary["exception_singleton_count"] == 4
        assert summary["boundary_turn_singleton_count"] == 2 * dataset.a + 2 * dataset.b - 4
        assert summary["all_doubletons_are_adjacent_turn_dominoes"]
        assert summary["uncovered_cycle_classes"] == [
            "R",
            f"T({dataset.a - 2},{dataset.b - 2})",
        ]
