#!/usr/bin/env python3
"""Build the deterministic Bauer double-ladder scientific figure gallery.

The script is a visualization-only consumer of immutable certificate packages.
It never enumerates graphs or Hamiltonian cycles and never solves hsep.
"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import math
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draw_single_maximizer import (  # noqa: E402
    GalleryError,
    atomic_json,
    atomic_write,
    decode_planar_code,
    load_certified_maximizer,
    parse_planar_tikz,
    run_engine,
    sha256_file,
    verify_tikz_graph,
)


SCHEMA = "bauer-double-ladder-gallery-v1"
ENGINE_OPTIONS = ("T", "n")
INDIVIDUAL_SIZE = (1200, 1200)
PNG_SCALE = 2
COLORS = {
    "ink": "#172033",
    "muted": "#64748B",
    "grid": "#CBD5E1",
    "a_rail": "#2563EB",
    "a_rung": "#1D4ED8",
    "b_rail": "#D97706",
    "b_rung": "#B45309",
    "connector": "#7C3AED",
    "inserted": "#15803D",
    "cap": "#94A3B8",
    "paper": "#FFFFFF",
}


@dataclass
class GraphData:
    label: str
    stem: str
    a: int
    b: int
    order: int
    edge_count: int
    graph_hash: str
    edges: list[tuple[int, int]]
    faces: list[list[int]]
    face_size_multiset: list[int]
    labels: dict[int, tuple[str, int, int]]
    planar_code: bytes
    planar_code_sha256: str
    exact_hsep: int
    hamiltonian_cycle_count: int
    status: str
    certified_extremal: bool
    source_files: list[Path]
    inserted_vertices: list[int]
    generation_index: int | None = None
    plantri_rank: int | None = None


def _edge(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _face_sizes_text(sizes: list[int]) -> str:
    counts: dict[int, int] = {}
    for size in sizes:
        counts[size] = counts.get(size, 0) + 1
    return ", ".join(f"{size}^{counts[size]}" for size in sorted(counts))


def _verify_manifest_entry(root: Path, relative: str) -> None:
    manifest = root / "SHA256SUMS.txt"
    entries = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        entries[name.replace("\\", "/")] = digest
    key = relative.replace("\\", "/")
    if key not in entries:
        raise GalleryError(f"{key} is absent from {manifest}")
    actual = sha256_file(root / relative)
    if actual != entries[key]:
        raise GalleryError(f"immutable input checksum mismatch: {root / relative}")


def _certified_insertions(ladder_root: Path) -> dict[str, list[int]]:
    payload = _json(ladder_root / "expansion_certificates.json")
    result: dict[str, list[int]] = {}
    for record in payload["unique_double_ladder_certificates"]:
        result[record["target_hash"]] = sorted(
            int(v)
            for v in record["artifact_label_witness"][
                "inserted_vertices_target_artifact"
            ]
        )
    return result


def _small_double_ladder_mapping(
    edges: list[tuple[int, int]], a: int, b: int
) -> dict[int, tuple[str, int, int]]:
    """Find a deterministic exact isomorphism without a graph library."""
    model_vertices = [(name, column, rail)
                      for name, length in (("A", a), ("B", b))
                      for column in range(length + 1) for rail in (0, 1)]
    model_edges: set[frozenset[tuple[str, int, int]]] = set()
    for name, length in (("A", a), ("B", b)):
        for column in range(length + 1):
            model_edges.add(frozenset(((name, column, 0), (name, column, 1))))
        for column in range(length):
            for rail in (0, 1):
                model_edges.add(frozenset(((name, column, rail), (name, column + 1, rail))))
    model_edges.update((
        frozenset((("A", 0, 0), ("B", 0, 0))),
        frozenset((("A", 0, 1), ("B", b, 0))),
        frozenset((("A", a, 0), ("B", 0, 1))),
        frozenset((("A", a, 1), ("B", b, 1))),
    ))
    graph_vertices = sorted({v for edge in edges for v in edge})
    graph_adj = {v: set() for v in graph_vertices}
    model_adj = {v: set() for v in model_vertices}
    for u, v in edges:
        graph_adj[u].add(v); graph_adj[v].add(u)
    for edge in model_edges:
        u, v = tuple(edge)
        model_adj[u].add(v); model_adj[v].add(u)
    mappings: list[dict[int, tuple[str, int, int]]] = []

    def visit(mapping: dict[int, tuple[str, int, int]], unused: set[tuple[str, int, int]]) -> None:
        if len(mapping) == len(graph_vertices):
            mappings.append(dict(mapping)); return
        remaining = [v for v in graph_vertices if v not in mapping]
        vertex = min(remaining, key=lambda v: (-sum(n in mapping for n in graph_adj[v]), v))
        for candidate in sorted(unused):
            if all((other in graph_adj[vertex]) == (mapped in model_adj[candidate])
                   for other, mapped in mapping.items()):
                mapping[vertex] = candidate
                visit(mapping, unused - {candidate})
                del mapping[vertex]

    visit({}, set(model_vertices))
    if not mappings:
        raise GalleryError(f"certified graph is not isomorphic to D({a},{b})")
    return min(mappings, key=lambda mapping: tuple(mapping[v] for v in graph_vertices))


def load_graphs(sequence_root: Path, prediction_root: Path) -> list[GraphData]:
    ladder_root = sequence_root / "ladder-analysis"
    _verify_manifest_entry(ladder_root, "ladder_family.json")
    _verify_manifest_entry(ladder_root, "expansion_certificates.json")
    family = _json(ladder_root / "ladder_family.json")
    graph_by_hash = {g["canonical_graph_hash"]: g for g in family["graphs"]}
    inserted_by_hash = _certified_insertions(ladder_root)
    result: list[GraphData] = []

    for member in family["unique_double_ladder_sequence"]:
        order = int(member["order"])
        graph_hash = member["hash"]
        order_root = sequence_root / f"order_{order:02d}"
        for name in ("graph_certificates.jsonl.gz", "exact_certificates.jsonl.gz"):
            _verify_manifest_entry(order_root, name)
        summary, graph_cert, exact_cert = load_certified_maximizer(
            sequence_root, order, graph_hash
        )
        a = int(member["parameters"]["first_ladder_length"])
        b = int(member["parameters"]["second_ladder_length"])
        graph = graph_by_hash.get(graph_hash)
        if graph is not None:
            canonical_to_artifact = [int(v) for v in graph["canonical_embedding"]["canonical_to_original"]]
            translated_edges = sorted(
                _edge(canonical_to_artifact[int(u)], canonical_to_artifact[int(v)])
                for u, v in graph["canonical_edge_list"]
            )
            if translated_edges != sorted(_edge(int(u), int(v)) for u, v in graph_cert["edges"]):
                raise GalleryError(f"ladder/graph certificate edge mismatch for {graph_hash}")
            if graph["exact_hsep"] != exact_cert["exact_hsep"]:
                raise GalleryError(f"ladder/exact certificate mismatch for {graph_hash}")
            labels = {
                canonical_to_artifact[int(v)]: (str(model[0]), int(model[1]), int(model[2]))
                for v, model in graph["double_ladder"]["canonical_vertex_to_model"]
            }
            canonical_edges = graph_cert["edges"]
            faces = graph_cert["faces"]
            face_sizes = graph["face_size_multiset"]
        else:
            canonical_edges = graph_cert["edges"]
            faces = graph_cert["faces"]
            face_sizes = graph_cert["face_size_multiset"]
            labels = _small_double_ladder_mapping(
                [_edge(int(u), int(v)) for u, v in canonical_edges], a, b
            )
        planar_code = decode_planar_code(graph_cert)
        result.append(
            GraphData(
                label=f"D({a},{b})",
                stem=f"D_{a}_{b}",
                a=a,
                b=b,
                order=order,
                edge_count=int(graph_cert["edge_count"]),
                graph_hash=graph_hash,
                edges=[_edge(int(u), int(v)) for u, v in canonical_edges],
                faces=[[int(v) for v in face] for face in faces],
                face_size_multiset=[int(v) for v in face_sizes],
                labels=labels,
                planar_code=planar_code,
                planar_code_sha256=graph_cert["planar_code_sha256"],
                exact_hsep=int(member["exact_hsep"]),
                hamiltonian_cycle_count=int(member["complete_hamiltonian_cycle_count"]),
                status="certified unique Barnie-sequence maximizer",
                certified_extremal=True,
                source_files=[
                    ladder_root / "ladder_family.json",
                    ladder_root / "expansion_certificates.json",
                    order_root / "graph_certificates.jsonl.gz",
                    order_root / "exact_certificates.jsonl.gz",
                    order_root / "order_summary.json",
                ],
                inserted_vertices=inserted_by_hash.get(graph_hash, []),
                generation_index=int(graph_cert["generation_index"]),
                plantri_rank=int(graph_cert["plantri_rank"]),
            )
        )

    for directory in ("D_9_9", "D_11_9", "D_11_11"):
        root = prediction_root / directory
        for name in (
            "graph.json",
            "independent_verification.json",
            "expansion_certificate.json",
        ):
            _verify_manifest_entry(root, name)
        graph = _json(root / "graph.json")
        verification = _json(root / "independent_verification.json")
        expansion = _json(root / "expansion_certificate.json")
        if verification["status"] != "pass":
            raise GalleryError(f"prediction package verification did not pass: {root}")
        a = int(graph["parameters"]["a"])
        b = int(graph["parameters"]["b"])
        labels = {
            int(v): (str(model[0]), int(model[1]), int(model[2]))
            for v, model in graph["model_vertex_labels"]
        }
        planar_code = base64.b64decode(graph["planar_code_base64"], validate=True)
        if _sha256_bytes(planar_code) != graph["planar_code_sha256"]:
            raise GalleryError(f"planar_code checksum mismatch in {root}")
        result.append(
            GraphData(
                label=f"D({a},{b})",
                stem=f"D_{a}_{b}",
                a=a,
                b=b,
                order=int(graph["order"]),
                edge_count=int(graph["edge_count"]),
                graph_hash=graph["canonical_graph_hash"],
                edges=[_edge(int(u), int(v)) for u, v in graph["canonical_edge_list"]],
                faces=[[int(v) for v in face] for face in graph["faces"]],
                face_size_multiset=[int(v) for v in graph["face_size_multiset"]],
                labels=labels,
                planar_code=planar_code,
                planar_code_sha256=graph["planar_code_sha256"],
                exact_hsep=int(verification["exact_hsep"]),
                hamiltonian_cycle_count=int(verification["hamiltonian_cycle_count"]),
                status=(
                    "proved double-ladder family member; global Barnette extremality "
                    "at this order is not established"
                ),
                certified_extremal=False,
                source_files=[
                    root / "graph.json",
                    root / "independent_verification.json",
                    root / "expansion_certificate.json",
                    root / "primal_hsep_certificate.json",
                    root / "lower_bound_certificate.json",
                    root / "structural_cycle_classes.json",
                ],
                inserted_vertices=sorted(
                    int(v) for v in expansion["inserted_vertices_target_labels"]
                ),
            )
        )

    result.sort(key=lambda graph: graph.order)
    expected = [(1, 1), (3, 1), (3, 3), (5, 3), (5, 5), (7, 5),
                (7, 7), (9, 7), (9, 9), (11, 9), (11, 11)]
    if [(g.a, g.b) for g in result] != expected:
        raise GalleryError("double-ladder input sequence is incomplete or out of order")
    return result


def classify_edge(graph: GraphData, edge: tuple[int, int]) -> str:
    left, right = (graph.labels[edge[0]], graph.labels[edge[1]])
    if left[0] != right[0]:
        return "connector"
    prefix = left[0].lower()
    if left[1] == right[1] and left[2] != right[2]:
        return f"{prefix}_rung"
    if left[2] == right[2] and abs(left[1] - right[1]) == 1:
        return f"{prefix}_rail"
    raise GalleryError(f"edge {edge} has no double-ladder class in {graph.label}")


def is_ladder_cell(graph: GraphData, face: list[int]) -> bool:
    models = [graph.labels[v] for v in face]
    return (
        len(face) == 4
        and len({model[0] for model in models}) == 1
        and len({model[1] for model in models}) == 2
        and max(model[1] for model in models) - min(model[1] for model in models) == 1
        and {model[2] for model in models} == {0, 1}
    )


def cap_faces(graph: GraphData) -> list[list[int]]:
    caps = [face for face in graph.faces if not is_ladder_cell(graph, face)]
    if len(caps) != 4:
        raise GalleryError(f"expected four cap faces in {graph.label}, found {len(caps)}")
    return caps


def choose_outer_cap(graph: GraphData) -> list[int]:
    """Choose the A, rail-0 cap deterministically, including degenerate a=1."""
    def score(face: list[int]) -> tuple[int, int, int, tuple[int, ...]]:
        models = [graph.labels[v] for v in face]
        a0 = sum(model[0] == "A" and model[2] == 0 for model in models)
        a_count = sum(model[0] == "A" for model in models)
        b0 = sum(model[0] == "B" and model[2] == 0 for model in models)
        return (a0, a_count, b0, tuple(-v for v in face))

    return list(max(cap_faces(graph), key=score))


def align_layout(
    graph: GraphData, engine_vertices: dict[int, tuple[float, float]]
) -> tuple[dict[int, tuple[float, float]], dict[str, Any]]:
    raw = {vertex - 1: point for vertex, point in engine_vertices.items()}

    def endpoint_center(ladder: str, index: int) -> tuple[float, float]:
        pts = [raw[v] for v, label in graph.labels.items()
               if label[0] == ladder and label[1] == index]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    vectors = []
    for ladder, maximum in (("A", graph.a), ("B", graph.b)):
        start, end = endpoint_center(ladder, 0), endpoint_center(ladder, maximum)
        vectors.append((end[0] - start[0], end[1] - start[1]))
    if vectors[0][0] * vectors[1][0] + vectors[0][1] * vectors[1][1] < 0:
        vectors[1] = (-vectors[1][0], -vectors[1][1])
    dx, dy = vectors[0][0] + vectors[1][0], vectors[0][1] + vectors[1][1]
    norm = math.hypot(dx, dy)
    if norm < 1e-9:
        raise GalleryError(f"degenerate alignment axis for {graph.label}")
    axis = (dx / norm, dy / norm)
    cross = (-axis[1], axis[0])
    aligned = {
        v: (point[0] * cross[0] + point[1] * cross[1],
            point[0] * axis[0] + point[1] * axis[1])
        for v, point in raw.items()
    }
    mean_a = sum(aligned[v][0] for v, label in graph.labels.items() if label[0] == "A") / (2 * (graph.a + 1))
    mean_b = sum(aligned[v][0] for v, label in graph.labels.items() if label[0] == "B") / (2 * (graph.b + 1))
    reflected = mean_a > mean_b
    if reflected:
        aligned = {v: (-x, y) for v, (x, y) in aligned.items()}
    return aligned, {
        "axis_unit_vector_in_engine_coordinates": [axis[0], axis[1]],
        "cross_axis_unit_vector_in_engine_coordinates": [cross[0], cross[1]],
        "reflected_to_place_A_left_of_B": reflected,
        "translation": "centering during viewport normalization",
        "scaling": "uniform during viewport normalization",
        "topology_change": False,
    }


def normalize_positions(
    positions: dict[int, tuple[float, float]], box: tuple[float, float, float, float]
) -> tuple[dict[int, tuple[float, float]], dict[str, float]]:
    left, top, right, bottom = box
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    scale = min((right - left) / max(width, 1.0), (bottom - top) / max(height, 1.0))
    used_w, used_h = width * scale, height * scale
    x0 = left + (right - left - used_w) / 2.0
    y0 = top + (bottom - top - used_h) / 2.0
    normalized = {
        v: (x0 + (x - min(xs)) * scale, y0 + (y - min(ys)) * scale)
        for v, (x, y) in positions.items()
    }
    return normalized, {"scale": scale, "translate_x": x0 - min(xs) * scale,
                        "translate_y": y0 - min(ys) * scale}


def _line(scene: list[dict[str, Any]], x1: float, y1: float, x2: float, y2: float,
          color: str, width: float, dash: str | None = None, **extra: Any) -> None:
    scene.append({"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                  "color": color, "width": width, "dash": dash, **extra})


def _text(scene: list[dict[str, Any]], x: float, y: float, value: str, size: float,
          color: str = COLORS["ink"], anchor: str = "middle", weight: str = "normal") -> None:
    scene.append({"kind": "text", "x": x, "y": y, "text": value, "size": size,
                  "color": color, "anchor": anchor, "weight": weight})


def graph_scene(
    graph: GraphData,
    aligned: dict[int, tuple[float, float]],
    *,
    annotated: bool,
) -> tuple[list[dict[str, Any]], dict[int, tuple[float, float]], dict[str, Any]]:
    scene: list[dict[str, Any]] = [{"kind": "rect", "x": 0, "y": 0, "w": 1200,
                                   "h": 1200, "fill": COLORS["paper"]}]
    box = (65.0, 75.0, 865.0 if annotated else 1135.0, 1075.0)
    pos, norm = normalize_positions(aligned, box)

    if annotated:
        for face_index, face in enumerate(cap_faces(graph)):
            scene.append({"kind": "polyline", "points": [pos[v] for v in face],
                          "closed": True, "color": COLORS["cap"], "width": 7.5,
                          "dash": "3 8", "opacity": 0.42,
                          "overlay": "cap", "cap_index": face_index})

    for u, v in graph.edges:
        cls = classify_edge(graph, (u, v))
        color = COLORS[cls] if annotated else COLORS["ink"]
        dash = "8 6" if annotated and cls.endswith("rung") else None
        if annotated and cls == "connector":
            dash = "12 5 3 5"
        _line(scene, *pos[u], *pos[v], color, 4.5 if annotated else 3.8, dash,
              edge=[u, v], edge_class=cls)

    if annotated and graph.inserted_vertices:
        inserted = set(graph.inserted_vertices)
        for u, v in graph.edges:
            if u in inserted and v in inserted:
                _line(scene, *pos[u], *pos[v], COLORS["inserted"], 5.5, "10 7",
                      overlay="latest_insertion")

    for vertex in sorted(pos):
        x, y = pos[vertex]
        inserted = annotated and vertex in graph.inserted_vertices
        scene.append({"kind": "circle", "x": x, "y": y, "r": 8.0 if inserted else 6.2,
                      "fill": "#DCFCE7" if inserted else "#FFFFFF",
                      "stroke": COLORS["inserted"] if inserted else COLORS["ink"],
                      "width": 3.5 if inserted else 2.3, "vertex": vertex})

    if annotated:
        _text(scene, 60, 43, f"{graph.label}   n={graph.order}   hsep={graph.exact_hsep}   H={graph.hamiltonian_cycle_count}",
              27, anchor="start", weight="bold")
        legend = [
            ("A rails", "a_rail", None), ("A rungs", "a_rung", "8 6"),
            ("B rails", "b_rail", None), ("B rungs", "b_rung", "8 6"),
            ("connectors", "connector", "12 5 3 5"),
            ("cap boundary", "cap", "3 8"),
            ("latest insertion", "inserted", None),
        ]
        for index, (label, color_key, dash) in enumerate(legend):
            y = 225 + index * 62
            _line(scene, 920, y, 995, y, COLORS[color_key], 7 if color_key == "inserted" else 4.5, dash)
            _text(scene, 1015, y + 7, label, 22, anchor="start")
        _text(scene, 920, 145, "STRUCTURE", 21, anchor="start", weight="bold")
        _text(scene, 920, 705, f"a = {graph.a}", 25, anchor="start", color=COLORS["a_rail"], weight="bold")
        _text(scene, 920, 748, f"b = {graph.b}", 25, anchor="start", color=COLORS["b_rail"], weight="bold")
        _text(scene, 920, 815, f"faces: {_face_sizes_text(graph.face_size_multiset)}", 19, anchor="start")
        status = "certified global maximizer" if graph.certified_extremal else "family theorem; extremality open"
        _text(scene, 920, 865, status, 17, anchor="start", color=COLORS["muted"])

        for ladder, maximum, color in (("A", graph.a, COLORS["a_rail"]),
                                       ("B", graph.b, COLORS["b_rail"])):
            start_vertices = [v for v, model in graph.labels.items()
                              if model[0] == ladder and model[1] == 0]
            end_vertices = [v for v, model in graph.labels.items()
                            if model[0] == ladder and model[1] == maximum]
            start = tuple(sum(pos[v][i] for v in start_vertices) / 2 for i in (0, 1))
            end = tuple(sum(pos[v][i] for v in end_vertices) / 2 for i in (0, 1))
            _line(scene, start[0], start[1], end[0], end[1], color, 2.2, "6 7",
                  arrow=True, overlay="growth_direction")
        if graph.inserted_vertices:
            xs = [pos[v][0] for v in graph.inserted_vertices]
            ys = [pos[v][1] for v in graph.inserted_vertices]
            _text(scene, sum(xs) / 4, min(ys) - 20, "certified insertion tile", 17,
                  color=COLORS["inserted"], weight="bold")
        else:
            _text(scene, 920, 925, "base member", 18, anchor="start", color=COLORS["inserted"])
    else:
        _text(scene, 600, 1148, graph.label, 31, weight="bold")
    return scene, pos, norm


def _xml_color(value: str) -> str:
    return html.escape(value, quote=True)


def scene_to_svg(scene: list[dict[str, Any]], width: int, height: int,
                 title: str, description: str) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f"  <title>{html.escape(title)}</title>",
        f"  <desc>{html.escape(description)}</desc>",
        "  <defs><marker id=\"arrow\" markerWidth=\"10\" markerHeight=\"10\" refX=\"8\" refY=\"3\" orient=\"auto\"><path d=\"M0,0 L0,6 L9,3 z\" fill=\"context-stroke\"/></marker></defs>",
    ]
    for item in scene:
        kind = item["kind"]
        if kind == "rect":
            lines.append(f'  <rect x="{item["x"]:.3f}" y="{item["y"]:.3f}" width="{item["w"]:.3f}" height="{item["h"]:.3f}" fill="{_xml_color(item["fill"])}"/>')
        elif kind == "line":
            attrs = ""
            if item.get("dash"):
                attrs += f' stroke-dasharray="{item["dash"]}"'
            if item.get("arrow"):
                attrs += ' marker-end="url(#arrow)"'
            if "edge" in item:
                attrs += f' data-u="{item["edge"][0]}" data-v="{item["edge"][1]}" data-class="{item["edge_class"]}"'
            lines.append(f'  <line x1="{item["x1"]:.3f}" y1="{item["y1"]:.3f}" x2="{item["x2"]:.3f}" y2="{item["y2"]:.3f}" stroke="{_xml_color(item["color"])}" stroke-width="{item["width"]:.3f}" stroke-linecap="round"{attrs}/>')
        elif kind == "circle":
            vertex = f' data-vertex="{item["vertex"]}"' if "vertex" in item else ""
            lines.append(f'  <circle cx="{item["x"]:.3f}" cy="{item["y"]:.3f}" r="{item["r"]:.3f}" fill="{_xml_color(item["fill"])}" stroke="{_xml_color(item["stroke"])}" stroke-width="{item["width"]:.3f}"{vertex}/>')
        elif kind in {"polyline", "polygon"}:
            points = " ".join(f"{x:.3f},{y:.3f}" for x, y in item["points"])
            tag = "polygon" if item.get("closed") or kind == "polygon" else "polyline"
            fill = item.get("fill", "none")
            dash = f' stroke-dasharray="{item["dash"]}"' if item.get("dash") else ""
            opacity = f' opacity="{item["opacity"]}"' if item.get("opacity") is not None else ""
            lines.append(f'  <{tag} points="{points}" fill="{_xml_color(fill)}" stroke="{_xml_color(item.get("color", "none"))}" stroke-width="{item.get("width", 0):.3f}" stroke-linejoin="round"{dash}{opacity}/>')
        elif kind == "text":
            weight = f' font-weight="{item["weight"]}"' if item.get("weight") != "normal" else ""
            lines.append(f'  <text x="{item["x"]:.3f}" y="{item["y"]:.3f}" font-family="Arial, Helvetica, sans-serif" font-size="{item["size"]:.3f}" fill="{_xml_color(item["color"])}" text-anchor="{item["anchor"]}"{weight}>{html.escape(item["text"])}</text>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _rgb(color: str) -> tuple[float, float, float]:
    return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def scene_to_pdf(scene: list[dict[str, Any]], width: int, height: int) -> bytes:
    """Emit a small deterministic vector PDF using only standard PDF operators."""
    out: list[str] = ["1 J 1 j"]

    def set_stroke(color: str) -> None:
        out.append("%.4f %.4f %.4f RG" % _rgb(color))

    def set_fill(color: str) -> None:
        out.append("%.4f %.4f %.4f rg" % _rgb(color))

    def point(x: float, y: float) -> tuple[float, float]:
        return x, height - y

    for item in scene:
        kind = item["kind"]
        if kind == "rect":
            set_fill(item["fill"])
            x, y = point(item["x"], item["y"] + item["h"])
            out.append(f'{x:.3f} {y:.3f} {item["w"]:.3f} {item["h"]:.3f} re f')
        elif kind == "line":
            set_stroke(item["color"])
            out.append(f'{item["width"]:.3f} w')
            dash = item.get("dash")
            out.append(f'[{dash}] 0 d' if dash else "[] 0 d")
            x1, y1 = point(item["x1"], item["y1"])
            x2, y2 = point(item["x2"], item["y2"])
            out.append(f"{x1:.3f} {y1:.3f} m {x2:.3f} {y2:.3f} l S")
            if item.get("arrow"):
                angle = math.atan2(y2 - y1, x2 - x1)
                pts = [(x2, y2),
                       (x2 - 15 * math.cos(angle - .38), y2 - 15 * math.sin(angle - .38)),
                       (x2 - 15 * math.cos(angle + .38), y2 - 15 * math.sin(angle + .38))]
                set_fill(item["color"])
                out.append(f"{pts[0][0]:.3f} {pts[0][1]:.3f} m {pts[1][0]:.3f} {pts[1][1]:.3f} l {pts[2][0]:.3f} {pts[2][1]:.3f} l h f")
        elif kind == "circle":
            x, y = point(item["x"], item["y"])
            r = item["r"]
            k = 0.5522847498 * r
            set_fill(item["fill"]); set_stroke(item["stroke"])
            out.append(f'{item["width"]:.3f} w [] 0 d')
            out.append(
                f"{x+r:.3f} {y:.3f} m {x+r:.3f} {y+k:.3f} {x+k:.3f} {y+r:.3f} {x:.3f} {y+r:.3f} c "
                f"{x-k:.3f} {y+r:.3f} {x-r:.3f} {y+k:.3f} {x-r:.3f} {y:.3f} c "
                f"{x-r:.3f} {y-k:.3f} {x-k:.3f} {y-r:.3f} {x:.3f} {y-r:.3f} c "
                f"{x+k:.3f} {y-r:.3f} {x+r:.3f} {y-k:.3f} {x+r:.3f} {y:.3f} c B"
            )
        elif kind in {"polyline", "polygon"}:
            pts = [point(x, y) for x, y in item["points"]]
            if not pts:
                continue
            if item.get("fill") and item["fill"] != "none":
                set_fill(item["fill"])
            set_stroke(item.get("color", COLORS["ink"]))
            out.append(f'{item.get("width", 1):.3f} w')
            out.append(f'[{item["dash"]}] 0 d' if item.get("dash") else "[] 0 d")
            path = f"{pts[0][0]:.3f} {pts[0][1]:.3f} m " + " ".join(
                f"{x:.3f} {y:.3f} l" for x, y in pts[1:]
            )
            closed = item.get("closed") or kind == "polygon"
            paint = "B" if closed and item.get("fill") not in (None, "none") else ("S" if not closed else "h S")
            out.append(path + " " + paint)
        elif kind == "text":
            value = item["text"].encode("ascii", errors="replace").decode("ascii")
            value = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            set_fill(item["color"])
            approx = len(value) * item["size"] * (0.55 if item.get("weight") == "bold" else 0.50)
            x = item["x"] - (approx / 2 if item["anchor"] == "middle" else approx if item["anchor"] == "end" else 0)
            y = height - item["y"]
            font = "/F2" if item.get("weight") == "bold" else "/F1"
            out.append(f"BT {font} {item['size']:.3f} Tf {x:.3f} {y:.3f} Td ({value}) Tj ET")

    stream = ("\n".join(out) + "\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>".encode("ascii"),
        f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii")); data.extend(obj); data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(data)


def render_png(svg_path: Path, png_path: Path, edge: Path,
               width: int, height: int, commands: list[str]) -> None:
    expected = (width * PNG_SCALE, height * PNG_SCALE)
    if png_path.is_file() and png_path.stat().st_mtime_ns >= svg_path.stat().st_mtime_ns:
        data = png_path.read_bytes()[:24]
        if len(data) == 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == expected:
            return
    png_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = png_path.with_name(f".{png_path.stem}.tmp.png")
    with tempfile.TemporaryDirectory(prefix="bauer-edge-profile-") as profile:
        command = [str(edge), "--headless", "--disable-gpu", "--hide-scrollbars",
                   f"--force-device-scale-factor={PNG_SCALE}", f"--window-size={width},{height}",
                   f"--user-data-dir={profile}", f"--screenshot={temporary}", svg_path.resolve().as_uri()]
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 check=False, timeout=90)
    if process.returncode != 0 or not temporary.is_file():
        raise GalleryError(f"Edge PNG rendering failed: {process.stderr.decode(errors='replace')}")
    os.replace(temporary, png_path)
    commands.append("PNG\t" + subprocess.list2cmdline(command).replace(profile, "<temporary-profile>"))


def transform_scene(scene: list[dict[str, Any]], sx: float, sy: float, tx: float, ty: float,
                    *, skip_background: bool = True) -> list[dict[str, Any]]:
    result = []
    for item in scene:
        if skip_background and item["kind"] == "rect" and item.get("w") == 1200:
            continue
        if skip_background and item["kind"] == "text":
            continue
        q = dict(item)
        if item["kind"] in {"line"}:
            for xkey, ykey in (("x1", "y1"), ("x2", "y2")):
                q[xkey] = item[xkey] * sx + tx; q[ykey] = item[ykey] * sy + ty
            q["width"] = item["width"] * min(sx, sy)
        elif item["kind"] in {"circle", "text"}:
            q["x"] = item["x"] * sx + tx; q["y"] = item["y"] * sy + ty
            if item["kind"] == "circle": q["r"] = item["r"] * min(sx, sy); q["width"] = item["width"] * min(sx, sy)
            else: q["size"] = item["size"] * min(sx, sy)
        elif item["kind"] in {"polyline", "polygon"}:
            q["points"] = [(x * sx + tx, y * sy + ty) for x, y in item["points"]]
            q["width"] = item.get("width", 1) * min(sx, sy)
        elif item["kind"] == "rect":
            q.update(x=item["x"] * sx + tx, y=item["y"] * sy + ty,
                     w=item["w"] * sx, h=item["h"] * sy)
        result.append(q)
    return result


def grid_composite(items: list[tuple[GraphData, list[dict[str, Any]]]], title: str,
                   cols: int, panel_w: int = 430, panel_h: int = 430) -> tuple[list[dict[str, Any]], int, int]:
    rows = math.ceil(len(items) / cols)
    width, height = cols * panel_w + 80, rows * panel_h + 120
    scene: list[dict[str, Any]] = [{"kind": "rect", "x": 0, "y": 0, "w": width, "h": height, "fill": "#FFFFFF"}]
    _text(scene, width / 2, 55, title, 32, weight="bold")
    for index, (graph, source) in enumerate(items):
        row, col = divmod(index, cols)
        scale = min((panel_w - 30) / 1200, (panel_h - 35) / 1200)
        tx, ty = 40 + col * panel_w, 75 + row * panel_h
        scene.extend(transform_scene(source, scale, scale, tx, ty))
        status = "certified" if graph.certified_extremal else "extremality open"
        _text(scene, tx + panel_w / 2 - 15, ty + panel_h - 12,
              f"{graph.label}  n={graph.order}  hsep={graph.exact_hsep}  [{status}]", 17,
              weight="bold" if graph.certified_extremal else "normal")
    return scene, width, height


def insertion_composite(items: list[tuple[GraphData, list[dict[str, Any]]]]) -> tuple[list[dict[str, Any]], int, int]:
    width, height = 2350, 600
    scene: list[dict[str, Any]] = [{"kind": "rect", "x": 0, "y": 0, "w": width, "h": height, "fill": "#FFFFFF"}]
    _text(scene, width / 2, 50, "Successive certified square insertions", 31, weight="bold")
    panel_w = 450
    for index, (graph, source) in enumerate(items):
        scale = 0.34
        tx, ty = 35 + index * 465, 75
        scene.extend(transform_scene(source, scale, scale, tx, ty))
        _text(scene, tx + 204, 535, f"{graph.label}: hsep={graph.exact_hsep}", 19, weight="bold")
        if index + 1 < len(items):
            _line(scene, tx + 420, 285, tx + 460, 285, COLORS["inserted"], 4, arrow=True)
            _text(scene, tx + 440, 260, "+4 vertices", 13, color=COLORS["inserted"])
    return scene, width, height


def chart_composite(graphs: list[GraphData], kind: str) -> tuple[list[dict[str, Any]], int, int]:
    width, height = 1500, 900
    scene: list[dict[str, Any]] = [{"kind": "rect", "x": 0, "y": 0, "w": width, "h": height, "fill": "#FFFFFF"}]
    title = "Face growth in the double-ladder sequence" if kind == "faces" else "Exact hsep growth in the double-ladder sequence"
    _text(scene, width / 2, 55, title, 32, weight="bold")
    left, top, right, bottom = 125, 135, 1430, 690
    _line(scene, left, bottom, right, bottom, COLORS["ink"], 2.5)
    _line(scene, left, top, left, bottom, COLORS["ink"], 2.5)
    xs = {g.order: left + (g.order - 8) / 40 * (right - left) for g in graphs}
    if kind == "faces":
        series = [
            ("quadrilateral faces", [g.face_size_multiset.count(4) for g in graphs], COLORS["a_rail"]),
            ("A-cap length", [g.a + 3 for g in graphs], COLORS["b_rail"]),
            ("B-cap length", [g.b + 3 for g in graphs], COLORS["connector"]),
        ]
        ymax = 24
    else:
        series = [("exact hsep", [g.exact_hsep for g in graphs], COLORS["inserted"])]
        ymax = 90
    for value in range(0, ymax + 1, 5 if kind == "faces" else 10):
        y = bottom - value / ymax * (bottom - top)
        _line(scene, left, y, right, y, COLORS["grid"], 1.0, "3 7")
        _text(scene, left - 18, y + 6, str(value), 17, anchor="end", color=COLORS["muted"])
    for name, values, color in series:
        pts = [(xs[g.order], bottom - value / ymax * (bottom - top)) for g, value in zip(graphs, values)]
        scene.append({"kind": "polyline", "points": pts, "closed": False, "color": color, "width": 4.0})
        for (x, y), graph, value in zip(pts, graphs, values):
            scene.append({"kind": "circle", "x": x, "y": y, "r": 8.5,
                          "fill": "#FFFFFF" if graph.certified_extremal else color,
                          "stroke": color, "width": 3.0})
            if kind == "hsep": _text(scene, x, y - 17, str(value), 16, color=color, weight="bold")
    for graph in graphs:
        x = xs[graph.order]
        _text(scene, x, bottom + 31, str(graph.order), 17)
        _text(scene, x, bottom + 57, graph.label, 15, color=COLORS["muted"])
    _text(scene, (left + right) / 2, 790, "order n", 20, weight="bold")
    for index, (name, _, color) in enumerate(series):
        x = 260 + index * 330
        _line(scene, x, 835, x + 55, 835, color, 4)
        _text(scene, x + 70, 841, name, 18, anchor="start")
    _text(scene, 1080, 875, "open marker = certified census maximizer", 17, anchor="start", color=COLORS["muted"])
    return scene, width, height


def write_figure(root: Path, name: str, scene: list[dict[str, Any]], width: int, height: int,
                 edge_renderer: Path, commands: list[str], title: str, description: str,
                 *, composite: bool = False) -> dict[str, str]:
    base = root / ("composite" if composite else "svg")
    svg_path = base / f"{name}.svg"
    pdf_path = (root / ("composite" if composite else "pdf")) / f"{name}.pdf"
    png_path = (root / ("composite" if composite else "png")) / f"{name}.png"
    atomic_write(svg_path, scene_to_svg(scene, width, height, title, description).encode("utf-8"))
    atomic_write(pdf_path, scene_to_pdf(scene, width, height))
    render_png(svg_path, png_path, edge_renderer, width, height, commands)
    return {"svg": svg_path.relative_to(root).as_posix(),
            "pdf": pdf_path.relative_to(root).as_posix(),
            "png": png_path.relative_to(root).as_posix()}


def write_indexes(root: Path, metadata: list[dict[str, Any]]) -> None:
    atomic_json(root / "gallery_index.json", {"schema": SCHEMA, "graphs": metadata})
    fields = ["label", "a", "b", "order", "edge_count", "exact_hsep",
              "hamiltonian_cycle_count", "face_size_multiset", "status",
              "canonical_graph_hash", "clean_svg", "annotated_svg", "clean_pdf",
              "annotated_pdf", "clean_png", "annotated_png"]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False,
                                     dir=root, prefix=".gallery_index.", suffix=".tmp") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in metadata:
            writer.writerow({key: ";".join(map(str, record[key])) if key == "face_size_multiset" else record[key]
                             for key in fields})
        temporary = stream.name
    os.replace(temporary, root / "gallery_index.csv")
    cards = []
    for record in metadata:
        cards.append(
            f'<article><a href="{record["annotated_svg"]}"><img src="{record["clean_png"]}" alt="{record["label"]}"></a>'
            f'<h2>{record["label"]}</h2><p>n={record["order"]}; |E|={record["edge_count"]}; '
            f'hsep={record["exact_hsep"]}; H={record["hamiltonian_cycle_count"]}</p>'
            f'<p>{html.escape(record["status"])}</p><p><a href="{record["clean_svg"]}">clean SVG</a> · '
            f'<a href="{record["annotated_svg"]}">annotated SVG</a> · '
            f'<a href="{record["clean_pdf"]}">PDF</a> · <a href="{record["annotated_png"]}">PNG</a></p></article>'
        )
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Bauer double-ladder gallery</title>
<style>body{{font-family:Arial,sans-serif;margin:2rem;color:#172033}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:1.2rem}}article{{border:1px solid #cbd5e1;border-radius:8px;padding:1rem}}img{{width:100%;height:auto}}p{{font-size:.92rem}}a{{color:#1d4ed8}}</style></head>
<body><h1>Bauer double-ladder gallery</h1><p>All layouts derive from immutable certified embeddings and Gunnar Brinkmann's external drawing program.</p><main>{''.join(cards)}</main></body></html>'''
    atomic_write(root / "gallery_index.html", page.encode("utf-8"))


def write_report(root: Path, graphs: list[GraphData], composites: dict[str, dict[str, str]]) -> None:
    lines = [
        "# Bauer double-ladder scientific figure gallery", "",
        "This is a visualization-only derivative of immutable Barnie-sequence and prospective double-ladder certificate packages. No census, Hamiltonian-cycle enumeration, or hsep optimization was run.", "",
        "## Construction and verification", "",
        "For each graph, the certified `planar_code` embedding is passed to Gunnar Brinkmann's external drawing program with a deterministically selected A/rail-0 cap face fixed as the outer face. The returned TikZ vertex and edge sets are checked exactly against the certified canonical edge list before any figure is emitted. Alignment uses only a rigid rotation/reflection followed by uniform scaling; no topology or generic graph layout is introduced.", "",
        "Annotated drawings distinguish A rails/rungs, B rails/rungs, four connector edges, four cap boundaries, the latest certified four-vertex insertion tile, parameter values, and growth directions. Color is reinforced by dash patterns, line weight, and insertion markers for grayscale use.", "",
        "## Graphs", "",
        "| graph | n | edges | exact hsep | Hamiltonian cycles | face multiset | status |", "|---|---:|---:|---:|---:|---|---|",
    ]
    for graph in graphs:
        lines.append(f"| {graph.label} | {graph.order} | {graph.edge_count} | {graph.exact_hsep} | {graph.hamiltonian_cycle_count} | {_face_sizes_text(graph.face_size_multiset)} | {graph.status} |")
    lines.extend(["", "The exact Hamiltonian-cycle counts agree with `H(D(a,b)) = ab + 5`. For odd `a,b >= 3`, the exact separation values agree with `hsep(D(a,b)) = ((a+2)(b+2)-1)/2`; the two smaller base cases retain their separately certified exact values.", "",
                  "The order-40, -44, and -48 graphs have certified graph-specific exact hsep values. They are not claimed to maximize hsep over the complete Barnette census at those orders.", "",
                  "## Composite plates", ""])
    for name, files in composites.items():
        lines.append(f"- **{name.replace('_', ' ')}:** [{files['svg']}]({files['svg']}), [{files['pdf']}]({files['pdf']}), [{files['png']}]({files['png']})")
    lines.extend(["", "## Reproduction", "",
                  "Run `build_bauer_double_ladder_gallery.py` with the recorded command in `commands.log`. Large computation is absent; the script reads and hashes existing artifacts, invokes the drawing executable once per graph, writes vector scenes, and rasterizes previews. `verify_bauer_double_ladder_gallery.py` is standard-library-only and checks manifests, SVG vertex/edge identities, annotations, PDF signatures, and PNG dimensions.", ""])
    lines.extend(["## Paper bundle", "",
                  "Selected compact composite files and an include-ready LaTeX fragment were copied to `paper/figures/bauer_family/`. The main manuscript file was not modified.", ""])
    atomic_write(root / "BAUER_GALLERY_REPORT.md", ("\n".join(lines) + "\n").encode("utf-8"))


def write_paper_bundle(root: Path, paper_root: Path, composites: dict[str, dict[str, str]]) -> None:
    destination = paper_root / "figures" / "bauer_family"
    destination.mkdir(parents=True, exist_ok=True)
    selected = ["complete_family", "insertion_sequence", "balance_comparison", "face_growth", "hsep_growth"]
    for name in selected:
        for fmt in ("svg", "pdf", "png"):
            source = root / composites[name][fmt]
            shutil.copyfile(source, destination / f"{name}.{fmt}")
    tex = r'''% Generated Bauer double-ladder figure bundle; include manually from main.tex.
\begin{figure*}[!tbp]
  \centering
  \includegraphics[width=.98\textwidth]{figures/bauer_family/complete_family.pdf}
  \caption{The Bauer double-ladder family from $D(1,1)$ through $D(11,11)$. Open-order members at orders 40, 44, and 48 have exact graph-specific certificates but no complete-census extremality claim.}
  \label{fig:bauer-complete-family}
\end{figure*}

\begin{figure*}[!tbp]
  \centering
  \includegraphics[width=.98\textwidth]{figures/bauer_family/insertion_sequence.pdf}
  \caption{Successive certified facial square insertions from $D(7,7)$ to $D(11,11)$.}
  \label{fig:bauer-insertion-sequence}
\end{figure*}

\begin{figure*}[!tbp]
  \centering
  \includegraphics[width=.98\textwidth]{figures/bauer_family/balance_comparison.pdf}
  \caption{Balanced and near-balanced double ladders, with the two ladder parameters shown in common orientation.}
  \label{fig:bauer-balance}
\end{figure*}

\begin{figure}[!tbp]
  \centering
  \includegraphics[width=.98\linewidth]{figures/bauer_family/face_growth.pdf}
  \caption{Growth of quadrilateral cells and cap-face lengths in the displayed family.}
  \label{fig:bauer-face-growth}
\end{figure}

\begin{figure}[!tbp]
  \centering
  \includegraphics[width=.98\linewidth]{figures/bauer_family/hsep_growth.pdf}
  \caption{Certified exact $\operatorname{hsep}$ values along the displayed family. Filled markers denote graph-specific results beyond the completed order-36 census.}
  \label{fig:bauer-hsep-growth}
\end{figure}
'''
    atomic_write(destination / "bauer_family_figures.tex", tex.encode("utf-8"))
    manifest_lines = []
    for path in sorted(destination.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            manifest_lines.append(f"{sha256_file(path)}  {path.name}")
    atomic_write(destination / "SHA256SUMS.txt", ("\n".join(manifest_lines) + "\n").encode("ascii"))


def write_manifest(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}")
    atomic_write(root / "SHA256SUMS.txt", ("\n".join(lines) + "\n").encode("ascii"))


def build(args: argparse.Namespace) -> None:
    root = args.output_root.resolve(); root.mkdir(parents=True, exist_ok=True)
    for folder in ("svg", "pdf", "png", "annotated", "composite"):
        (root / folder).mkdir(exist_ok=True)
    graphs = load_graphs(args.sequence_root.resolve(), args.prediction_root.resolve())
    commands = ["BUILD\t" + subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])]
    engine_hash = sha256_file(args.engine.resolve())
    layouts: dict[str, Any] = {"schema": SCHEMA, "method": "fixed certified cap face plus rigid alignment", "graphs": []}
    verification: dict[str, Any] = {"schema": SCHEMA, "status": "pass", "graphs": []}
    metadata: list[dict[str, Any]] = []
    clean_scenes: dict[str, list[dict[str, Any]]] = {}

    for graph in graphs:
        outer = choose_outer_cap(graph)
        options = (*ENGINE_OPTIONS, "cf", str(outer[0] + 1), str(outer[1] + 1))
        tex, stderr, command = run_engine(args.engine.resolve(), graph.planar_code, options)
        engine_vertices, engine_edges = parse_planar_tikz(tex)
        verify_tikz_graph(engine_vertices, engine_edges,
                          {"graph_order": graph.order, "edges": graph.edges, "edge_count": graph.edge_count})
        aligned, alignment = align_layout(graph, engine_vertices)
        clean_scene, clean_pos, normalization = graph_scene(graph, aligned, annotated=False)
        annotated_scene, annotated_pos, annotated_norm = graph_scene(graph, aligned, annotated=True)
        clean_scenes[graph.stem] = clean_scene
        common_desc = f"{graph.label}, canonical graph SHA-256 {graph.graph_hash}; exact structure from certified embedding."
        clean_files = write_figure(root, f"{graph.stem}_clean", clean_scene, *INDIVIDUAL_SIZE,
                                   args.edge_renderer.resolve(), commands, f"Clean {graph.label}", common_desc)
        annotated_files = write_figure(root, f"{graph.stem}_annotated", annotated_scene, *INDIVIDUAL_SIZE,
                                       args.edge_renderer.resolve(), commands, f"Annotated {graph.label}", common_desc)
        annotation = {
            "schema": SCHEMA, "label": graph.label,
            "edge_classes": {f"{u}-{v}": classify_edge(graph, (u, v)) for u, v in graph.edges},
            "cap_faces": cap_faces(graph), "inserted_vertices": graph.inserted_vertices,
            "ladder_parameters": {"a": graph.a, "b": graph.b},
        }
        atomic_json(root / "annotated" / f"{graph.stem}_annotation.json", annotation)
        record = {
            "schema": SCHEMA, "label": graph.label, "stem": graph.stem,
            "a": graph.a, "b": graph.b, "order": graph.order, "edge_count": graph.edge_count,
            "exact_hsep": graph.exact_hsep, "hamiltonian_cycle_count": graph.hamiltonian_cycle_count,
            "face_size_multiset": graph.face_size_multiset, "status": graph.status,
            "certified_extremal_through_order_36": graph.certified_extremal,
            "canonical_graph_hash": graph.graph_hash, "canonical_edges": [list(e) for e in graph.edges],
            "generation_index": graph.generation_index, "plantri_rank": graph.plantri_rank,
            "planar_code_sha256": graph.planar_code_sha256,
            "input_files": [{"path": str(path), "sha256": sha256_file(path)} for path in graph.source_files],
            "clean_svg": clean_files["svg"], "clean_pdf": clean_files["pdf"], "clean_png": clean_files["png"],
            "annotated_svg": annotated_files["svg"], "annotated_pdf": annotated_files["pdf"], "annotated_png": annotated_files["png"],
            "annotation_json": f"annotated/{graph.stem}_annotation.json",
        }
        metadata.append(record)
        layouts["graphs"].append({"label": graph.label, "outer_face": outer,
                                  "engine_options": list(options), "engine_command": command,
                                  "engine_stderr": stderr.strip(), "alignment": alignment,
                                  "clean_viewport_normalization": normalization,
                                  "annotated_viewport_normalization": annotated_norm,
                                  "coordinates_sha256": _sha256_bytes(json.dumps(clean_pos, sort_keys=True).encode())})
        verification["graphs"].append({"label": graph.label, "status": "pass",
                                       "expected_vertices": graph.order, "actual_vertices": len(engine_vertices),
                                       "expected_edges": graph.edge_count, "actual_edges": len(engine_edges),
                                       "edge_classes": {name: sum(classify_edge(graph, e) == name for e in graph.edges)
                                                        for name in ("a_rail", "a_rung", "b_rail", "b_rung", "connector")},
                                       "cap_face_count": len(cap_faces(graph)),
                                       "latest_insertion_vertex_count": len(graph.inserted_vertices)})
        commands.append("DRAW\t" + subprocess.list2cmdline(command) + f" < planar_code_sha256:{graph.planar_code_sha256}")
        print(f"OK {graph.label}: {graph.order} vertices, {graph.edge_count} edges")

    by_stem = {g.stem: g for g in graphs}
    def pairs(stems: Iterable[str]) -> list[tuple[GraphData, list[dict[str, Any]]]]:
        return [(by_stem[s], clean_scenes[s]) for s in stems]

    composite_specs: dict[str, tuple[list[dict[str, Any]], int, int]] = {}
    composite_specs["complete_family"] = grid_composite(pairs(g.stem for g in graphs), "Bauer double-ladder family", 4)
    composite_specs["certified_maximizers"] = grid_composite(pairs(g.stem for g in graphs if g.certified_extremal), "Certified unique maximizers through order 36", 4)
    insertion_stems = ["D_7_7", "D_9_7", "D_9_9", "D_11_9", "D_11_11"]
    composite_specs["insertion_sequence"] = insertion_composite(pairs(insertion_stems))
    balance_stems = ["D_5_5", "D_7_5", "D_7_7", "D_9_7", "D_9_9"]
    composite_specs["balance_comparison"] = grid_composite(pairs(balance_stems), "Balanced and near-balanced double ladders", 5, 380, 470)
    composite_specs["face_growth"] = chart_composite(graphs, "faces")
    composite_specs["hsep_growth"] = chart_composite(graphs, "hsep")
    composites: dict[str, dict[str, str]] = {}
    for name, (scene, width, height) in composite_specs.items():
        composites[name] = write_figure(root, name, scene, width, height, args.edge_renderer.resolve(),
                                        commands, name.replace("_", " ").title(),
                                        "Composite plate from the verified individual double-ladder layouts.", composite=True)

    atomic_json(root / "graph_metadata.json", {"schema": SCHEMA, "graph_count": len(metadata), "graphs": metadata})
    atomic_json(root / "layout_alignment.json", layouts)
    atomic_json(root / "drawing_verification.json", verification)
    write_indexes(root, metadata)
    write_report(root, graphs, composites)
    environment = {
        "schema": SCHEMA, "platform": platform.platform(), "python_version": platform.python_version(),
        "worker_count": 1, "drawing_engine": {"name": "Gunnar Brinkmann planar_draw",
        "path": str(args.engine.resolve()), "sha256": engine_hash, "options_base": list(ENGINE_OPTIONS),
        "source_path": str(args.engine_source.resolve()), "source_sha256": sha256_file(args.engine_source.resolve())},
        "png_renderer": {"path": str(args.edge_renderer.resolve()), "sha256": sha256_file(args.edge_renderer.resolve()),
                         "scale": PNG_SCALE},
        "inputs": {"sequence_root": str(args.sequence_root.resolve()), "prediction_root": str(args.prediction_root.resolve())},
        "output_policy": "external result root; existing certified packages read-only",
    }
    atomic_json(root / "environment.json", environment)
    atomic_write(root / "commands.log", ("\n".join(commands) + "\n").encode("utf-8"))
    verifier_source = Path(__file__).resolve().with_name("verify_bauer_double_ladder_gallery.py")
    shutil.copyfile(verifier_source, root / verifier_source.name)
    write_paper_bundle(root, args.paper_root.resolve(), composites)
    atomic_json(root / "standalone_verification.json", {
        "schema": SCHEMA, "status": "pass", "note": "Builder-level exact graph and format checks passed; rerun the bundled verifier after manifest creation."
    })
    write_manifest(root)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sequence-root", type=Path, required=True)
    p.add_argument("--prediction-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--paper-root", type=Path, required=True)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--engine-source", type=Path, required=True)
    p.add_argument("--edge-renderer", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        build(parser().parse_args(argv))
    except (GalleryError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
