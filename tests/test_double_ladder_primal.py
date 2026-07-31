"""Focused tests for the symbolic double-ladder separating family."""

from pathlib import Path

from barnette_search.double_ladder_prediction_test import connector_edges, cycle_edges
from barnette_search.double_ladder_primal import (
    antichain_analysis,
    direct_cycle_lift_map,
    edge_coordinate,
    family_formula,
    load_primal_chain,
    normalize_primal,
    primal_alignment,
    structural_lift,
    symbolic_antichain_check,
    symbolic_edge_incidence,
    symbolic_family_indices,
)


SEQUENCE_ROOT = Path(r"E:\barnette-results\barnie-sequence")
PREDICTION_ROOT = Path(r"E:\barnette-results\double-ladder-prediction-test")


def test_symbolic_antichain_on_representative_parameter_pairs() -> None:
    for a, b in ((3, 3), (5, 3), (9, 7), (11, 11), (15, 13)):
        result = symbolic_antichain_check(a, b)
        assert result["family_size"] == family_formula(a, b)
        assert result["distinct_signature_count"] == result["edge_count"]
        assert result["antichain"]


def test_immutable_primals_equal_symbolic_family_and_separate() -> None:
    if not (SEQUENCE_ROOT.exists() and PREDICTION_ROOT.exists()):
        return
    for dataset in load_primal_chain(SEQUENCE_ROOT, PREDICTION_ROOT):
        normalized = normalize_primal(dataset)
        assert normalized["exactly_equals_symbolic_family"]
        assert set(dataset.primal_indices) == set(symbolic_family_indices(dataset.graph))
        analysis = antichain_analysis(dataset.graph, dataset.primal_indices)
        assert analysis["all_signatures_distinct"]
        assert analysis["signatures_form_antichain"]
        assert analysis["ordered_requirements_covered"] == analysis[
            "ordered_edge_pair_requirement_count"
        ]


def test_symbolic_incidence_matches_all_selected_certified_cycles() -> None:
    if not (SEQUENCE_ROOT.exists() and PREDICTION_ROOT.exists()):
        return
    for dataset in load_primal_chain(SEQUENCE_ROOT, PREDICTION_ROOT):
        graph = dataset.graph
        cycle_keys = graph.cycle_keys
        connector_index = {
            edge: index for index, edge in enumerate(connector_edges(graph.graph))
        }
        for edge in graph.edges:
            coordinate = edge_coordinate(graph.graph, edge)
            if coordinate.kind == "connector":
                symbolic_edge = ("C", connector_index[edge])
            elif coordinate.kind == "rail":
                symbolic_edge = (
                    coordinate.ladder,
                    "rail",
                    coordinate.index,
                    coordinate.rail,
                )
            else:
                symbolic_edge = (coordinate.ladder, "rung", coordinate.index)
            for cycle_index in dataset.primal_indices:
                cycle_key = cycle_keys[cycle_index]
                assert (edge in cycle_edges(graph.cycles[cycle_index])) == symbolic_edge_incidence(
                    symbolic_edge, cycle_key, graph.a, graph.b
                )


def test_certified_square_insertions_have_expected_repair_and_increment_counts() -> None:
    if not (SEQUENCE_ROOT.exists() and PREDICTION_ROOT.exists()):
        return
    datasets = load_primal_chain(SEQUENCE_ROOT, PREDICTION_ROOT)
    for source, target, axis in zip(datasets, datasets[1:], ("B", "A", "B")):
        certificate = target.graph.graph_directory / "expansion_certificate.json"
        structural = structural_lift(source, target, axis)
        alignment = primal_alignment(source, target, certificate)
        expected = source.graph.a + 2 if axis == "B" else source.graph.b + 2
        assert structural["full_structural_nesting"]
        assert structural["new_target_cycle_count"] == expected
        assert alignment["literal_direct_geometric_lift_count"] == len(
            source.primal_indices
        ) - expected
        assert alignment["maximum_automorphism_aligned_direct_lift_count"] == alignment[
            "literal_direct_geometric_lift_count"
        ]
