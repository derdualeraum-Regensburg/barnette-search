import sys
from pathlib import Path

TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from plot_hsep_ladder_metrics import (  # noqa: E402
    compute_residuals,
    deterministic_jitter,
    filter_order,
    load_rows,
    residual,
)


def _row(**overrides):
    base = {
        "canonical_graph_hash": "hash0",
        "graph_order": 24,
        "exact_hsep": 10,
        "ladder_max": 3,
        "double_ladder_score": 7.5,
        "best_disjoint_ladder_a": 3,
        "best_disjoint_ladder_b": 2,
        "best_disjoint_pair_exists": True,
    }
    base.update(overrides)
    return base


def test_filter_order_selects_only_matching_order_with_hsep_present() -> None:
    rows = [
        _row(canonical_graph_hash="a", graph_order=24),
        _row(canonical_graph_hash="b", graph_order=20),
        _row(canonical_graph_hash="c", graph_order=24, exact_hsep=None),
    ]
    assert [row["canonical_graph_hash"] for row in filter_order(rows, 24)] == ["a"]


def test_residual_is_none_without_disjoint_pair() -> None:
    assert residual(_row(double_ladder_score=None)) is None


def test_residual_computes_signed_difference() -> None:
    assert residual(_row(exact_hsep=10, double_ladder_score=7.5)) == 2.5


def test_compute_residuals_preserves_order_and_none_entries() -> None:
    rows = [_row(exact_hsep=10, double_ladder_score=7.5), _row(double_ladder_score=None)]
    assert compute_residuals(rows) == [2.5, None]


def test_deterministic_jitter_spreads_overlapping_points_symmetrically_around_zero() -> None:
    rows = [
        _row(canonical_graph_hash="bbb", double_ladder_score=5.0, exact_hsep=10),
        _row(canonical_graph_hash="aaa", double_ladder_score=5.0, exact_hsep=10),
        _row(canonical_graph_hash="ccc", double_ladder_score=5.0, exact_hsep=10),
    ]
    offsets = deterministic_jitter(rows, "double_ladder_score", "exact_hsep", step=0.1)
    assert offsets == {"aaa": -0.1, "bbb": 0.0, "ccc": 0.1}


def test_deterministic_jitter_is_zero_for_unique_points() -> None:
    rows = [_row(canonical_graph_hash="x", double_ladder_score=1.0, exact_hsep=2)]
    assert deterministic_jitter(rows, "double_ladder_score", "exact_hsep") == {"x": 0.0}


def test_deterministic_jitter_does_not_mix_distinct_overlap_groups() -> None:
    rows = [
        _row(canonical_graph_hash="a", double_ladder_score=1.0, exact_hsep=2),
        _row(canonical_graph_hash="b", double_ladder_score=1.0, exact_hsep=2),
        _row(canonical_graph_hash="c", double_ladder_score=3.0, exact_hsep=9),
    ]
    offsets = deterministic_jitter(rows, "double_ladder_score", "exact_hsep")
    assert offsets["c"] == 0.0
    assert offsets["a"] != offsets["b"]


def test_deterministic_jitter_is_repeatable_across_calls() -> None:
    rows = [
        _row(canonical_graph_hash="bbb", double_ladder_score=5.0, exact_hsep=10),
        _row(canonical_graph_hash="aaa", double_ladder_score=5.0, exact_hsep=10),
    ]
    first = deterministic_jitter(rows, "double_ladder_score", "exact_hsep")
    second = deterministic_jitter(rows, "double_ladder_score", "exact_hsep")
    assert first == second


def test_load_rows_parses_optional_and_boolean_fields(tmp_path: Path) -> None:
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text(
        "canonical_graph_hash,graph_order,exact_hsep,ladder_max,double_ladder_score,"
        "best_disjoint_ladder_a,best_disjoint_ladder_b,best_disjoint_pair_exists\n"
        "abc,24,10,0,,,,False\n",
        encoding="utf-8",
    )
    [row] = load_rows(csv_path)
    assert row["graph_order"] == 24
    assert row["exact_hsep"] == 10
    assert row["ladder_max"] == 0
    assert row["double_ladder_score"] is None
    assert row["best_disjoint_ladder_a"] is None
    assert row["best_disjoint_pair_exists"] is False
