import networkx as nx
import pytest

from barnette_search.ladder_analysis import double_ladder_graph
from barnette_search.ladder_structure_metrics import (
    _is_simple_chordfree_cycle,
    _maximal_valid_windows,
    compute_ladder_parameters,
)


def _rotation(graph: nx.Graph) -> tuple[tuple[int, ...], ...]:
    graph = nx.convert_node_labels_to_integers(graph, ordering="sorted")
    planar, embedding = nx.check_planarity(graph)
    assert planar
    return tuple(
        tuple(embedding.neighbors_cw_order(vertex))
        for vertex in range(graph.number_of_nodes())
    )


# Three unit squares in a row (I-tromino): entry/exit edges at the middle
# square are opposite, so the strip runs straight through as one strip.
_STRAIGHT_ROTATION = (
    (4, 1),
    (5, 2, 0),
    (6, 3, 1),
    (7, 2),
    (5, 0),
    (6, 1, 4),
    (7, 2, 5),
    (3, 6),
)

# Three unit squares in an L (L-tromino): at the middle square the edge
# shared with the first neighbor and the edge shared with the second
# neighbor are adjacent, not opposite, so the mandatory continuation rule
# splits this into two overlapping length-2 strips at the bend.
_BENT_ROTATION = (
    (3, 1),
    (4, 2, 0),
    (5, 1),
    (4, 0),
    (6, 5, 1, 3),
    (7, 2, 4),
    (7, 4),
    (5, 6),
)

# T-tetromino: a center square adjacent to left/right neighbors through
# opposite edges (a through-strip) and to a third neighbor through a
# perpendicular edge (a stub strip), both strips overlapping at the center.
_BRANCH_ROTATION = (
    (4, 1),
    (5, 2, 0),
    (6, 3, 1),
    (7, 2),
    (5, 0),
    (8, 6, 1, 4),
    (9, 7, 2, 5),
    (3, 6),
    (9, 5),
    (6, 8),
)

# Plus-pentomino: a center square whose two opposite-edge slots are both
# fully quad-adjacent, producing two crossing through-strips.
_CROSS_ROTATION = (
    (3, 1),
    (2, 0),
    (5, 10, 1, 3),
    (4, 2, 0, 8),
    (6, 5, 3, 9),
    (7, 11, 2, 4),
    (7, 4),
    (5, 6),
    (9, 3),
    (4, 8),
    (11, 2),
    (10, 5),
)


def test_straight_chain_forms_one_strip() -> None:
    result = compute_ladder_parameters(_STRAIGHT_ROTATION)
    assert result["face_count_4"] == 3
    assert result["strict_ladder_lengths_all"] == [3]
    assert result["ladder_max"] == 3
    assert result["ladder_strip_count"] == 1
    assert result["closed_ladder_strip_count"] == 0
    assert result["degenerate_closed_polychord_count"] == 0
    [component] = result["quadrilateral_adjacency_component_types"]
    assert component["type"] == "path"
    assert component["size"] == 3


def test_bent_chain_splits_into_two_overlapping_strips() -> None:
    result = compute_ladder_parameters(_BENT_ROTATION)
    assert result["face_count_4"] == 3
    assert result["strict_ladder_lengths_all"] == [2, 2]
    assert result["ladder_max"] == 2
    assert result["ladder_strip_count"] == 2
    [component] = result["quadrilateral_adjacency_component_types"]
    assert component["type"] == "path"
    assert component["size"] == 3
    strips = result["strict_ladder_strips"]
    faces_a, faces_b = strips[0]["faces"], strips[1]["faces"]
    assert faces_a != faces_b
    assert set(faces_a) & set(faces_b)


def test_branch_face_yields_through_strip_and_stub() -> None:
    result = compute_ladder_parameters(_BRANCH_ROTATION)
    assert result["face_count_4"] == 4
    assert result["strict_ladder_lengths_all"] == [3, 2]
    assert result["ladder_max"] == 3
    assert result["quadrilateral_adjacency_branch_vertex_count"] == 1
    [component] = result["quadrilateral_adjacency_component_types"]
    assert component["type"] == "branch"
    assert component["size"] == 4
    strips = result["strict_ladder_strips"]
    through = next(strip for strip in strips if strip["length"] == 3)
    stub = next(strip for strip in strips if strip["length"] == 2)
    assert set(through["faces"]) & set(stub["faces"])


def test_cross_face_yields_two_crossing_through_strips() -> None:
    result = compute_ladder_parameters(_CROSS_ROTATION)
    assert result["face_count_4"] == 5
    assert result["strict_ladder_lengths_all"] == [3, 3]
    assert result["ladder_max"] == 3
    strips = result["strict_ladder_strips"]
    assert len(strips) == 2
    assert set(strips[0]["faces"]) & set(strips[1]["faces"])
    assert strips[0]["faces"] != strips[1]["faces"]


def test_isolated_quadrilateral_is_reported_and_excluded_from_strips() -> None:
    result = compute_ladder_parameters(_BENT_ROTATION)
    assert result["isolated_quadrilateral_count"] == 0
    # The straight rotation's outer face is an octagon; no isolated quads there.
    straight = compute_ladder_parameters(_STRAIGHT_ROTATION)
    assert straight["isolated_quadrilateral_count"] == 0


def test_two_disjoint_ladders_are_reported_as_separate_components() -> None:
    rows = list(_STRAIGHT_ROTATION + tuple(tuple(n + 8 for n in row) for row in _STRAIGHT_ROTATION))
    row3 = list(rows[3])
    row3.insert(1, 11)
    rows[3] = tuple(row3)
    row11 = list(rows[11])
    row11.insert(1, 3)
    rows[11] = tuple(row11)
    result = compute_ladder_parameters(tuple(rows))
    assert result["face_count_4"] == 6
    assert result["strict_ladder_lengths_all"] == [3, 3]
    assert result["ladder_component_count"] == 2
    assert result["best_disjoint_ladder_a"] == 3
    assert result["best_disjoint_ladder_b"] == 3
    assert result["best_pair_contains_ladder_max"] is True
    assert result["double_ladder_score_times_2"] == (3 + 2) * (3 + 2) - 1
    assert result["double_ladder_score"] == ((3 + 2) * (3 + 2) - 1) / 2


def test_triangular_prism_gives_one_closed_three_face_strip() -> None:
    graph = nx.Graph()
    graph.add_edges_from([(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (0, 3), (1, 4), (2, 5)])
    result = compute_ladder_parameters(_rotation(graph))
    assert result["face_count_4"] == 3
    assert result["closed_ladder_strip_count"] == 1
    assert result["closed_ladder_strip_lengths"] == [3]
    assert result["degenerate_closed_polychord_count"] == 0
    assert result["strict_ladder_strips"] == []
    [component] = result["quadrilateral_adjacency_component_types"]
    assert component["type"] == "cycle"
    assert component["size"] == 3


def test_cube_gives_three_disjoint_closed_four_face_strips() -> None:
    result = compute_ladder_parameters(_rotation(nx.cubical_graph()))
    assert result["face_count_4"] == 6
    assert result["closed_ladder_strip_count"] == 3
    assert result["closed_ladder_strip_lengths"] == [4, 4, 4]
    assert result["degenerate_closed_polychord_count"] == 0
    assert result["strict_ladder_strips"] == []
    assert result["isolated_quadrilateral_count"] == 0


@pytest.mark.parametrize(
    ("first_length", "second_length"),
    [(3, 3), (5, 3), (5, 5), (7, 7)],
)
def test_double_ladder_scores_match_known_values(first_length: int, second_length: int) -> None:
    rotation = _rotation(double_ladder_graph(first_length, second_length))
    result = compute_ladder_parameters(rotation)
    expected_times_2 = (first_length + 2) * (second_length + 2) - 1
    assert result["double_ladder_score_times_2"] == expected_times_2
    assert result["double_ladder_score"] == expected_times_2 / 2
    assert sorted(result["strict_ladder_lengths_all"][:2], reverse=True) == sorted(
        (first_length, second_length), reverse=True
    )


def _relabel_rotation(
    rotation: tuple[tuple[int, ...], ...], permutation: dict[int, int]
) -> tuple[tuple[int, ...], ...]:
    new_rotation: list[tuple[int, ...]] = [()] * len(rotation)
    for old_vertex, row in enumerate(rotation):
        new_rotation[permutation[old_vertex]] = tuple(permutation[neighbor] for neighbor in row)
    return tuple(new_rotation)


def _invariant_fields(result: dict) -> dict:
    return {
        "face_count_4": result["face_count_4"],
        "component_signature": sorted(
            (component["size"], component["type"])
            for component in result["quadrilateral_adjacency_component_types"]
        ),
        "branch_vertex_count": result["quadrilateral_adjacency_branch_vertex_count"],
        "isolated_quadrilateral_count": result["isolated_quadrilateral_count"],
        "strict_ladder_lengths_all": sorted(result["strict_ladder_lengths_all"], reverse=True),
        "closed_ladder_strip_lengths": sorted(result["closed_ladder_strip_lengths"], reverse=True),
        "degenerate_closed_polychord_lengths": sorted(
            result["degenerate_closed_polychord_lengths"], reverse=True
        ),
        "ladder_face_coverage": result["ladder_face_coverage"],
        "ladder_face_fraction": result["ladder_face_fraction"],
        "ladder_max": result["ladder_max"],
        "ladder_strip_count": result["ladder_strip_count"],
        "ladder_component_count": result["ladder_component_count"],
        "best_disjoint_pair_exists": result["best_disjoint_pair_exists"],
        "best_disjoint_ladder_a": result["best_disjoint_ladder_a"],
        "best_disjoint_ladder_b": result["best_disjoint_ladder_b"],
        "best_pair_contains_ladder_max": result["best_pair_contains_ladder_max"],
        "double_ladder_score": result["double_ladder_score"],
        "double_ladder_score_times_2": result["double_ladder_score_times_2"],
    }


def test_relabeling_vertices_does_not_change_ladder_parameters() -> None:
    baseline = compute_ladder_parameters(_BENT_ROTATION)
    permutation = {index: (index + 3) % len(_BENT_ROTATION) for index in range(len(_BENT_ROTATION))}
    relabeled_rotation = _relabel_rotation(_BENT_ROTATION, permutation)
    relabeled = compute_ladder_parameters(relabeled_rotation)
    assert _invariant_fields(baseline) == _invariant_fields(relabeled)


def test_mirroring_embedding_does_not_change_ladder_parameters() -> None:
    baseline = compute_ladder_parameters(_BRANCH_ROTATION)
    mirrored_rotation = tuple(tuple(reversed(row)) for row in _BRANCH_ROTATION)
    mirrored = compute_ladder_parameters(mirrored_rotation)
    assert _invariant_fields(baseline) == _invariant_fields(mirrored)


def test_maximal_valid_windows_splits_on_repeated_face() -> None:
    windows = _maximal_valid_windows([10, 11, 10, 12], {})
    lengths = sorted(right - left + 1 for left, right in windows)
    assert lengths == [2, 3]


def test_maximal_valid_windows_splits_on_chord() -> None:
    plain_adjacency = {1: {4}, 4: {1}}
    windows = _maximal_valid_windows([1, 2, 3, 4], plain_adjacency)
    lengths = sorted(right - left + 1 for left, right in windows)
    assert lengths == [3, 3]


def test_is_simple_chordfree_cycle_detects_repeats_and_chords() -> None:
    assert _is_simple_chordfree_cycle([1, 2, 3], {}) is True
    assert _is_simple_chordfree_cycle([1, 2, 1, 3], {}) is False
    assert _is_simple_chordfree_cycle([1, 2, 3, 4], {1: {3}, 3: {1}}) is False
