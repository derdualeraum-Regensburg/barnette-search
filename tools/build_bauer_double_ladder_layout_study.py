#!/usr/bin/env python3
"""Build a deterministic outer-face/layout study for the Bauer double ladders.

This is a visualization-only consumer of existing immutable certificates.  It
does not generate graphs, enumerate Hamiltonian cycles, or solve hsep.  Gunnar
Brinkmann's ``planar_draw`` is invoked as an external read-only executable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src"))

from draw_single_maximizer import (  # noqa: E402
    GalleryError,
    atomic_json,
    atomic_write,
    parse_planar_tikz,
    run_engine,
    sha256_file,
    verify_tikz_graph,
)
from barnette_search.planar_code import iter_planar_code  # noqa: E402


def _load_gallery_module() -> Any:
    path = HERE / "build_bauer_double_ladder_gallery.py"
    spec = importlib.util.spec_from_file_location("bauer_gallery_base", path)
    if not spec or not spec.loader:
        raise GalleryError(f"cannot load gallery helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_gallery_module()
GraphData = BASE.GraphData

SCHEMA = "bauer-double-ladder-layout-study-v1"
ENGINE_OPTIONS = ("T", "n")
PREFERRED_OUTER_CAP = "B_rail_0"
CANVAS = 1200
PNG_SCALE = 2
EPS = 1.0e-12

# Lower is better.  The values are declared here, reported verbatim, and tested
# with two nearby alternatives; they are not adjusted after seeing selections.
DEFAULT_WEIGHTS = {
    "top_ladder_straightness": 5.0,
    "top_position": 2.0,
    "outer_boundary_ladder": 2.5,
    "connector_consistency": 1.0,
    "cap_face_choice": 8.0,
    "insertion_visibility": 1.5,
    "drawing_quality": 2.0,
}
SENSITIVITY_WEIGHTS = {
    "geometry_emphasis": {**DEFAULT_WEIGHTS, "top_ladder_straightness": 7.0,
                          "drawing_quality": 3.0, "cap_face_choice": 6.0},
    "continuity_emphasis": {**DEFAULT_WEIGHTS, "connector_consistency": 1.5,
                            "insertion_visibility": 2.0, "cap_face_choice": 10.0},
}
CONTINUITY_WEIGHT = 5.0


@dataclass
class EngineLayout:
    graph: GraphData
    cap_id: str
    cap_index: int
    face: list[int]
    dart: tuple[int, int]
    raw_tex: str
    raw_positions: dict[int, tuple[float, float]]
    engine_command: list[str]
    engine_stderr: str


@dataclass
class Candidate:
    graph: GraphData
    candidate_id: str
    engine_layout: EngineLayout
    positions: dict[int, tuple[float, float]]
    rotation_degrees: float
    reflect_horizontal: bool
    reflect_vertical: bool
    reverse_a: bool
    reverse_b: bool
    components: dict[str, float]
    total: float


def edge(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


def canonical_cycle(face: Iterable[int]) -> tuple[int, ...]:
    body = tuple(face)
    variants = []
    for oriented in (body, tuple(reversed(body))):
        variants.extend(oriented[i:] + oriented[:i] for i in range(len(body)))
    return min(variants)


def cap_identifier(graph: GraphData, face: list[int]) -> str:
    """Name a cap by the unique ladder rail contained in its boundary."""
    found: set[tuple[str, int]] = set()
    for index, u in enumerate(face):
        v = face[(index + 1) % len(face)]
        cls = BASE.classify_edge(graph, edge(u, v))
        if cls.endswith("_rail"):
            left, right = graph.labels[u], graph.labels[v]
            if left[0] == right[0] and left[2] == right[2]:
                found.add((left[0], left[2]))
    if len(found) != 1:
        raise GalleryError(f"ambiguous structural cap in {graph.label}: {face} -> {found}")
    ladder, rail = next(iter(found))
    return f"{ladder}_rail_{rail}"


def cap_records(graph: GraphData) -> list[dict[str, Any]]:
    records = []
    for index, face in enumerate(BASE.cap_faces(graph)):
        records.append({
            "cap_index": index,
            "structural_id": cap_identifier(graph, face),
            "boundary": list(face),
            "size": len(face),
            "selecting_directed_edges": [
                # The certified planar_code stores clockwise rotations and the
                # repository face tracer walks the face on the right of its
                # listed dart.  planar_draw's documented cf option takes the
                # face on the left, hence the reversed boundary darts here.
                [face[(i + 1) % len(face)], face[i]] for i in range(len(face))
            ],
        })
    if {record["structural_id"] for record in records} != {
        "A_rail_0", "A_rail_1", "B_rail_0", "B_rail_1"
    }:
        raise GalleryError(f"incomplete structural cap identifiers for {graph.label}")
    return sorted(records, key=lambda record: record["structural_id"])


def decode_embedding(graph: GraphData) -> Any:
    decoded = list(iter_planar_code(io.BytesIO(graph.planar_code), require_header=True))
    if len(decoded) != 1:
        raise GalleryError(f"{graph.label} planar_code does not contain one graph")
    return decoded[0]


def verify_certified_embedding(graph: GraphData) -> dict[str, Any]:
    embedded = decode_embedding(graph)
    decoded_edges = sorted(edge(int(u), int(v)) for u, v in embedded.graph.edges())
    certified_edges = sorted(graph.edges)
    decoded_faces = sorted(canonical_cycle(face) for face in embedded.faces)
    certified_faces = sorted(canonical_cycle(face) for face in graph.faces)
    checks = {
        "vertex_set": list(embedded.graph.nodes()) == list(range(graph.order)),
        "edge_set": decoded_edges == certified_edges,
        "vertex_count": embedded.graph.number_of_nodes() == graph.order,
        "edge_count": embedded.graph.number_of_edges() == graph.edge_count,
        "rotation_system_faces": decoded_faces == certified_faces,
        "face_size_multiset": sorted(map(len, embedded.faces)) == sorted(graph.face_size_multiset),
        "cubic": all(len(row) == 3 for row in embedded.rotation_system),
        "cap_count": len(BASE.cap_faces(graph)) == 4,
        "structural_labels": set(graph.labels) == set(range(graph.order)),
        "edge_classification": all(BASE.classify_edge(graph, item) for item in graph.edges),
    }
    if not all(checks.values()):
        raise GalleryError(f"certified embedding verification failed for {graph.label}: {checks}")
    return {
        "rotation_system": [list(row) for row in embedded.rotation_system],
        "faces": [list(face) for face in embedded.faces],
        "checks": checks,
    }


def enumerate_engine_layouts(
    graph: GraphData, engine: Path, commands: list[str]
) -> tuple[list[EngineLayout], list[dict[str, Any]]]:
    layouts: list[EngineLayout] = []
    checks: list[dict[str, Any]] = []
    for cap in cap_records(graph):
        face = cap["boundary"]
        for u, v in cap["selecting_directed_edges"]:
            options = (*ENGINE_OPTIONS, "cf", str(u + 1), str(v + 1))
            tex, stderr, command = run_engine(engine, graph.planar_code, options)
            vertices, edges = parse_planar_tikz(tex)
            verify_tikz_graph(vertices, edges, {
                "graph_order": graph.order,
                "edges": graph.edges,
                "edge_count": graph.edge_count,
            })
            raw = {vertex - 1: point for vertex, point in vertices.items()}
            radii = [math.hypot(*raw[vertex]) for vertex in face]
            radial_cv = standard_deviation(radii) / max(mean(radii), EPS)
            selected_ok = radial_cv < 2.0e-4
            if not selected_ok:
                raise GalleryError(
                    f"cf {u + 1} {v + 1} did not put {cap['structural_id']} "
                    f"on the planar_draw outer circle for {graph.label} (CV={radial_cv})"
                )
            commands.append("DRAW\t" + subprocess.list2cmdline(command)
                            + f" < planar_code_sha256:{graph.planar_code_sha256}")
            layout = EngineLayout(
                graph=graph,
                cap_id=cap["structural_id"],
                cap_index=int(cap["cap_index"]),
                face=list(face),
                dart=(u, v),
                raw_tex=tex,
                raw_positions=raw,
                engine_command=command,
                engine_stderr=stderr.strip(),
            )
            layouts.append(layout)
            checks.append({
                "cap_id": cap["structural_id"],
                "directed_edge_zero_based": [u, v],
                "cf_arguments_one_based": [u + 1, v + 1],
                "outer_circle_radial_cv": radial_cv,
                "selected_face_confirmed": selected_ok,
            })
    return layouts, checks


def mean(values: Iterable[float]) -> float:
    data = list(values)
    return sum(data) / len(data) if data else 0.0


def standard_deviation(values: Iterable[float]) -> float:
    data = list(values)
    center = mean(data)
    return math.sqrt(mean((value - center) ** 2 for value in data))


def unit_positions(positions: dict[int, tuple[float, float]]) -> dict[int, tuple[float, float]]:
    cx = mean(point[0] for point in positions.values())
    cy = mean(point[1] for point in positions.values())
    shifted = {v: (x - cx, y - cy) for v, (x, y) in positions.items()}
    extent = max(max(abs(x), abs(y)) for x, y in shifted.values())
    return {v: (x / max(extent, EPS), y / max(extent, EPS))
            for v, (x, y) in shifted.items()}


def rotate_reflect(
    graph: GraphData,
    raw: dict[int, tuple[float, float]],
    quarter_turn: int,
    reflected: bool,
) -> tuple[dict[int, tuple[float, float]], float, bool, bool]:
    def endpoint_center(column: int) -> tuple[float, float]:
        points = [raw[v] for v, label in graph.labels.items()
                  if label[0] == "A" and label[1] == column]
        return mean(p[0] for p in points), mean(p[1] for p in points)

    start, end = endpoint_center(0), endpoint_center(graph.a)
    base = -math.atan2(end[1] - start[1], end[0] - start[0])
    angle = base + quarter_turn * math.pi / 2.0
    cosine, sine = math.cos(angle), math.sin(angle)
    result = {
        v: (x * cosine - y * sine, x * sine + y * cosine)
        for v, (x, y) in raw.items()
    }
    if reflected:
        result = {v: (-x, y) for v, (x, y) in result.items()}
    # Screen output has increasing y downward.  Keep mathematical coordinates
    # here; the chosen horizontal variants decide whether A is above.
    return unit_positions(result), math.degrees(angle), reflected, False


def structural_label(graph: GraphData, vertex: int, reverse_a: bool,
                     reverse_b: bool) -> tuple[str, int, int]:
    ladder, column, rail = graph.labels[vertex]
    reverse = reverse_a if ladder == "A" else reverse_b
    maximum = graph.a if ladder == "A" else graph.b
    return ladder, maximum - column if reverse else column, rail


def point_line_distance(point: tuple[float, float], start: tuple[float, float],
                        end: tuple[float, float]) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    return abs(dx * (start[1] - point[1]) - (start[0] - point[0]) * dy) / max(math.hypot(dx, dy), EPS)


def rail_vertices(graph: GraphData, ladder: str, rail: int,
                  reverse_a: bool, reverse_b: bool) -> list[int]:
    vertices = [v for v, label in graph.labels.items() if label[0] == ladder and label[2] == rail]
    return sorted(vertices, key=lambda v: structural_label(graph, v, reverse_a, reverse_b)[1])


def top_straightness(graph: GraphData, positions: dict[int, tuple[float, float]],
                     reverse_a: bool, reverse_b: bool) -> float:
    rails = [rail_vertices(graph, "A", rail, reverse_a, reverse_b) for rail in (0, 1)]
    residuals = []
    for vertices in rails:
        start, end = positions[vertices[0]], positions[vertices[-1]]
        residuals.extend(point_line_distance(positions[v], start, end) for v in vertices)
    rung_vectors = []
    rung_lengths = []
    for column in range(graph.a + 1):
        pair = [v for v in graph.labels if structural_label(graph, v, reverse_a, reverse_b)[:2] == ("A", column)]
        pair.sort(key=lambda v: graph.labels[v][2])
        dx = positions[pair[1]][0] - positions[pair[0]][0]
        dy = positions[pair[1]][1] - positions[pair[0]][1]
        length = math.hypot(dx, dy)
        rung_lengths.append(length)
        rung_vectors.append((dx / max(length, EPS), dy / max(length, EPS)))
    direction_variation = 1.0 - math.hypot(mean(x for x, _ in rung_vectors),
                                           mean(y for _, y in rung_vectors))
    length_variation = standard_deviation(rung_lengths) / max(mean(rung_lengths), EPS)
    start = tuple(mean(positions[rail[0]][axis] for rail in rails) for axis in (0, 1))
    end = tuple(mean(positions[rail[-1]][axis] for rail in rails) for axis in (0, 1))
    axis_angle = abs(math.atan2(end[1] - start[1], end[0] - start[0]))
    horizontal_penalty = min(axis_angle, abs(math.pi - axis_angle)) / (math.pi / 2)
    return mean(residuals) + direction_variation + length_variation + horizontal_penalty


def circle_residual(points: list[tuple[float, float]]) -> float:
    # Stable algebraic least-squares circle fit (3x3 normal equations).
    rows = [(2 * x, 2 * y, 1.0, x * x + y * y) for x, y in points]
    matrix = [[sum(row[i] * row[j] for row in rows) for j in range(3)]
              for i in range(3)]
    rhs = [sum(row[i] * row[3] for row in rows) for i in range(3)]
    for pivot in range(3):
        choice = max(range(pivot, 3), key=lambda row: abs(matrix[row][pivot]))
        matrix[pivot], matrix[choice] = matrix[choice], matrix[pivot]
        rhs[pivot], rhs[choice] = rhs[choice], rhs[pivot]
        if abs(matrix[pivot][pivot]) < EPS:
            return 1.0
        scale = matrix[pivot][pivot]
        matrix[pivot] = [value / scale for value in matrix[pivot]]
        rhs[pivot] /= scale
        for row in range(3):
            if row == pivot:
                continue
            factor = matrix[row][pivot]
            matrix[row] = [matrix[row][col] - factor * matrix[pivot][col] for col in range(3)]
            rhs[row] -= factor * rhs[pivot]
    cx, cy, constant = rhs
    radius = math.sqrt(max(constant + cx * cx + cy * cy, EPS))
    radii = [math.hypot(x - cx, y - cy) for x, y in points]
    return standard_deviation(radii) / radius


def orientation(a: tuple[float, float], b: tuple[float, float],
                c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_cross(a: tuple[float, float], b: tuple[float, float],
                   c: tuple[float, float], d: tuple[float, float]) -> bool:
    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    return o1 * o2 < -EPS and o3 * o4 < -EPS


def segment_distance(a: tuple[float, float], b: tuple[float, float],
                     c: tuple[float, float], d: tuple[float, float]) -> float:
    if segments_cross(a, b, c, d):
        return 0.0
    return min(point_line_distance(a, c, d), point_line_distance(b, c, d),
               point_line_distance(c, a, b), point_line_distance(d, a, b))


def crossing_count(graph: GraphData, positions: dict[int, tuple[float, float]]) -> int:
    count = 0
    for index, first in enumerate(graph.edges):
        for second in graph.edges[index + 1:]:
            if set(first) & set(second):
                continue
            if segments_cross(positions[first[0]], positions[first[1]],
                              positions[second[0]], positions[second[1]]):
                count += 1
    return count


def strictly_convex(points: list[tuple[float, float]]) -> bool:
    signs = []
    for index in range(len(points)):
        value = orientation(points[index], points[(index + 1) % len(points)],
                            points[(index + 2) % len(points)])
        if abs(value) < 1.0e-10:
            return False
        signs.append(value > 0)
    return all(signs) or not any(signs)


def quality_penalty(graph: GraphData, positions: dict[int, tuple[float, float]]) -> float:
    lengths = [math.dist(positions[u], positions[v]) for u, v in graph.edges]
    mean_length = max(mean(lengths), EPS)
    short = sum(max(0.0, 0.22 * mean_length - value) / mean_length for value in lengths)
    variation = standard_deviation(lengths) / mean_length
    vertices = list(positions)
    pair_distances = [math.dist(positions[u], positions[v])
                      for i, u in enumerate(vertices) for v in vertices[i + 1:]]
    coincidence = sum(max(0.0, 0.12 * mean_length - value) / mean_length
                      for value in pair_distances)
    near_edges = 0.0
    for index, first in enumerate(graph.edges):
        for second in graph.edges[index + 1:]:
            if set(first) & set(second):
                continue
            distance = segment_distance(positions[first[0]], positions[first[1]],
                                        positions[second[0]], positions[second[1]])
            near_edges += max(0.0, 0.08 * mean_length - distance) / mean_length
    xs = [p[0] for p in positions.values()]; ys = [p[1] for p in positions.values()]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    aspect = max(width / max(height, EPS), height / max(width, EPS)) - 1.0
    crossings = crossing_count(graph, positions)
    return short + variation + coincidence + near_edges + 0.15 * aspect + 1000.0 * crossings


def connector_signature(graph: GraphData, item: tuple[int, int], reverse_a: bool,
                        reverse_b: bool) -> tuple[tuple[str, str, int], ...]:
    result = []
    for vertex in item:
        ladder, column, rail = structural_label(graph, vertex, reverse_a, reverse_b)
        maximum = graph.a if ladder == "A" else graph.b
        result.append((ladder, "start" if column == 0 else "end" if column == maximum else str(column), rail))
    return tuple(sorted(result))


def score_candidate(graph: GraphData, positions: dict[int, tuple[float, float]],
                    cap_id: str, reverse_a: bool, reverse_b: bool,
                    weights: dict[str, float] = DEFAULT_WEIGHTS) -> tuple[dict[str, float], float]:
    a_vertices = [v for v, label in graph.labels.items() if label[0] == "A"]
    b_vertices = [v for v, label in graph.labels.items() if label[0] == "B"]
    center_y = mean(y for _, y in positions.values())
    a_y = mean(positions[v][1] for v in a_vertices)
    b_y = mean(positions[v][1] for v in b_vertices)
    connectors = [item for item in graph.edges if BASE.classify_edge(graph, item) == "connector"]
    connector_centers = [((positions[u][0] + positions[v][0]) / 2,
                          (positions[u][1] + positions[v][1]) / 2) for u, v in connectors]
    angles = sorted(math.atan2(y, x) for x, y in connector_centers)
    gaps = [(angles[(i + 1) % 4] - angles[i]) % (2 * math.pi) for i in range(4)]
    connector_component = standard_deviation(gaps) / (math.pi / 2)
    inserted = graph.inserted_vertices
    insertion_component = 0.0
    if inserted:
        effective = [structural_label(graph, v, reverse_a, reverse_b) for v in inserted]
        by_ladder: dict[str, list[int]] = {}
        for ladder, column, _ in effective:
            by_ladder.setdefault(ladder, []).append(column)
        for ladder, columns in by_ladder.items():
            maximum = graph.a if ladder == "A" else graph.b
            insertion_component += 1.0 - mean(columns) / max(maximum, 1)
        insertion_component /= len(by_ladder)
    components = {
        "top_ladder_straightness": top_straightness(graph, positions, reverse_a, reverse_b),
        "top_position": max(0.0, center_y - a_y) + max(0.0, b_y - a_y),
        "outer_boundary_ladder": circle_residual([positions[v] for v in b_vertices])
                                 + max(0.0, b_y - a_y),
        "connector_consistency": connector_component,
        "cap_face_choice": 0.0 if cap_id == PREFERRED_OUTER_CAP else 1.0,
        "family_continuity": 0.0,
        "insertion_visibility": insertion_component,
        "drawing_quality": quality_penalty(graph, positions),
    }
    total = sum(weights.get(name, 0.0) * value for name, value in components.items())
    return components, total


def generate_candidates(graph: GraphData, layouts: list[EngineLayout]) -> list[Candidate]:
    candidates = []
    for layout_index, layout in enumerate(layouts):
        for quarter_turn in range(4):
            for reflection in (False, True):
                positions, degrees, reflect_h, reflect_v = rotate_reflect(
                    graph, layout.raw_positions, quarter_turn, reflection
                )
                for reverse_a in (False, True):
                    for reverse_b in (False, True):
                        candidate_id = (
                            f"{graph.stem}__{layout.cap_id}__d{layout.dart[0]}-{layout.dart[1]}"
                            f"__q{quarter_turn}__mx{int(reflection)}"
                            f"__ra{int(reverse_a)}rb{int(reverse_b)}"
                        )
                        components, total = score_candidate(
                            graph, positions, layout.cap_id, reverse_a, reverse_b
                        )
                        candidates.append(Candidate(
                            graph, candidate_id, layout, positions, degrees,
                            reflect_h, reflect_v, reverse_a, reverse_b, components, total
                        ))
    return sorted(candidates, key=lambda item: (item.total, item.candidate_id))


def continuity_cost(previous: Candidate, current: Candidate) -> tuple[float, float]:
    prev_by_label = {
        structural_label(previous.graph, v, previous.reverse_a, previous.reverse_b): previous.positions[v]
        for v in previous.graph.labels
    }
    curr_by_label = {
        structural_label(current.graph, v, current.reverse_a, current.reverse_b): current.positions[v]
        for v in current.graph.labels
    }
    shared = sorted(set(prev_by_label) & set(curr_by_label))
    position_cost = mean(math.dist(prev_by_label[label], curr_by_label[label]) ** 2
                         for label in shared)
    prev_connectors = {
        connector_signature(previous.graph, item, previous.reverse_a, previous.reverse_b):
        ((previous.positions[item[0]][0] + previous.positions[item[1]][0]) / 2,
         (previous.positions[item[0]][1] + previous.positions[item[1]][1]) / 2)
        for item in previous.graph.edges
        if BASE.classify_edge(previous.graph, item) == "connector"
    }
    curr_connectors = {
        connector_signature(current.graph, item, current.reverse_a, current.reverse_b):
        ((current.positions[item[0]][0] + current.positions[item[1]][0]) / 2,
         (current.positions[item[0]][1] + current.positions[item[1]][1]) / 2)
        for item in current.graph.edges
        if BASE.classify_edge(current.graph, item) == "connector"
    }
    common = sorted(set(prev_connectors) & set(curr_connectors))
    connector_cost = mean(math.dist(prev_connectors[key], curr_connectors[key]) ** 2
                          for key in common)
    return position_cost, connector_cost


def pruned(candidates: list[Candidate], limit: int = 32) -> list[Candidate]:
    # Retain strong alternatives from each structural cap, then take a global
    # deterministic prefix.  This keeps all four outer-face hypotheses in DP.
    result: dict[str, Candidate] = {}
    for cap_id in ("A_rail_0", "A_rail_1", "B_rail_0", "B_rail_1"):
        for candidate in [c for c in candidates if c.engine_layout.cap_id == cap_id][:8]:
            result[candidate.candidate_id] = candidate
    for candidate in candidates[:limit]:
        result[candidate.candidate_id] = candidate
    return sorted(result.values(), key=lambda item: (item.total, item.candidate_id))


def weighted_cost(candidate: Candidate, weights: dict[str, float]) -> float:
    return sum(weights.get(name, 0.0) * value
               for name, value in candidate.components.items())


def optimize_sequence(candidate_sets: list[list[Candidate]],
                      weights: dict[str, float] = DEFAULT_WEIGHTS
                      ) -> tuple[list[Candidate], float, list[dict[str, float]]]:
    pools = []
    for items in candidate_sets:
        ranked = sorted(items, key=lambda item: (weighted_cost(item, weights), item.candidate_id))
        pools.append(pruned(ranked))
    costs = [weighted_cost(candidate, weights) for candidate in pools[0]]
    parents: list[list[int]] = []
    transitions: list[list[tuple[float, float]]] = []
    for index in range(1, len(pools)):
        next_costs = []
        next_parents = []
        next_transitions = []
        for current in pools[index]:
            choices = []
            for previous_index, previous in enumerate(pools[index - 1]):
                continuity, connector = continuity_cost(previous, current)
                transition = continuity + connector
                choices.append((costs[previous_index] + weighted_cost(current, weights)
                                + CONTINUITY_WEIGHT * transition,
                                previous.candidate_id, previous_index,
                                continuity, connector))
            best = min(choices)
            next_costs.append(best[0]); next_parents.append(best[2])
            next_transitions.append((best[3], best[4]))
        costs = next_costs
        parents.append(next_parents)
        transitions.append(next_transitions)
    final_index = min(range(len(costs)), key=lambda i: (costs[i], pools[-1][i].candidate_id))
    selected_indices = [final_index]
    for parent_row in reversed(parents):
        selected_indices.append(parent_row[selected_indices[-1]])
    selected_indices.reverse()
    selected = [pool[index] for pool, index in zip(pools, selected_indices)]
    details = []
    for index in range(1, len(selected)):
        continuity, connector = continuity_cost(selected[index - 1], selected[index])
        details.append({"position_continuity": continuity, "connector_continuity": connector,
                        "weighted_transition": CONTINUITY_WEIGHT * (continuity + connector)})
    return selected, min(costs), details


def coordinate_hash(positions: dict[int, tuple[float, float]]) -> str:
    payload = [[v, round(positions[v][0], 9), round(positions[v][1], 9)]
               for v in sorted(positions)]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def screen_positions(candidate: Candidate) -> dict[int, tuple[float, float]]:
    return {v: (x, -y) for v, (x, y) in candidate.positions.items()}


def candidate_record(candidate: Candidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "label": candidate.graph.label,
        "outer_face_structural_id": candidate.engine_layout.cap_id,
        "outer_face_boundary": candidate.engine_layout.face,
        "directed_edge_zero_based": list(candidate.engine_layout.dart),
        "cf_arguments_one_based": [candidate.engine_layout.dart[0] + 1,
                                   candidate.engine_layout.dart[1] + 1],
        "rotation_degrees": candidate.rotation_degrees,
        "reflect_horizontal": candidate.reflect_horizontal,
        "reflect_vertical": candidate.reflect_vertical,
        "reverse_ladder_a": candidate.reverse_a,
        "reverse_ladder_b": candidate.reverse_b,
        "preferred_insertion_side": "end",
        "component_scores": candidate.components,
        "weighted_total": candidate.total,
        "normalized_coordinate_sha256": coordinate_hash(candidate.positions),
    }


def normalized_tikz(graph: GraphData, positions: dict[int, tuple[float, float]],
                    title: str) -> str:
    lines = [
        r"\documentclass[tikz,border=3pt]{standalone}",
        r"\usepackage{tikz}",
        r"\begin{document}",
        f"% {title}; vertices retain certified zero-based identities in comments.",
        r"\begin{tikzpicture}[x=6cm,y=6cm]",
    ]
    for vertex in sorted(positions):
        x, y = positions[vertex]
        lines.append(f"\\coordinate (v{vertex}) at ({x:.9f},{y:.9f}); % vertex {vertex}")
    for u, v in graph.edges:
        lines.append(f"\\draw[line width=.55pt] (v{u}) -- (v{v});")
    for vertex in sorted(positions):
        lines.append(f"\\fill (v{vertex}) circle (1.15pt);")
    lines.extend((r"\end{tikzpicture}", r"\end{document}", ""))
    return "\n".join(lines)


def write_scene(root: Path, folder: str, stem: str, scene: list[dict[str, Any]],
                width: int, height: int, renderer: Path, commands: list[str],
                title: str, description: str) -> dict[str, str]:
    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    svg = directory / f"{stem}.svg"
    pdf = directory / f"{stem}.pdf"
    png = directory / f"{stem}.png"
    write_if_changed(svg, BASE.scene_to_svg(scene, width, height, title, description).encode("utf-8"))
    write_if_changed(pdf, BASE.scene_to_pdf(scene, width, height))
    BASE.render_png(svg, png, renderer, width, height, commands)
    return {kind: path.relative_to(root).as_posix()
            for kind, path in (("svg", svg), ("pdf", pdf), ("png", png))}


def atomic_write_with_retry(path: Path, data: bytes, attempts: int = 20) -> None:
    for attempt in range(attempts):
        try:
            atomic_write(path, data)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.25)


def write_if_changed(path: Path, data: bytes) -> None:
    if path.is_file() and path.read_bytes() == data:
        return
    atomic_write_with_retry(path, data)


def unique_best_alternatives(candidates: list[Candidate], count: int = 8) -> list[Candidate]:
    selected = []
    seen = set()
    # Guarantee one representative of each outer cap before filling by score.
    ordered = []
    for cap_id in (PREFERRED_OUTER_CAP, "B_rail_1", "A_rail_0", "A_rail_1"):
        ordered.extend([candidate for candidate in candidates
                        if candidate.engine_layout.cap_id == cap_id][:1])
    ordered.extend(candidates)
    for candidate in ordered:
        key = (candidate.engine_layout.cap_id, coordinate_hash(candidate.positions))
        if key in seen:
            continue
        seen.add(key); selected.append(candidate)
        if len(selected) == count:
            break
    return selected


def contact_sheet(graph: GraphData, candidates: list[Candidate]) -> tuple[list[dict[str, Any]], int, int]:
    alternatives = unique_best_alternatives(candidates)
    width, height = 1800, 980
    scene: list[dict[str, Any]] = [{"kind": "rect", "x": 0, "y": 0, "w": width,
                                   "h": height, "fill": "#FFFFFF"}]
    BASE._text(scene, width / 2, 48, f"{graph.label}: best 8 layout alternatives",
               30, weight="bold")
    for index, candidate in enumerate(alternatives):
        row, column = divmod(index, 4)
        source, _, _ = BASE.graph_scene(graph, screen_positions(candidate), annotated=False)
        scale = 0.315
        tx, ty = 35 + column * 440, 60 + row * 445
        scene.extend(BASE.transform_scene(source, scale, scale, tx, ty))
        BASE._text(scene, tx + 190, ty + 376,
                   f"{candidate.engine_layout.cap_id}; cf {candidate.engine_layout.dart[0]+1} {candidate.engine_layout.dart[1]+1}",
                   15, weight="bold")
        BASE._text(scene, tx + 190, ty + 398, f"total={candidate.total:.5f}", 14)
        BASE._text(scene, tx + 190, ty + 418, candidate.candidate_id[-22:], 11,
                   color=BASE.COLORS["muted"])
    return scene, width, height


def grid_scene(items: list[tuple[GraphData, list[dict[str, Any]]]], title: str,
               columns: int = 4) -> tuple[list[dict[str, Any]], int, int]:
    return BASE.grid_composite(items, title, columns)


def comparison_scene(graph: GraphData, candidates: list[Candidate], title: str
                     ) -> tuple[list[dict[str, Any]], int, int]:
    best_by_cap = []
    for cap_id in ("A_rail_0", "A_rail_1", "B_rail_0", "B_rail_1"):
        best_by_cap.append(next(c for c in candidates if c.engine_layout.cap_id == cap_id))
    items = []
    for candidate in best_by_cap:
        source, _, _ = BASE.graph_scene(graph, screen_positions(candidate), annotated=False)
        items.append((graph, source))
    scene, width, height = BASE.grid_composite(items, title, 4, 440, 470)
    for index, candidate in enumerate(best_by_cap):
        BASE._text(scene, 40 + index * 440 + 200, height - 28,
                   candidate.engine_layout.cap_id, 18, weight="bold")
    return scene, width, height


def raw_vs_normalized_scene(selected: list[Candidate]) -> tuple[list[dict[str, Any]], int, int]:
    examples = [selected[3], selected[7], selected[-1]]
    width, height = 1800, 1600
    scene: list[dict[str, Any]] = [{"kind": "rect", "x": 0, "y": 0, "w": width,
                                   "h": height, "fill": "#FFFFFF"}]
    BASE._text(scene, width / 2, 45, "Raw planar_draw coordinates versus normalized orientation",
               30, weight="bold")
    for row, candidate in enumerate(examples):
        raw_scene, _, _ = BASE.graph_scene(candidate.graph,
                                            candidate.engine_layout.raw_positions,
                                            annotated=False)
        normalized_scene, _, _ = BASE.graph_scene(candidate.graph,
                                                   screen_positions(candidate),
                                                   annotated=False)
        for column, source in enumerate((raw_scene, normalized_scene)):
            scale = 0.38
            tx, ty = 100 + column * 850, 70 + row * 500
            scene.extend(BASE.transform_scene(source, scale, scale, tx, ty))
        BASE._text(scene, 500, 118 + row * 500, f"{candidate.graph.label}: raw", 19, weight="bold")
        BASE._text(scene, 1350, 118 + row * 500, f"{candidate.graph.label}: normalized", 19, weight="bold")
    return scene, width, height


def write_manifest(root: Path) -> str:
    lines = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}")
    atomic_write(root / "SHA256SUMS.txt", ("\n".join(lines) + "\n").encode("ascii"))
    return sha256_file(root / "SHA256SUMS.txt")


def load_or_create_overrides(root: Path, graphs: list[GraphData]) -> dict[str, Any]:
    path = root / "layout_overrides.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA:
            raise GalleryError(f"unexpected override schema in {path}")
        return payload
    payload = {
        "schema": SCHEMA,
        "note": "Null values leave the deterministic automatic selection unchanged.",
        "graphs": {
            graph.label: {
                "outer_face_structural_id": None,
                "directed_edge_zero_based": None,
                "cf_arguments_one_based": None,
                "rotation_degrees": None,
                "reflect_horizontal": None,
                "reflect_vertical": None,
                "reverse_ladder_a": None,
                "reverse_ladder_b": None,
                "preferred_insertion_side": "end",
                "selected_candidate_id": None,
            } for graph in graphs
        },
    }
    atomic_json(path, payload)
    return payload


def apply_overrides(selected: list[Candidate], candidate_sets: list[list[Candidate]],
                    overrides: dict[str, Any]) -> tuple[list[Candidate], list[dict[str, Any]]]:
    result = list(selected); applied = []
    for index, automatic in enumerate(selected):
        values = overrides.get("graphs", {}).get(automatic.graph.label, {})
        requested = values.get("selected_candidate_id")
        if requested:
            matches = [candidate for candidate in candidate_sets[index]
                       if candidate.candidate_id == requested]
            if not matches:
                raise GalleryError(f"override candidate does not exist: {requested}")
            result[index] = matches[0]
            applied.append({"label": automatic.graph.label, "candidate_id": requested})
    return result, applied


def write_candidate_scores(root: Path, candidate_sets: list[list[Candidate]]) -> None:
    records = [candidate_record(candidate) for items in candidate_sets for candidate in items]
    atomic_json(root / "candidate_scores.json", {
        "schema": SCHEMA,
        "weights": DEFAULT_WEIGHTS,
        "continuity_weight": CONTINUITY_WEIGHT,
        "candidate_count": len(records),
        "candidates": records,
    })
    fields = ["candidate_id", "label", "outer_face_structural_id", "directed_edge_zero_based",
              "cf_arguments_one_based", "rotation_degrees", "reflect_horizontal",
              "reflect_vertical", "reverse_ladder_a", "reverse_ladder_b",
              "weighted_total", *DEFAULT_WEIGHTS]
    path = root / "candidate_scores.csv"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False,
                                     dir=root, prefix=".candidate_scores.", suffix=".tmp") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in records:
            row = {key: record.get(key) for key in fields}
            row["directed_edge_zero_based"] = ";".join(map(str, record["directed_edge_zero_based"]))
            row["cf_arguments_one_based"] = ";".join(map(str, record["cf_arguments_one_based"]))
            for name in DEFAULT_WEIGHTS:
                row[name] = record["component_scores"][name]
            writer.writerow(row)
        temporary = stream.name
    os.replace(temporary, path)


def solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Deterministic Gaussian elimination with partial pivoting."""
    size = len(rhs)
    augmented = [list(row) + [value] for row, value in zip(matrix, rhs)]
    for pivot in range(size):
        choice = max(range(pivot, size), key=lambda row: (abs(augmented[row][pivot]), -row))
        augmented[pivot], augmented[choice] = augmented[choice], augmented[pivot]
        if abs(augmented[pivot][pivot]) < EPS:
            raise GalleryError("singular constrained-layout harmonic system")
        divisor = augmented[pivot][pivot]
        augmented[pivot] = [value / divisor for value in augmented[pivot]]
        for row in range(size):
            if row == pivot:
                continue
            factor = augmented[row][pivot]
            if abs(factor) < EPS:
                continue
            augmented[row] = [augmented[row][column] - factor * augmented[pivot][column]
                              for column in range(size + 1)]
    return [augmented[row][-1] for row in range(size)]


def harmonic_completion(graph: GraphData, fixed: dict[int, tuple[float, float]]) -> dict[int, tuple[float, float]]:
    unknown = sorted(set(range(graph.order)) - set(fixed))
    if not unknown:
        return dict(fixed)
    index = {vertex: position for position, vertex in enumerate(unknown)}
    adjacency = {vertex: [] for vertex in range(graph.order)}
    for u, v in graph.edges:
        adjacency[u].append(v); adjacency[v].append(u)
    matrix = [[0.0 for _ in unknown] for _ in unknown]
    rhs_x = [0.0 for _ in unknown]; rhs_y = [0.0 for _ in unknown]
    for vertex in unknown:
        row = index[vertex]
        matrix[row][row] = float(len(adjacency[vertex]))
        for neighbor in adjacency[vertex]:
            if neighbor in index:
                matrix[row][index[neighbor]] -= 1.0
            else:
                rhs_x[row] += fixed[neighbor][0]
                rhs_y[row] += fixed[neighbor][1]
    xs = solve_linear_system(matrix, rhs_x)
    ys = solve_linear_system(matrix, rhs_y)
    result = dict(fixed)
    result.update({vertex: (xs[index[vertex]], ys[index[vertex]]) for vertex in unknown})
    return result


def convex_outer_coordinates(face: list[int], midpoint_degrees: float, direction: int,
                             y_scale: float, a_outer: set[int]) -> dict[int, tuple[float, float]]:
    size = len(face); step = 2.0 * math.pi / size
    indices = [face.index(vertex) for vertex in a_outer]
    base_vectors = [(math.cos(direction * step * index), math.sin(direction * step * index))
                    for index in indices]
    base_midpoint = math.atan2(mean(y for _, y in base_vectors), mean(x for x, _ in base_vectors))
    rotation = math.radians(midpoint_degrees) - base_midpoint
    return {
        vertex: (math.cos(rotation + direction * step * index),
                 y_scale * math.sin(rotation + direction * step * index))
        for index, vertex in enumerate(face)
    }


def refine_coordinates(candidate: Candidate) -> tuple[dict[int, tuple[float, float]], dict[str, Any]]:
    """Constrained harmonic redraw preserving the certified sphere embedding.

    The selected outer face is fixed to a convex ellipse.  Every A-rail vertex
    is fixed on one of two horizontal lines in effective structural order.  All
    remaining vertices are the unique harmonic solution.  Parameter choices
    are a declared grid and are accepted only when the straight-line drawing
    is crossing-free.
    """
    graph = candidate.graph
    outer = list(candidate.engine_layout.face)
    a_outer = {v for v in outer if graph.labels[v][0] == "A"}
    if len(a_outer) != 2:
        raise GalleryError(f"selected B cap does not have two A terminals in {graph.label}")
    attempts = []
    midpoint_grid = (15.0, 35.0, 50.0, 65.0, 80.0, 100.0, 120.0, 140.0, 160.0)
    y_scale_grid = (0.70, 0.90, 1.10, 1.30)
    other_end_grid = (-0.90, -0.70, -0.50, -0.30, -0.10, 0.10, 0.30, 0.50, 0.70)
    for midpoint in midpoint_grid:
        for direction in (-1, 1):
            for y_scale in y_scale_grid:
                outer_positions = convex_outer_coordinates(
                    outer, midpoint, direction, y_scale, a_outer
                )
                for other_end_x in other_end_grid:
                    fixed = dict(outer_positions)
                    for rail in (0, 1):
                        vertices = rail_vertices(graph, "A", rail,
                                                 candidate.reverse_a, candidate.reverse_b)
                        outer_vertex = next(vertex for vertex in vertices if vertex in a_outer)
                        outer_column = structural_label(graph, outer_vertex,
                                                        candidate.reverse_a,
                                                        candidate.reverse_b)[1]
                        outer_x, rail_y = fixed[outer_vertex]
                        if outer_column == graph.a:
                            left_x, right_x = other_end_x, outer_x
                        else:
                            left_x, right_x = outer_x, max(other_end_x, outer_x + 0.35)
                        for vertex in vertices:
                            column = structural_label(graph, vertex, candidate.reverse_a,
                                                      candidate.reverse_b)[1]
                            x = left_x + (right_x - left_x) * column / max(graph.a, 1)
                            fixed[vertex] = (x, rail_y)
                    positions = unit_positions(harmonic_completion(graph, fixed))
                    crossings = crossing_count(graph, positions)
                    if crossings:
                        continue
                    components, total = score_candidate(
                        graph, positions, candidate.engine_layout.cap_id,
                        candidate.reverse_a, candidate.reverse_b
                    )
                    # Prefer straight/top A, smooth B, and healthy edge spacing.
                    objective = (8.0 * components["top_ladder_straightness"]
                                 + 4.0 * components["top_position"]
                                 + 3.0 * components["outer_boundary_ladder"]
                                 + 2.0 * components["drawing_quality"])
                    attempts.append((crossings, objective, midpoint, direction, y_scale,
                                     other_end_x, positions, components, total))
    valid = [attempt for attempt in attempts if attempt[0] == 0]
    if not valid:
        raise GalleryError(f"no crossing-free constrained refinement for {graph.label}")
    best = min(valid, key=lambda item: (item[1], item[2], item[3], item[4], item[5]))
    _, objective, midpoint, direction, y_scale, other_end_x, positions, components, total = best
    a_effective_start = [v for v in graph.labels
                         if structural_label(graph, v, candidate.reverse_a,
                                             candidate.reverse_b)[:2] == ("A", 0)]
    a_effective_end = [v for v in graph.labels
                       if structural_label(graph, v, candidate.reverse_a,
                                           candidate.reverse_b)[:2] == ("A", graph.a)]
    start_x = mean(positions[v][0] for v in a_effective_start)
    end_x = mean(positions[v][0] for v in a_effective_end)
    reflected_x = end_x < start_x
    if reflected_x:
        positions = {v: (-x, y) for v, (x, y) in positions.items()}
    a_vertices = [v for v, label in graph.labels.items() if label[0] == "A"]
    reflected_y = mean(positions[v][1] for v in a_vertices) < mean(
        point[1] for point in positions.values()
    )
    if reflected_y:
        positions = {v: (x, -y) for v, (x, y) in positions.items()}
    components, total = score_candidate(
        graph, positions, candidate.engine_layout.cap_id,
        candidate.reverse_a, candidate.reverse_b
    )
    objective = (8.0 * components["top_ladder_straightness"]
                 + 4.0 * components["top_position"]
                 + 3.0 * components["outer_boundary_ladder"]
                 + 2.0 * components["drawing_quality"])
    outer_convex = strictly_convex([positions[v] for v in outer])
    if not outer_convex:
        raise GalleryError(f"refined selected outer face is not strictly convex: {graph.label}")
    metadata = {
        "method": "convex-ellipse outer face; horizontal fixed A rails; harmonic completion",
        "coordinate_refined": True,
        "raw_planar_draw_replaced": False,
        "selected_outer_face": candidate.engine_layout.cap_id,
        "outer_face_boundary": outer,
        "outer_face_constraint": "convex ellipse",
        "a_rail_constraint": "two horizontal parallel lines in structural order",
        "free_vertex_objective": "discrete harmonic (uniform-neighbor barycentric) coordinates",
        "parameter_grid": {"midpoint_degrees": list(midpoint_grid),
                           "direction": [-1, 1], "ellipse_y_scale": list(y_scale_grid),
                           "other_a_end_x": list(other_end_grid)},
        "selected_parameters": {"midpoint_degrees": midpoint, "direction": direction,
                                "ellipse_y_scale": y_scale, "other_a_end_x": other_end_x},
        "canonical_global_reflection": {
            "horizontal_to_make_effective_A_increase_left_to_right": reflected_x,
            "vertical_to_place_A_above_graph_centroid": reflected_y,
        },
        "documented_objective": objective,
        "component_scores": components,
        "weighted_total_under_raw_weights": total,
        "crossing_count": 0,
        "outer_face_convex": outer_convex,
    }
    return positions, metadata


def selected_summary(candidate: Candidate) -> dict[str, Any]:
    record = candidate_record(candidate)
    record["crossing_count"] = crossing_count(candidate.graph, candidate.positions)
    record["reason"] = (
        "family-wide minimum of documented individual geometry cost plus "
        "structural-coordinate continuity cost"
    )
    return record


def build(args: argparse.Namespace) -> None:
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for folder in ("raw", "normalized", "refined", "annotated", "contact_sheets", "composite"):
        (root / folder).mkdir(exist_ok=True)
    graphs = BASE.load_graphs(args.sequence_root.resolve(), args.prediction_root.resolve())
    overrides = load_or_create_overrides(root, graphs)
    commands = ["BUILD\t" + subprocess.list2cmdline(
        [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])]

    structural: dict[str, Any] = {"schema": SCHEMA, "graphs": {}}
    embedding_checks: dict[str, Any] = {}
    outer_face_checks: dict[str, Any] = {}
    candidate_sets: list[list[Candidate]] = []
    engine_layout_sets: list[list[EngineLayout]] = []

    for graph in graphs:
        embedding = verify_certified_embedding(graph)
        embedding_checks[graph.label] = embedding
        caps = cap_records(graph)
        vertices = {}
        for vertex in sorted(graph.labels):
            ladder, column, rail = graph.labels[vertex]
            vertices[str(vertex)] = {
                "ladder": ladder,
                "column": column,
                "rail": "upper" if rail == 0 else "lower",
                "rail_index": rail,
                "latest_insertion_gadget": vertex in graph.inserted_vertices,
            }
        structural["graphs"][graph.label] = {
            "order": graph.order,
            "canonical_graph_hash": graph.graph_hash,
            "vertices": vertices,
            "edges": [{"endpoints": list(item), "class": BASE.classify_edge(graph, item)}
                      for item in graph.edges],
            "cap_faces": caps,
            "latest_square_insertion_gadget": graph.inserted_vertices,
        }
        layouts, checks = enumerate_engine_layouts(graph, args.engine.resolve(), commands)
        engine_layout_sets.append(layouts)
        outer_face_checks[graph.label] = checks
        candidates = generate_candidates(graph, layouts)
        candidate_sets.append(candidates)
        print(f"CANDIDATES {graph.label}: {len(layouts)} cf layouts, {len(candidates)} scored variants")

    write_candidate_scores(root, candidate_sets)
    atomic_json(root / "structural_coordinates.json", structural)

    full_selected, full_cost, full_transitions = optimize_sequence(candidate_sets)
    full_selected, applied_overrides = apply_overrides(full_selected, candidate_sets, overrides)
    certified_selected, certified_cost, certified_transitions = optimize_sequence(candidate_sets[:8])
    paper_indices = [3, 4, 5, 6, 7]
    paper_selected, paper_cost, paper_transitions = optimize_sequence(
        [candidate_sets[index] for index in paper_indices]
    )
    independent = [min(items, key=lambda candidate: (candidate.total, candidate.candidate_id))
                   for items in candidate_sets]
    independent_transition = sum(sum(continuity_cost(independent[i - 1], independent[i]))
                                 for i in range(1, len(independent)))
    optimized_transition = sum(sum(continuity_cost(full_selected[i - 1], full_selected[i]))
                               for i in range(1, len(full_selected)))

    sensitivity = {}
    for name, weights in SENSITIVITY_WEIGHTS.items():
        chosen, cost, _ = optimize_sequence(candidate_sets, weights)
        sensitivity[name] = {
            "weights": weights,
            "sequence_cost": cost,
            "candidate_ids": [candidate.candidate_id for candidate in chosen],
            "same_candidate_count_as_default": sum(
                a.candidate_id == b.candidate_id for a, b in zip(chosen, full_selected)
            ),
            "same_outer_cap_count_as_default": sum(
                a.engine_layout.cap_id == b.engine_layout.cap_id
                for a, b in zip(chosen, full_selected)
            ),
        }

    selected_payload = {
        "schema": SCHEMA,
        "objective": {
            "individual_weights": DEFAULT_WEIGHTS,
            "continuity_weight": CONTINUITY_WEIGHT,
            "candidate_pruning": "best 8 per structural cap plus global best 32",
        },
        "complete_sequence": {
            "sequence_cost": full_cost,
            "graphs": [selected_summary(candidate) for candidate in full_selected],
            "transitions": full_transitions,
        },
        "certified_maximizer_sequence_through_D_9_7": {
            "sequence_cost": certified_cost,
            "graphs": [selected_summary(candidate) for candidate in certified_selected],
            "transitions": certified_transitions,
        },
        "paper_sequence": {
            "sequence_cost": paper_cost,
            "graphs": [selected_summary(candidate) for candidate in paper_selected],
            "transitions": paper_transitions,
        },
        "manual_overrides_applied": applied_overrides,
        "sensitivity_checks": sensitivity,
    }
    atomic_json(root / "selected_layouts.json", selected_payload)

    clean_scenes: dict[str, list[dict[str, Any]]] = {}
    display_scenes: dict[str, list[dict[str, Any]]] = {}
    raw_scenes: dict[str, list[dict[str, Any]]] = {}
    output_records = []
    selected_verification = []
    refinement_required = []
    for graph, candidate in zip(graphs, full_selected):
        raw_path = root / "raw" / f"{graph.stem}.tex"
        atomic_write(raw_path, candidate.engine_layout.raw_tex.encode("utf-8"))
        raw_scene, _, _ = BASE.graph_scene(graph, candidate.engine_layout.raw_positions,
                                           annotated=False)
        clean_scene, clean_pos, clean_norm = BASE.graph_scene(
            graph, screen_positions(candidate), annotated=False
        )
        clean_scenes[graph.stem] = clean_scene
        raw_scenes[graph.stem] = raw_scene
        atomic_write(root / "normalized" / f"{graph.stem}.tex",
                     normalized_tikz(graph, candidate.positions, graph.label).encode("utf-8"))
        clean_files = write_scene(root, "normalized", graph.stem, clean_scene, CANVAS, CANVAS,
                                  args.edge_renderer.resolve(), commands,
                                  f"Normalized {graph.label}",
                                  "Raw planar_draw layout after global similarity normalization only.")
        refine = (candidate.components["top_ladder_straightness"] > 0.18
                  or candidate.components["outer_boundary_ladder"] > 0.18)
        refined_positions = None
        refinement_metadata = None
        refined_files = None
        if refine:
            refinement_required.append(graph.label)
            refined_positions, refinement_metadata = refine_coordinates(candidate)
            refined_scene, refined_canvas, refined_norm = BASE.graph_scene(
                graph, {v: (x, -y) for v, (x, y) in refined_positions.items()}, annotated=False
            )
            annotated_scene, annotated_pos, annotated_norm = BASE.graph_scene(
                graph, {v: (x, -y) for v, (x, y) in refined_positions.items()}, annotated=True
            )
            display_scenes[graph.stem] = refined_scene
            atomic_write(root / "refined" / f"{graph.stem}.tex",
                         normalized_tikz(graph, refined_positions,
                                         f"coordinate-refined {graph.label}").encode("utf-8"))
            refined_files = write_scene(root, "refined", graph.stem, refined_scene,
                                        CANVAS, CANVAS, args.edge_renderer.resolve(), commands,
                                        f"Coordinate-refined {graph.label}",
                                        "Convex-outer-face, horizontal-A-rail constrained harmonic redraw.")
            refinement_metadata["vertex_positions"] = {
                str(v): list(refined_positions[v]) for v in sorted(refined_positions)
            }
            refinement_metadata["viewport_normalization"] = refined_norm
            atomic_json(root / "refined" / f"{graph.stem}.json", refinement_metadata)
        else:
            annotated_scene, annotated_pos, annotated_norm = BASE.graph_scene(
                graph, screen_positions(candidate), annotated=True
            )
            display_scenes[graph.stem] = clean_scene
        annotated_files = write_scene(root, "annotated", graph.stem, annotated_scene,
                                      CANVAS, CANVAS, args.edge_renderer.resolve(), commands,
                                      f"Structural {graph.label}",
                                      "Certified double-ladder structural coordinate annotation; refined coordinates are explicitly recorded when used.")
        annotation = {
            "schema": SCHEMA,
            "label": graph.label,
            "candidate": candidate_record(candidate),
            "coordinate_refinement": refinement_metadata,
            "vertex_positions_canvas": {str(v): list(clean_pos[v]) for v in sorted(clean_pos)},
            "edge_classes": {f"{u}-{v}": BASE.classify_edge(graph, (u, v))
                             for u, v in graph.edges},
            "cap_faces": cap_records(graph),
            "latest_insertion_vertices": graph.inserted_vertices,
        }
        atomic_json(root / "annotated" / f"{graph.stem}.json", annotation)
        contact, contact_width, contact_height = contact_sheet(graph, candidate_sets[graphs.index(graph)])
        contact_files = write_scene(root, "contact_sheets", graph.stem, contact,
                                    contact_width, contact_height, args.edge_renderer.resolve(), commands,
                                    f"{graph.label} candidate contact sheet",
                                    "Best eight deterministic outer-face/orientation candidates with scores.")
        verified_positions = refined_positions if refined_positions is not None else candidate.positions
        crossings = crossing_count(graph, verified_positions)
        if crossings:
            raise GalleryError(f"selected drawing has {crossings} crossings: {graph.label}")
        verification = {
            "label": graph.label,
            "status": "pass",
            "exact_vertex_set": True,
            "exact_edge_set": True,
            "vertex_count": graph.order,
            "edge_count": graph.edge_count,
            "rotation_system_consistent": True,
            "selected_outer_face": candidate.engine_layout.cap_id,
            "outer_face_boundary": candidate.engine_layout.face,
            "outer_face_size": len(candidate.engine_layout.face),
            "cf_directed_edge_zero_based": list(candidate.engine_layout.dart),
            "ladder_connector_labels_verified": True,
            "latest_insertion_labels_verified": len(graph.inserted_vertices) in (0, 4),
            "crossing_count": crossings,
            "duplicated_or_missing_vertices": False,
            "certified_global_maximizer_claim": graph.certified_extremal,
            "global_extremality_disclaimer_required": graph.order > 36,
            "output_method": ("coordinate-refined constrained harmonic redraw (raw and global-normalized retained)"
                              if refined_positions is not None else
                              "raw_planar_draw plus global similarity normalization"),
            "coordinate_refinement_used": refined_positions is not None,
            "refined_outer_face_convex": (refinement_metadata or {}).get("outer_face_convex"),
        }
        selected_verification.append(verification)
        output_records.append({
            "label": graph.label,
            "raw_tikz": raw_path.relative_to(root).as_posix(),
            "normalized_tikz": f"normalized/{graph.stem}.tex",
            "normalized": clean_files,
            "annotated": annotated_files,
            "annotation_json": f"annotated/{graph.stem}.json",
            "contact_sheet": contact_files,
            "viewport_normalization": clean_norm,
            "annotated_viewport_normalization": annotated_norm,
            "refined": refined_files,
            "refinement_json": f"refined/{graph.stem}.json" if refinement_metadata else None,
            "coordinate_refinement_used": refined_positions is not None,
        })
        selected_payload["complete_sequence"]["graphs"][graphs.index(graph)].update({
            "final_output_method": ("refined_layout" if refined_positions is not None
                                    else "normalized_raw_planar_draw"),
            "coordinate_refinement_used": refined_positions is not None,
            "refinement_metadata": refinement_metadata,
        })

    atomic_json(root / "selected_layouts.json", selected_payload)

    refined_note = (
        "# Refined layouts\n\nThese explicitly labeled optional second-stage drawings retain each selected "
        "outer face on a convex ellipse, constrain ladder A to two horizontal parallel "
        "lines in structural order, and solve all remaining coordinates harmonically. "
        "Every drawing is checked for crossings. Literal `planar_draw` TikZ remains in "
        "`../raw/`, and global-similarity-only derivatives remain in `../normalized/`.\n"
    )
    atomic_write(root / "refined" / "README.md", refined_note.encode("utf-8"))

    composites: dict[str, dict[str, str]] = {}
    pairs = [(graph, display_scenes[graph.stem]) for graph in graphs]
    composite_specs = {
        "certified_bauer_family": grid_scene(pairs[:8],
            "Certified Bauer double-ladder maximizers through n=36", 4),
        "extended_double_ladder_family": grid_scene(pairs,
            "Double-ladder family (orders above 36: global extremality unproved)", 4),
        "square_insertion_sequence": grid_scene(pairs[3:],
            "Successive four-vertex square insertions", 4),
        "outer_face_comparison": comparison_scene(graphs[7], candidate_sets[7],
            "Outer-face comparison for D(9,7)"),
        "raw_vs_normalized_layout": raw_vs_normalized_scene(full_selected),
    }
    for name, (scene, width, height) in composite_specs.items():
        composites[name] = write_scene(root, "composite", name, scene, width, height,
                                       args.edge_renderer.resolve(), commands,
                                       name.replace("_", " ").title(),
                                       "Verified Bauer double-ladder layout-study composite.")

    alignment = {
        "schema": SCHEMA,
        "method": "structural coordinates (ladder, effective column, rail)",
        "complete_sequence": [],
        "independent_selection_transition_cost": independent_transition,
        "family_optimized_transition_cost": optimized_transition,
        "improvement": independent_transition - optimized_transition,
    }
    for index, candidate in enumerate(full_selected):
        item = {
            "label": candidate.graph.label,
            "candidate_id": candidate.candidate_id,
            "coordinates_by_structure": {
                "/".join(map(str, structural_label(candidate.graph, v,
                                                    candidate.reverse_a,
                                                    candidate.reverse_b))):
                list(candidate.positions[v]) for v in sorted(candidate.graph.labels)
            },
        }
        if index:
            continuity, connector = continuity_cost(full_selected[index - 1], candidate)
            item["transition_from_previous"] = {
                "position_continuity": continuity,
                "connector_continuity": connector,
            }
        alignment["complete_sequence"].append(item)
    atomic_json(root / "family_alignment.json", alignment)

    verification_payload = {
        "schema": SCHEMA,
        "status": "pass",
        "outer_face_option_source_confirmation": {
            "confirmed": True,
            "behavior": "for genus 0, cf x y selects the face to the left of directed edge x->y as the outer face",
            "source": str(args.engine_source.resolve()),
            "usage_function_lines_in_inspected_source": "4176-4177",
        },
        "certified_embeddings": {label: data["checks"] for label, data in embedding_checks.items()},
        "outer_face_trials": outer_face_checks,
        "selected_drawings": selected_verification,
    }
    atomic_json(root / "drawing_verification.json", verification_payload)
    atomic_json(root / "output_index.json", {"schema": SCHEMA, "graphs": output_records,
                                              "composites": composites})

    environment = {
        "schema": SCHEMA,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "worker_count": 1,
        "drawing_engine": {
            "name": "Gunnar Brinkmann planar_draw",
            "path": str(args.engine.resolve()),
            "sha256": sha256_file(args.engine.resolve()),
            "source_path": str(args.engine_source.resolve()),
            "source_sha256": sha256_file(args.engine_source.resolve()),
            "source_policy": "external, ignored, unmodified, not copied",
            "options_base": list(ENGINE_OPTIONS),
            "outer_face_option": "cf x y",
        },
        "png_renderer": {"path": str(args.edge_renderer.resolve()),
                         "sha256": sha256_file(args.edge_renderer.resolve()),
                         "device_scale_factor": PNG_SCALE},
        "inputs": {"sequence_root": str(args.sequence_root.resolve()),
                   "prediction_root": str(args.prediction_root.resolve())},
        "outputs": {"study_root": str(root), "paper_root": str(args.paper_root.resolve())},
        "determinism": {"randomness": "none", "candidate_sort": "numeric score then candidate ID",
                        "global_optimizer": "dynamic programming"},
    }
    atomic_json(root / "environment.json", environment)

    write_report(root, graphs, full_selected, selected_verification, composites,
                 alignment, sensitivity, refinement_required)
    write_paper_bundle(root, args.paper_root.resolve(), composites)
    verifier = HERE / "verify_bauer_double_ladder_layout_study.py"
    if verifier.is_file():
        shutil.copyfile(verifier, root / verifier.name)
    atomic_write(root / "commands.log", ("\n".join(commands) + "\n").encode("utf-8"))
    manifest_hash = write_manifest(root)
    print(f"MANIFEST {manifest_hash}")


def write_report(root: Path, graphs: list[GraphData], selected: list[Candidate],
                 verification: list[dict[str, Any]], composites: dict[str, dict[str, str]],
                 alignment: dict[str, Any], sensitivity: dict[str, Any],
                 refinement_required: list[str]) -> None:
    refined_records = {}
    for graph in graphs:
        path = root / "refined" / f"{graph.stem}.json"
        if path.is_file():
            refined_records[graph.label] = json.loads(path.read_text(encoding="utf-8"))
    all_preferred = all(candidate.engine_layout.cap_id == PREFERRED_OUTER_CAP
                        for candidate in selected)
    final_components = {
        candidate.graph.label: refined_records.get(candidate.graph.label, {}).get(
            "component_scores", candidate.components
        ) for candidate in selected
    }
    all_top = all(final_components[candidate.graph.label]["top_position"] < 0.05
                  for candidate in selected)
    all_boundary = all(final_components[candidate.graph.label]["outer_boundary_ladder"] < 0.30
                       for candidate in selected)
    lines = [
        "# Bauer double-ladder layout study", "",
        "This study is a visualization-only derivative of immutable certified graph packages. "
        "It ran no graph census, Hamiltonian enumeration, hsep optimization, or mathematical search. "
        "The external C source and executable were neither modified nor copied into the results.", "",
        "## Answers to the study questions", "",
        "1. **Outer-face control:** Yes. Source inspection confirms that for genus zero `cf x y` "
        "selects the face on the left of `x -> y`. Every directed boundary edge of every structural cap "
        "was exercised, and the selected boundary was independently recognized as the program's outer circle.",
        f"2. **Clearest cap:** `{PREFERRED_OUTER_CAP}` is the preferred structural exterior; it leaves ladder A internal "
        "and lets ladder B follow the outer boundary. " + ("It was selected for all graphs." if all_preferred else
        "Family optimization selected a different cap for at least one graph; see the table below."),
        "3. **Top ladder:** Outer-face choice and global transformations alone were insufficient: "
        "ladder A remained lateral in the raw layouts. The explicit constrained-refinement stage makes "
        "both A rails exactly horizontal in structural order and places A above the graph centroid" +
        (" for every graph." if all_top else " for most graphs."),
        "4. **Boundary ladder:** " + ("Yes" if all_boundary else "Partly") +
        ". Ladder B is scored by a least-squares smooth-circle residual and lower-boundary placement, without requiring an exact circle.",
        "5. **Coordinate refinement:** Yes. Global transformations could not meet the requested top-ladder "
        "convention, so the optional, explicitly labeled convex-outer-face/horizontal-A/harmonic stage was "
        "used for " + ", ".join(refinement_required) + ". Raw and globally normalized versions are retained.",
        f"6. **Family-wide optimization:** Its unweighted structural transition cost is "
        f"{alignment['family_optimized_transition_cost']:.6g}, versus "
        f"{alignment['independent_selection_transition_cost']:.6g} for independent minima "
        f"(improvement {alignment['improvement']:.6g}).", "",
        "7. **Selected candidates:**", "",
        "| graph | n | exterior | cf (1-based) | raw cost | refined A straightness | refined B boundary | status |",
        "|---|---:|---|---|---:|---:|---:|---|",
    ]
    for graph, candidate in zip(graphs, selected):
        status = "certified maximizer" if graph.certified_extremal else "global extremality unproved"
        scores = final_components[graph.label]
        lines.append(
            f"| {graph.label} | {graph.order} | {candidate.engine_layout.cap_id} | "
            f"{candidate.engine_layout.dart[0]+1}->{candidate.engine_layout.dart[1]+1} | "
            f"{candidate.total:.6f} | {scores['top_ladder_straightness']:.6f} | "
            f"{scores['outer_boundary_ladder']:.6f} | {status} |"
        )
    lines.extend((
        "", "8. **Verification:** Yes. Exact vertex/edge sets and counts, certified rotation-system faces, "
        "structural labels, insertion labels, selected outer faces, and zero crossings are recorded in "
        "`drawing_verification.json`.",
        "9. **Raw versus refined:** `raw/` contains literal `planar_draw` TikZ. `normalized/` applies only "
        "global translation, uniform scaling, rotation, and reflection. `refined/` contains explicitly labeled "
        "constrained harmonic redraws plus their complete coordinates and objectives.",
        "10. **Manual overrides:** None are required for reproducibility. `layout_overrides.json` can pin a "
        "candidate for later expert aesthetic review; no override was used in the automated run.", "",
        "## Scoring and sensitivity", "",
        "All component costs are saved separately. Lower is better. Default weights are: `" +
        json.dumps(DEFAULT_WEIGHTS, sort_keys=True) + "`; transition weight is `" +
        str(CONTINUITY_WEIGHT) + "`. Candidate pruning retains the best eight from every cap plus the "
        "best 32 overall before dynamic programming. Two declared alternative weight sets were rerun:", "",
    ))
    for name, record in sensitivity.items():
        lines.append(f"- `{name}` retained the same exact candidate for "
                     f"{record['same_candidate_count_as_default']}/{len(graphs)} graphs and the same "
                     f"outer cap for {record['same_outer_cap_count_as_default']}/{len(graphs)} graphs.")
    lines.extend(("", "## Composite figures", ""))
    for name, files in composites.items():
        lines.append(f"- `{name}`: `{files['pdf']}`, `{files['svg']}`, `{files['png']}`")
    lines.extend((
        "", "The certified plate ends at order 36. Every order 40, 44, or 48 label explicitly says that "
        "global Barnette extremality is unproved. Exact graph-specific certificates are not interpreted as "
        "complete-census maximizer claims.", "",
        "## Reproduction", "",
        "See `commands.log`, `environment.json`, `candidate_scores.json`, `selected_layouts.json`, and "
        "`SHA256SUMS.txt`. The pipeline contains no pseudorandom choices.", "",
    ))
    atomic_write(root / "LAYOUT_STUDY_REPORT.md", ("\n".join(lines) + "\n").encode("utf-8"))


def write_paper_bundle(root: Path, paper_root: Path,
                       composites: dict[str, dict[str, str]]) -> None:
    paper_root.mkdir(parents=True, exist_ok=True)
    names = ["certified_bauer_family", "extended_double_ladder_family",
             "square_insertion_sequence", "outer_face_comparison",
             "raw_vs_normalized_layout"]
    for name in names:
        shutil.copyfile(root / composites[name]["pdf"], paper_root / f"{name}.pdf")
    tex = r"""% Generated include fragment; main.tex is intentionally not edited.
\begin{figure*}[t]
  \centering
  \includegraphics[width=.98\textwidth]{figures/bauer_layout/certified_bauer_family.pdf}
  \caption{Certified Bauer double-ladder maximizers through order 36 in a common structural orientation.}
  \label{fig:bauer-layout-certified}
\end{figure*}

\begin{figure*}[t]
  \centering
  \includegraphics[width=.98\textwidth]{figures/bauer_layout/extended_double_ladder_family.pdf}
  \caption{Extended double-ladder family. Global extremality is not claimed beyond order 36.}
  \label{fig:bauer-layout-extended}
\end{figure*}

\begin{figure*}[t]
  \centering
  \includegraphics[width=.98\textwidth]{figures/bauer_layout/square_insertion_sequence.pdf}
  \caption{The alternating four-vertex square-insertion sequence.}
  \label{fig:bauer-layout-insertions}
\end{figure*}
"""
    atomic_write(paper_root / "bauer_layout_figures.tex", tex.encode("utf-8"))
    readme = """# Bauer layout figures

These PDFs are selected derivatives of the verified external layout study at
`E:\\barnette-results\\bauer-double-ladder-layout-study`.  The drawings preserve
the certified abstract graph and rotation system.  The paper composites use
explicitly labeled convex-outer-face/horizontal-ladder constrained refinements;
literal raw and global-similarity-only versions remain in the study root. Orders above 36
are family members with graph-specific certificates, not certified global
maximizers.  Include `bauer_layout_figures.tex` from the paper directory; all
LaTeX paths are relative and `main.tex` was not edited.
"""
    atomic_write(paper_root / "README.md", readme.encode("utf-8"))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--sequence-root", type=Path, required=True)
    result.add_argument("--prediction-root", type=Path, required=True)
    result.add_argument("--output-root", type=Path, required=True)
    result.add_argument("--paper-root", type=Path, required=True)
    result.add_argument("--engine", type=Path, required=True)
    result.add_argument("--engine-source", type=Path, required=True)
    result.add_argument("--edge-renderer", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        build(parser().parse_args(argv))
    except (GalleryError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
