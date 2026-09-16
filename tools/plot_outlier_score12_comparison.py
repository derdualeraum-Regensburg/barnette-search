"""Compare planar embeddings of n=24 graphs sharing double_ladder_score=12.

Reads only the existing exact-hsep census (graph_certificate.json) and the
independent ladder_structure_metrics module; computes no new hsep values,
touches no solver/certificate/verifier code, and never generates a random
layout. Vertex coordinates come exclusively from one certified invocation of
the unmodified external engine ``tools/planar_draw.c`` per graph.
"""

from __future__ import annotations

import argparse
import base64
import glob
import hashlib
import re
import subprocess
import sys
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

from barnette_search.ladder_structure_metrics import compute_ladder_parameters, trace_faces
from barnette_search.paths import results_root

DEFAULT_CENSUS_ROOT = results_root() / "hsep-census-through-24"
GRAPH_ORDER = 24
ENGINE_OPTIONS = ("T", "n", "B")
ENGINE_SOURCE = Path(__file__).parent / "planar_draw.c"
ENGINE_COMPAT_INCLUDE = Path(__file__).parent / "planar_draw_compat"
DPI = 300

# Okabe-Ito colorblind-safe palette.
COLOR_BEST_A = "#0072B2"
COLOR_BEST_B = "#D55E00"
COLOR_OTHER_STRIP = "#999999"
COLOR_CLOSED_STRIP = "#009E73"
COLOR_BRANCH_OR_CYCLE = "#CC79A7"
COLOR_ISOLATED_EDGE = "#000000"

# Ascending by exact_hsep: low, medium, and the +6 outlier at score 12.
SELECTED_GRAPHS = (
    {"hash_prefix": "9b4a35d4ef34", "role": "low hsep"},
    {"hash_prefix": "7ba281d5392d", "role": "medium hsep"},
    {"hash_prefix": "2ce3cb144cff", "role": "outlier (high hsep)"},
)

_NODE_RE = re.compile(r"^\\node\s+\[[^]]*\]\s+\((\d+)\)\s+at\s+\((-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\)\s+\{\};$")
_EDGE_RE = re.compile(r"^\\draw\s+\[[^]]*\]\s+\((\d+)\)\s+to\s+\((\d+)\);$")


class ComparisonError(RuntimeError):
    """A failed certificate, drawing, or output invariant."""


def _normalized_edge(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


def find_graph_directory(census_root: Path, order: int, hash_prefix: str) -> Path:
    matches = glob.glob(str(census_root / f"n{order:02d}" / f"*{hash_prefix}*"))
    if len(matches) != 1:
        raise ComparisonError(f"expected one census directory for {hash_prefix}, found {len(matches)}")
    return Path(matches[0])


def decode_planar_code(certificate: dict[str, Any]) -> bytes:
    data = base64.b64decode(certificate["planar_code_base64"], validate=True)
    if hashlib.sha256(data).hexdigest() != certificate["planar_code_sha256"]:
        raise ComparisonError("planar_code SHA-256 mismatch")
    if not data.startswith(b">>planar_code<<"):
        raise ComparisonError("planar_code header is missing")
    return data


def planar_code_to_ascii(data: bytes) -> bytes:
    header = b">>planar_code<<"
    payload = data[len(header):] if data.startswith(header) else data
    if not payload:
        raise ComparisonError("empty planar_code payload")
    order = payload[0]
    zero_count = 0
    end = None
    for index, value in enumerate(payload[1:], 1):
        if value == 0:
            zero_count += 1
            if zero_count == order:
                end = index + 1
                break
    if end is None or end != len(payload):
        raise ComparisonError("planar_code does not contain exactly one complete record")
    return (" ".join(str(value) for value in payload) + "\n").encode("ascii")


def compile_engine(engine_path: Path) -> list[str]:
    command = [
        sys.executable, "-m", "ziglang", "cc", "-O4", "-std=gnu11",
        "-I", str(ENGINE_COMPAT_INCLUDE), "-Wl,--stack,67108864",
        "-o", str(engine_path), str(ENGINE_SOURCE), "-lm",
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        raise ComparisonError(
            f"failed to compile planar_draw.c: {completed.stderr.decode('utf-8', 'replace')}"
        )
    return command


def run_planar_draw(engine_path: Path, planar_code: bytes) -> str:
    completed = subprocess.run(
        [str(engine_path), *ENGINE_OPTIONS],
        input=planar_code_to_ascii(planar_code),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ComparisonError(
            f"planar_draw failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', 'replace').strip()}"
        )
    text = completed.stdout.decode("utf-8").replace("\r\n", "\n")
    if text.count("\\begin{tikzpicture}") != 1:
        raise ComparisonError("planar_draw did not emit exactly one TikZ drawing")
    return text


def parse_planar_draw(text: str) -> tuple[dict[int, tuple[float, float]], list[tuple[int, int]]]:
    positions: dict[int, tuple[float, float]] = {}
    edges: list[tuple[int, int]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        node = _NODE_RE.match(line)
        if node:
            vertex = int(node.group(1)) - 1
            if vertex in positions:
                raise ComparisonError("duplicate vertex in planar_draw output")
            positions[vertex] = (float(node.group(2)), float(node.group(3)))
            continue
        item = _EDGE_RE.match(line)
        if item:
            edges.append(_normalized_edge(int(item.group(1)) - 1, int(item.group(2)) - 1))
    if len(edges) != len(set(edges)):
        raise ComparisonError("duplicate edge in planar_draw output")
    return positions, sorted(edges)


def crossing_pairs(
    positions: dict[int, tuple[float, float]], edges: list[tuple[int, int]]
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    def orientation(a, b, c) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def segments_cross(a, b, c, d) -> bool:
        o1 = orientation(a, b, c)
        o2 = orientation(a, b, d)
        o3 = orientation(c, d, a)
        o4 = orientation(c, d, b)
        return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)

    crossings = []
    for first, second in combinations(edges, 2):
        if set(first) & set(second):
            continue
        a, b = positions[first[0]], positions[first[1]]
        c, d = positions[second[0]], positions[second[1]]
        if segments_cross(a, b, c, d):
            crossings.append((first, second))
    return crossings


def find_best_disjoint_pair(
    strips: list[dict[str, Any]], target_a: int, target_b: int
) -> tuple[int, int]:
    """Locate two face-disjoint strips reproducing the recorded (a, b) pair."""
    best: tuple[int, int, int] | None = None
    for i, j in combinations(range(len(strips)), 2):
        left, right = strips[i], strips[j]
        if not set(left["faces"]).isdisjoint(right["faces"]):
            continue
        a, b = sorted((left["length"], right["length"]), reverse=True)
        if (a, b) != (target_a, target_b):
            continue
        candidate = (i, j)
        if best is None:
            best = candidate
    if best is None:
        raise ComparisonError(f"no disjoint pair reproduces recorded ({target_a}, {target_b})")
    return best


def load_graph(census_root: Path, hash_prefix: str) -> dict[str, Any]:
    import json

    directory = find_graph_directory(census_root, GRAPH_ORDER, hash_prefix)
    certificate = json.loads((directory / "graph_certificate.json").read_text(encoding="utf-8"))
    if certificate["canonical_graph_hash"][: len(hash_prefix)] != hash_prefix:
        raise ComparisonError(f"hash prefix mismatch in {directory}")

    result_path = directory / "hsep_certificate.json"
    exact_hsep = json.loads(result_path.read_text(encoding="utf-8"))["exact_hsep"]

    rotation = certificate["rotation_system"]
    faces = trace_faces(rotation)
    parameters = compute_ladder_parameters(rotation)
    strips = parameters["strict_ladder_strips"]
    best_index_a, best_index_b = find_best_disjoint_pair(
        strips, parameters["best_disjoint_ladder_a"], parameters["best_disjoint_ladder_b"]
    )

    planar_code = decode_planar_code(certificate)
    return {
        "hash_prefix": hash_prefix,
        "canonical_graph_hash": certificate["canonical_graph_hash"],
        "edges": [_normalized_edge(u, v) for u, v in certificate["edges"]],
        "planar_code": planar_code,
        "faces": faces,
        "parameters": parameters,
        "strips": strips,
        "best_pair_indices": (best_index_a, best_index_b),
        "exact_hsep": exact_hsep,
    }


def render_positions(engine_path: Path, graph: dict[str, Any]) -> dict[int, tuple[float, float]]:
    text = run_planar_draw(engine_path, graph["planar_code"])
    positions, drawn_edges = parse_planar_draw(text)
    if drawn_edges != sorted(graph["edges"]):
        raise ComparisonError(f"planar_draw output does not reproduce certified edges for {graph['hash_prefix']}")
    crossings = crossing_pairs(positions, drawn_edges)
    if crossings:
        raise ComparisonError(f"planar_draw layout contains crossings for {graph['hash_prefix']}: {crossings}")
    return positions


def face_category(face_index: int, graph: dict[str, Any]) -> str:
    strips = graph["strips"]
    best_a_index, best_b_index = graph["best_pair_indices"]
    if face_index in strips[best_a_index]["faces"]:
        return "best_a"
    if face_index in strips[best_b_index]["faces"]:
        return "best_b"
    for component in graph["parameters"]["quadrilateral_adjacency_component_types"]:
        if face_index in component["faces"]:
            if component["type"] == "branch" or component["type"] == "cycle":
                return "branch_or_cycle"
            if component["type"] == "isolated":
                return "isolated"
    for strip in strips:
        if face_index in strip["faces"]:
            return "other_strip"
    return "other_quad"


CATEGORY_STYLE = {
    "best_a": {"facecolor": COLOR_BEST_A, "alpha": 0.55, "label": "best disjoint pair: strip A"},
    "best_b": {"facecolor": COLOR_BEST_B, "alpha": 0.55, "label": "best disjoint pair: strip B"},
    "other_strip": {"facecolor": COLOR_OTHER_STRIP, "alpha": 0.35, "label": "other open ladder strip"},
    "closed_strip": {"facecolor": COLOR_CLOSED_STRIP, "alpha": 0.45, "label": "closed ladder strip"},
    "branch_or_cycle": {"facecolor": COLOR_BRANCH_OR_CYCLE, "alpha": 0.45, "label": "branched/cyclic quad component"},
    "isolated": {"facecolor": "none", "alpha": 1.0, "label": "isolated quadrilateral"},
    "other_quad": {"facecolor": "#DDDDDD", "alpha": 0.4, "label": None},
}


def draw_panel(ax, graph: dict[str, Any], positions: dict[int, tuple[float, float]]) -> None:
    for index, face in enumerate(graph["faces"]):
        if len(face) != 4:
            continue
        category = face_category(index, graph)
        style = CATEGORY_STYLE[category]
        polygon_points = [positions[v] for v in face]
        edgecolor = "black" if category == "isolated" else "none"
        linestyle = "dotted" if category == "isolated" else "solid"
        polygon = Polygon(
            polygon_points,
            closed=True,
            facecolor=style["facecolor"],
            alpha=style["alpha"],
            edgecolor=edgecolor,
            linestyle=linestyle,
            linewidth=1.2,
            zorder=1,
        )
        ax.add_patch(polygon)

    for u, v in graph["edges"]:
        (x1, y1), (x2, y2) = positions[u], positions[v]
        ax.plot([x1, x2], [y1, y2], color="black", linewidth=0.8, zorder=2)

    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]
    ax.scatter(xs, ys, color="black", s=6, zorder=3)

    ax.set_aspect("equal")
    ax.axis("off")


def caption_text(graph: dict[str, Any]) -> str:
    parameters = graph["parameters"]
    return (
        f"hash {graph['canonical_graph_hash'][:12]}\u2026\n"
        f"n = {GRAPH_ORDER}, exact hsep = {graph['exact_hsep']}\n"
        f"double_ladder_score = {parameters['double_ladder_score']}, "
        f"ladder_max = {parameters['ladder_max']}\n"
        f"ladder profile ({parameters['best_disjoint_ladder_a']}, "
        f"{parameters['best_disjoint_ladder_b']})"
    )


def build_figure(graphs: list[dict[str, Any]], positions_by_graph: list[dict[int, tuple[float, float]]]):
    fig, axes = plt.subplots(1, len(graphs), figsize=(5.0 * len(graphs), 5.6))
    for ax, graph, positions, role in zip(
        axes, graphs, positions_by_graph, (item["role"] for item in SELECTED_GRAPHS)
    ):
        draw_panel(ax, graph, positions)
        ax.set_title(role, fontsize=11)
        ax.text(
            0.5, -0.06, caption_text(graph),
            transform=ax.transAxes, ha="center", va="top", fontsize=8, linespacing=1.4,
        )

    legend_handles = [
        Polygon([(0, 0)], closed=True, facecolor=style["facecolor"], alpha=style["alpha"], label=style["label"])
        for style in CATEGORY_STYLE.values()
        if style["label"] is not None
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=3, fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.08))
    fig.suptitle(
        "Graphs sharing double_ladder_score = 12 (n=24): why does the outlier reach hsep 18?",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    return fig


def _save_figure(fig, output_dir: Path, name: str, overwrite: bool) -> None:
    for suffix in ("png", "pdf"):
        target = output_dir / f"{name}.{suffix}"
        if target.exists() and not overwrite:
            raise FileExistsError(f"{target} already exists; pass --overwrite to regenerate")
    for suffix in ("png", "pdf"):
        fig.savefig(output_dir / f"{name}.{suffix}", dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def build_markdown(graphs: list[dict[str, Any]]) -> str:
    lines = [
        "# Outlier comparison: double_ladder_score = 12 at n = 24",
        "",
        "Three graphs from the exact n=24 hsep census share `double_ladder_score = 12`",
        "(ladder profile (3, 3)) but have markedly different `exact_hsep` values.",
        "`double_ladder_score` is a descriptive structural statistic derived from the",
        "best face-disjoint pair of open quadrilateral ladder strips; it is not a",
        "lower or upper bound on hsep.",
        "",
        "## Selected graphs",
        "",
        "| role | canonical hash (short) | exact_hsep | face_count_4 | ladder_strip_count | ladder profile |",
        "|---|---|---|---|---|---|",
    ]
    for graph, item in zip(graphs, SELECTED_GRAPHS):
        parameters = graph["parameters"]
        lines.append(
            f"| {item['role']} | `{graph['canonical_graph_hash'][:12]}` | {graph['exact_hsep']} | "
            f"{parameters['face_count_4']} | {parameters['ladder_strip_count']} | "
            f"({parameters['best_disjoint_ladder_a']}, {parameters['best_disjoint_ladder_b']}) |"
        )
    lines += [
        "",
        "## Observed structural differences",
        "",
        "- All three graphs have exactly one best face-disjoint pair of length-3 open",
        "  ladder strips, giving the same `double_ladder_score = 12`.",
        "- The low- and medium-hsep graphs share an identical quadrilateral-face count",
        "  (9) and identical strip/component counts (3 strips, 3 components), yet their",
        "  `exact_hsep` differs (11 vs. 15) - the summary counts alone do not determine hsep.",
        "- The clearest visible difference is the relative *placement* of the two",
        "  best-pair strips around the embedding, not just their lengths: in the",
        "  low-hsep graph the two strips (blue/orange) sit on opposite sides of the",
        "  octagonal outer structure, separated by the third, unused strip (gray) on",
        "  each side. In the medium-hsep graph the two strips are diagonally adjacent,",
        "  sharing a common corner region. In the outlier they are clustered on the same",
        "  side of the graph, immediately next to each other, with the unused strip and",
        "  remaining faces pushed entirely to the opposite side.",
        "- The outlier graph also has one fewer quadrilateral face overall (8 instead of",
        "  9) and a different non-quadrilateral face-size profile (four hexagons and two",
        "  octagons, instead of two hexagons and three octagons), while still reaching",
        "  the same best-pair length (3, 3); its third (non-selected) ladder strip is",
        "  correspondingly shorter.",
        "- This indicates that `double_ladder_score` captures only the lengths of the",
        "  single best disjoint strip pair and is blind to where that pair sits relative",
        "  to the rest of the embedding - a plausible structural explanation for why the",
        "  outlier's exact_hsep exceeds the other two despite an identical score.",
        "",
        "## Figure",
        "",
        "See `outlier_score12_comparison.png` / `.pdf` in this directory.",
        "",
    ]
    return "\n".join(lines)


def execute(census_root: Path, output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    graphs = [load_graph(census_root, item["hash_prefix"]) for item in SELECTED_GRAPHS]

    with tempfile.TemporaryDirectory() as build_directory:
        engine_path = Path(build_directory) / ("planar_draw.exe" if sys.platform == "win32" else "planar_draw")
        compile_engine(engine_path)
        positions_by_graph = [render_positions(engine_path, graph) for graph in graphs]

    fig = build_figure(graphs, positions_by_graph)
    _save_figure(fig, output_dir, "outlier_score12_comparison", overwrite)

    markdown_path = output_dir / "outlier_score12_comparison.md"
    if markdown_path.exists() and not overwrite:
        raise FileExistsError(f"{markdown_path} already exists; pass --overwrite to regenerate")
    markdown_path.write_text(build_markdown(graphs), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census-root", type=Path, default=DEFAULT_CENSUS_ROOT)
    parser.add_argument("--output-dir", type=Path, default=Path("results/ladder-visualizations"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    execute(args.census_root.resolve(), args.output_dir.resolve(), args.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
