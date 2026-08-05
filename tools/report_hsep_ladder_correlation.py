"""Correlation report between exact hsep and embedding-based ladder parameters.

Reads only the aggregated ladder-structure-metrics JSONL produced by
tools/compute_ladder_structure_metrics.py (which itself reads only the
existing exact-hsep census); computes no new hsep values and modifies no
solver, certificate, or verifier code. Writes a new markdown + CSV report;
never overwrites existing manuscript files.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

METRIC_FIELDS = (
    "ladder_max",
    "ladder_second_disjoint",
    "ladder_face_fraction",
    "double_ladder_score",
)


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = math.sqrt(variance_x * variance_y)
    if denominator == 0:
        return None
    return covariance / denominator


def rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        run_end = index
        while (
            run_end + 1 < len(order)
            and values[order[run_end + 1]] == values[order[index]]
        ):
            run_end += 1
        average_rank = (index + run_end) / 2 + 1
        for position in range(index, run_end + 1):
            ranks[order[position]] = average_rank
        index = run_end + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 2:
        return None
    return pearson(rank(xs), rank(ys))


def paired_values(
    records: Sequence[dict[str, Any]], metric: str
) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for record in records:
        value = record.get(metric)
        hsep = record.get("exact_hsep")
        if value is None or hsep is None:
            continue
        xs.append(float(value))
        ys.append(float(hsep))
    return xs, ys


def correlation_table(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for metric in METRIC_FIELDS:
        xs, ys = paired_values(records, metric)
        rows.append(
            {
                "metric": metric,
                "n": len(xs),
                "pearson_r": pearson(xs, ys),
                "spearman_rho": spearman(xs, ys),
            }
        )
    return rows


def profile_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(metric) for metric in METRIC_FIELDS)


def find_profile_mismatches(
    records: Sequence[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_profile: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for record in records:
        by_profile.setdefault(profile_key(record), []).append(record)
    mismatches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group in by_profile.values():
        if len(group) < 2:
            continue
        hseps = {record.get("exact_hsep") for record in group}
        if len(hseps) > 1:
            ordered = sorted(group, key=lambda record: record["canonical_graph_hash"])
            for i in range(len(ordered)):
                for j in range(i + 1, len(ordered)):
                    if ordered[i]["exact_hsep"] != ordered[j]["exact_hsep"]:
                        mismatches.append((ordered[i], ordered[j]))
    return mismatches


def find_high_hsep_low_score_outliers(
    records: Sequence[dict[str, Any]], top_count: int = 10
) -> list[dict[str, Any]]:
    candidates = [
        record
        for record in records
        if record.get("exact_hsep") is not None and record.get("double_ladder_score") is not None
    ]
    candidates.sort(
        key=lambda record: (
            record["exact_hsep"] - record["double_ladder_score"],
            -record["exact_hsep"],
        ),
        reverse=True,
    )
    return candidates[:top_count]


def write_markdown(path: Path, sections: dict[str, str]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for title, body in sections.items():
            handle.write(f"## {title}\n\n{body}\n\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def format_correlation_rows(rows: Sequence[dict[str, Any]]) -> str:
    lines = ["| metric | n | Pearson r | Spearman rho |", "| --- | --- | --- | --- |"]
    for row in rows:
        pearson_value = "n/a" if row["pearson_r"] is None else f"{row['pearson_r']:.4f}"
        spearman_value = "n/a" if row["spearman_rho"] is None else f"{row['spearman_rho']:.4f}"
        lines.append(f"| {row['metric']} | {row['n']} | {pearson_value} | {spearman_value} |")
    return "\n".join(lines)


def format_mismatches(pairs: Sequence[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    if not pairs:
        return "None found."
    lines = ["| hash A | hsep A | hash B | hsep B | shared profile |", "| --- | --- | --- | --- | --- |"]
    for left, right in pairs:
        lines.append(
            f"| {left['canonical_graph_hash'][:12]} | {left['exact_hsep']} | "
            f"{right['canonical_graph_hash'][:12]} | {right['exact_hsep']} | "
            f"{profile_key(left)} |"
        )
    return "\n".join(lines)


def format_outliers(records: Sequence[dict[str, Any]]) -> str:
    if not records:
        return "None found."
    lines = [
        "| hash | order | exact_hsep | double_ladder_score | gap |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in records:
        gap = record["exact_hsep"] - record["double_ladder_score"]
        lines.append(
            f"| {record['canonical_graph_hash'][:12]} | {record['graph_order']} | "
            f"{record['exact_hsep']} | {record['double_ladder_score']} | {gap:.1f} |"
        )
    return "\n".join(lines)


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames = ["metric", "n", "pearson_r", "spearman_rho"]
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def execute(input_jsonl: Path, output_root: Path, resume: bool) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "hsep_ladder_correlation_report.md"
    csv_path = output_root / "hsep_ladder_correlation.csv"
    if not resume and (report_path.exists() or csv_path.exists()):
        raise FileExistsError(
            f"report already exists under {output_root}; pass --resume to regenerate "
            "or choose a fresh --output-root"
        )

    records = load_records(input_jsonl)
    n24_records = [record for record in records if record["graph_order"] == 24]
    pooled_records = records

    primary_rows = correlation_table(n24_records)
    pooled_rows = correlation_table(pooled_records)
    mismatches_n24 = find_profile_mismatches(n24_records)
    mismatches_pooled = find_profile_mismatches(pooled_records)
    outliers_n24 = find_high_hsep_low_score_outliers(n24_records)

    sections = {
        "Scope": (
            f"Computed from {len(records)} graphs total ({len(n24_records)} at n=24) "
            "in the existing exact-hsep census through n=24. No new hsep values were "
            "computed. double_ladder_score is a descriptive structural statistic only, "
            "never an hsep lower bound."
        ),
        "Primary correlations (n=24 only)": format_correlation_rows(primary_rows),
        "Secondary correlations (pooled n<=24, CONFOUNDED by graph order)": format_correlation_rows(
            pooled_rows
        ),
        "Identical ladder profile, different hsep (n=24 only)": format_mismatches(mismatches_n24),
        "Identical ladder profile, different hsep (pooled, CONFOUNDED)": format_mismatches(
            mismatches_pooled
        ),
        "High hsep / low double_ladder_score outliers (n=24 only)": format_outliers(outliers_n24),
    }
    write_markdown(report_path, sections)
    write_csv(csv_path, primary_rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    execute(args.input_jsonl.resolve(), args.output_root.resolve(), args.resume)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
