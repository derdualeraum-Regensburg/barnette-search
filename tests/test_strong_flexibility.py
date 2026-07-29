"""Deterministic unit tests for both stronger flexibility properties."""

from dataclasses import asdict
from pathlib import Path

import networkx as nx
import pytest

import barnette_search.flexibility_common as common
from barnette_search.all_edge_flexibility import (
    analyze_all_edge_pair_flexibility,
)
from barnette_search.hamiltonian import verify_hamiltonian_cycle
from barnette_search.three_edge_path_flexibility import (
    analyze_three_edge_path_flexibility,
    enumerate_three_edge_paths,
)


def _selected(cycle: tuple[object, ...]) -> set[frozenset[object]]:
    return {
        frozenset((left, right)) for left, right in zip(cycle, cycle[1:])
    }


def _logical_result(result: object) -> dict[str, object]:
    value = asdict(result)
    for field in tuple(value):
        if "time" in field or field.startswith("hardest_"):
            value.pop(field)
    return value


def test_all_ordered_edge_pairs_are_unique_and_separately_oriented(
    tmp_path: Path,
) -> None:
    graph = nx.cubical_graph()
    result = analyze_all_edge_pair_flexibility(
        graph,
        retain_pair_details=True,
        retain_witness_cycles=True,
        candidate_output_directory=tmp_path,
    )
    assert result.total_ordered_edge_pairs == 12 * 11
    assert result.property_satisfied
    assert result.number_of_constrained_sat_calls < result.total_ordered_edge_pairs
    assert result.pair_details is not None
    keys = [detail.key for detail in result.pair_details]
    assert len(keys) == len(set(keys))
    assert (((0, 1), (0, 3))) in keys
    assert (((0, 3), (0, 1))) in keys

    assert result.witnesses is not None
    witnesses = {
        witness.certificate_hash: witness.cycle for witness in result.witnesses
    }
    for detail in result.pair_details:
        cycle = witnesses[detail.witness_certificate_hash]
        assert cycle is not None and verify_hamiltonian_cycle(graph, cycle)
        selected = _selected(cycle)
        assert frozenset(detail.required_edges[0]) in selected
        assert frozenset(detail.forbidden_edges[0]) not in selected


def test_all_edge_cover_is_deterministic_and_supports_noninteger_labels(
    tmp_path: Path,
) -> None:
    labels = {node: f"vertex-{10 * node + 3}" for node in nx.cubical_graph()}
    graph = nx.relabel_nodes(nx.cubical_graph(), labels)
    first = analyze_all_edge_pair_flexibility(
        graph, retain_pair_details=True, candidate_output_directory=tmp_path / "a"
    )
    second = analyze_all_edge_pair_flexibility(
        graph, retain_pair_details=True, candidate_output_directory=tmp_path / "b"
    )
    assert _logical_result(first) == _logical_result(second)


def test_all_edge_unsat_fixture_writes_independent_evidence(tmp_path: Path) -> None:
    result = analyze_all_edge_pair_flexibility(
        nx.cycle_graph(4), candidate_output_directory=tmp_path
    )
    assert not result.property_satisfied
    assert result.candidate_requires_review
    report = Path(result.candidate_report_path)
    assert (report / "primary_constrained.cnf").is_file()
    assert (report / "minisat22_constrained.cnf").is_file()
    assert (report / "graph_embedding_and_labels.json").is_file()
    assert "manual review" in (report / "candidate_report.json").read_text(
        encoding="utf-8"
    )


def test_three_edge_paths_are_simple_canonical_and_reverse_deduplicated() -> None:
    graph = nx.cycle_graph(4)
    paths = enumerate_three_edge_paths(graph)
    assert len(paths) == 4
    assert len(paths) == len(set(paths))
    assert all(len(set(path)) == 4 for path in paths)
    assert all(tuple(reversed(path)) not in paths or tuple(reversed(path)) == path for path in paths)


def test_three_edge_path_witnesses_enforce_middle_and_outer_edges(
    tmp_path: Path,
) -> None:
    graph = nx.cubical_graph()
    result = analyze_three_edge_path_flexibility(
        graph,
        retain_path_details=True,
        retain_witness_cycles=True,
        candidate_output_directory=tmp_path,
    )
    assert result.number_of_distinct_three_edge_paths == 48
    assert result.property_satisfied
    assert result.number_of_constrained_sat_calls < 48
    assert result.path_details is not None and result.witnesses is not None
    witnesses = {
        witness.certificate_hash: witness.cycle for witness in result.witnesses
    }
    for detail in result.path_details:
        cycle = witnesses[detail.witness_certificate_hash]
        assert cycle is not None and verify_hamiltonian_cycle(graph, cycle)
        selected = _selected(cycle)
        assert frozenset(detail.required_edges[0]) in selected
        assert all(frozenset(edge) not in selected for edge in detail.forbidden_edges)


def test_three_edge_path_cover_is_deterministic(tmp_path: Path) -> None:
    graph = nx.cubical_graph()
    first = analyze_three_edge_path_flexibility(
        graph, retain_path_details=True, candidate_output_directory=tmp_path / "a"
    )
    second = analyze_three_edge_path_flexibility(
        graph, retain_path_details=True, candidate_output_directory=tmp_path / "b"
    )
    assert _logical_result(first) == _logical_result(second)


def test_three_edge_path_unsat_fixture_writes_review(tmp_path: Path) -> None:
    result = analyze_three_edge_path_flexibility(
        nx.cycle_graph(4), candidate_output_directory=tmp_path
    )
    assert not result.property_satisfied
    assert result.candidate_requires_review
    assert Path(result.candidate_report_path).is_dir()


def test_invalid_certificate_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(common, "verify_hamiltonian_cycle", lambda graph, cycle: False)
    with pytest.raises(RuntimeError, match="independent verification"):
        analyze_three_edge_path_flexibility(
            nx.cubical_graph(), candidate_output_directory=tmp_path
        )
