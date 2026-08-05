"""Resumable CLI: compute embedding-based ladder structural metrics for the
external hsep census through n=24.

Reads only the existing exact-hsep census (graph_certificate.json +
benchmark_result.json per graph); never computes new hsep values and never
touches hsep solver, certificate, or verifier code. Writes a new, separate
aggregated JSONL + CSV under --output-root; never overwrites an existing
completed output.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Iterator, Sequence

from barnette_search import result_storage
from barnette_search.ladder_structure_metrics import compute_ladder_parameters

CSV_FIELDNAMES = (
    "canonical_graph_hash",
    "graph_order",
    "generation_index",
    "status",
    "exact_hsep",
    "hamiltonian_cycle_count",
    "face_count_4",
    "quadrilateral_adjacency_branch_vertex_count",
    "isolated_quadrilateral_count",
    "ladder_face_coverage",
    "ladder_face_fraction",
    "ladder_max",
    "ladder_strip_count",
    "ladder_component_count",
    "closed_ladder_strip_count",
    "degenerate_closed_polychord_count",
    "best_disjoint_pair_exists",
    "best_disjoint_ladder_a",
    "best_disjoint_ladder_b",
    "best_pair_contains_ladder_max",
    "ladder_second_disjoint",
    "double_ladder_score",
    "double_ladder_score_times_2",
)


def iter_census_graph_directories(census_root: Path) -> Iterator[Path]:
    for order_directory in sorted(census_root.glob("n*")):
        if not order_directory.is_dir() or order_directory.name.startswith("."):
            continue
        for graph_directory in sorted(order_directory.iterdir()):
            if not graph_directory.is_dir():
                continue
            if (graph_directory / "graph_certificate.json").is_file() and (
                graph_directory / "benchmark_result.json"
            ).is_file():
                yield graph_directory


def build_record(certificate: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    graph_hash = str(certificate["canonical_graph_hash"])
    if str(result["canonical_graph_hash"]) != graph_hash:
        raise ValueError(f"certificate/result canonical_graph_hash mismatch for {graph_hash}")
    if int(certificate["graph_order"]) != int(result["graph_order"]):
        raise ValueError(f"certificate/result graph_order mismatch for {graph_hash}")
    parameters = compute_ladder_parameters(certificate["rotation_system"])
    record: dict[str, Any] = {
        "canonical_graph_hash": graph_hash,
        "graph_order": int(certificate["graph_order"]),
        "generation_index": int(certificate["generation_index"]),
        "status": result.get("status"),
        "exact_hsep": result.get("exact_hsep"),
        "hamiltonian_cycle_count": result.get("hamiltonian_cycle_count"),
    }
    record.update(parameters)
    return record


def write_csv(path: Path, records: Sequence[dict[str, Any]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for record in records:
            writer.writerow({name: record.get(name) for name in CSV_FIELDNAMES})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def execute(census_root: Path, output_root: Path, resume: bool) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_root / "ladder_structure_metrics.checkpoint.jsonl"
    final_jsonl = output_root / "ladder_structure_metrics.jsonl"
    final_csv = output_root / "ladder_structure_metrics.csv"

    if not resume and (checkpoint_path.exists() or final_jsonl.exists() or final_csv.exists()):
        raise FileExistsError(
            f"output already exists under {output_root}; pass --resume to continue "
            "or choose a fresh --output-root"
        )

    completed = {
        str(record["canonical_graph_hash"])
        for record in result_storage.read_checkpoint(checkpoint_path)
    }
    for graph_directory in iter_census_graph_directories(census_root):
        certificate = json.loads(
            (graph_directory / "graph_certificate.json").read_text(encoding="utf-8")
        )
        graph_hash = str(certificate["canonical_graph_hash"])
        if graph_hash in completed:
            continue
        result = json.loads(
            (graph_directory / "benchmark_result.json").read_text(encoding="utf-8")
        )
        record = build_record(certificate, result)
        result_storage.append_checkpoint(checkpoint_path, record)
        completed.add(graph_hash)

    records = sorted(
        result_storage.read_checkpoint(checkpoint_path),
        key=lambda record: (int(record["graph_order"]), int(record["generation_index"])),
    )
    result_storage.write_jsonl_atomic(final_jsonl, records)
    write_csv(final_csv, records)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    execute(args.census_root.resolve(), args.output_root.resolve(), args.resume)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
