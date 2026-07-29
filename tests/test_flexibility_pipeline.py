"""Resume and candidate-retention tests without external generators."""

from io import BytesIO
from pathlib import Path

import networkx as nx
import pytest

import barnette_search.flexibility_enumeration as pipeline
from barnette_search.flexibility_common import graph_context
from barnette_search.planar_code import encode_planar_code, iter_planar_code
from barnette_search.plantri import PlantriVersion
from barnette_search.result_storage import append_checkpoint, read_jsonl


class _FakeStream:
    def __init__(self, embedded) -> None:
        self.embedded = embedded
        self.stderr_text = "controlled plantri statistics"

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter((self.embedded,))


def _embedded_cube():
    graph = nx.cubical_graph()
    planar, embedding = nx.check_planarity(graph)
    assert planar
    rotation = tuple(tuple(embedding.neighbors_cw_order(v)) for v in graph)
    return next(iter_planar_code(BytesIO(encode_planar_code(rotation))))


def _options(detail: str = "summary") -> pipeline.FlexibilityRunOptions:
    return pipeline.FlexibilityRunOptions(
        test_all_edge_pairs=True,
        test_three_edge_paths=True,
        output_detail=detail,
        retain_top_k=1,
        compress_results=True,
        workers=1,
    )


def _version(tmp_path: Path) -> PlantriVersion:
    executable = tmp_path / "plantri"
    executable.write_bytes(b"controlled")
    return PlantriVersion(executable, "5.8", "0" * 64, "Plantri version 5.8")


def test_interrupted_checkpoint_resumes_without_duplicate_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedded = _embedded_cube()
    monkeypatch.setattr(
        pipeline,
        "stream_barnette_graphs",
        lambda version, order: _FakeStream(embedded),
    )
    options = _options()
    context = graph_context(embedded.graph)
    task = pipeline._WorkerTask(
        generation_index=0,
        requested_vertex_count=8,
        planar_code=encode_planar_code(embedded.rotation_system),
        canonical_graph_hash=context.canonical_graph_hash,
        plantri_version="5.8",
        plantri_executable_sha256="0" * 64,
        plantri_command=("plantri", "-b", "-c3", "-d", "6", "-"),
        test_all_edge_pairs=True,
        test_three_edge_paths=True,
        retain_details=False,
        retain_witness_cycles=False,
        cross_check_backtracking=True,
        candidate_output_directory=str(tmp_path / "candidates"),
        compress_candidates=True,
    )
    checkpoint = tmp_path / "barnette_08.strong_flexibility.checkpoint.jsonl"
    config = tmp_path / "barnette_08.strong_flexibility.checkpoint.config"
    append_checkpoint(checkpoint, pipeline._analyze_worker(task))
    config.write_text(pipeline._config_signature(options, 8) + "\n", encoding="ascii")

    records, _ = pipeline._run_order(
        8,
        _version(tmp_path),
        tmp_path,
        options,
        resume=True,
        overwrite=False,
        graph_planar_codes={},
    )
    assert len(records) == 1
    final = tmp_path / "barnette_08.strong_flexibility.jsonl.gz"
    assert len(list(read_jsonl(final))) == 1
    assert not checkpoint.exists()


def test_candidates_mode_retains_details_only_in_candidate_file(tmp_path: Path) -> None:
    embedded = _embedded_cube()
    context = graph_context(embedded.graph)
    options = _options("candidates")
    summary_task = pipeline._WorkerTask(
        generation_index=0,
        requested_vertex_count=8,
        planar_code=encode_planar_code(embedded.rotation_system),
        canonical_graph_hash=context.canonical_graph_hash,
        plantri_version="5.8",
        plantri_executable_sha256="0" * 64,
        plantri_command=("plantri", "-b", "-c3", "-d", "6", "-"),
        test_all_edge_pairs=True,
        test_three_edge_paths=True,
        retain_details=False,
        retain_witness_cycles=False,
        cross_check_backtracking=False,
        candidate_output_directory=str(tmp_path / "review"),
        compress_candidates=True,
    )
    summary = pipeline._analyze_worker(summary_task)
    assert "pair_details" not in summary["all_edge_pairs"]
    pipeline._candidate_details(
        {"all_edge_pairs": [context.canonical_graph_hash]},
        [summary],
        {context.canonical_graph_hash: summary_task.planar_code},
        tmp_path,
        options,
    )
    [detailed] = read_jsonl(
        tmp_path / "strong_flexibility.candidates.jsonl.gz"
    )
    assert len(detailed["all_edge_pairs"]["pair_details"]) == 132
    assert len(detailed["three_edge_paths"]["path_details"]) == 48
