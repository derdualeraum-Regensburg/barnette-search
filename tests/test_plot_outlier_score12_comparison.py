import sys
from pathlib import Path

TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from plot_outlier_score12_comparison import (  # noqa: E402
    ComparisonError,
    crossing_pairs,
    face_category,
    find_best_disjoint_pair,
    parse_planar_draw,
    planar_code_to_ascii,
)


def test_planar_code_to_ascii_converts_one_complete_record() -> None:
    payload = b">>planar_code<<" + bytes([3, 2, 3, 0, 1, 3, 0, 1, 2, 0])
    assert planar_code_to_ascii(payload) == b"3 2 3 0 1 3 0 1 2 0\n"


def test_planar_code_to_ascii_rejects_incomplete_record() -> None:
    payload = b">>planar_code<<" + bytes([3, 2, 3, 0, 1, 3, 0])
    try:
        planar_code_to_ascii(payload)
    except ComparisonError:
        return
    raise AssertionError("expected ComparisonError")


def test_parse_planar_draw_extracts_positions_and_edges() -> None:
    tex = (
        "\\begin{tikzpicture}\n"
        "\\node [style] (1) at (0.0,0.0) {};\n"
        "\\node [style] (2) at (1.5,2.5) {};\n"
        "\\draw [style] (1) to (2);\n"
        "\\end{tikzpicture}\n"
    )
    positions, edges = parse_planar_draw(tex)
    assert positions == {0: (0.0, 0.0), 1: (1.5, 2.5)}
    assert edges == [(0, 1)]


def test_crossing_pairs_detects_a_genuine_crossing() -> None:
    positions = {0: (0.0, 0.0), 1: (1.0, 1.0), 2: (0.0, 1.0), 3: (1.0, 0.0)}
    edges = [(0, 1), (2, 3)]
    assert crossing_pairs(positions, edges) == [((0, 1), (2, 3))]


def test_crossing_pairs_ignores_non_crossing_edges() -> None:
    positions = {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (0.0, 1.0), 3: (1.0, 1.0)}
    edges = [(0, 1), (2, 3)]
    assert crossing_pairs(positions, edges) == []


def test_find_best_disjoint_pair_matches_recorded_lengths() -> None:
    strips = [
        {"faces": [0, 1], "length": 2},
        {"faces": [2, 3], "length": 2},
        {"faces": [4], "length": 1},
    ]
    assert find_best_disjoint_pair(strips, 2, 2) == (0, 1)


def test_find_best_disjoint_pair_raises_when_no_match_exists() -> None:
    strips = [{"faces": [0], "length": 1}, {"faces": [1], "length": 1}]
    try:
        find_best_disjoint_pair(strips, 3, 3)
    except ComparisonError:
        return
    raise AssertionError("expected ComparisonError")


def test_face_category_prefers_best_pair_over_generic_strip() -> None:
    graph = {
        "strips": [{"faces": [0, 1]}, {"faces": [2, 3]}, {"faces": [4, 5]}],
        "best_pair_indices": (0, 1),
        "parameters": {"quadrilateral_adjacency_component_types": []},
    }
    assert face_category(0, graph) == "best_a"
    assert face_category(2, graph) == "best_b"
    assert face_category(4, graph) == "other_strip"


def test_face_category_reports_isolated_and_branch_components() -> None:
    graph = {
        "strips": [{"faces": [0, 1]}, {"faces": [2, 3]}],
        "best_pair_indices": (0, 1),
        "parameters": {
            "quadrilateral_adjacency_component_types": [
                {"type": "isolated", "faces": [9]},
                {"type": "branch", "faces": [10, 11]},
            ]
        },
    }
    assert face_category(9, graph) == "isolated"
    assert face_category(10, graph) == "branch_or_cycle"
