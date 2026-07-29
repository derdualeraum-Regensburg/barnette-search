"""Unit tests for exhaustive same-face edge-flexibility analysis."""

from dataclasses import asdict
from pathlib import Path

import networkx as nx

from barnette_search.edge_flexibility import analyze_same_face_edge_flexibility
from barnette_search.hamiltonian import verify_hamiltonian_cycle


def _embedding(graph: nx.Graph) -> nx.PlanarEmbedding:
    planar, embedding = nx.check_planarity(graph)
    assert planar
    return embedding


def _edge_keys(cycle: tuple[object, ...]) -> set[frozenset[object]]:
    return {
        frozenset((left, right)) for left, right in zip(cycle, cycle[1:])
    }


def test_greedy_cover_certifies_every_cube_pair(tmp_path: Path) -> None:
    graph = nx.cubical_graph()
    result = analyze_same_face_edge_flexibility(
        graph,
        _embedding(graph),
        candidate_output_directory=tmp_path,
    )
    assert result.complete_property_holds
    assert not result.candidate_requires_review
    assert result.total_ordered_same_face_edge_pairs == 72
    assert result.number_of_sat_calls < result.total_ordered_same_face_edge_pairs
    assert result.number_of_distinct_witness_cycles == result.number_of_sat_calls
    assert result.backtracking_queries == 72
    assert result.backtracking_agreements == 72
    assert all(record.witness_certificate_hash for record in result.pair_records)

    witnesses = {
        witness.certificate_hash: witness for witness in result.witnesses
    }
    for record in result.pair_records:
        witness = witnesses[record.witness_certificate_hash]
        assert verify_hamiltonian_cycle(graph, witness.cycle)
        selected = _edge_keys(witness.cycle)
        assert frozenset(record.required_edge) in selected
        assert frozenset(record.forbidden_edge) not in selected


def test_ordered_pairs_are_distinct_and_multiface_occurrences_deduplicate(
    tmp_path: Path,
) -> None:
    graph = nx.cycle_graph(4)
    result = analyze_same_face_edge_flexibility(
        graph,
        _embedding(graph),
        cross_check_backtracking=False,
        candidate_output_directory=tmp_path,
    )
    assert result.total_ordered_same_face_edge_pairs == 12
    records = {
        (record.required_edge, record.forbidden_edge): record
        for record in result.pair_records
    }
    assert ((0, 1), (1, 2)) in records
    assert ((1, 2), (0, 1)) in records
    assert records[((0, 1), (1, 2))].face_indices == (0, 1)


def test_unsatisfiable_pair_saves_review_evidence(tmp_path: Path) -> None:
    graph = nx.cycle_graph(4)
    result = analyze_same_face_edge_flexibility(
        graph,
        _embedding(graph),
        cross_check_backtracking=False,
        candidate_output_directory=tmp_path,
    )
    assert not result.complete_property_holds
    assert result.candidate_requires_review
    assert result.failed_ordered_pair is not None
    candidate = Path(result.candidate_report_directory)
    assert (candidate / "graph_and_embedding.json").is_file()
    assert (candidate / "primary_constrained.cnf").is_file()
    assert (candidate / "independent_constrained.cnf").is_file()
    report = (candidate / "candidate_report.json").read_text(encoding="utf-8")
    assert "manual review required" in report
    assert "MiniSat22" in report


def test_witness_cover_is_deterministic_except_for_timings(tmp_path: Path) -> None:
    graph = nx.cubical_graph()
    embedding = _embedding(graph)
    first = analyze_same_face_edge_flexibility(
        graph,
        embedding,
        cross_check_backtracking=False,
        candidate_output_directory=tmp_path / "first",
    )
    second = analyze_same_face_edge_flexibility(
        graph,
        embedding,
        cross_check_backtracking=False,
        candidate_output_directory=tmp_path / "second",
    )
    assert first.pair_records == second.pair_records
    assert first.witnesses == second.witnesses
    assert [
        (call.required_edge, call.forbidden_edge, call.satisfiable)
        for call in first.sat_calls
    ] == [
        (call.required_edge, call.forbidden_edge, call.satisfiable)
        for call in second.sat_calls
    ]
    first_data = asdict(first)
    second_data = asdict(second)
    for key in (
        "total_sat_time_seconds",
        "maximum_single_query_sat_time_seconds",
        "backtracking_runtime_seconds",
        "sat_calls",
    ):
        first_data.pop(key)
        second_data.pop(key)
    assert first_data == second_data
