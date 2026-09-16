import gzip
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from run_hsep_census_through_24 import (  # noqa: E402
    load_census,
    load_jsonl,
    resolve_census_files,
    validate_summary,
)


def _write_summary(path: Path, generated: int, reference: int, extra: str = "") -> None:
    path.write_text(
        f"requested_vertex_count,generated_count,reference_count{extra}\n"
        f"8,{generated},{reference}{',x' if extra else ''}\n",
        encoding="utf-8",
    )


def test_resolve_census_files_prefers_plain_schema(tmp_path: Path) -> None:
    (tmp_path / "barnette_08.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "barnette_08.summary.csv").write_text("", encoding="utf-8")
    jsonl, summary, gzipped = resolve_census_files(tmp_path, 8)
    assert jsonl.name == "barnette_08.jsonl"
    assert summary.name == "barnette_08.summary.csv"
    assert gzipped is False


def test_resolve_census_files_falls_back_to_strong_flexibility_gzip(tmp_path: Path) -> None:
    with gzip.open(tmp_path / "barnette_26.strong_flexibility.jsonl.gz", "wt") as handle:
        handle.write("")
    (tmp_path / "barnette_26.strong_flexibility.summary.csv").write_text("", encoding="utf-8")
    jsonl, summary, gzipped = resolve_census_files(tmp_path, 26)
    assert jsonl.name == "barnette_26.strong_flexibility.jsonl.gz"
    assert gzipped is True


def test_resolve_census_files_raises_when_neither_schema_present(tmp_path: Path) -> None:
    try:
        resolve_census_files(tmp_path, 30)
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def _record(order: int, index: int, graph_hash: str, with_generation_index: bool) -> dict:
    record = {"requested_vertex_count": order, "canonical_graph_hash": graph_hash}
    if with_generation_index:
        record["generation_index"] = index
    return record


def test_load_jsonl_accepts_plain_records_without_generation_index(tmp_path: Path) -> None:
    path = tmp_path / "barnette_08.jsonl"
    path.write_text(json.dumps(_record(8, 0, "aaa", with_generation_index=False)) + "\n", encoding="utf-8")
    records = load_jsonl(path, 8, gzipped=False)
    assert len(records) == 1


def test_load_jsonl_reads_gzip_and_checks_generation_index(tmp_path: Path) -> None:
    path = tmp_path / "barnette_26.strong_flexibility.jsonl.gz"
    lines = [
        json.dumps(_record(26, 0, "aaa", with_generation_index=True)),
        json.dumps(_record(26, 1, "bbb", with_generation_index=True)),
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    records = load_jsonl(path, 26, gzipped=True)
    assert [record["canonical_graph_hash"] for record in records] == ["aaa", "bbb"]


def test_load_jsonl_rejects_out_of_sequence_generation_index(tmp_path: Path) -> None:
    path = tmp_path / "barnette_26.strong_flexibility.jsonl.gz"
    lines = [
        json.dumps(_record(26, 0, "aaa", with_generation_index=True)),
        json.dumps(_record(26, 5, "bbb", with_generation_index=True)),
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    try:
        load_jsonl(path, 26, gzipped=True)
    except ValueError as error:
        assert "out-of-sequence" in str(error)
        return
    raise AssertionError("expected ValueError")


def test_load_jsonl_rejects_duplicate_hashes(tmp_path: Path) -> None:
    path = tmp_path / "barnette_08.jsonl"
    lines = [
        json.dumps(_record(8, 0, "aaa", with_generation_index=False)),
        json.dumps(_record(8, 1, "aaa", with_generation_index=False)),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        load_jsonl(path, 8, gzipped=False)
    except ValueError as error:
        assert "duplicate" in str(error)
        return
    raise AssertionError("expected ValueError")


def test_validate_summary_skips_hash_check_without_jsonl_sha256_column(tmp_path: Path) -> None:
    jsonl = tmp_path / "barnette_26.strong_flexibility.jsonl.gz"
    with gzip.open(jsonl, "wt") as handle:
        handle.write("")
    summary = tmp_path / "barnette_26.strong_flexibility.summary.csv"
    _write_summary(summary, generated=2, reference=2)
    validate_summary(summary, jsonl, count=2)


def test_validate_summary_raises_on_count_mismatch(tmp_path: Path) -> None:
    jsonl = tmp_path / "barnette_26.strong_flexibility.jsonl.gz"
    with gzip.open(jsonl, "wt") as handle:
        handle.write("")
    summary = tmp_path / "barnette_26.strong_flexibility.summary.csv"
    _write_summary(summary, generated=2, reference=2)
    try:
        validate_summary(summary, jsonl, count=3)
    except ValueError as error:
        assert "count mismatch" in str(error)
        return
    raise AssertionError("expected ValueError")


def test_load_census_skips_orders_not_requested(tmp_path: Path) -> None:
    (tmp_path / "barnette_08.jsonl").write_text(
        json.dumps(_record(8, 0, "aaa", with_generation_index=False)) + "\n", encoding="utf-8"
    )
    (tmp_path / "barnette_08.summary.csv").write_text(
        "requested_vertex_count,generated_count,reference_count\n8,1,1\n", encoding="utf-8"
    )
    censuses = load_census(tmp_path, [8])
    assert list(censuses.keys()) == [8]
    assert len(censuses[8]) == 1
