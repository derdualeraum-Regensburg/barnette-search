"""Visualize exact hsep against embedding-based ladder metrics for n=24.

Reads only the existing ladder_structure_metrics.csv (itself produced
read-only from the exact-hsep census); computes no new hsep values and
touches no solver, certificate, verifier, or manuscript files.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from barnette_search.ladder_analysis import double_ladder_graph, graph_canonical_hash

JITTER_STEP = 0.06
DPI = 300
D55_HASH = graph_canonical_hash(double_ladder_graph(5, 5))


def _parse_optional_int(value: str) -> int | None:
    return None if value in ("", None) else int(value)


def _parse_optional_float(value: str) -> float | None:
    return None if value in ("", None) else float(value)


def _parse_bool(value: str) -> bool:
    return value == "True"


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [
            {
                "canonical_graph_hash": raw["canonical_graph_hash"],
                "graph_order": int(raw["graph_order"]),
                "exact_hsep": _parse_optional_int(raw["exact_hsep"]),
                "ladder_max": _parse_optional_int(raw["ladder_max"]),
                "double_ladder_score": _parse_optional_float(raw["double_ladder_score"]),
                "best_disjoint_ladder_a": _parse_optional_int(raw["best_disjoint_ladder_a"]),
                "best_disjoint_ladder_b": _parse_optional_int(raw["best_disjoint_ladder_b"]),
                "best_disjoint_pair_exists": _parse_bool(raw["best_disjoint_pair_exists"]),
            }
            for raw in csv.DictReader(handle)
        ]


def filter_order(rows: Sequence[dict[str, Any]], order: int) -> list[dict[str, Any]]:
    return [row for row in rows if row["graph_order"] == order and row["exact_hsep"] is not None]


def residual(row: dict[str, Any]) -> float | None:
    if row["double_ladder_score"] is None:
        return None
    return row["exact_hsep"] - row["double_ladder_score"]


def compute_residuals(rows: Sequence[dict[str, Any]]) -> list[float | None]:
    return [residual(row) for row in rows]


def deterministic_jitter(
    rows: Sequence[dict[str, Any]], x_key: str, y_key: str, step: float = JITTER_STEP
) -> dict[str, float]:
    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row[x_key], row[y_key]), []).append(row)
    offsets: dict[str, float] = {}
    for group in groups.values():
        ordered = sorted(group, key=lambda row: row["canonical_graph_hash"])
        count = len(ordered)
        for position, row in enumerate(ordered):
            offsets[row["canonical_graph_hash"]] = (position - (count - 1) / 2) * step
    return offsets


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = math.sqrt(variance_x * variance_y)
    return None if denominator == 0 else covariance / denominator


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        run_end = index
        while run_end + 1 < len(order) and values[order[run_end + 1]] == values[order[index]]:
            run_end += 1
        average_rank = (index + run_end) / 2 + 1
        for position in range(index, run_end + 1):
            ranks[order[position]] = average_rank
        index = run_end + 1
    return ranks


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    return None if len(xs) < 2 else _pearson(_rank(xs), _rank(ys))


def _format_correlation(pearson_r: float | None, spearman_rho: float | None) -> str:
    pearson_text = "n/a" if pearson_r is None else f"{pearson_r:.3f}"
    spearman_text = "n/a" if spearman_rho is None else f"{spearman_rho:.3f}"
    return f"Pearson r = {pearson_text}, Spearman \u03c1 = {spearman_text}"


def _apply_scientific_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.3,
            "figure.figsize": (6.0, 4.5),
        }
    )


def _save(fig: "plt.Figure", output_dir: Path, name: str, overwrite: bool) -> None:
    for suffix in ("png", "pdf"):
        target = output_dir / f"{name}.{suffix}"
        if target.exists() and not overwrite:
            raise FileExistsError(f"{target} already exists; pass --overwrite to regenerate")
    for suffix in ("png", "pdf"):
        fig.savefig(output_dir / f"{name}.{suffix}", dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def plot_scatter_hsep_vs_double_ladder_score(
    rows: Sequence[dict[str, Any]], output_dir: Path, overwrite: bool
) -> None:
    scored = [row for row in rows if row["double_ladder_score"] is not None]
    scores = [row["double_ladder_score"] for row in scored]
    hseps = [row["exact_hsep"] for row in scored]
    jitter = deterministic_jitter(scored, "double_ladder_score", "exact_hsep")
    jittered_x = [row["double_ladder_score"] + jitter[row["canonical_graph_hash"]] for row in scored]

    fig, ax = plt.subplots()
    ax.scatter(jittered_x, hseps, s=28, color="steelblue", zorder=3, label="graph (n=24)")

    axis_min = min(scores + hseps) - 1
    axis_max = max(scores + hseps) + 1
    ax.plot(
        [axis_min, axis_max],
        [axis_min, axis_max],
        linestyle="--",
        color="gray",
        linewidth=1,
        zorder=1,
        label="y = x (descriptive reference, not a bound)",
    )

    d55_matches = [row for row in scored if row["canonical_graph_hash"] == D55_HASH]
    for row in d55_matches:
        x = row["double_ladder_score"] + jitter[row["canonical_graph_hash"]]
        ax.scatter([x], [row["exact_hsep"]], s=70, color="firebrick", zorder=4, label="D(5,5)")
        ax.annotate(
            "D(5,5)",
            (x, row["exact_hsep"]),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=9,
            color="firebrick",
        )

    residuals = [(row, residual(row)) for row in scored]
    top_positive = sorted(
        (item for item in residuals if item[1] is not None),
        key=lambda item: item[1],
        reverse=True,
    )[:5]
    for rank, (row, value) in enumerate(top_positive):
        x = row["double_ladder_score"] + jitter[row["canonical_graph_hash"]]
        ax.annotate(
            f"{row['canonical_graph_hash'][:8]} (+{value:.1f})",
            (x, row["exact_hsep"]),
            textcoords="offset points",
            xytext=(8, -10 - 12 * rank),
            fontsize=7,
            color="black",
            arrowprops={"arrowstyle": "-", "color": "gray", "linewidth": 0.6},
        )

    ax.set_xlabel("double_ladder_score (descriptive, not an hsep bound)")
    ax.set_ylabel("exact hsep")
    ax.set_title(_format_correlation(_pearson(scores, hseps), _spearman(scores, hseps)), fontsize=9)
    fig.suptitle("Exact hsep vs. double-ladder score (n=24)")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    _save(fig, output_dir, "scatter_hsep_vs_double_ladder_score_n24", overwrite)


def plot_hsep_ranges_by_ladder_profile(
    rows: Sequence[dict[str, Any]], output_dir: Path, overwrite: bool
) -> None:
    profiles: dict[tuple[int, int], list[int]] = {}
    scores: dict[tuple[int, int], float] = {}
    for row in rows:
        if row["double_ladder_score"] is None:
            continue
        key = (row["best_disjoint_ladder_a"], row["best_disjoint_ladder_b"])
        profiles.setdefault(key, []).append(row["exact_hsep"])
        scores[key] = row["double_ladder_score"]
    ordered_keys = sorted(profiles, key=lambda key: scores[key])

    fig, ax = plt.subplots(figsize=(8.0, 4.5))
    for position, key in enumerate(ordered_keys):
        values = profiles[key]
        distinct_values = sorted(set(values))
        multi_valued = len(distinct_values) > 1
        color = "crimson" if multi_valued else "steelblue"
        ax.plot(
            [position, position],
            [min(distinct_values), max(distinct_values)],
            color=color,
            linewidth=2,
            zorder=1,
        )
        ax.scatter(
            [position] * len(distinct_values),
            distinct_values,
            color=color,
            s=24,
            zorder=2,
        )
        if min(distinct_values) == 11 and max(distinct_values) == 18:
            ax.annotate(
                f"{key}: hsep 11-18",
                (position, max(distinct_values)),
                textcoords="offset points",
                xytext=(4, 6),
                fontsize=8,
                color="crimson",
            )

    ax.set_xticks(range(len(ordered_keys)))
    ax.set_xticklabels([str(key) for key in ordered_keys], rotation=90, fontsize=6)
    ax.set_xlabel("ladder profile (best_disjoint_ladder_a, best_disjoint_ladder_b), sorted by double_ladder_score")
    ax.set_ylabel("observed exact hsep")
    ax.set_title(
        "hsep range per ladder profile (n=24); crimson = more than one observed hsep value",
        fontsize=9,
    )
    fig.suptitle("Observed hsep ranges by ladder profile (n=24)")
    _save(fig, output_dir, "hsep_ranges_by_ladder_profile_n24", overwrite)


def plot_residual_histogram(rows: Sequence[dict[str, Any]], output_dir: Path, overwrite: bool) -> None:
    residuals = compute_residuals(rows)
    numeric = [value for value in residuals if value is not None]
    missing_count = residuals.count(None)

    fig, ax = plt.subplots()
    ax.hist(numeric, bins=max(len(set(numeric)), 1), color="steelblue", edgecolor="black", zorder=2)
    if missing_count:
        ax.bar(
            [min(numeric) - 2 if numeric else -1],
            [missing_count],
            width=0.8,
            color="lightgray",
            edgecolor="black",
            hatch="//",
            zorder=2,
            label=f"no disjoint pair (n={missing_count})",
        )
        ax.legend(loc="upper right", fontsize=8, frameon=False)

    ax.set_xlabel("exact_hsep - double_ladder_score")
    ax.set_ylabel("number of graphs")
    fig.suptitle("Residual distribution: exact hsep minus double-ladder score (n=24)")
    ax.set_title(f"n={len(numeric)} graphs with a disjoint pair, {missing_count} without", fontsize=9)
    _save(fig, output_dir, "residual_histogram_n24", overwrite)


def plot_scatter_hsep_vs_ladder_max(
    rows: Sequence[dict[str, Any]], output_dir: Path, overwrite: bool
) -> None:
    values = [row["ladder_max"] for row in rows]
    hseps = [row["exact_hsep"] for row in rows]
    jitter = deterministic_jitter(rows, "ladder_max", "exact_hsep")
    jittered_x = [row["ladder_max"] + jitter[row["canonical_graph_hash"]] for row in rows]

    fig, ax = plt.subplots()
    ax.scatter(jittered_x, hseps, s=28, color="steelblue", zorder=2, label="graph (n=24)")
    ax.set_xlabel("ladder_max (single strongest strip length, no pairing)")
    ax.set_ylabel("exact hsep")
    ax.set_title(_format_correlation(_pearson(values, hseps), _spearman(values, hseps)), fontsize=9)
    fig.suptitle("Exact hsep vs. ladder_max (n=24) - for comparison with the pair metric")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    _save(fig, output_dir, "scatter_hsep_vs_ladder_max_n24", overwrite)


def execute(input_csv: Path, output_dir: Path, overwrite: bool) -> None:
    _apply_scientific_style()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = filter_order(load_rows(input_csv), 24)
    plot_scatter_hsep_vs_double_ladder_score(rows, output_dir, overwrite)
    plot_hsep_ranges_by_ladder_profile(rows, output_dir, overwrite)
    plot_residual_histogram(rows, output_dir, overwrite)
    plot_scatter_hsep_vs_ladder_max(rows, output_dir, overwrite)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("results/ladder-visualizations"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    execute(args.input_csv.resolve(), args.output_dir.resolve(), args.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
