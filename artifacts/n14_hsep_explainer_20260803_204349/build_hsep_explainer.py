#!/usr/bin/env python3
"""Build the n=14 hsep explainer with an explicit ordered-pair witness matrix."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET


PREVIOUS = (
    Path(__file__).resolve().parents[1]
    / "n14_hsep_explainer_20260803_202646"
    / "build_hsep_explainer.py"
)
spec = importlib.util.spec_from_file_location("n14_hsep_explainer_twelve_columns", PREVIOUS)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load previous certified builder: {PREVIOUS}")
previous = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = previous
spec.loader.exec_module(previous)

helper = previous.helper
previous_build_scene = helper.build_scene
original_write_new = helper.write_new
original_write_json_new = helper.write_json_new

SELECTED = [1, 2, 3, 4, 5, 7, 8, 10, 11, 12]
UNUSED = [6, 9]
WITNESS_MAP: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}


def item_anchor(item: dict[str, Any]) -> tuple[float, float]:
    if item["kind"] == "line":
        return min(item["x1"], item["x2"]), min(item["y1"], item["y2"])
    return float(item.get("x", 0)), float(item.get("y", 0))


def strip_old_panel_c(scene):
    kept = []
    for item in scene.items:
        x, y = item_anchor(item)
        if item.get("class") == "cycle-column-arrow":
            continue
        if item["kind"] == "text" and item.get("value") in {"Z6", "Z9"} and x > 1600:
            continue
        if (
            item["kind"] == "rect"
            and 1640 <= x <= 1710
            and 35 <= item.get("width", 0) <= 50
            and 20 <= item.get("height", 0) <= 35
        ):
            continue
        if x >= 1730 and 300 <= y < 1700:
            continue
        kept.append(item)
    scene.items = kept


def witness_for(first, second, cycles, selected):
    for cycle_index in selected:
        cycle = cycles[cycle_index - 1]
        if first in cycle and second not in cycle:
            return cycle_index
    raise helper.BuildError(f"no selected witness for ordered edge pair {first}, {second}")


def build_ordered_pair_panel(scene, graph_edges, cycles, selected, signatures):
    global WITNESS_MAP
    WITNESS_MAP = {
        (first, second): witness_for(first, second, cycles, selected)
        for first in graph_edges
        for second in graph_edges
        if first != second
    }
    if len(WITNESS_MAP) != 420 or set(WITNESS_MAP.values()) - set(selected):
        raise helper.BuildError("ordered-pair witness matrix is incomplete or uses an unselected cycle")

    scene.text(1790, 326, "Trennzeugnis der ausgewählten 10 Zyklen", size=19, color=helper.NAVY, weight=700)
    scene.text(1790, 350, "Zeile e, Spalte f: Zahl k bedeutet e in Ck und f nicht in Ck.", size=13, color=helper.MUTED)

    grid_x, grid_y, cell = 1840, 405, 27
    scene.text(1818, 395, "e \\ f", size=12, color=helper.MUTED, weight=700, anchor="middle")
    for index, edge in enumerate(graph_edges, 1):
        scene.text(grid_x - 12, grid_y + (index - 1) * cell + 18, f"{edge[0]}–{edge[1]}", size=11, color=helper.INK, weight=700, anchor="end")
        scene.text(grid_x + (index - 1) * cell + 12, grid_y - 11, f"{index:02d}", size=9, color=helper.MUTED, weight=700, anchor="middle")

    example_first = graph_edges[0]
    example_second = graph_edges[1]
    for row, first in enumerate(graph_edges):
        for column, second in enumerate(graph_edges):
            x = grid_x + column * cell
            y = grid_y + row * cell
            if first == second:
                scene.rect(
                    x, y, cell - 2, cell - 2,
                    fill=helper.LIGHT, stroke=helper.WHITE, stroke_width=1, radius=3,
                    css_class="separation-diagonal-cell",
                    attrs={"data-edge": f"{first[0]}-{first[1]}"},
                )
                scene.text(x + 12.5, y + 18, "–", size=10, color=helper.UNUSED, weight=700, anchor="middle")
                continue
            witness = WITNESS_MAP[(first, second)]
            is_example = (first, second) in {
                (example_first, example_second),
                (example_second, example_first),
            }
            scene.rect(
                x, y, cell - 2, cell - 2,
                fill=helper.AMBER_SOFT if is_example else helper.BLUE_SOFT,
                stroke=helper.AMBER if is_example else "#B7D9EC",
                stroke_width=2.5 if is_example else 0.7,
                radius=3,
                css_class="separation-witness-cell",
                attrs={
                    "data-row-edge": f"{first[0]}-{first[1]}",
                    "data-column-edge": f"{second[0]}-{second[1]}",
                    "data-witness-cycle-index": witness,
                },
            )
            scene.text(x + 12.5, y + 18, str(witness), size=9, color=helper.NAVY, weight=700, anchor="middle")

    scene.text(2122, 991, "Spalten 01–21 folgen derselben Kantenreihenfolge wie die Zeilen.", size=12, color=helper.MUTED, anchor="middle")

    callout_x = 2425
    scene.rect(callout_x, 375, 285, 390, fill=helper.AMBER_SOFT, stroke=helper.AMBER, stroke_width=1.8, radius=14)
    scene.text(callout_x + 142, 410, "Ein Kantenpaar", size=18, color=helper.NAVY, weight=700, anchor="middle")
    forward = WITNESS_MAP[(example_first, example_second)]
    backward = WITNESS_MAP[(example_second, example_first)]
    helper.add_lines(
        scene,
        callout_x + 18,
        450,
        [
            f"e = {example_first[0]}–{example_first[1]},  f = {example_second[0]}–{example_second[1]}",
            "",
            f"Feld (e,f):  C{forward}",
            "enthält e und meidet f.",
            "",
            f"Feld (f,e):  C{backward}",
            "enthält f und meidet e.",
            "",
            "Beide Richtungen sind",
            "direkt bezeugt.",
        ],
        size=15,
        color=helper.INK,
        gap=28,
    )
    scene.rect(callout_x, 790, 285, 190, fill=helper.TEAL_SOFT, stroke="#A9DCCA", stroke_width=1.5, radius=14)
    scene.text(callout_x + 142, 830, "Vollständig", size=19, color=helper.NAVY, weight=700, anchor="middle")
    helper.add_lines(
        scene,
        callout_x + 142,
        868,
        ["420 von 420 Feldern", "außerhalb der Diagonale", "sind mit einem der zehn", "blauen Zyklen belegt."],
        size=15,
        color=helper.TEAL,
        weight=700,
        gap=25,
        anchor="middle",
    )

    scene.rect(1780, 1015, 930, 120, fill=helper.BLUE_SOFT, stroke="#B7D9EC", stroke_width=1.5, radius=14)
    scene.text(2245, 1052, "C6 UND C9 KÖNNEN ENTFERNT WERDEN", size=20, color=helper.NAVY, weight=700, anchor="middle")
    scene.text(2245, 1082, "Danach bleiben 0 offene Trennanforderungen: alle 420 Felder sind weiterhin belegt.", size=15, color=helper.INK, anchor="middle")
    scene.text(2245, 1111, "Die Zahlen 6 und 9 kommen in dieser Zeugenmatrix nicht vor.", size=15, color=helper.MUTED, weight=700, anchor="middle")

    # Compact 12-column signature table retained as a machine-readable visual cross-check.
    sig_x, sig_y, sig_col, sig_row = 1852, 1237, 23, 16
    scene.text(1795, 1180, "0/1-Signaturen (Kontrolle)", size=18, color=helper.NAVY, weight=700)
    scene.text(1795, 1205, "C6 und C9 grau; die zehn blauen Spalten genügen bereits.", size=12, color=helper.MUTED)
    scene.text(sig_x - 10, sig_y - 8, "Kante", size=10, color=helper.MUTED, weight=700, anchor="end")
    for column, cycle_index in enumerate(range(1, 13)):
        is_unused = cycle_index in UNUSED
        scene.text(sig_x + column * sig_col + 10, sig_y - 8, str(cycle_index), size=9, color=helper.UNUSED if is_unused else helper.MUTED, weight=700, anchor="middle")
    for row, edge in enumerate(graph_edges):
        y = sig_y + row * sig_row
        scene.text(sig_x - 10, y + 11, f"{edge[0]}–{edge[1]}", size=9, color=helper.INK, weight=700, anchor="end")
        for column, cycle_index in enumerate(range(1, 13)):
            bit = "1" if edge in cycles[cycle_index - 1] else "0"
            is_unused = cycle_index in UNUSED
            fill = ("#818B95" if bit == "1" else "#E1E4E7") if is_unused else (helper.BLUE if bit == "1" else helper.LIGHT)
            text_color = helper.WHITE if bit == "1" else helper.MUTED
            scene.rect(
                sig_x + column * sig_col,
                y,
                sig_col - 3,
                sig_row - 2,
                fill=fill,
                stroke=helper.WHITE,
                stroke_width=0.5,
                radius=2,
                css_class="compact-signature-cell",
                attrs={
                    "data-edge": f"{edge[0]}-{edge[1]}",
                    "data-cycle-index": cycle_index,
                    "data-bit": bit,
                    "data-selected": str(cycle_index not in UNUSED).lower(),
                },
            )
            scene.text(sig_x + column * sig_col + 10, y + 11, bit, size=8, color=text_color, weight=700, anchor="middle")

    scene.rect(2180, 1160, 530, 450, fill=helper.AMBER_SOFT, stroke=helper.AMBER, stroke_width=2, radius=14)
    scene.text(2210, 1202, "Exakter Lower Bound", size=23, color=helper.NAVY, weight=700)
    helper.add_lines(
        scene,
        2210,
        1245,
        [
            "Das Primalzertifikat oben zeigt:",
            "10 Zyklen genügen.",
            "",
            "Die vorhandenen exakten Zertifikate",
            "prüfen alle 4.017 Teilmengen aus",
            "höchstens 9 der 12 Zyklen.",
            "",
            "Für jede davon bleibt mindestens eine",
            "gerichtete Trennanforderung offen.",
            "",
            "Also genügen 9 Zyklen nicht.",
        ],
        size=16,
        color=helper.INK,
        gap=29,
    )
    scene.text(2445, 1580, "Obere Schranke 10 + untere Schranke 10", size=16, color=helper.AMBER, weight=700, anchor="middle")


def ordered_pair_build_scene(source_positions, graph_edges, cycles, selected, signatures):
    scene = previous_build_scene(source_positions, graph_edges, cycles, selected, signatures)
    strip_old_panel_c(scene)
    build_ordered_pair_panel(scene, graph_edges, cycles, selected, signatures)
    return scene


def verify_ordered_pair_svg(path, selected, graph_edges, signatures, source_positions, coordinate_hash):
    root = ET.parse(path).getroot()
    if root.attrib.get("data-source-coordinate-sha256") != coordinate_hash:
        raise helper.BuildError("SVG coordinate hash mismatch")
    witnesses = {}
    compact = {}
    tile_selection = {}
    vertices_checked = 0
    for element in root.iter():
        css_class = element.attrib.get("class")
        if css_class == "separation-witness-cell":
            first = helper.edge(map(int, element.attrib["data-row-edge"].split("-")))
            second = helper.edge(map(int, element.attrib["data-column-edge"].split("-")))
            witnesses[(first, second)] = int(element.attrib["data-witness-cycle-index"])
        elif css_class == "compact-signature-cell":
            edge = helper.edge(map(int, element.attrib["data-edge"].split("-")))
            cycle_index = int(element.attrib["data-cycle-index"])
            compact[(edge, cycle_index)] = element.attrib["data-bit"]
        elif css_class == "cycle-tile":
            tile_selection[int(element.attrib["data-cycle-index"])] = element.attrib["data-selected"] == "true"
        elif css_class == "graph-vertex":
            vertex = int(element.attrib["data-vertex"])
            source_x = float(element.attrib["data-source-x"])
            source_y = float(element.attrib["data-source-y"])
            expected_x, expected_y = source_positions[vertex]
            if not (math.isclose(source_x, expected_x, abs_tol=1e-9) and math.isclose(source_y, expected_y, abs_tol=1e-9)):
                raise helper.BuildError("embedded coordinate mismatch")
            vertices_checked += 1
    if witnesses != WITNESS_MAP:
        raise helper.BuildError("SVG ordered-pair witness matrix mismatch")
    if len(witnesses) != 420 or set(witnesses.values()) - set(selected):
        raise helper.BuildError("SVG witness matrix is incomplete or uses C6/C9")
    expected_compact = {
        (edge, cycle_index): previous.all_column_bits[(edge, cycle_index)]
        for edge in graph_edges
        for cycle_index in range(1, 13)
    }
    if compact != expected_compact:
        raise helper.BuildError("SVG compact 12-column signature matrix mismatch")
    if tile_selection != {index: index in set(selected) for index in range(1, 13)}:
        raise helper.BuildError("SVG selection tiles mismatch")
    return {
        "ordered_pair_witness_cells_checked": len(witnesses),
        "diagonal_cells_expected": 21,
        "all_420_ordered_requirements_have_selected_witnesses": True,
        "witness_cycles_used": sorted(set(witnesses.values())),
        "unused_cycles_appear_as_witnesses": sorted(set(witnesses.values()) & set(UNUSED)),
        "compact_signature_cells_checked": len(compact),
        "cycle_tiles_checked": len(tile_selection),
        "graph_vertex_instances_checked": vertices_checked,
        "source_coordinate_hash_matches": True,
    }


def patched_write_json_new(path, value):
    if path.name == "didactic_figure_verification.json":
        value["ordered_pair_witness_matrix"] = {
            "edge_rows": 21,
            "edge_columns": 21,
            "diagonal_cells": 21,
            "off_diagonal_requirements": 420,
            "filled_off_diagonal_cells": 420,
            "all_witness_cycles_belong_to_certified_selected_10": True,
            "witness_cycle_indices_used": sorted(set(WITNESS_MAP.values())),
            "cycles_6_and_9_used_as_witnesses": False,
            "open_requirements_after_removing_cycles_6_and_9": 0,
            "cell_semantics": "row edge is contained in witness cycle; column edge is avoided",
        }
        value["display_matrix"] = {
            "primary_display": "21x21 ordered-edge-pair witness matrix",
            "compact_context_display": "21x12 all-cycle signature matrix",
            "grey_context_columns": [6, 9],
        }
    original_write_json_new(path, value)


def patched_write_new(path, data):
    if path.name == "README.md":
        text = data.decode("utf-8")
        marker = "Die Hauptgrafik zeigt"
        start = text.find(marker)
        end = text.find("\n\nAlle Graphteilbilder", start)
        if start >= 0 and end >= 0:
            replacement = (
                "Die Hauptgrafik zeigt den Grundgraphen und alle zwölf Hamiltonkreise. "
                "Im zentralen 21×21-Trennzeugnis steht in Feld (e,f) ein ausgewählter Zyklus, "
                "der die Zeilenkante e enthält und die Spaltenkante f meidet. Alle 420 Felder "
                "außerhalb der Diagonale sind ausschließlich mit Zyklen des zertifizierten "
                "10er-Primalzertifikats belegt; C6 und C9 werden nicht verwendet. Die kleine "
                "0/1-Matrix zeigt ergänzend alle zwölf Zyklen mit C6 und C9 als graue Kontextspalten. "
                "Die Aussage, dass neun Zyklen nicht genügen, stützt sich auf das vorhandene exakte "
                "Lower-Bound-Zertifikat mit 4.017 geprüften Teilmengen; sie wird nicht aus der Grafik abgeleitet."
            )
            text = text[:start] + replacement + text[end:]
        text = text.replace(
            "- `signature_matrix.csv`: zertifizierte 21×10-Kantensignaturen; die Grafik ergänzt C6 und C9 grau als Kontext",
            "- `signature_matrix.csv`: zertifizierte 21×10-Kantensignaturen; die Grafik ergänzt C6 und C9 grau als Kontext\n"
            "- 21×21-Trennzeugnis in der Hauptgrafik: 420 maschinengeprüfte gerichtete Anforderungen",
        )
        data = text.encode("utf-8")
    original_write_new(path, data)


helper.build_scene = ordered_pair_build_scene
helper.parse_svg_verification = verify_ordered_pair_svg
helper.write_json_new = patched_write_json_new
helper.write_new = patched_write_new


if __name__ == "__main__":
    raise SystemExit(helper.main())
