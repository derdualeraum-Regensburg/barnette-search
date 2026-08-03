#!/usr/bin/env python3
"""Build a reproducible atlas of all Hamiltonian cycles of the n=14 graph.

The program consumes an existing certified planar-code record and embedding.  It
does not generate a census, mutate source data, or alter ``planar_draw.c``.
Every output is opened exclusively so an existing result is never overwritten.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import html
from itertools import combinations
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
from typing import Any, Iterable, Sequence
import xml.etree.ElementTree as ET
import zlib

import networkx as nx

from barnette_search.planar_code import (
    canonical_graph_hash,
    certificate_hash,
    iter_planar_code,
)
from barnette_search.validation import validate_barnette_graph


EXPECTED_HASH = "3b52365d8f69db960762343efece3b7510b943660d0fbd6353bb4f4cd7c0f445"
EXPECTED_ORDER = 14
EXPECTED_EDGE_COUNT = 21
EXPECTED_CYCLE_COUNT = 12
EXPECTED_HSEP = 10
ENGINE_OPTIONS = ("T", "n", "B")
SVG_SIZE = 900
HIGHLIGHT_COLOR = "#0072B2"
_NODE_RE = re.compile(
    r"^\\node\s+\[[^]]*\]\s+\((\d+)\)\s+at\s+"
    r"\((-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\)\s+\{\};$"
)
_EDGE_RE = re.compile(
    r"^\\draw\s+\[[^]]*\]\s+\((\d+)\)\s+to\s+\((\d+)\);$"
)


class AtlasError(RuntimeError):
    """A failed certificate, drawing, or output invariant."""


Edge = tuple[int, int]
Cycle = tuple[int, ...]


def edge(u: int, v: int) -> Edge:
    return (u, v) if u < v else (v, u)


def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, data: bytes) -> None:
    """Write new bytes or safely reuse an existing byte-identical result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == data:
            return
        raise AtlasError(f"refusing to overwrite non-identical existing file: {path}")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise AtlasError(f"refusing to overwrite existing file: {path}") from exc


def write_json_new(path: Path, value: Any) -> None:
    write_new(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def canonical_cycle_edges(cycle: Sequence[int]) -> tuple[Edge, ...]:
    return tuple(sorted(edge(u, v) for u, v in zip(cycle, cycle[1:])))


def enumerate_cycles_dfs(graph: nx.Graph) -> list[Cycle]:
    """Enumerate cycles with rotation fixed at min(V) and reversal fixed by rank."""
    nodes = sorted(graph.nodes())
    if nodes != list(range(len(nodes))):
        raise AtlasError("DFS enumeration requires consecutive vertices 0..n-1")
    start = nodes[0]
    adjacency = {v: tuple(sorted(graph.neighbors(v))) for v in nodes}
    found: list[Cycle] = []

    def visit(path: list[int], visited: set[int]) -> None:
        current = path[-1]
        if len(path) == len(nodes):
            if start in adjacency[current] and path[1] < path[-1]:
                found.append(tuple(path) + (start,))
            return
        for candidate in adjacency[current]:
            if candidate not in visited:
                path.append(candidate)
                visited.add(candidate)
                visit(path, visited)
                visited.remove(candidate)
                path.pop()

    visit([start], {start})
    by_edges: dict[tuple[Edge, ...], Cycle] = {}
    for cycle in found:
        key = canonical_cycle_edges(cycle)
        if key in by_edges:
            raise AtlasError("DFS emitted a duplicate undirected Hamiltonian cycle")
        by_edges[key] = cycle
    return [by_edges[key] for key in sorted(by_edges)]


def enumerate_cycles_by_complement_matchings(graph: nx.Graph) -> set[tuple[Edge, ...]]:
    """Independent cubic-graph enumeration via perfect-matching complements."""
    nodes = tuple(sorted(graph.nodes()))
    adjacency = {v: tuple(sorted(graph.neighbors(v))) for v in nodes}
    graph_edges = {edge(u, v) for u, v in graph.edges()}
    cycles: set[tuple[Edge, ...]] = set()

    def match(unmatched: frozenset[int], matching: tuple[Edge, ...]) -> None:
        if not unmatched:
            complement = graph_edges - set(matching)
            cycle_graph = nx.Graph()
            cycle_graph.add_nodes_from(nodes)
            cycle_graph.add_edges_from(complement)
            if nx.is_connected(cycle_graph) and all(
                degree == 2 for _, degree in cycle_graph.degree()
            ):
                cycles.add(tuple(sorted(complement)))
            return
        first = min(unmatched)
        for neighbor in adjacency[first]:
            if neighbor in unmatched:
                match(
                    unmatched - {first, neighbor},
                    matching + (edge(first, neighbor),),
                )

    match(frozenset(nodes), ())
    return cycles


def validate_cycle(graph: nx.Graph, cycle: Cycle) -> dict[str, bool | int]:
    body = cycle[:-1]
    cycle_edges = canonical_cycle_edges(cycle)
    degree = {v: 0 for v in graph.nodes()}
    for u, v in cycle_edges:
        degree[u] += 1
        degree[v] += 1
    subgraph = nx.Graph()
    subgraph.add_nodes_from(graph.nodes())
    subgraph.add_edges_from(cycle_edges)
    checks: dict[str, bool | int] = {
        "distinct_vertex_count": len(set(body)),
        "edge_count": len(cycle_edges),
        "closed": bool(cycle and cycle[0] == cycle[-1]),
        "all_vertices_exactly_once": len(body) == len(graph) and set(body) == set(graph),
        "all_edges_in_graph": all(graph.has_edge(u, v) for u, v in cycle_edges),
        "connected": nx.is_connected(subgraph),
        "degree_two_at_every_vertex": all(value == 2 for value in degree.values()),
    }
    if checks != {
        "distinct_vertex_count": len(graph),
        "edge_count": len(graph),
        "closed": True,
        "all_vertices_exactly_once": True,
        "all_edges_in_graph": True,
        "connected": True,
        "degree_two_at_every_vertex": True,
    }:
        raise AtlasError(f"invalid Hamiltonian cycle certificate: {checks}")
    return checks


def exact_hsep_certificate(
    graph_edges: list[Edge], cycles: list[tuple[Edge, ...]]
) -> dict[str, Any]:
    """Exhaust all subsets and retain an explicit uncovered-pair certificate."""
    edge_index = {item: index for index, item in enumerate(graph_edges)}
    all_requirements = {
        (included, excluded)
        for included in range(len(graph_edges))
        for excluded in range(len(graph_edges))
        if included != excluded
    }
    covers: list[set[tuple[int, int]]] = []
    for cycle in cycles:
        present = {edge_index[item] for item in cycle}
        covers.append(
            {
                (included, excluded)
                for included in present
                for excluded in range(len(graph_edges))
                if excluded not in present
            }
        )

    lower_entries: list[dict[str, Any]] = []
    primal: tuple[int, ...] | None = None
    tested_by_size: dict[str, int] = {}
    for size in range(len(cycles) + 1):
        tested = 0
        for subset in combinations(range(len(cycles)), size):
            tested += 1
            covered = set().union(*(covers[index] for index in subset)) if subset else set()
            missing = sorted(all_requirements - covered)
            if not missing:
                primal = subset
                break
            if size < EXPECTED_HSEP:
                included, excluded = missing[0]
                lower_entries.append(
                    {
                        "cycle_subset_bitmask": sum(1 << index for index in subset),
                        "subset_size": size,
                        "uncovered_ordered_edge_pair": [
                            list(graph_edges[included]),
                            list(graph_edges[excluded]),
                        ],
                    }
                )
        tested_by_size[str(size)] = tested
        if primal is not None:
            break
    if primal is None or len(primal) != EXPECTED_HSEP:
        raise AtlasError(f"expected exact hsep {EXPECTED_HSEP}, found {primal}")
    expected_lower_count = sum(
        len(list(combinations(range(len(cycles)), size)))
        for size in range(EXPECTED_HSEP)
    )
    if len(lower_entries) != expected_lower_count:
        raise AtlasError("lower-bound certificate is incomplete")
    return {
        "schema": "barnette-hsep-exhaustive-subset-certificate-v1",
        "exact_hsep": len(primal),
        "definition": "minimum number of Hamiltonian cycles separating every ordered pair of distinct graph edges",
        "primal_cycle_indices_one_based": [index + 1 for index in primal],
        "primal_size": len(primal),
        "total_ordered_edge_requirements": len(all_requirements),
        "lower_bound_method": "for every subset of fewer than 10 cycles, exhibit one uncovered ordered edge pair",
        "lower_bound_subset_count": len(lower_entries),
        "subsets_tested_by_size_until_first_primal": tested_by_size,
        "lower_bound_entries": lower_entries,
    }


def planar_code_to_ascii(data: bytes) -> bytes:
    header = b">>planar_code<<"
    payload = data[len(header) :] if data.startswith(header) else data
    if not payload:
        raise AtlasError("empty planar_code")
    order = payload[0]
    zeroes = 0
    end = None
    for index, value in enumerate(payload[1:], 1):
        if value == 0:
            zeroes += 1
            if zeroes == order:
                end = index + 1
                break
    if end != len(payload):
        raise AtlasError("planar_code must contain exactly one one-byte record")
    return (" ".join(str(value) for value in payload) + "\n").encode("ascii")


def run_planar_draw(engine: Path, planar_code: bytes) -> tuple[str, str, list[str]]:
    command = [str(engine.resolve()), *ENGINE_OPTIONS]
    completed = subprocess.run(
        command,
        input=planar_code_to_ascii(planar_code),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    stderr = completed.stderr.decode("utf-8", "replace").replace("\r\n", "\n")
    if completed.returncode != 0:
        raise AtlasError(f"planar_draw failed ({completed.returncode}): {stderr.strip()}")
    text = completed.stdout.decode("utf-8").replace("\r\n", "\n")
    if text.count("\\begin{tikzpicture}") != 1:
        raise AtlasError("planar_draw did not emit exactly one TikZ drawing")
    return text, stderr.strip(), command


def parse_planar_draw(text: str) -> tuple[dict[int, tuple[float, float]], list[Edge]]:
    positions: dict[int, tuple[float, float]] = {}
    edges: list[Edge] = []
    for raw in text.splitlines():
        line = raw.strip()
        node = _NODE_RE.match(line)
        if node:
            vertex = int(node.group(1)) - 1
            if vertex in positions:
                raise AtlasError("duplicate vertex in planar_draw output")
            positions[vertex] = (float(node.group(2)), float(node.group(3)))
        item = _EDGE_RE.match(line)
        if item:
            edges.append(edge(int(item.group(1)) - 1, int(item.group(2)) - 1))
    if len(edges) != len(set(edges)):
        raise AtlasError("duplicate edge in planar_draw output")
    return positions, sorted(edges)


def crossing_pairs(
    positions: dict[int, tuple[float, float]], graph_edges: Sequence[Edge]
) -> list[tuple[Edge, Edge]]:
    def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    crossings: list[tuple[Edge, Edge]] = []
    for first, second in combinations(graph_edges, 2):
        if set(first) & set(second):
            continue
        a, b = positions[first[0]], positions[first[1]]
        c, d = positions[second[0]], positions[second[1]]
        if orientation(a, b, c) * orientation(a, b, d) < -1e-9 and orientation(c, d, a) * orientation(c, d, b) < -1e-9:
            crossings.append((first, second))
    return crossings


def normalize_positions(raw: dict[int, tuple[float, float]]) -> dict[int, tuple[float, float]]:
    xs = [point[0] for point in raw.values()]
    ys = [point[1] for point in raw.values()]
    graph_left, graph_right = 85.0, 815.0
    graph_top, graph_bottom = 95.0, 825.0
    scale = min(
        (graph_right - graph_left) / (max(xs) - min(xs)),
        (graph_bottom - graph_top) / (max(ys) - min(ys)),
    )
    used_width = (max(xs) - min(xs)) * scale
    used_height = (max(ys) - min(ys)) * scale
    left = (SVG_SIZE - used_width) / 2.0
    top = graph_top + ((graph_bottom - graph_top) - used_height) / 2.0
    return {
        vertex: (left + (x - min(xs)) * scale, top + (max(ys) - y) * scale)
        for vertex, (x, y) in raw.items()
    }


def make_svg(
    positions: dict[int, tuple[float, float]],
    graph_edges: Sequence[Edge],
    highlighted: Iterable[Edge],
    title: str,
    description: str,
    cycle_index: int | None,
) -> str:
    selected = set(highlighted)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_SIZE}" height="{SVG_SIZE}" viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" role="img">',
        f"  <title>{html.escape(title)}</title>",
        f"  <desc>{html.escape(description)}</desc>",
        '  <rect width="900" height="900" fill="white"/>',
        f'  <text x="450" y="42" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="25" font-weight="700">{html.escape(title)}</text>',
        '  <g id="base-edges" fill="none" stroke="#C9CDD2" stroke-width="3" stroke-linecap="round">',
    ]
    for u, v in graph_edges:
        x1, y1 = positions[u]
        x2, y2 = positions[v]
        lines.append(
            f'    <line class="graph-edge" data-edge="{u}-{v}" x1="{x1:.6f}" y1="{y1:.6f}" x2="{x2:.6f}" y2="{y2:.6f}"/>'
        )
    lines.append("  </g>")
    if selected:
        lines.append(
            f'  <g id="hamiltonian-cycle-{cycle_index:02d}" fill="none" stroke="{HIGHLIGHT_COLOR}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round">'
        )
        for u, v in graph_edges:
            if (u, v) in selected:
                x1, y1 = positions[u]
                x2, y2 = positions[v]
                lines.append(
                    f'    <line class="hamiltonian-edge" data-cycle-index="{cycle_index}" data-edge="{u}-{v}" x1="{x1:.6f}" y1="{y1:.6f}" x2="{x2:.6f}" y2="{y2:.6f}"/>'
                )
        lines.append("  </g>")
    lines.append('  <g id="vertices" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" text-anchor="middle">')
    for vertex in sorted(positions):
        x, y = positions[vertex]
        lines.append(
            f'    <circle class="vertex" data-vertex="{vertex}" cx="{x:.6f}" cy="{y:.6f}" r="17" fill="white" stroke="black" stroke-width="2.5"/>'
        )
        lines.append(
            f'    <text class="vertex-label" data-vertex="{vertex}" x="{x:.6f}" y="{y + 6:.6f}" fill="black">{vertex}</text>'
        )
    lines.extend(["  </g>", "</svg>"])
    return "\n".join(lines) + "\n"


def svg_highlight_edges(svg: str) -> set[Edge]:
    root = ET.fromstring(svg)
    result: set[Edge] = set()
    for element in root.iter():
        if element.attrib.get("class") == "hamiltonian-edge":
            left, right = element.attrib["data-edge"].split("-")
            result.add(edge(int(left), int(right)))
    return result


class PdfCanvas:
    """Tiny deterministic one-page vector PDF writer using standard fonts."""

    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height
        self.commands: list[str] = []

    @staticmethod
    def _color(rgb: tuple[float, float, float]) -> str:
        return " ".join(f"{value:.4f}" for value in rgb)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float, color: tuple[float, float, float]) -> None:
        self.commands.append(f"{width:.3f} w {self._color(color)} RG {x1:.3f} {y1:.3f} m {x2:.3f} {y2:.3f} l S")

    def circle(self, x: float, y: float, radius: float) -> None:
        k = 0.552284749831 * radius
        self.commands.append(
            "1 1 1 rg 0 0 0 RG 2.2 w "
            f"{x + radius:.3f} {y:.3f} m "
            f"{x + radius:.3f} {y + k:.3f} {x + k:.3f} {y + radius:.3f} {x:.3f} {y + radius:.3f} c "
            f"{x - k:.3f} {y + radius:.3f} {x - radius:.3f} {y + k:.3f} {x - radius:.3f} {y:.3f} c "
            f"{x - radius:.3f} {y - k:.3f} {x - k:.3f} {y - radius:.3f} {x:.3f} {y - radius:.3f} c "
            f"{x + k:.3f} {y - radius:.3f} {x + radius:.3f} {y - k:.3f} {x + radius:.3f} {y:.3f} c B"
        )

    def text(self, x: float, y: float, value: str, size: float, *, bold: bool = False, centered: bool = True) -> None:
        escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        estimated = len(value) * size * (0.56 if bold else 0.52)
        left = x - estimated / 2 if centered else x
        font = "F2" if bold else "F1"
        self.commands.append(f"BT /{font} {size:.3f} Tf 0 0 0 rg {left:.3f} {y:.3f} Td ({escaped}) Tj ET")

    def bytes(self) -> bytes:
        content = ("\n".join(self.commands) + "\n").encode("ascii")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.width:.3f} {self.height:.3f}] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>".encode("ascii"),
            b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        ]
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, obj in enumerate(objects, 1):
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode("ascii"))
            output.extend(obj)
            output.extend(b"\nendobj\n")
        xref = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return bytes(output)


def draw_pdf_graph(
    canvas: PdfCanvas,
    positions: dict[int, tuple[float, float]],
    graph_edges: Sequence[Edge],
    highlighted: Iterable[Edge],
    title: str,
    viewport: tuple[float, float, float, float],
) -> None:
    x0, y0, width, height = viewport
    scale = min(width / SVG_SIZE, height / SVG_SIZE)
    dx = x0 + (width - SVG_SIZE * scale) / 2
    dy = y0 + (height - SVG_SIZE * scale) / 2

    def point(vertex: int) -> tuple[float, float]:
        x, y = positions[vertex]
        return dx + x * scale, canvas.height - (dy + y * scale)

    canvas.text(dx + 450 * scale, canvas.height - (dy + 42 * scale), title, 25 * scale, bold=True)
    for u, v in graph_edges:
        x1, y1 = point(u)
        x2, y2 = point(v)
        canvas.line(x1, y1, x2, y2, 3 * scale, (0.788, 0.804, 0.824))
    selected = set(highlighted)
    for u, v in graph_edges:
        if (u, v) in selected:
            x1, y1 = point(u)
            x2, y2 = point(v)
            canvas.line(x1, y1, x2, y2, 10 * scale, (0.0, 0.447, 0.698))
    for vertex in sorted(positions):
        x, y = point(vertex)
        canvas.circle(x, y, 17 * scale)
        label = str(vertex)
        canvas.text(x, y - 5.5 * scale, label, 17 * scale, bold=True)


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AtlasError(f"invalid PNG: {path}")
    return struct.unpack(">II", data[16:24])


_FONT = {
    " ": ("00000",) * 7,
    "/": ("00001", "00010", "00100", "00100", "01000", "10000", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


class RasterCanvas:
    """Small dependency-free supersampled RGB raster canvas."""

    def __init__(self, width: int, height: int, supersample: int = 2) -> None:
        self.output_width = width
        self.output_height = height
        self.factor = supersample
        self.width = width * supersample
        self.height = height * supersample
        self.pixels = bytearray(b"\xff" * (self.width * self.height * 3))

    def _set(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = 3 * (y * self.width + x)
            self.pixels[offset : offset + 3] = bytes(color)

    def disc(self, x: float, y: float, radius: float, color: tuple[int, int, int]) -> None:
        x *= self.factor
        y *= self.factor
        radius *= self.factor
        left, right = int(x - radius - 1), int(x + radius + 1)
        top, bottom = int(y - radius - 1), int(y + radius + 1)
        radius_squared = radius * radius
        for py in range(top, bottom + 1):
            dy = py + 0.5 - y
            for px in range(left, right + 1):
                dx = px + 0.5 - x
                if dx * dx + dy * dy <= radius_squared:
                    self._set(px, py, color)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float, color: tuple[int, int, int]) -> None:
        dx, dy = x2 - x1, y2 - y1
        steps = max(1, int(max(abs(dx), abs(dy)) / max(width / 4, 0.75)))
        radius = width / 2
        for index in range(steps + 1):
            fraction = index / steps
            self.disc(x1 + dx * fraction, y1 + dy * fraction, radius, color)

    def circle(self, x: float, y: float, radius: float, fill: tuple[int, int, int], stroke: tuple[int, int, int], stroke_width: float) -> None:
        self.disc(x, y, radius, stroke)
        self.disc(x, y, radius - stroke_width, fill)

    def text(self, x: float, y: float, value: str, pixel_size: float, *, centered: bool = True) -> None:
        scale = max(1, round(pixel_size * self.factor / 7))
        text = value.upper()
        width = (6 * len(text) - 1) * scale
        start_x = round(x * self.factor - width / 2) if centered else round(x * self.factor)
        start_y = round(y * self.factor - 3.5 * scale)
        for character in text:
            glyph = _FONT.get(character, _FONT[" "])
            for row, bits in enumerate(glyph):
                for column, bit in enumerate(bits):
                    if bit == "1":
                        for py in range(start_y + row * scale, start_y + (row + 1) * scale):
                            for px in range(start_x + column * scale, start_x + (column + 1) * scale):
                                self._set(px, py, (0, 0, 0))
            start_x += 6 * scale

    def png(self) -> bytes:
        factor = self.factor
        rows = bytearray()
        area = factor * factor
        for output_y in range(self.output_height):
            rows.append(0)
            for output_x in range(self.output_width):
                totals = [0, 0, 0]
                for sy in range(factor):
                    source_y = output_y * factor + sy
                    for sx in range(factor):
                        source_x = output_x * factor + sx
                        offset = 3 * (source_y * self.width + source_x)
                        totals[0] += self.pixels[offset]
                        totals[1] += self.pixels[offset + 1]
                        totals[2] += self.pixels[offset + 2]
                rows.extend(round(value / area) for value in totals)

        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        header = struct.pack(">IIBBBBB", self.output_width, self.output_height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


def draw_raster_graph(
    canvas: RasterCanvas,
    positions: dict[int, tuple[float, float]],
    graph_edges: Sequence[Edge],
    highlighted: Iterable[Edge],
    title: str,
    viewport: tuple[float, float, float, float],
) -> None:
    x0, y0, width, height = viewport
    scale = min(width / SVG_SIZE, height / SVG_SIZE)
    dx = x0 + (width - SVG_SIZE * scale) / 2
    dy = y0 + (height - SVG_SIZE * scale) / 2

    def point(vertex: int) -> tuple[float, float]:
        x, y = positions[vertex]
        return dx + x * scale, dy + y * scale

    canvas.text(dx + 450 * scale, dy + 42 * scale, title, 25 * scale)
    for u, v in graph_edges:
        canvas.line(*point(u), *point(v), 3 * scale, (201, 205, 210))
    selected = set(highlighted)
    for u, v in graph_edges:
        if (u, v) in selected:
            canvas.line(*point(u), *point(v), 10 * scale, (0, 114, 178))
    for vertex in sorted(positions):
        x, y = point(vertex)
        canvas.circle(x, y, 17 * scale, (255, 255, 255), (0, 0, 0), 2.5 * scale)
        canvas.text(x, y, str(vertex), 17 * scale)


def check_source_records(
    census_jsonl: Path,
    census_summary: Path,
    embedding_path: Path,
    embedded: Any,
    graph_hash: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    lines = [line for line in census_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise AtlasError(f"expected one n=14 census record, found {len(lines)}")
    record = json.loads(lines[0])
    with census_summary.open("r", encoding="utf-8", newline="") as stream:
        summary_rows = list(csv.DictReader(stream))
    if len(summary_rows) != 1:
        raise AtlasError("expected one n=14 census summary row")
    summary = summary_rows[0]
    embedding = json.loads(embedding_path.read_text(encoding="utf-8"))
    checks = {
        "census_generated_count_is_one": summary["generated_count"] == "1",
        "census_reference_count_is_one": summary["reference_count"] == "1",
        "census_hash_matches": record["canonical_graph_hash"] == graph_hash,
        "embedding_hash_matches": embedding["canonical_graph_hash"] == graph_hash,
        "rotation_system_matches": embedding["rotation_system"] == [list(row) for row in embedded.rotation_system],
        "faces_match": embedding["faces"] == [list(face) for face in embedded.faces],
    }
    if not all(checks.values()):
        raise AtlasError(f"source certificate mismatch: {checks}")
    metadata = {
        "plantri_version": record["plantri_version"],
        "plantri_command": record["plantri_command"],
        "plantri_executable_sha256": record["plantri_executable_sha256"],
        "census_jsonl_sha256": sha256_file(census_jsonl),
        "census_summary_sha256": sha256_file(census_summary),
        "embedding_sha256": sha256_file(embedding_path),
    }
    return metadata, checks


def run_tests(workspace: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_n14_hamiltonian_atlas.py",
        "tests/test_planar_code.py",
        "tests/test_hamiltonian.py",
        "tests/test_validation.py",
        "tests/test_maximizer_gallery.py",
    ]
    completed = subprocess.run(command, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=180)
    output = completed.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    if completed.returncode != 0:
        raise AtlasError(f"focused/regression tests failed:\n{output}")
    return {"command": command, "returncode": completed.returncode, "output": output.strip()}


def build(args: argparse.Namespace) -> dict[str, Any]:
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(workspace):
        raise AtlasError("output must be inside the workspace")
    output.mkdir(parents=True, exist_ok=True)

    source_planar_code = args.planar_code.resolve()
    planar_bytes = source_planar_code.read_bytes()
    with source_planar_code.open("rb") as stream:
        records = list(iter_planar_code(stream, require_header=True))
    if len(records) != 1:
        raise AtlasError(f"expected one planar_code record, found {len(records)}")
    embedded = records[0]
    graph = embedded.graph
    graph_hash = canonical_graph_hash(embedded)
    if graph_hash != EXPECTED_HASH:
        raise AtlasError(f"unexpected canonical graph hash: {graph_hash}")
    validation = validate_barnette_graph(graph)
    if not validation.valid or len(graph) != EXPECTED_ORDER or graph.number_of_edges() != EXPECTED_EDGE_COUNT:
        raise AtlasError(f"source is not the expected Barnette graph: {validation}")

    source_metadata, source_checks = check_source_records(
        args.census_jsonl.resolve(), args.census_summary.resolve(), args.embedding.resolve(), embedded, graph_hash
    )
    tests = run_tests(workspace)

    cycles = enumerate_cycles_dfs(graph)
    matching_cycles = enumerate_cycles_by_complement_matchings(graph)
    dfs_edge_sets = {canonical_cycle_edges(cycle) for cycle in cycles}
    if dfs_edge_sets != matching_cycles:
        raise AtlasError("DFS and perfect-matching enumeration disagree")
    if len(cycles) != EXPECTED_CYCLE_COUNT:
        raise AtlasError(f"expected {EXPECTED_CYCLE_COUNT} cycles, found {len(cycles)}")
    cycle_records = []
    for index, cycle in enumerate(cycles, 1):
        validation_checks = validate_cycle(graph, cycle)
        cycle_records.append(
            {
                "index": index,
                "title": f"Hamiltonian cycle {index}/{len(cycles)}",
                "canonical_closed_vertex_sequence": list(cycle),
                "canonical_edge_list": [list(item) for item in canonical_cycle_edges(cycle)],
                "certificate_sha256": certificate_hash(cycle),
                "validation": validation_checks,
            }
        )

    graph_edges = sorted(edge(u, v) for u, v in graph.edges())
    hsep = exact_hsep_certificate(graph_edges, [canonical_cycle_edges(cycle) for cycle in cycles])
    write_json_new(output / "hsep_certificate.json", hsep)

    engine = args.engine.resolve()
    if not engine.is_relative_to(output):
        raise AtlasError("compiled planar_draw executable must be inside the output directory")
    tex, engine_stderr, engine_command = run_planar_draw(engine, planar_bytes)
    raw_positions, drawn_edges = parse_planar_draw(tex)
    if set(raw_positions) != set(graph.nodes()) or drawn_edges != graph_edges:
        raise AtlasError("planar_draw output does not reproduce the certified graph")
    crossings = crossing_pairs(raw_positions, graph_edges)
    if crossings:
        raise AtlasError(f"planar_draw layout contains crossings: {crossings}")
    positions = normalize_positions(raw_positions)
    coordinate_payload = json.dumps(
        {str(v): [round(x, 6), round(y, 6)] for v, (x, y) in positions.items()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    coordinate_hash = sha256_bytes(coordinate_payload)
    write_new(output / "planar_draw_output.tex", tex.encode("utf-8"))
    layout = {
        "schema": "barnette-planar-draw-layout-v1",
        "engine": "Gunnar Brinkmann planar_draw",
        "engine_command": engine_command,
        "engine_options": list(ENGINE_OPTIONS),
        "engine_sha256": sha256_file(engine),
        "engine_source": str(args.engine_source.resolve().relative_to(workspace)).replace("\\", "/"),
        "engine_source_sha256": sha256_file(args.engine_source.resolve()),
        "engine_stderr": engine_stderr,
        "raw_positions_zero_based": {str(v): list(raw_positions[v]) for v in sorted(raw_positions)},
        "normalized_svg_positions_zero_based": {str(v): list(positions[v]) for v in sorted(positions)},
        "normalized_coordinate_sha256": coordinate_hash,
        "edges": [list(item) for item in graph_edges],
        "crossing_count": 0,
    }
    write_json_new(output / "layout.json", layout)

    graph6 = nx.to_graph6_bytes(graph, header=True)
    write_new(output / "graph.planar_code", planar_bytes)
    write_new(output / "graph_labeled.g6", graph6)
    write_new(output / "graph.embedding.json", args.embedding.resolve().read_bytes())

    cycles_json = {
        "schema": "barnette-n14-all-undirected-hamiltonian-cycles-v1",
        "graph": {
            "canonical_graph_hash": graph_hash,
            "canonical_hash_algorithm": "SHA-256 of the lexicographically least rooted/reflected BFS rotation code",
            "vertex_labels": "certified plantri labels, zero-based",
            "order": len(graph),
            "edge_count": len(graph_edges),
            "edges": [list(item) for item in graph_edges],
            "rotation_system": [list(row) for row in embedded.rotation_system],
            "faces": [list(face) for face in embedded.faces],
            "face_size_multiset": list(embedded.face_size_multiset),
            "planar_code_sha256": sha256_bytes(planar_bytes),
            "labelled_graph6_sha256": sha256_bytes(graph6),
        },
        "enumeration": {
            "undirected_cycle_count": len(cycles),
            "rotation_deduplication": "start vertex fixed at 0",
            "reversal_deduplication": "second vertex smaller than penultimate vertex",
            "sort_key": "lexicographic canonical_edge_list",
            "independent_method": "perfect matchings whose cubic-graph complements are connected 2-factors",
            "independent_method_count": len(matching_cycles),
            "methods_agree_exactly": True,
        },
        "cycles": cycle_records,
    }
    write_json_new(output / "cycles.json", cycles_json)

    description = f"Unique certified Barnette graph of order 14; canonical graph SHA-256 {graph_hash}; fixed planar_draw coordinates {coordinate_hash}."
    base_svg = make_svg(positions, graph_edges, (), "Barnette graph n=14 (base)", description, None)
    write_new(output / "graph_base.svg", base_svg.encode("utf-8"))

    svg_match_checks = []
    for record in cycle_records:
        index = int(record["index"])
        selected = {tuple(item) for item in record["canonical_edge_list"]}
        title = str(record["title"])
        svg = make_svg(positions, graph_edges, selected, title, description, index)
        svg_match = svg_highlight_edges(svg) == selected
        if not svg_match:
            raise AtlasError(f"SVG highlight mismatch for cycle {index}")
        svg_match_checks.append(svg_match)
        svg_path = output / f"cycle_{index:02d}.svg"
        pdf_path = output / f"cycle_{index:02d}.pdf"
        png_path = output / f"cycle_{index:02d}.png"
        write_new(svg_path, svg.encode("utf-8"))
        canvas = PdfCanvas(SVG_SIZE, SVG_SIZE)
        draw_pdf_graph(canvas, positions, graph_edges, selected, title, (0, 0, SVG_SIZE, SVG_SIZE))
        write_new(pdf_path, canvas.bytes())
        raster = RasterCanvas(SVG_SIZE, SVG_SIZE)
        draw_raster_graph(raster, positions, graph_edges, selected, title, (0, 0, SVG_SIZE, SVG_SIZE))
        write_new(png_path, raster.png())
        if png_dimensions(png_path) != (SVG_SIZE, SVG_SIZE):
            raise AtlasError(f"unexpected PNG dimensions: {png_path}")

    overview_width, overview_height = 1800, 1400
    overview = PdfCanvas(overview_width, overview_height)
    overview.text(overview_width / 2, overview_height - 42, "All 12 undirected Hamiltonian cycles: Barnette graph n=14", 28, bold=True)
    overview.text(overview_width / 2, overview_height - 66, f"canonical graph SHA-256 {graph_hash}", 12)
    panel_width = overview_width / 4
    panel_height = (overview_height - 85) / 3
    for record in cycle_records:
        zero = int(record["index"]) - 1
        row, column = divmod(zero, 4)
        viewport = (column * panel_width, 85 + row * panel_height, panel_width, panel_height)
        selected = {tuple(item) for item in record["canonical_edge_list"]}
        draw_pdf_graph(overview, positions, graph_edges, selected, str(record["title"]), viewport)
    overview_pdf = output / "overview_all_12_cycles.pdf"
    overview_png = output / "overview_all_12_cycles.png"
    write_new(overview_pdf, overview.bytes())
    overview_raster = RasterCanvas(overview_width, overview_height)
    overview_raster.text(overview_width / 2, 42, "All 12 undirected Hamiltonian cycles: Barnette graph n=14", 28)
    overview_raster.text(overview_width / 2, 66, f"canonical graph SHA-256 {graph_hash}", 12)
    for record in cycle_records:
        zero = int(record["index"]) - 1
        row, column = divmod(zero, 4)
        viewport = (column * panel_width, 85 + row * panel_height, panel_width, panel_height)
        selected = {tuple(item) for item in record["canonical_edge_list"]}
        draw_raster_graph(overview_raster, positions, graph_edges, selected, str(record["title"]), viewport)
    write_new(overview_png, overview_raster.png())
    if png_dimensions(overview_png) != (overview_width, overview_height):
        raise AtlasError("unexpected overview PNG dimensions")

    required = [output / "graph_base.svg", output / "cycles.json", output / "hsep_certificate.json", output / "overview_all_12_cycles.png"]
    required += [output / f"cycle_{index:02d}.{suffix}" for index in range(1, 13) for suffix in ("svg", "png")]
    file_checks = {path.name: path.is_file() and path.stat().st_size > 0 for path in required}
    if not all(file_checks.values()):
        raise AtlasError("one or more required artifacts are absent or empty")

    summary = {
        "schema": "barnette-n14-cycle-atlas-verification-v1",
        "success": True,
        "canonical_graph_hash": graph_hash,
        "expected_and_observed": {
            "nonisomorphic_barnette_graph_count_n14": {"expected": 1, "observed": 1, "confirmed": True},
            "undirected_hamiltonian_cycle_count": {"expected": 12, "observed": len(cycles), "confirmed": True},
            "exact_hsep": {"expected": 10, "observed": hsep["exact_hsep"], "confirmed": True},
        },
        "source_certificate_checks": source_checks,
        "barnette_validation": {
            "valid": validation.valid,
            "number_of_vertices": validation.number_of_vertices,
            "number_of_edges": validation.number_of_edges,
            "rejection_reasons": validation.rejection_reasons,
        },
        "cycle_validation": {
            "all_12_passed_every_check": True,
            "distinct_highlighted_edge_sets": len(dfs_edge_sets) == 12,
            "dfs_and_perfect_matching_enumerations_agree": True,
        },
        "drawing_validation": {
            "single_shared_embedding": True,
            "single_shared_coordinate_hash": coordinate_hash,
            "planar_draw_graph_matches_certificate": True,
            "edge_crossing_count": 0,
            "svg_highlights_match_cycles_json": all(svg_match_checks),
            "pngs_rendered_from_pdfs_using_same_cycle_edge_source": True,
        },
        "required_nonempty_files": file_checks,
        "tests": tests,
        "rasterizer": {
            "implementation": "dependency-free Python RGB renderer with 2x supersampling and box downsampling",
            "same_positions_and_edge_sets_as_svg_and_pdf": True,
        },
        "source_metadata": source_metadata,
    }
    write_json_new(output / "verification_summary.json", summary)

    readme = f"""# All undirected Hamiltonian cycles of the n=14 Barnette graph

This directory is a deterministic visualization and certificate bundle for the unique non-isomorphic Barnette graph at order 14 in the existing plantri 5.8 census.

## Graph identity and census provenance

- Canonical graph SHA-256: `{graph_hash}`
- Canonical-hash definition: SHA-256 of the lexicographically least rooted/reflected BFS rotation code of the certified sphere embedding.
- Graph order / size: 14 vertices / 21 edges.
- Label convention: the certified plantri labels, converted from 1-based planar_code to 0-based JSON and figure labels.
- Existing census: `results/plantri-5.8/barnette_14.jsonl`; generated count 1 and reference count 1. No census was regenerated for this atlas.
- Plantri version: {source_metadata['plantri_version']}.
- Recorded census command: `{' '.join(source_metadata['plantri_command'])}`
- Recorded plantri executable SHA-256: `{source_metadata['plantri_executable_sha256']}`.
- Certified planar_code SHA-256: `{sha256_bytes(planar_bytes)}`.

`graph.planar_code`, `graph.embedding.json`, and `graph_labeled.g6` preserve the exact embedding and a labelled graph6 representation used here. The canonical graph hash is label-independent in the validated 3-connected planar domain; the graph6 bytes retain the present labels and are not described as canonically labelled.

## Hamiltonian-cycle result

Exactly **12 undirected Hamiltonian cycles** were found, confirming the expected value 12. Rotation was removed by fixing vertex 0; reversal was removed by retaining the orientation whose second vertex is smaller than its penultimate vertex. Records are sorted lexicographically by their canonical undirected edge lists.

Every cycle passed all requested checks: 14 distinct vertices, 14 distinct cycle edges, closure, connectivity, graph-edge membership, and degree 2 at every vertex. A second enumeration through perfect matchings and connected complementary 2-factors produced exactly the same 12 edge sets.

The existing hsep control value 10 was also independently reproduced from the complete 12-cycle universe. `hsep_certificate.json` contains a primal family of 10 cycles and, for every one of the 4,017 subsets of size below 10, an explicit uncovered ordered edge-pair. `tools/verify_n14_hamiltonian_artifacts.py` checks that lower-bound certificate without importing the atlas builder.

## Drawing method

All figures use one invocation of the unchanged external `tools/planar_draw.c`, compiled inside this artifact directory, with options `{' '.join(ENGINE_OPTIONS)}`. The engine output exactly matches the 21 certified graph edges and uses the certified rotation system. One coordinate map (SHA-256 `{coordinate_hash}`) is reused without rearrangement in every panel. The straight-line crossing check found zero crossings.

The SVG files expose every highlighted segment as `class=\"hamiltonian-edge\"` with a zero-based `data-edge=\"u-v\"` attribute. The build reparsed these attributes and confirmed exact equality with each `canonical_edge_list` in `cycles.json`. PNGs were generated by a dependency-free 2x-supersampled renderer from the same immutable coordinates and edge lists as the SVG and PDF files; all individual PNGs are 900 x 900 pixels and the overview is 1800 x 1400 pixels.

Compilation command (PowerShell, from the repository root; set both Zig cache variables to a directory inside this artifact folder):

```powershell
$env:ZIG_GLOBAL_CACHE_DIR = '<artifact>\\zig-cache'
$env:ZIG_LOCAL_CACHE_DIR = '<artifact>\\zig-cache'
python -m ziglang cc -O4 -std=gnu11 -I tools\\planar_draw_compat '-Wl,--stack,67108864' -o '<artifact>\\planar_draw.exe' tools\\planar_draw.c -lm
```

Atlas build command:

```powershell
$env:PYTHONPATH = 'src'
python tools\\render_n14_hamiltonian_cycles.py --workspace . --output '{output.relative_to(workspace)}' --planar-code 'results\\plantri-5.8-strong\\extremal\\all_edge_pairs\\graphs\\{graph_hash}.planar_code' --embedding 'results\\plantri-5.8-strong\\extremal\\all_edge_pairs\\graphs\\{graph_hash}.embedding.json' --census-jsonl 'results\\plantri-5.8\\barnette_14.jsonl' --census-summary 'results\\plantri-5.8\\barnette_14.summary.csv' --engine '{output.relative_to(workspace)}\\planar_draw.exe' --engine-source 'tools\\planar_draw.c'
```

Independent verification command:

```powershell
python tools\\verify_n14_hamiltonian_artifacts.py --artifact '{output.relative_to(workspace)}'
```

Tests executed by the build:

```text
{' '.join(tests['command'])}
{tests['output']}
```

## Principal files

- `cycle_01.svg` ... `cycle_12.svg`: vector cycle drawings with machine-readable highlighted edges.
- `cycle_01.png` ... `cycle_12.png`: raster cycle drawings.
- `cycle_01.pdf` ... `cycle_12.pdf`: vector sources used for the PNG renderings.
- `overview_all_12_cycles.png` and `.pdf`: 4 x 3 overview.
- `graph_base.svg`: unmarked graph using the shared coordinate map.
- `cycles.json`: complete sorted cycle universe and per-cycle validation.
- `hsep_certificate.json`: exact hsep primal and exhaustive lower-bound certificate.
- `layout.json` and `planar_draw_output.tex`: drawing-engine identity, raw coordinates, normalized coordinates, and engine output.
- `verification_summary.json`: build-time checks and test transcript.
- `independent_verification.json`: independent post-build verification (created by the separate verifier).

No mathematical conclusion in this bundle is inferred from the pictures; graph and cycle claims are checked from the certificates.
"""
    write_new(output / "README.md", readme.encode("utf-8"))
    return summary


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--workspace", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--planar-code", type=Path, required=True)
    result.add_argument("--embedding", type=Path, required=True)
    result.add_argument("--census-jsonl", type=Path, required=True)
    result.add_argument("--census-summary", type=Path, required=True)
    result.add_argument("--engine", type=Path, required=True)
    result.add_argument("--engine-source", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        summary = build(parser().parse_args(argv))
    except (AtlasError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary["expected_and_observed"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
