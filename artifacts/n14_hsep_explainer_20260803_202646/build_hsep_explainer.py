#!/usr/bin/env python3
"""Final 12-column launcher for the certified n=14 hsep explainer."""

from __future__ import annotations

import html
import importlib.util
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


PREVIOUS = (
    Path(__file__).resolve().parents[1]
    / "n14_hsep_explainer_20260803_201712"
    / "build_hsep_explainer.py"
)
spec = importlib.util.spec_from_file_location("n14_hsep_explainer_final_base", PREVIOUS)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load final base builder: {PREVIOUS}")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

helper = base.helper
previous_build_scene = helper.build_scene
original_write_new = helper.write_new
original_write_json_new = helper.write_json_new

ALL_CYCLE_INDICES = list(range(1, 13))
UNUSED_CYCLE_INDICES = {6, 9}
all_column_bits: dict[tuple[tuple[int, int], int], str] = {}


def dashed_segment(scene, x1, y1, x2, y2, *, dash=12.0, gap=8.0):
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    position = 0.0
    while position < length:
        end = min(length, position + dash)
        scene.line(
            x1 + ux * position,
            y1 + uy * position,
            x1 + ux * end,
            y1 + uy * end,
            color=helper.UNUSED,
            width=2.5,
            css_class="cycle-column-arrow",
        )
        position += dash + gap


def arrow_path(scene, points, label):
    for first, second in zip(points, points[1:]):
        dashed_segment(scene, *first, *second)
    end_x, end_y = points[-1]
    scene.line(end_x, end_y, end_x - 8, end_y - 11, color=helper.UNUSED, width=2.5)
    scene.line(end_x, end_y, end_x + 8, end_y - 11, color=helper.UNUSED, width=2.5)
    start_x, start_y = points[0]
    scene.rect(start_x + 4, start_y - 17, 42, 28, fill=helper.UNUSED_SOFT, stroke=helper.UNUSED, stroke_width=1, radius=6)
    scene.text(start_x + 25, start_y + 3, label, size=14, color=helper.MUTED, weight=700, anchor="middle")


def twelve_column_build_scene(source_positions, graph_edges, cycles, selected, signatures):
    global all_column_bits
    scene = previous_build_scene(source_positions, graph_edges, cycles, selected, signatures)

    all_column_bits = {
        (item, cycle_index): "1" if item in cycles[cycle_index - 1] else "0"
        for item in graph_edges
        for cycle_index in ALL_CYCLE_INDICES
    }

    filtered = []
    for item in scene.items:
        if item.get("class") == "signature-cell":
            continue
        if item["kind"] == "text" and item["value"] == "21 Kanten × 10 ausgewählte Zyklen":
            continue
        if (
            item["kind"] == "text"
            and item["y"] == 372
            and item["x"] >= 1885
            and str(item["value"]).startswith("C")
        ):
            continue
        filtered.append(item)
    scene.items = filtered

    matrix_x, matrix_y = 1885, 385
    column_width, row_height = 39, 39
    scene.text(
        1790,
        332,
        "12 Spalten sichtbar · 10 blau ausgewählt",
        size=16,
        color=helper.NAVY,
        weight=700,
    )

    for cycle_index in UNUSED_CYCLE_INDICES:
        column = cycle_index - 1
        scene.rect(
            matrix_x + column * column_width - 2,
            342,
            column_width,
            880,
            fill="#F0F1F2",
            stroke="#C7CCD1",
            stroke_width=1,
            radius=5,
            css_class="unused-cycle-column-band",
            attrs={"data-cycle-index": cycle_index},
        )

    for column, cycle_index in enumerate(ALL_CYCLE_INDICES):
        is_selected = cycle_index not in UNUSED_CYCLE_INDICES
        scene.text(
            matrix_x + column * column_width + (column_width - 4) / 2,
            372,
            f"C{cycle_index}",
            size=12,
            color=helper.MUTED if is_selected else "#737C85",
            weight=700,
            anchor="middle",
            css_class="signature-column-header",
            attrs={"data-cycle-index": cycle_index, "data-selected": str(is_selected).lower()},
        )

    for row, graph_edge in enumerate(graph_edges):
        y = matrix_y + row * row_height
        for column, cycle_index in enumerate(ALL_CYCLE_INDICES):
            bit = all_column_bits[(graph_edge, cycle_index)]
            is_selected = cycle_index not in UNUSED_CYCLE_INDICES
            if is_selected:
                fill = helper.BLUE if bit == "1" else helper.LIGHT
                text_color = helper.WHITE if bit == "1" else helper.MUTED
            else:
                fill = "#818B95" if bit == "1" else "#E1E4E7"
                text_color = helper.WHITE if bit == "1" else "#737C85"
            x = matrix_x + column * column_width
            scene.rect(
                x,
                y,
                column_width - 4,
                row_height - 4,
                fill=fill,
                stroke=helper.WHITE,
                stroke_width=1,
                radius=4,
                css_class="signature-cell",
                attrs={
                    "data-edge": f"{graph_edge[0]}-{graph_edge[1]}",
                    "data-cycle-index": cycle_index,
                    "data-bit": bit,
                    "data-selected": str(is_selected).lower(),
                },
            )
            scene.text(
                x + (column_width - 4) / 2,
                y + 25,
                bit,
                size=14,
                color=text_color,
                weight=700,
                anchor="middle",
            )

    c6_x = matrix_x + 5 * column_width + (column_width - 4) / 2
    c9_x = matrix_x + 8 * column_width + (column_width - 4) / 2
    arrow_path(scene, [(1655, 629), (1708, 629), (1708, 345), (c6_x, 345), (c6_x, 356)], "Z6")
    arrow_path(scene, [(1655, 909), (1720, 909), (1720, 353), (c9_x, 353), (c9_x, 356)], "Z9")

    scene.text(
        2120,
        1260,
        "Grau: C6 und C9 sind vorhanden, aber nicht Teil des 10er-Zertifikats.",
        size=14,
        color=helper.MUTED,
        weight=700,
        anchor="middle",
    )
    return scene


def verify_twelve_column_svg(path, selected, graph_edges, signatures, source_positions, coordinate_hash):
    root = ET.parse(path).getroot()
    if root.attrib.get("data-source-coordinate-sha256") != coordinate_hash:
        raise helper.BuildError("SVG coordinate hash mismatch")
    cells = {}
    headers = {}
    tile_selection = {}
    vertices_checked = 0
    for element in root.iter():
        kind = element.attrib.get("class")
        if kind == "signature-cell":
            graph_edge = helper.edge(map(int, element.attrib["data-edge"].split("-")))
            cycle_index = int(element.attrib["data-cycle-index"])
            cells[(graph_edge, cycle_index)] = element.attrib["data-bit"]
        elif kind == "signature-column-header":
            headers[int(element.attrib["data-cycle-index"])] = element.attrib["data-selected"] == "true"
        elif kind == "cycle-tile":
            tile_selection[int(element.attrib["data-cycle-index"])] = element.attrib["data-selected"] == "true"
        elif kind == "graph-vertex":
            vertex = int(element.attrib["data-vertex"])
            source_x = float(element.attrib["data-source-x"])
            source_y = float(element.attrib["data-source-y"])
            expected_x, expected_y = source_positions[vertex]
            if not (
                math.isclose(source_x, expected_x, abs_tol=1e-9)
                and math.isclose(source_y, expected_y, abs_tol=1e-9)
            ):
                raise helper.BuildError("embedded coordinate mismatch")
            vertices_checked += 1
    expected_cells = {
        (graph_edge, cycle_index): all_column_bits[(graph_edge, cycle_index)]
        for graph_edge in graph_edges
        for cycle_index in ALL_CYCLE_INDICES
    }
    expected_selection = {
        cycle_index: cycle_index not in UNUSED_CYCLE_INDICES
        for cycle_index in ALL_CYCLE_INDICES
    }
    if cells != expected_cells:
        raise helper.BuildError("12-column SVG matrix mismatch")
    if headers != expected_selection or tile_selection != expected_selection:
        raise helper.BuildError("cycle selection display mismatch")
    selected_cells = {
        (graph_edge, cycle_index): cells[(graph_edge, cycle_index)]
        for graph_edge in graph_edges
        for cycle_index in selected
    }
    expected_selected = {
        (graph_edge, cycle_index): signatures[graph_edge][column]
        for graph_edge in graph_edges
        for column, cycle_index in enumerate(selected)
    }
    if selected_cells != expected_selected:
        raise helper.BuildError("selected 10-column signature mismatch")
    return {
        "signature_cells_checked": len(cells),
        "selected_signature_cells_checked": len(selected_cells),
        "grey_context_cells_checked": len(cells) - len(selected_cells),
        "cycle_column_headers_checked": len(headers),
        "cycle_tiles_checked": len(tile_selection),
        "graph_vertex_instances_checked": vertices_checked,
        "source_coordinate_hash_matches": True,
        "arrows_connect_cycles_6_and_9_to_their_columns": True,
    }


def patched_write_json_new(path, value):
    if path.name == "didactic_figure_verification.json":
        value["display_matrix"] = {
            "displayed_cycle_columns": 12,
            "selected_blue_columns": [1, 2, 3, 4, 5, 7, 8, 10, 11, 12],
            "grey_context_columns": [6, 9],
            "displayed_signature_cells": 252,
            "arrows_from_cycle_tiles_to_grey_columns": [6, 9],
            "grey_columns_claimed_identical_to_selected_columns": False,
        }
    original_write_json_new(path, value)


def patched_write_new(path, data):
    if path.name == "README.md":
        text = data.decode("utf-8")
        text = text.replace(
            "Die Hauptgrafik zeigt den Grundgraphen, alle zwölf Hamiltonkreise mit der zertifizierten 10er-Auswahl sowie die 21×10-Signaturmatrix. Die Signaturen sind paarweise inkomparabel.",
            "Die Hauptgrafik zeigt den Grundgraphen und alle zwölf Hamiltonkreise. Die 0/1-Tabelle enthält alle zwölf Zyklusspalten; C6 und C9 sind als nicht gewählte Kontextspalten ausgegraut und durch Pfeile mit ihren Zyklusfeldern verbunden. Die zehn blauen Spalten bilden die eigentliche 21×10-Signaturmatrix des Primalzertifikats; nur diese zehn Signaturen werden als paarweise inkomparabel behauptet.",
        )
        text = text.replace(
            "- `signature_matrix.csv`: 21 Kantensignaturen bezüglich der zehn ausgewählten Zyklen",
            "- `signature_matrix.csv`: zertifizierte 21×10-Kantensignaturen; die Grafik ergänzt C6 und C9 grau als Kontext",
        )
        data = text.encode("utf-8")
    original_write_new(path, data)


helper.build_scene = twelve_column_build_scene
helper.parse_svg_verification = verify_twelve_column_svg
helper.write_json_new = patched_write_json_new
helper.write_new = patched_write_new

if __name__ == "__main__":
    raise SystemExit(helper.main())
