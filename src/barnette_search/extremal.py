"""Publication-oriented ranking and extraction of extremal graph instances."""

from __future__ import annotations

from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

from .flexibility_common import percentile
from .planar_code import iter_planar_code


RANKING_METRICS = (
    "number_of_witness_cycles",
    "witness_cover_ratio",
    "total_sat_wall_time_seconds",
    "maximum_query_time_seconds",
    "total_subtour_constraints",
    "p99_query_time_seconds",
)
TIMING_METRICS = {
    "total_sat_wall_time_seconds",
    "maximum_query_time_seconds",
    "p99_query_time_seconds",
}


def _statistics(values: list[float]) -> dict[str, float]:
    if not values:
        return {name: 0.0 for name in ("minimum", "median", "mean", "p95", "p99", "maximum")}
    return {
        "minimum": min(values),
        "median": median(values),
        "mean": mean(values),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "maximum": max(values),
    }


def _save_graph_artifacts(
    record: dict[str, Any], planar_code: bytes, directory: Path
) -> None:
    graph_hash = record["canonical_graph_hash"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{graph_hash}.planar_code").write_bytes(planar_code)
    from io import BytesIO

    [embedded] = iter_planar_code(BytesIO(planar_code), require_header=True)
    embedding_record = {
        "canonical_graph_hash": graph_hash,
        "rotation_system": embedded.rotation_system,
        "faces": embedded.faces,
        "face_size_multiset": embedded.face_size_multiset,
        "plantri_command": record["plantri_command"],
    }
    (directory / f"{graph_hash}.embedding.json").write_text(
        json.dumps(embedding_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / f"{graph_hash}.txt").write_text(
        "\n".join(
            (
                f"Canonical graph hash: {graph_hash}",
                f"Graph order: {record['requested_vertex_count']}",
                f"plantri command: {' '.join(record['plantri_command'])}",
                "Timing rankings are machine-dependent benchmarks, not invariant complexity measures.",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def write_extremal_outputs(
    records: list[dict[str, Any]],
    graph_planar_codes: dict[str, bytes],
    output_directory: Path,
    *,
    top_k: int,
) -> dict[str, list[str]]:
    """Write leaderboards, graph artifacts, and order-comparison statistics."""
    selected: dict[str, list[str]] = {}
    output_directory.mkdir(parents=True, exist_ok=True)
    for analysis in ("all_edge_pairs", "three_edge_paths"):
        analysis_records = [record for record in records if analysis in record]
        if not analysis_records:
            continue
        analysis_directory = output_directory / analysis
        analysis_directory.mkdir(parents=True, exist_ok=True)
        selected_hashes: set[str] = set()
        for metric in RANKING_METRICS:
            ranked = sorted(
                analysis_records,
                key=lambda record: (
                    -float(record[analysis][metric]),
                    record["canonical_graph_hash"],
                ),
            )
            leaderboard = analysis_directory / f"leaderboard_{metric}.csv"
            with leaderboard.open("w", encoding="utf-8", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(
                    (
                        "rank",
                        "canonical_graph_hash",
                        "vertex_count",
                        "value",
                        "machine_dependent_timing",
                        "plantri_command",
                    )
                )
                for rank, record in enumerate(ranked[:top_k], start=1):
                    writer.writerow(
                        (
                            rank,
                            record["canonical_graph_hash"],
                            record["requested_vertex_count"],
                            record[analysis][metric],
                            metric in TIMING_METRICS,
                            " ".join(record["plantri_command"]),
                        )
                    )
                    selected_hashes.add(record["canonical_graph_hash"])
        selected[analysis] = sorted(selected_hashes)
        graph_directory = analysis_directory / "graphs"
        by_hash = {record["canonical_graph_hash"]: record for record in records}
        for graph_hash in sorted(selected_hashes):
            _save_graph_artifacts(
                by_hash[graph_hash], graph_planar_codes[graph_hash], graph_directory
            )

        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for record in analysis_records:
            grouped[int(record["requested_vertex_count"])].append(record)
        with (analysis_directory / "order_comparison.csv").open(
            "w", encoding="utf-8", newline=""
        ) as output:
            writer = csv.writer(output)
            writer.writerow(
                (
                    "vertex_count",
                    "metric",
                    "minimum",
                    "median",
                    "mean",
                    "p95",
                    "p99",
                    "maximum",
                    "machine_dependent_timing",
                )
            )
            for order in sorted(grouped):
                for metric in RANKING_METRICS:
                    stats = _statistics(
                        [float(record[analysis][metric]) for record in grouped[order]]
                    )
                    writer.writerow(
                        (order, metric, *stats.values(), metric in TIMING_METRICS)
                    )
    return selected
