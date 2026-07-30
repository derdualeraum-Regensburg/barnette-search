from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from time import sleep

import networkx as nx
import pytest

from barnette_search.independent_review import (
    ArtifactBundle,
    DEFAULT_SAMPLE_SEED,
    ReviewConstraint,
    _backtracking_with_timeout,
    _deterministic_metric_comparison,
    _escalate,
    _run_cover,
    deterministic_backtracking_indices,
    discover_artifacts,
    enumerate_all_edge_constraints,
    run_independent_review,
    validate_artifact_bundle,
)
from barnette_search.planar_code import (
    canonical_graph_hash,
    encode_planar_code,
    iter_planar_code,
)


def _cube_artifact(tmp_path: Path) -> tuple[ArtifactBundle, object]:
    graph = nx.cubical_graph()
    planar, embedding = nx.check_planarity(graph)
    assert planar
    rotation = tuple(
        tuple(embedding.neighbors_cw_order(vertex)) for vertex in graph.nodes()
    )
    planar_code = encode_planar_code(rotation)
    embedded = next(iter_planar_code(BytesIO(planar_code)))
    graph_hash = canonical_graph_hash(embedded)
    graph_directory = tmp_path / "graphs"
    graph_directory.mkdir(parents=True)
    planar_path = graph_directory / f"{graph_hash}.planar_code"
    embedding_path = graph_directory / f"{graph_hash}.embedding.json"
    report_path = graph_directory / f"{graph_hash}.txt"
    planar_path.write_bytes(planar_code)
    embedding_path.write_text(
        json.dumps(
            {
                "canonical_graph_hash": graph_hash,
                "rotation_system": embedded.rotation_system,
                "faces": embedded.faces,
                "face_size_multiset": embedded.face_size_multiset,
                "plantri_command": ["plantri", "-b", "-c3", "-d", "6", "-"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        f"Canonical graph hash: {graph_hash}\n"
        "Graph order: 8\n"
        "plantri command: plantri -b -c3 -d 6 -\n",
        encoding="utf-8",
    )
    bundle = ArtifactBundle(
        graph_hash=graph_hash,
        planar_code_paths=(str(planar_path),),
        embedding_paths=(str(embedding_path),),
        report_paths=(str(report_path),),
        leaderboard_categories=("all_edge_pairs:test:rank-1",),
        original_record={},
    )
    return bundle, embedded


def _original_edge_metrics(review: dict[str, object]) -> dict[str, object]:
    return {
        "total_ordered_edge_pairs": review["total_constraints"],
        "number_of_constrained_sat_calls": review["number_of_sat_calls"],
        "number_of_witness_cycles": review["number_of_witness_cycles"],
        "witness_cover_ratio": review["witness_cover_ratio"],
        "average_pairs_certified_per_witness": review[
            "average_constraints_per_witness"
        ],
        "maximum_pairs_certified_by_one_witness": review[
            "maximum_constraints_by_one_witness"
        ],
        "total_subtour_iterations": review["total_subtour_iterations"],
        "total_subtour_constraints": review["total_subtour_constraints"],
    }


def test_artifact_hash_validation_and_embedding_consistency(tmp_path: Path) -> None:
    bundle, embedded = _cube_artifact(tmp_path)
    decoded, status = validate_artifact_bundle(bundle)
    assert decoded.rotation_system == embedded.rotation_system
    assert status["canonical_hash_matches"]
    assert status["embedding_matches_graph"]

    path = Path(bundle.embedding_paths[0])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["rotation_system"][0].reverse()
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="rotation system"):
        validate_artifact_bundle(bundle)


def test_artifact_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    bundle, _ = _cube_artifact(tmp_path)
    invalid = ArtifactBundle(
        graph_hash="0" * 64,
        planar_code_paths=bundle.planar_code_paths,
        embedding_paths=bundle.embedding_paths,
        report_paths=bundle.report_paths,
        leaderboard_categories=bundle.leaderboard_categories,
        original_record={},
    )
    with pytest.raises(ValueError, match="canonical hash mismatch"):
        validate_artifact_bundle(invalid)


def test_deterministic_constraint_sampling() -> None:
    first = deterministic_backtracking_indices(
        100,
        graph_order=32,
        graph_hash="a" * 64,
        analysis_name="all_edge_pairs",
        hardest_index=42,
        seed=DEFAULT_SAMPLE_SEED,
    )
    second = deterministic_backtracking_indices(
        100,
        graph_order=32,
        graph_hash="a" * 64,
        analysis_name="all_edge_pairs",
        hardest_index=42,
        seed=DEFAULT_SAMPLE_SEED,
    )
    assert first == second
    assert {0, 42, 99} <= set(first)
    assert len(first) == 13
    assert deterministic_backtracking_indices(
        7,
        graph_order=24,
        graph_hash="b" * 64,
        analysis_name="three_edge_paths",
        hardest_index=None,
        seed=1,
    ) == tuple(range(7))


def test_metric_recomputation_and_agreement_reporting() -> None:
    graph = nx.cubical_graph()
    constraints = enumerate_all_edge_constraints(graph)
    recomputed = _run_cover(graph, constraints, solver="glucose3")
    original = _original_edge_metrics(recomputed)
    agreement, differences = _deterministic_metric_comparison(
        recomputed, original, "all_edge_pairs"
    )
    assert agreement
    assert differences == {}

    original["number_of_witness_cycles"] = int(
        original["number_of_witness_cycles"]
    ) + 1
    agreement, differences = _deterministic_metric_comparison(
        recomputed, original, "all_edge_pairs"
    )
    assert not agreement
    assert "number_of_witness_cycles" in differences


def test_timeout_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_solver(*args: object, **kwargs: object) -> None:
        sleep(0.05)
        return None

    monkeypatch.setattr(
        "barnette_search.independent_review.find_constrained_hamiltonian_cycle",
        slow_solver,
    )
    result = _backtracking_with_timeout(
        nx.cycle_graph(4),
        ReviewConstraint(((0, 1), (2, 3)), ((0, 1),), ((2, 3),)),
        0.001,
    )
    assert result["status"] == "timeout"
    assert result["satisfiable"] is None


def test_discrepancy_escalation_exports_both_cnfs(tmp_path: Path) -> None:
    bundle, embedded = _cube_artifact(tmp_path / "source")
    constraint = enumerate_all_edge_constraints(embedded.graph)[0]
    embedding = json.loads(Path(bundle.embedding_paths[0]).read_text(encoding="utf-8"))
    report = _escalate(
        embedded.graph,
        Path(bundle.planar_code_paths[0]).read_bytes(),
        embedding,
        bundle.graph_hash,
        "all_edge_pairs",
        constraint,
        tmp_path / "reports",
        1.0,
        "intentional test mismatch",
    )
    directory = Path(report)
    assert (directory / "minisat22.cnf").is_file()
    assert (directory / "glucose3.cnf").is_file()
    assert (directory / "discrepancy_report.json.gz").is_file()


def test_duplicate_leaderboard_artifacts_are_deduplicated(tmp_path: Path) -> None:
    extremal = tmp_path / "extremal"
    category = extremal / "all_edge_pairs"
    category.mkdir(parents=True)
    graph_hash = "a" * 64
    (category / "leaderboard_metric.csv").write_text(
        "rank,canonical_graph_hash\n"
        f"1,{graph_hash}\n"
        f"2,{graph_hash}\n",
        encoding="utf-8",
    )
    (tmp_path / "barnette_08.strong_flexibility.jsonl").write_text(
        json.dumps({"canonical_graph_hash": graph_hash}) + "\n",
        encoding="utf-8",
    )
    [bundle] = discover_artifacts(extremal)
    assert bundle.graph_hash == graph_hash
    assert len(bundle.leaderboard_categories) == 2


def test_completed_empty_review_resumes_without_duplicates(tmp_path: Path) -> None:
    extremal = tmp_path / "extremal"
    extremal.mkdir()
    output = tmp_path / "review"
    assert run_independent_review(
        extremal, output_directory=output, workers=1
    ) == ()
    assert run_independent_review(
        extremal, output_directory=output, workers=1, resume=True
    ) == ()
    assert (output / "verification_records.jsonl.gz").is_file()
    assert "timing_comparison" in (
        output / "verification_summary.csv"
    ).read_text(encoding="utf-8").splitlines()[0]
