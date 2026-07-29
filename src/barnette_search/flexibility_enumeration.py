"""Compact, resumable, deterministic graph-level flexibility pipeline."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import socket
from time import perf_counter
from typing import Any

from .all_edge_flexibility import analyze_all_edge_pair_flexibility
from .extremal import write_extremal_outputs
from .planar_code import canonical_graph_hash, encode_planar_code, iter_planar_code
from .plantri import (
    PlantriVersion,
    barnette_plantri_command,
    detect_plantri_version,
    locate_plantri,
    stream_barnette_graphs,
)
from .result_storage import (
    append_checkpoint,
    read_checkpoint,
    read_jsonl,
    write_jsonl_atomic,
)
from .three_edge_path_flexibility import analyze_three_edge_path_flexibility
from .validation import validate_barnette_graph


REFERENCE_COUNTS = {
    8: 1,
    10: 0,
    12: 1,
    14: 1,
    16: 2,
    18: 2,
    20: 8,
    22: 8,
    24: 32,
    26: 57,
    28: 185,
    30: 466,
    32: 1543,
}


@dataclass(frozen=True, slots=True)
class FlexibilityRunOptions:
    """Serializable behavior affecting logical analysis output."""

    test_all_edge_pairs: bool
    test_three_edge_paths: bool
    output_detail: str
    retain_top_k: int
    compress_results: bool
    workers: int


@dataclass(frozen=True, slots=True)
class _WorkerTask:
    generation_index: int
    requested_vertex_count: int
    planar_code: bytes
    canonical_graph_hash: str
    plantri_version: str
    plantri_executable_sha256: str
    plantri_command: tuple[str, ...]
    test_all_edge_pairs: bool
    test_three_edge_paths: bool
    retain_details: bool
    retain_witness_cycles: bool
    cross_check_backtracking: bool
    candidate_output_directory: str
    compress_candidates: bool


def _versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for package in ("barnette-search", "networkx", "python-sat"):
        try:
            result[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            result[package] = None
    return result


def _decode_graph(data: bytes):
    from io import BytesIO

    [embedded] = iter_planar_code(BytesIO(data), require_header=True)
    return embedded


def _compact_analysis(value: dict[str, Any], detail_field: str) -> dict[str, Any]:
    if value.get(detail_field) is None:
        value.pop(detail_field, None)
    if value.get("witnesses") is None:
        value.pop("witnesses", None)
    return value


def _analyze_worker(task: _WorkerTask) -> dict[str, Any]:
    embedded = _decode_graph(task.planar_code)
    graph = embedded.graph
    validation = validate_barnette_graph(graph)
    if not validation.valid:
        raise RuntimeError(
            f"worker received a non-Barnette graph: {validation.rejection_reasons}"
        )
    record: dict[str, Any] = {
        "generation_index": task.generation_index,
        "requested_vertex_count": task.requested_vertex_count,
        "canonical_graph_hash": task.canonical_graph_hash,
        "edge_count": graph.number_of_edges(),
        "face_size_multiset": embedded.face_size_multiset,
        "plantri_version": task.plantri_version,
        "plantri_executable_sha256": task.plantri_executable_sha256,
        "plantri_command": task.plantri_command,
    }
    candidate_directory = Path(task.candidate_output_directory)
    if task.test_all_edge_pairs:
        result = analyze_all_edge_pair_flexibility(
            graph,
            retain_pair_details=task.retain_details,
            retain_witness_cycles=task.retain_witness_cycles,
            cross_check_backtracking=task.cross_check_backtracking,
            candidate_output_directory=candidate_directory,
            compress_candidates=task.compress_candidates,
        )
        if result.canonical_graph_hash != task.canonical_graph_hash:
            raise RuntimeError("worker canonical graph hash changed after serialization")
        record["all_edge_pairs"] = _compact_analysis(
            asdict(result), "pair_details"
        )
    if task.test_three_edge_paths:
        result = analyze_three_edge_path_flexibility(
            graph,
            retain_path_details=task.retain_details,
            retain_witness_cycles=task.retain_witness_cycles,
            cross_check_backtracking=task.cross_check_backtracking,
            candidate_output_directory=candidate_directory,
            compress_candidates=task.compress_candidates,
        )
        if result.canonical_graph_hash != task.canonical_graph_hash:
            raise RuntimeError("worker canonical graph hash changed after serialization")
        record["three_edge_paths"] = _compact_analysis(
            asdict(result), "path_details"
        )
    return record


def _config_signature(options: FlexibilityRunOptions, order: int) -> str:
    logical = {
        "order": order,
        "all_edge_pairs": options.test_all_edge_pairs,
        "three_edge_paths": options.test_three_edge_paths,
        "output_detail": options.output_detail,
        "compress_results": options.compress_results,
    }
    return sha256(json.dumps(logical, sort_keys=True).encode()).hexdigest()


def _write_config(path: Path, signature: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(signature + "\n", encoding="ascii")
    os.replace(temporary, path)


def _process_completed(
    futures: dict[Future[dict[str, Any]], _WorkerTask],
    completed_records: dict[str, dict[str, Any]],
    checkpoint_path: Path,
    *,
    wait_for_all: bool,
) -> None:
    if not futures:
        return
    if wait_for_all:
        done, _ = wait(futures)
    else:
        done, _ = wait(futures, return_when=FIRST_COMPLETED)
    for future in sorted(done, key=lambda item: futures[item].generation_index):
        task = futures.pop(future)
        record = future.result()
        graph_hash = record["canonical_graph_hash"]
        if graph_hash in completed_records:
            raise RuntimeError(f"duplicate completed graph record: {graph_hash}")
        if record["generation_index"] != task.generation_index:
            raise RuntimeError("worker returned the wrong generation index")
        append_checkpoint(checkpoint_path, record)
        completed_records[graph_hash] = record


def _summary_row(
    order: int,
    records: list[dict[str, Any]],
    elapsed: float,
    plantri_stderr: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "requested_vertex_count": order,
        "generated_count": len(records),
        "reference_count": REFERENCE_COUNTS.get(order),
        "total_runtime_seconds": elapsed,
        "plantri_stderr": plantri_stderr.strip(),
    }
    for analysis, prefix, total_field in (
        ("all_edge_pairs", "all_edge", "total_ordered_edge_pairs"),
        (
            "three_edge_paths",
            "three_edge_path",
            "number_of_distinct_three_edge_paths",
        ),
    ):
        values = [record[analysis] for record in records if analysis in record]
        if not values:
            continue
        row.update(
            {
                f"{prefix}_property_graphs": sum(
                    int(value["property_satisfied"]) for value in values
                ),
                f"{prefix}_candidate_graphs": sum(
                    int(value["candidate_requires_review"]) for value in values
                ),
                f"{prefix}_total_constraints": sum(
                    int(value[total_field]) for value in values
                ),
                f"{prefix}_sat_calls": sum(
                    int(value["number_of_constrained_sat_calls"])
                    for value in values
                ),
                f"{prefix}_witness_cycles": sum(
                    int(value["number_of_witness_cycles"]) for value in values
                ),
                f"{prefix}_sat_time_seconds": sum(
                    float(value["total_sat_wall_time_seconds"])
                    for value in values
                ),
                f"{prefix}_subtour_iterations": sum(
                    int(value["total_subtour_iterations"]) for value in values
                ),
                f"{prefix}_subtour_constraints": sum(
                    int(value["total_subtour_constraints"]) for value in values
                ),
                f"{prefix}_backtracking_queries": sum(
                    int(value["backtracking_queries"]) for value in values
                ),
                f"{prefix}_backtracking_agreements": sum(
                    int(value["backtracking_agreements"]) for value in values
                ),
                f"{prefix}_backtracking_time_seconds": sum(
                    float(value["backtracking_runtime_seconds"])
                    for value in values
                ),
            }
        )
    return row


def _write_csv(path: Path, row: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)


def _run_order(
    order: int,
    version: PlantriVersion,
    output_directory: Path,
    options: FlexibilityRunOptions,
    *,
    resume: bool,
    overwrite: bool,
    graph_planar_codes: dict[str, bytes],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    suffix = ".jsonl.gz" if options.compress_results else ".jsonl"
    base = output_directory / f"barnette_{order:02d}.strong_flexibility"
    final_path = Path(str(base) + suffix)
    checkpoint_path = Path(str(base) + ".checkpoint.jsonl")
    config_path = Path(str(base) + ".checkpoint.config")
    summary_path = Path(str(base) + ".summary.csv")
    signature = _config_signature(options, order)

    if overwrite:
        for path in (final_path, checkpoint_path, config_path, summary_path):
            if path.exists():
                path.unlink()
    if final_path.exists() and not resume:
        raise FileExistsError(f"refusing to overwrite {final_path}")
    if checkpoint_path.exists() and not resume:
        raise FileExistsError(
            f"unfinished checkpoint exists; use --resume or --overwrite: {checkpoint_path}"
        )
    if resume and config_path.exists():
        existing_signature = config_path.read_text(encoding="ascii").strip()
        if existing_signature != signature:
            raise ValueError("resume checkpoint options do not match this run")
    elif not final_path.exists():
        _write_config(config_path, signature)

    existing_records = (
        list(read_jsonl(final_path))
        if final_path.exists()
        else list(read_checkpoint(checkpoint_path))
    )
    completed_records: dict[str, dict[str, Any]] = {}
    for record in existing_records:
        graph_hash = record["canonical_graph_hash"]
        if graph_hash in completed_records:
            raise RuntimeError(f"duplicate checkpoint graph hash: {graph_hash}")
        completed_records[graph_hash] = record

    command = barnette_plantri_command(version.executable, order)
    started = perf_counter()
    generated_hashes: set[str] = set()
    futures: dict[Future[dict[str, Any]], _WorkerTask] = {}
    executor = ProcessPoolExecutor(max_workers=options.workers) if options.workers > 1 else None
    generation_index = 0
    try:
        with stream_barnette_graphs(version, order) as stream:
            for embedded in stream:
                validation = validate_barnette_graph(embedded.graph)
                if not validation.valid:
                    raise RuntimeError(
                        f"plantri graph failed validation: {validation.rejection_reasons}"
                    )
                graph_hash = canonical_graph_hash(embedded)
                if graph_hash in generated_hashes:
                    raise RuntimeError(f"duplicate generated graph hash: {graph_hash}")
                generated_hashes.add(graph_hash)
                serialized = encode_planar_code(embedded.rotation_system)
                graph_planar_codes[graph_hash] = serialized
                if graph_hash in completed_records:
                    generation_index += 1
                    continue
                task = _WorkerTask(
                    generation_index=generation_index,
                    requested_vertex_count=order,
                    planar_code=serialized,
                    canonical_graph_hash=graph_hash,
                    plantri_version=version.version,
                    plantri_executable_sha256=version.executable_sha256,
                    plantri_command=command,
                    test_all_edge_pairs=options.test_all_edge_pairs,
                    test_three_edge_paths=options.test_three_edge_paths,
                    retain_details=options.output_detail == "full",
                    retain_witness_cycles=options.output_detail == "full",
                    cross_check_backtracking=order <= 24,
                    candidate_output_directory=str(output_directory / "review_candidates"),
                    compress_candidates=options.compress_results,
                )
                if executor is None:
                    record = _analyze_worker(task)
                    append_checkpoint(checkpoint_path, record)
                    completed_records[graph_hash] = record
                else:
                    futures[executor.submit(_analyze_worker, task)] = task
                    if len(futures) >= 2 * options.workers:
                        _process_completed(
                            futures,
                            completed_records,
                            checkpoint_path,
                            wait_for_all=False,
                        )
                generation_index += 1
            if executor is not None:
                _process_completed(
                    futures,
                    completed_records,
                    checkpoint_path,
                    wait_for_all=True,
                )
        plantri_stderr = stream.stderr_text
    except BaseException:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        if executor is not None:
            executor.shutdown(wait=True)

    expected = REFERENCE_COUNTS.get(order)
    if expected is not None and generation_index != expected:
        raise RuntimeError(
            f"enumeration count mismatch for {order}: generated {generation_index}, expected {expected}"
        )
    if set(completed_records) != generated_hashes:
        raise RuntimeError("completed graph identities do not match generated identities")
    records = sorted(
        completed_records.values(), key=lambda record: record["generation_index"]
    )
    write_jsonl_atomic(final_path, records)
    elapsed = perf_counter() - started
    summary = _summary_row(order, records, elapsed, plantri_stderr)
    _write_csv(summary_path, summary)
    if checkpoint_path.exists():
        checkpoint_path.unlink()
    if config_path.exists():
        config_path.unlink()
    return records, summary


def _candidate_details(
    selected: dict[str, list[str]],
    records: list[dict[str, Any]],
    graph_planar_codes: dict[str, bytes],
    output_directory: Path,
    options: FlexibilityRunOptions,
) -> None:
    selected_hashes = set().union(*map(set, selected.values())) if selected else set()
    selected_hashes.update(
        record["canonical_graph_hash"]
        for record in records
        if any(
            record.get(analysis, {}).get("candidate_requires_review", False)
            for analysis in ("all_edge_pairs", "three_edge_paths")
        )
    )
    by_hash = {record["canonical_graph_hash"]: record for record in records}
    detailed: list[dict[str, Any]] = []
    for graph_hash in sorted(selected_hashes):
        source = by_hash[graph_hash]
        task = _WorkerTask(
            generation_index=source["generation_index"],
            requested_vertex_count=source["requested_vertex_count"],
            planar_code=graph_planar_codes[graph_hash],
            canonical_graph_hash=graph_hash,
            plantri_version=source["plantri_version"],
            plantri_executable_sha256=source["plantri_executable_sha256"],
            plantri_command=tuple(source["plantri_command"]),
            test_all_edge_pairs=options.test_all_edge_pairs,
            test_three_edge_paths=options.test_three_edge_paths,
            retain_details=True,
            retain_witness_cycles=True,
            cross_check_backtracking=False,
            candidate_output_directory=str(output_directory / "review_candidates"),
            compress_candidates=options.compress_results,
        )
        record = _analyze_worker(task)
        record["retention_reasons"] = [
            analysis for analysis, hashes in selected.items() if graph_hash in hashes
        ]
        detailed.append(record)
    path = output_directory / (
        "strong_flexibility.candidates.jsonl.gz"
        if options.compress_results
        else "strong_flexibility.candidates.jsonl"
    )
    write_jsonl_atomic(path, detailed)


def run_strong_flexibility_enumeration(
    vertex_counts: list[int],
    *,
    executable: str | Path | None,
    output_directory: Path,
    test_all_edge_pairs: bool,
    test_three_edge_paths: bool,
    output_detail: str,
    retain_top_k: int,
    compress_results: bool,
    resume: bool,
    workers: int,
    allow_other_version: bool = False,
    overwrite: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Run selected strong analyses with safe checkpoints and stable ordering."""
    if not test_all_edge_pairs and not test_three_edge_paths:
        raise ValueError("select at least one strong flexibility analysis")
    if output_detail not in {"summary", "candidates", "full"}:
        raise ValueError("output_detail must be summary, candidates, or full")
    if workers < 1 or retain_top_k < 1:
        raise ValueError("workers and retain_top_k must be positive")
    if any(order <= 0 or order % 2 for order in vertex_counts):
        raise ValueError("Barnette vertex counts must be positive and even")
    output_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = output_directory / "strong_flexibility_run_metadata.json"
    if metadata_path.exists() and not (resume or overwrite):
        raise FileExistsError(f"refusing to overwrite {metadata_path}")
    version = detect_plantri_version(
        locate_plantri(executable), allow_other_version=allow_other_version
    )
    options = FlexibilityRunOptions(
        test_all_edge_pairs=test_all_edge_pairs,
        test_three_edge_paths=test_three_edge_paths,
        output_detail=output_detail,
        retain_top_k=retain_top_k,
        compress_results=compress_results,
        workers=workers,
    )
    started_at = datetime.now(timezone.utc)
    all_records: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    graph_planar_codes: dict[str, bytes] = {}
    for order in vertex_counts:
        records, summary = _run_order(
            order,
            version,
            output_directory,
            options,
            resume=resume,
            overwrite=overwrite,
            graph_planar_codes=graph_planar_codes,
        )
        all_records.extend(records)
        summaries.append(summary)
        print(
            f"n={order}: {summary['generated_count']} graphs, "
            f"{summary.get('all_edge_sat_calls', 0)} all-edge SAT calls, "
            f"{summary.get('three_edge_path_sat_calls', 0)} path SAT calls, "
            f"{summary['total_runtime_seconds']:.6f}s"
        )

    selected = write_extremal_outputs(
        all_records,
        graph_planar_codes,
        output_directory / "extremal",
        top_k=retain_top_k,
    )
    if output_detail == "candidates":
        _candidate_details(
            selected, all_records, graph_planar_codes, output_directory, options
        )

    metadata_record = {
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_vertex_counts": vertex_counts,
        "options": asdict(options),
        "plantri": asdict(version),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "dependency_versions": _versions(),
        "solver_configuration": {
            "primary": "Glucose3",
            "independent_candidate_rerun": "MiniSat22",
            "cardinality_encoding": "PySAT sequential counter",
            "random_seed": None,
            "ordering": "deterministic plantri order and insertion-rank edge order",
        },
        "machine": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "worker_count": workers,
            "peak_memory_bytes": None,
            "peak_memory_note": (
                "not measured: reliable aggregate peak memory across spawned "
                "worker processes was unavailable without an extra monitor"
            ),
        },
        "summaries": summaries,
        "extremal_selected_hashes": selected,
    }
    temporary = metadata_path.with_name(metadata_path.name + ".tmp")
    temporary.write_text(
        json.dumps(metadata_record, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, metadata_path)
    return tuple(summaries)
