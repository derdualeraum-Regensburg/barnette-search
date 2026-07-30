"""Focused Phase 1--2 audit, ranking, selection, and reconstruction tests."""

from collections import Counter
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import networkx as nx
import pytest

import barnette_search.hsep_order38 as phase12
from barnette_search.planar_code import (
    canonical_graph_hash,
    encode_planar_code,
    iter_planar_code,
)
from barnette_search.plantri import PlantriVersion


def _analysis(
    *,
    name: str,
    graph_hash: str,
    order: int,
    edges: int,
    faces: list[int],
    witnesses: int,
    subtours: int,
) -> dict[str, object]:
    if name == "all_edge_pairs":
        universe = edges * (edges - 1)
        result: dict[str, object] = {
            "total_ordered_edge_pairs": universe,
            "average_pairs_certified_per_witness": universe / witnesses,
            "maximum_pairs_certified_by_one_witness": max(1, universe // 4),
            "hardest_ordered_pair": [[0, 1], [2, 3]],
        }
    else:
        universe = 4 * edges
        result = {
            "number_of_distinct_three_edge_paths": universe,
            "average_paths_certified_per_witness": universe / witnesses,
            "maximum_paths_certified_by_one_witness": max(1, universe // 4),
            "hardest_path": [0, 1, 2, 3],
        }
    result.update(
        {
            "graph_order": order,
            "edge_count": edges,
            "canonical_graph_hash": graph_hash,
            "face_size_multiset": faces,
            "number_of_constrained_sat_calls": witnesses,
            "number_of_witness_cycles": witnesses,
            "witness_cover_ratio": witnesses / universe,
            "total_sat_wall_time_seconds": witnesses / 1000,
            "median_query_time_seconds": 0.001,
            "p95_query_time_seconds": 0.002,
            "p99_query_time_seconds": 0.003,
            "maximum_query_time_seconds": 0.004,
            "total_subtour_iterations": max(1, subtours // 2),
            "total_subtour_constraints": subtours,
            "property_satisfied": True,
            "candidate_requires_review": False,
            "candidate_report_path": None,
            "backtracking_queries": 0,
            "backtracking_agreements": 0,
            "backtracking_runtime_seconds": 0.0,
        }
    )
    return result


def _record(
    index: int,
    *,
    order: int = 8,
    faces: list[int] | None = None,
    ae_witness: int = 4,
    ae_subtour: int = 7,
    path_witness: int = 3,
    path_subtour: int = 6,
) -> dict[str, object]:
    edges = 3 * order // 2
    face_list = list(faces if faces is not None else [4] * (edges - order + 2))
    graph_hash = f"{index + 1:064x}"
    return {
        "generation_index": index,
        "requested_vertex_count": order,
        "canonical_graph_hash": graph_hash,
        "edge_count": edges,
        "face_size_multiset": face_list,
        "plantri_version": "5.8",
        "plantri_executable_sha256": "a" * 64,
        "plantri_command": ["plantri", "-b", "-c3", "-d", "6", "-"],
        "all_edge_pairs": _analysis(
            name="all_edge_pairs",
            graph_hash=graph_hash,
            order=order,
            edges=edges,
            faces=face_list,
            witnesses=ae_witness,
            subtours=ae_subtour,
        ),
        "three_edge_paths": _analysis(
            name="three_edge_paths",
            graph_hash=graph_hash,
            order=order,
            edges=edges,
            faces=face_list,
            witnesses=path_witness,
            subtours=path_subtour,
        ),
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    opener = gzip.open if path.suffix == ".gz" else path.open
    if path.suffix == ".gz":
        with opener(path, "wt", encoding="utf-8", newline="\n") as output:
            for record in records:
                output.write(json.dumps(record, sort_keys=True) + "\n")
    else:
        with opener("w", encoding="utf-8", newline="\n") as output:
            for record in records:
                output.write(json.dumps(record, sort_keys=True) + "\n")


@pytest.mark.parametrize("suffix", (".jsonl", ".jsonl.gz"))
def test_audit_accepts_exact_plain_and_gzip_schema(
    tmp_path: Path, suffix: str
) -> None:
    records = [_record(0), _record(1, ae_witness=5)]
    path = tmp_path / f"records{suffix}"
    _write_jsonl(path, records)

    audited = phase12.audit_source(path, expected_order=8, expected_count=2)

    assert len(audited.records) == 2
    assert audited.blank_line_count == 0
    assert audited.decompressed_size_bytes > 0
    assert audited.face_pattern_counts == Counter({(4, 4, 4, 4, 4, 4): 2})


def test_audit_rejects_count_identity_and_face_ambiguity(tmp_path: Path) -> None:
    valid = _record(0)
    path = tmp_path / "records.jsonl"
    _write_jsonl(path, [valid])
    with pytest.raises(ValueError, match="record count"):
        phase12.audit_source(path, expected_order=8, expected_count=2)

    nested_mismatch = _record(0)
    nested_mismatch["all_edge_pairs"]["canonical_graph_hash"] = "f" * 64  # type: ignore[index]
    _write_jsonl(path, [nested_mismatch])
    with pytest.raises(ValueError, match="hash does not match"):
        phase12.audit_source(path, expected_order=8, expected_count=1)

    bad_faces = _record(0)
    bad_faces["face_size_multiset"] = [2, 4, 4, 4, 4, 6]
    _write_jsonl(path, [bad_faces])
    with pytest.raises(ValueError, match="even sizes at least four"):
        phase12.audit_source(path, expected_order=8, expected_count=1)

    zero_witness = _record(0)
    analysis = zero_witness["all_edge_pairs"]  # type: ignore[assignment]
    analysis["number_of_witness_cycles"] = 0  # type: ignore[index]
    analysis["number_of_constrained_sat_calls"] = 0  # type: ignore[index]
    analysis["witness_cover_ratio"] = 0.0  # type: ignore[index]
    analysis["average_pairs_certified_per_witness"] = 0.0  # type: ignore[index]
    _write_jsonl(path, [zero_witness])
    with pytest.raises(ValueError, match="witness count must be positive"):
        phase12.audit_source(path, expected_order=8, expected_count=1)

    bad_hardest = _record(0)
    bad_hardest["three_edge_paths"]["hardest_path"] = [0, 1, 1, 3]  # type: ignore[index]
    _write_jsonl(path, [bad_hardest])
    with pytest.raises(ValueError, match="invalid shape or labels"):
        phase12.audit_source(path, expected_order=8, expected_count=1)


def test_tied_ranks_midpercentiles_and_robust_scale_fallbacks() -> None:
    assert phase12._competition_rank_and_midpercentile([1, 2, 2, 4], 2) == (
        2,
        0.5,
    )
    assert phase12._rank_lookup([1, 2, 2, 4])[2] == (2, 0.5)
    assert phase12._distribution([1, 2, 3, 4, 5], timing=False).robust_scale_method == "1.4826*MAD"
    assert phase12._distribution([0, 0, 0, 1], timing=False).robust_scale_method in {
        "IQR/1.349",
        "P90-P10/2.563",
    }
    constant = phase12._distribution([7, 7, 7], timing=True)
    assert constant.robust_scale_method == "constant"
    assert constant.robust_z(999) == 0.0
    assert constant.log1p_statistics is not None


def _order38_faces() -> list[list[int]]:
    # Each tuple has 21 even face sizes summing to 114.
    return [
        [4] * 17 + [6, 6, 16, 18],
        [4] * 16 + [6, 6, 6, 14, 18],
        [4] * 16 + [6, 6, 6, 16, 16],
        [4] * 16 + [6, 6, 8, 12, 18],
        [4] * 16 + [6, 6, 10, 10, 18],
        [4] * 16 + [6, 6, 10, 12, 16],
        [4] * 16 + [6, 6, 10, 14, 14],
        [4] * 16 + [6, 6, 12, 12, 14],
    ]


def test_diverse_selection_is_deterministic_and_aggregates_reasons() -> None:
    common_faces = [4] * 15 + [6, 6, 8, 8, 10, 12]
    records: list[dict[str, object]] = []
    unique_faces = _order38_faces()
    for index in range(45):
        records.append(
            _record(
                index,
                order=38,
                faces=unique_faces[index - 25] if 25 <= index < 33 else common_faces,
                ae_witness=(100 - index if index < 10 else 20 + index % 7),
                ae_subtour=(100 - index if 10 <= index < 15 else 30 + index % 9),
                path_witness=(100 - index if 15 <= index < 20 else 15 + index % 5),
                path_subtour=(100 - index if 20 <= index < 25 else 25 + index % 11),
            )
        )
    face_counts = Counter(tuple(record["face_size_multiset"]) for record in records)
    dataset = phase12.AuditDataset(
        path=Path("controlled.jsonl"),
        records=records,  # type: ignore[arg-type]
        source_size_bytes=1,
        source_sha256="1" * 64,
        decompressed_size_bytes=1,
        decompressed_sha256="2" * 64,
        blank_line_count=0,
        plantri_command=("plantri", "-b", "-c3", "-d", "21", "-"),
        plantri_version="5.8",
        plantri_executable_sha256="a" * 64,
        face_pattern_counts=face_counts,
    )

    first = phase12.select_candidates(dataset)
    reversed_dataset = phase12.AuditDataset(
        path=dataset.path,
        records=list(reversed(records)),  # type: ignore[arg-type]
        source_size_bytes=dataset.source_size_bytes,
        source_sha256=dataset.source_sha256,
        decompressed_size_bytes=dataset.decompressed_size_bytes,
        decompressed_sha256=dataset.decompressed_sha256,
        blank_line_count=0,
        plantri_command=dataset.plantri_command,
        plantri_version=dataset.plantri_version,
        plantri_executable_sha256=dataset.plantri_executable_sha256,
        face_pattern_counts=face_counts,
    )
    second = phase12.select_candidates(reversed_dataset)

    assert [item["canonical_graph_hash"] for item in first.candidates] == [
        item["canonical_graph_hash"] for item in second.candidates
    ]
    reason_codes = {
        reason["code"]
        for candidate in first.candidates
        for reason in candidate["selection_reasons"]
    }
    assert {
        "AE_WITNESS_TOP10",
        "AE_SUBTOUR_TOP5",
        "PATH_WITNESS_TOP5",
        "PATH_SUBTOUR_TOP5",
        "FACE_UNIQUE",
        "MULTIVARIATE_TOP5",
        "RARE_FACE_CONTROL_LOW",
        "RARE_FACE_CONTROL_CENTRAL",
        "RARE_FACE_CONTROL_PATH_HARD",
    } <= reason_codes
    assert first.unique_face_graph_count == 8
    assert len({item["canonical_graph_hash"] for item in first.candidates}) == len(
        first.candidates
    )


def _embedded_cube():
    graph = nx.cubical_graph()
    planar, embedding = nx.check_planarity(graph)
    assert planar
    rotation = tuple(tuple(embedding.neighbors_cw_order(vertex)) for vertex in graph)
    return next(iter_planar_code(BytesIO(encode_planar_code(rotation))))


class _FakeStream:
    def __init__(self, embedded) -> None:
        self.embedded = embedded
        self.stderr_text = "1 bipartite cubic graphs written to stdout"

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter((self.embedded,))


def test_reconstruction_writes_certificates_and_fails_closed_on_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedded = _embedded_cube()
    graph_hash = canonical_graph_hash(embedded)
    executable = tmp_path / "plantri.exe"
    executable.write_bytes(b"controlled")
    executable_hash = sha256(executable.read_bytes()).hexdigest()
    version = PlantriVersion(executable, "5.8", executable_hash, "Plantri 5.8")
    monkeypatch.setattr(phase12, "detect_plantri_version", lambda path: version)
    monkeypatch.setattr(
        phase12,
        "stream_barnette_graphs",
        lambda selected_version, order: _FakeStream(embedded),
    )
    candidate = {
        "canonical_graph_hash": graph_hash,
        "generation_index": 0,
        "requested_vertex_count": 8,
        "edge_count": 12,
        "face_size_multiset": [4] * 6,
    }
    selection = phase12.CandidateSelection(
        candidates=[candidate],
        profiles={},
        metric_values={},
        multivariate_scores={},
        required_strata_union_size=1,
        unique_face_graph_count=0,
    )
    dataset = phase12.AuditDataset(
        path=tmp_path / "source.jsonl",
        records=[{"canonical_graph_hash": graph_hash}],
        source_size_bytes=1,
        source_sha256="c" * 64,
        decompressed_size_bytes=1,
        decompressed_sha256="d" * 64,
        blank_line_count=0,
        plantri_command=(str(executable), "-b", "-c3", "-d", "21", "-"),
        plantri_version="5.8",
        plantri_executable_sha256=executable_hash,
        face_pattern_counts=Counter({(4, 4, 4, 4, 4, 4): 1}),
    )

    manifest = phase12.reconstruct_candidates(
        dataset,
        selection,
        executable=executable,
        output_directory=tmp_path / "out",
        resume=False,
        overwrite=False,
    )
    saved = manifest["candidates"][graph_hash]
    assert Path(saved["planar_code_path"]).is_file()
    assert saved["barnette_validation"]["valid"]
    assert not phase12._validate_saved_reconstruction(
        saved, tmp_path / "out", expected_hash="f" * 64
    )

    embedding_path = Path(saved["embedding_path"])
    original_embedding = embedding_path.read_bytes()
    changed_embedding = json.loads(original_embedding)
    changed_embedding["canonical_edge_identifiers"][0]["endpoints"] = [0, 0]
    embedding_path.write_text(
        json.dumps(changed_embedding, sort_keys=True), encoding="utf-8"
    )
    changed_saved = dict(
        saved, embedding_sha256=sha256(embedding_path.read_bytes()).hexdigest()
    )
    assert not phase12._validate_saved_reconstruction(
        changed_saved,
        tmp_path / "out",
        expected_hash=graph_hash,
        expected_candidate=candidate,
    )
    embedding_path.write_bytes(original_embedding)

    graph6_path = Path(saved["graph6_path"])
    original_graph6 = graph6_path.read_bytes()
    relabeled = nx.relabel_nodes(embedded.graph, {0: 1, 1: 0})
    assert {
        frozenset(edge) for edge in relabeled.edges()
    } != {frozenset(edge) for edge in embedded.graph.edges()}
    changed_graph6 = phase12._retained_label_graph6_bytes(relabeled)
    assert changed_graph6 != original_graph6
    graph6_path.write_bytes(changed_graph6)
    graph6_changed_saved = dict(
        saved,
        graph6=changed_graph6.decode("ascii").strip(),
        graph6_sha256=sha256(changed_graph6).hexdigest(),
    )
    assert not phase12._validate_saved_reconstruction(
        graph6_changed_saved,
        tmp_path / "out",
        expected_hash=graph_hash,
        expected_candidate=candidate,
    )
    graph6_path.write_bytes(original_graph6)

    manifest_path = tmp_path / "out" / "reconstruction_manifest.json"
    original_manifest = manifest_path.read_bytes()
    provenance_tamper = json.loads(original_manifest)
    provenance_tamper["verification_scope"] = "unchecked"
    manifest_path.write_text(
        json.dumps(provenance_tamper, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="missing or changed"):
        phase12.reconstruct_candidates(
            dataset,
            selection,
            executable=executable,
            output_directory=tmp_path / "out",
            resume=True,
            overwrite=False,
        )
    manifest_path.write_bytes(original_manifest)

    tampered_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered_manifest["candidates"][graph_hash]["planar_code_base64"] = "invalid!"
    manifest_path.write_text(
        json.dumps(tampered_manifest, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="missing or changed"):
        phase12.reconstruct_candidates(
            dataset,
            selection,
            executable=executable,
            output_directory=tmp_path / "out",
            resume=True,
            overwrite=False,
        )

    bad_candidate = dict(candidate, canonical_graph_hash="f" * 64)
    bad_selection = phase12.CandidateSelection(
        candidates=[bad_candidate],
        profiles={},
        metric_values={},
        multivariate_scores={},
        required_strata_union_size=1,
        unique_face_graph_count=0,
    )
    with pytest.raises(RuntimeError, match="hashes as"):
        phase12.reconstruct_candidates(
            dataset,
            bad_selection,
            executable=executable,
            output_directory=tmp_path / "bad",
            resume=False,
            overwrite=False,
        )


def test_worker_cap_is_enforced_before_io(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and 4"):
        phase12.run_phase12(
            tmp_path / "missing.jsonl",
            output_directory=tmp_path / "output",
            workers=5,
        )


def test_output_lock_and_owned_cleanup_preserve_unrelated_files(tmp_path: Path) -> None:
    lock_path = tmp_path / ".phase12.lock"
    with phase12._OutputLock(lock_path):
        assert lock_path.is_file()
        with pytest.raises(RuntimeError, match="output lock"):
            with phase12._OutputLock(lock_path):
                pass
    assert lock_path.is_file()
    with phase12._OutputLock(lock_path):
        pass

    (tmp_path / "candidate_pool.json").write_text("stale", encoding="utf-8")
    unrelated = tmp_path / "user-notes.txt"
    unrelated.write_text("preserve", encoding="utf-8")
    graph_directory = tmp_path / "candidate_graphs"
    graph_directory.mkdir()
    (graph_directory / f"{'a' * 64}.g6").write_text("stale", encoding="ascii")
    graph_note = graph_directory / "notes.txt"
    graph_note.write_text("preserve", encoding="utf-8")

    phase12._clear_phase12_outputs(tmp_path)

    assert not (tmp_path / "candidate_pool.json").exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve"
    assert graph_note.read_text(encoding="utf-8") == "preserve"


def test_debug_filtered_report_does_not_claim_full_pool() -> None:
    common_faces = [4] * 15 + [6, 6, 8, 8, 10, 12]
    records = [
        _record(
            index,
            order=38,
            faces=common_faces,
            ae_witness=20 + index,
            ae_subtour=30 + index,
            path_witness=15 + index % 5,
            path_subtour=25 + index,
        )
        for index in range(12)
    ]
    dataset = phase12.AuditDataset(
        path=Path("controlled.jsonl"),
        records=records,  # type: ignore[arg-type]
        source_size_bytes=1,
        source_sha256="1" * 64,
        decompressed_size_bytes=1,
        decompressed_sha256="2" * 64,
        blank_line_count=0,
        plantri_command=("plantri", "-b", "-c3", "-d", "21", "-"),
        plantri_version="5.8",
        plantri_executable_sha256="a" * 64,
        face_pattern_counts=Counter({tuple(common_faces): len(records)}),
    )
    selection = phase12.select_candidates(dataset)
    chosen = selection.candidates[0]
    selection.candidates = [chosen]
    selection.debug_graph_hash = chosen["canonical_graph_hash"]

    report = phase12._candidate_report_markdown(dataset, selection)

    assert "Debug-filtered output" in report
    assert "must not be presented as the complete candidate pool" in report
    assert "full deterministic pool" in report
    assert "1 candidates" not in report


def test_refused_rerun_does_not_mutate_completed_output(tmp_path: Path) -> None:
    metadata_path = tmp_path / "phase12_run_metadata.json"
    metadata_path.write_text(
        json.dumps({"status": "complete"}) + "\n", encoding="utf-8"
    )
    checksum_path = tmp_path / "SHA256SUMS.txt"
    checksum_path.write_text(
        f"{sha256(metadata_path.read_bytes()).hexdigest()}  "
        "phase12_run_metadata.json\n",
        encoding="utf-8",
    )
    before = {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    }

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        phase12.run_phase12(
            tmp_path / "missing.jsonl",
            output_directory=tmp_path,
        )

    after = {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    }
    assert after == before
    assert not (tmp_path / "phase12_failure.json").exists()
