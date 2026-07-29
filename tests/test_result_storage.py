"""Compact storage, compression, checkpoint, and detail-mode tests."""

from dataclasses import replace
from pathlib import Path

import networkx as nx

from barnette_search.flexibility_enumeration import _WorkerTask, _analyze_worker
from barnette_search.planar_code import encode_planar_code
from barnette_search.result_storage import (
    append_checkpoint,
    read_checkpoint,
    read_jsonl,
    write_jsonl_atomic,
)


def _cube_task(tmp_path: Path, *, detailed: bool) -> _WorkerTask:
    graph = nx.cubical_graph()
    planar, embedding = nx.check_planarity(graph)
    assert planar
    rotation = tuple(tuple(embedding.neighbors_cw_order(v)) for v in graph)
    from barnette_search.flexibility_common import graph_context

    return _WorkerTask(
        generation_index=0,
        requested_vertex_count=8,
        planar_code=encode_planar_code(rotation),
        canonical_graph_hash=graph_context(graph).canonical_graph_hash,
        plantri_version="5.8",
        plantri_executable_sha256="0" * 64,
        plantri_command=("plantri", "-b", "-c3", "-d", "6", "-"),
        test_all_edge_pairs=True,
        test_three_edge_paths=True,
        retain_details=detailed,
        retain_witness_cycles=detailed,
        cross_check_backtracking=False,
        candidate_output_directory=str(tmp_path / "candidates"),
        compress_candidates=False,
    )


def test_summary_and_full_worker_records(tmp_path: Path) -> None:
    summary = _analyze_worker(_cube_task(tmp_path, detailed=False))
    assert "pair_details" not in summary["all_edge_pairs"]
    assert "path_details" not in summary["three_edge_paths"]
    assert "witnesses" not in summary["all_edge_pairs"]

    full = _analyze_worker(_cube_task(tmp_path, detailed=True))
    assert len(full["all_edge_pairs"]["pair_details"]) == 132
    assert len(full["three_edge_paths"]["path_details"]) == 48
    assert all(
        witness["cycle"] is not None
        for witness in full["all_edge_pairs"]["witnesses"]
    )


def test_plain_and_gzip_jsonl_round_trip(tmp_path: Path) -> None:
    records = [{"generation_index": 1, "hash": "b"}, {"generation_index": 0, "hash": "a"}]
    for name in ("records.jsonl", "records.jsonl.gz"):
        path = tmp_path / name
        write_jsonl_atomic(path, records)
        assert list(read_jsonl(path)) == records


def test_checkpoint_ignores_only_truncated_final_record(tmp_path: Path) -> None:
    path = tmp_path / "run.checkpoint.jsonl"
    append_checkpoint(path, {"canonical_graph_hash": "a"})
    with path.open("ab") as output:
        output.write(b'{"canonical_graph_hash":')
    assert read_checkpoint(path) == ({"canonical_graph_hash": "a"},)


def test_worker_output_is_logically_deterministic(tmp_path: Path) -> None:
    task = _cube_task(tmp_path, detailed=False)
    first = _analyze_worker(task)
    second = _analyze_worker(replace(task, generation_index=1))
    first.pop("generation_index")
    second.pop("generation_index")
    for analysis in ("all_edge_pairs", "three_edge_paths"):
        for field in tuple(first[analysis]):
            if "time" in field or field.startswith("hardest_"):
                first[analysis].pop(field)
                second[analysis].pop(field)
    assert first == second
