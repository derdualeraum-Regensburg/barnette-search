"""Tests for enumeration invariants that do not require plantri."""

from io import BytesIO
from pathlib import Path

import networkx as nx
import pytest

import barnette_search.enumeration as enumeration
from barnette_search.planar_code import (
    canonical_graph_hash,
    encode_planar_code,
    iter_planar_code,
)
from barnette_search.plantri import PlantriVersion


def _embedded_cube():
    graph = nx.cubical_graph()
    planar, embedding = nx.check_planarity(graph)
    assert planar
    rotation = tuple(tuple(embedding.neighbors_cw_order(v)) for v in graph)
    return next(iter_planar_code(BytesIO(encode_planar_code(rotation))))


class _FakeStream:
    def __init__(self, records: list[object]) -> None:
        self.records = records
        self.stderr_text = "fake generation statistics"

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter(self.records)


def test_duplicate_hash_is_a_hard_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedded = _embedded_cube()
    monkeypatch.setattr(
        enumeration,
        "stream_barnette_graphs",
        lambda version, order: _FakeStream([embedded]),
    )
    executable = tmp_path / "plantri"
    executable.write_bytes(b"fake")
    version = PlantriVersion(executable, "5.8", "0" * 64, "Plantri version 5.8")

    with pytest.raises(RuntimeError, match="duplicate canonical graph hash"):
        enumeration.enumerate_vertex_count(
            8,
            plantri_version=version,
            output_directory=tmp_path / "output",
            seen_hashes={canonical_graph_hash(embedded)},
        )


def test_odd_order_is_rejected_before_starting_plantri(tmp_path: Path) -> None:
    version = PlantriVersion(tmp_path / "unused", "5.8", "0" * 64, "")
    with pytest.raises(ValueError, match="even"):
        enumeration.enumerate_vertex_count(
            9, plantri_version=version, output_directory=tmp_path
        )


def test_reference_count_mismatch_is_a_hard_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        enumeration,
        "stream_barnette_graphs",
        lambda version, order: _FakeStream([]),
    )
    executable = tmp_path / "plantri"
    executable.write_bytes(b"fake")
    version = PlantriVersion(executable, "5.8", "0" * 64, "")
    with pytest.raises(RuntimeError, match="generated 0, expected 1"):
        enumeration.enumerate_vertex_count(
            8, plantri_version=version, output_directory=tmp_path / "output"
        )


def test_edge_flexibility_output_does_not_overwrite_hamiltonicity_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedded = _embedded_cube()
    monkeypatch.setattr(
        enumeration,
        "stream_barnette_graphs",
        lambda version, order: _FakeStream([embedded]),
    )
    output = tmp_path / "output"
    output.mkdir()
    original = output / "barnette_08.jsonl"
    original.write_text("original Hamiltonicity result\n", encoding="utf-8")
    executable = tmp_path / "plantri"
    executable.write_bytes(b"fake")
    version = PlantriVersion(executable, "5.8", "0" * 64, "")

    summary = enumeration.enumerate_edge_flexibility_vertex_count(
        8,
        plantri_version=version,
        output_directory=output,
        overwrite=True,
    )
    assert original.read_text(encoding="utf-8") == "original Hamiltonicity result\n"
    assert summary.generated_count == 1
    assert summary.graphs_satisfying_complete_property == 1
    assert (output / "barnette_08.edge_flexibility.jsonl").is_file()
