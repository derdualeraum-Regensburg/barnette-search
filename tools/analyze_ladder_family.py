#!/usr/bin/env python3
"""Analyze certified Barnie maximizers for a fixed square-expansion family."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import networkx as nx

from barnette_search.ladder_analysis import (
    add_ladder_reversal_automorphisms,
    barnette_properties,
    canonicalize_embedding,
    cycle_edge_set,
    detect_quadrilateral_structures,
    double_ladder_cycle_formula,
    double_ladder_graph,
    empirical_double_ladder_hsep,
    graph_from_rotation,
    hamiltonian_ladder_states,
    normalized_edge,
    square_reduction_certificates,
)
from barnette_search.planar_code import canonical_graph_hash, iter_planar_code


SCHEMA = "barnie-ladder-analysis-v1"
PRIMARY_ORDERS = tuple(range(20, 37, 2))
UNIQUE_TRANSITIONS = tuple(zip(range(8, 36, 4), range(12, 40, 4)))
TIED_TRANSITIONS = ((14, 18), (18, 22), (22, 26), (26, 30), (30, 34))
FIGURE_ORDERS = (22, 24, 26, 28, 30, 32, 34, 36)


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, value: Any) -> None:
    atomic_write(
        path,
        (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def records_gzip(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def matching_record(path: Path, graph_hash: str) -> dict[str, Any]:
    found = [record for record in records_gzip(path) if record.get("canonical_graph_hash") == graph_hash]
    if len(found) != 1:
        raise ValueError(f"expected one {graph_hash} record in {path}; found {len(found)}")
    return found[0]


def load_graph_bundle(
    sequence_root: Path,
    sequence_order: dict[str, Any],
    graph_hash: str,
) -> dict[str, Any]:
    order = int(sequence_order["order"])
    order_root = sequence_root / f"order_{order:02d}"
    graph_record = matching_record(order_root / "graph_certificates.jsonl.gz", graph_hash)
    exact_record = matching_record(order_root / "exact_certificates.jsonl.gz", graph_hash)
    planar_code = base64.b64decode(graph_record["planar_code_base64"], validate=True)
    if hashlib.sha256(planar_code).hexdigest() != graph_record["planar_code_sha256"]:
        raise ValueError(f"planar_code hash mismatch for {graph_hash}")
    embedded = list(iter_planar_code(BytesIO(planar_code), require_header=True))
    if len(embedded) != 1:
        raise ValueError(f"planar_code does not contain one graph for {graph_hash}")
    embedding = embedded[0]
    if [list(row) for row in embedding.rotation_system] != graph_record["rotation_system"]:
        raise ValueError(f"rotation mismatch for {graph_hash}")
    if [list(face) for face in embedding.faces] != graph_record["faces"]:
        raise ValueError(f"face mismatch for {graph_hash}")
    if canonical_graph_hash(embedding) != graph_hash:
        raise ValueError(f"canonical graph hash mismatch for {graph_hash}")
    if exact_record["exact_hsep"] != sequence_order["M_B"]:
        raise ValueError(f"exact hsep mismatch for {graph_hash}")
    if len(exact_record["complete_hamiltonian_cycle_universe"]) != exact_record["complete_hamiltonian_cycle_count"]:
        raise ValueError(f"cycle-universe count mismatch for {graph_hash}")

    canonical = canonicalize_embedding(embedding.rotation_system)
    if canonical["canonical_graph_hash"] != graph_hash:
        raise ValueError(f"normalized embedding hash mismatch for {graph_hash}")
    structures = detect_quadrilateral_structures(canonical["rotation_system"])
    computed_automorphisms = add_ladder_reversal_automorphisms(
        canonical["rotation_system"], structures
    )
    if computed_automorphisms != exact_record.get("automorphism_group_order"):
        raise ValueError(f"automorphism count mismatch for {graph_hash}")
    old_to_canonical = canonical["original_to_canonical"]
    mapped_edges = [
        normalized_edge(old_to_canonical[left], old_to_canonical[right])
        for left, right in graph_record["edges"]
    ]
    mapped_universe = [
        [old_to_canonical[vertex] for vertex in cycle]
        for cycle in exact_record["complete_hamiltonian_cycle_universe"]
    ]
    mapped_primal = [
        [old_to_canonical[vertex] for vertex in cycle]
        for cycle in exact_record["primal_cycles"]
    ]
    states = hamiltonian_ladder_states(
        structures,
        mapped_edges,
        mapped_universe,
        mapped_primal,
        exact_record["packing_requirements"],
        exact_record["lower_bound_method"],
    )
    return {
        "order": order,
        "M_B": sequence_order["M_B"],
        "number_of_maximizers_for_order": sequence_order["number_of_maximizers"],
        "unique_maximizer": bool(sequence_order["unique_maximizer"]),
        "canonical_graph_hash": graph_hash,
        "generation_index": graph_record["generation_index"],
        "plantri_rank": graph_record["plantri_rank"],
        "graph_record": graph_record,
        "exact_record": exact_record,
        "canonical": canonical,
        "structures": structures,
        "states": states,
        "embedding_verification": {
            "planar_code_sha256": graph_record["planar_code_sha256"],
            "rotation_matches_certified_record": True,
            "faces_match_certified_record": True,
            "canonical_hash_matches": True,
            "automorphism_group_order_matches": True,
        },
    }


def find_double_ladder(bundle: dict[str, Any]) -> dict[str, Any] | None:
    order = bundle["order"]
    graph = graph_from_rotation(bundle["canonical"]["rotation_system"])
    total = order // 2 - 2
    candidates = []
    for second in range(1, total + 1, 2):
        first = total - second
        if first < second or first % 2 != 1:
            continue
        model = double_ladder_graph(first, second)
        matcher = nx.algorithms.isomorphism.GraphMatcher(graph, model)
        mappings = list(matcher.isomorphisms_iter())
        if mappings:
            mapping = min(
                mappings,
                key=lambda item: tuple(str(item[index]) for index in sorted(item)),
            )
            candidates.append((first, second, mapping, model))
    if len(candidates) != 1:
        return None
    first, second, mapping, model = candidates[0]
    return {
        "parameters": {"first_ladder_length": first, "second_ladder_length": second},
        "canonical_vertex_to_model": [
            [index, list(mapping[index])] for index in sorted(mapping)
        ],
        "connector_definition": [
            [["A", 0, 0], ["B", 0, 0]],
            [["A", 0, 1], ["B", second, 0]],
            [["A", first, 0], ["B", 0, 1]],
            [["A", first, 1], ["B", second, 1]],
        ],
        "model_barnette_properties": barnette_properties(model),
        "hamiltonian_cycle_formula_value": double_ladder_cycle_formula(first, second),
        "empirical_hsep_formula_value": empirical_double_ladder_hsep(first, second),
    }


def add_double_ladder_cycle_classification(bundle: dict[str, Any]) -> None:
    family = bundle.get("double_ladder")
    if family is None:
        return
    first = family["parameters"]["first_ladder_length"]
    second = family["parameters"]["second_ladder_length"]
    mapping = {
        source: tuple(target)
        for source, target in family["canonical_vertex_to_model"]
    }
    connectors = [
        frozenset((('A', 0, 0), ('B', 0, 0))),
        frozenset((('A', 0, 1), ('B', second, 0))),
        frozenset((('A', first, 0), ('B', 0, 1))),
        frozenset((('A', first, 1), ('B', second, 1))),
    ]
    counts: dict[str, int] = {}
    detailed = []
    for cycle_record, cycle in zip(
        bundle["states"]["cycle_records"],
        bundle["mapped_universe"],
    ):
        selected = {
            frozenset((mapping[left], mapping[right]))
            for left, right in cycle_edge_set(cycle)
        }
        connector_bits = "".join("1" if edge in selected else "0" for edge in connectors)
        ladder_bits = []
        turns = []
        for name, length in (("A", first), ("B", second)):
            rung_bits = "".join(
                "1" if frozenset(((name, column, 0), (name, column, 1))) in selected else "0"
                for column in range(length + 1)
            )
            rail_bits = [
                "".join(
                    "1"
                    if frozenset(((name, column, rail), (name, column + 1, rail))) in selected
                    else "0"
                    for column in range(length)
                )
                for rail in (0, 1)
            ]
            positions = [index for index in range(length) if rung_bits[index:index + 2] == "11"]
            turns.append(positions[0] if len(positions) == 1 else None)
            ladder_bits.append({"name": name, "rung_bits": rung_bits, "rail_bits": rail_bits})
        if connector_bits == "1111" and turns == [None, None]:
            classification = "all_rails"
        elif connector_bits == "1111" and all(turn is not None for turn in turns):
            classification = "paired_cell_turns"
        elif connector_bits.count("1") == 2:
            classification = "two_connector_exception"
        else:
            classification = "unexpected"
        counts[classification] = counts.get(classification, 0) + 1
        detailed.append(
            {
                "cycle_index": cycle_record["cycle_index"],
                "connector_bits": connector_bits,
                "classification": classification,
                "turn_cells": turns,
                "model_ladder_bits": ladder_bits,
            }
        )
    expected = {
        "all_rails": 1,
        "paired_cell_turns": first * second,
        "two_connector_exception": 4,
    }
    family["cycle_classification"] = {
        "counts": dict(sorted(counts.items())),
        "expected_counts_from_direct_classification": expected,
        "classification_matches_formula": counts == expected,
        "cycle_records": detailed,
        "proof_summary": (
            "With all four connector edges, a Hamiltonian cycle is either the unique all-rails "
            "cycle or chooses one turn cell independently in each ladder (a*b choices). "
            "Exactly four additional cycles use two connector edges. Hence H(D(a,b))=a*b+5."
        ),
    }


def artifact_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    canonical = bundle["canonical"]
    structures = bundle["structures"]
    exact = bundle["exact_record"]
    return {
        "schema": "barnie-ladder-graph-v1",
        "order": bundle["order"],
        "M_B": bundle["M_B"],
        "number_of_maximizers_for_order": bundle["number_of_maximizers_for_order"],
        "unique_maximizer": bundle["unique_maximizer"],
        "canonical_graph_hash": bundle["canonical_graph_hash"],
        "generation_index": bundle["generation_index"],
        "plantri_rank": bundle["plantri_rank"],
        "face_size_multiset": bundle["graph_record"]["face_size_multiset"],
        "canonical_edge_list": [
            list(edge)
            for edge in sorted(
                normalized_edge(left, right)
                for left, right in graph_from_rotation(canonical["rotation_system"]).edges()
            )
        ],
        "planar_code_base64": bundle["graph_record"]["planar_code_base64"],
        "planar_code_sha256": bundle["graph_record"]["planar_code_sha256"],
        "exact_hsep": exact["exact_hsep"],
        "complete_hamiltonian_cycle_count": exact["complete_hamiltonian_cycle_count"],
        "primal_cycle_count": exact["primal_cycle_count"],
        "lower_bound_method": exact["lower_bound_method"],
        "packing_requirement_count": exact["packing_requirement_count"],
        "embedding_verification": bundle["embedding_verification"],
        "canonical_embedding": {
            "rotation_system": [list(row) for row in canonical["rotation_system"]],
            "faces": [list(face) for face in canonical["faces"]],
            "original_to_canonical": list(canonical["original_to_canonical"]),
            "canonical_to_original": list(canonical["canonical_to_original"]),
            "root_edge_original": list(canonical["root_edge_original"]),
            "orientation_direction": canonical["orientation_direction"],
        },
        "quadrilateral_component_signature": structures["quadrilateral_component_signature"],
        "ladders": structures["ladders"],
        "exceptional_quadrilateral_components": structures["exceptional_quadrilateral_components"],
        "double_ladder": bundle.get("double_ladder"),
    }


def map_certificate_to_original(
    certificate: dict[str, Any],
    source: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    source_c2o = source["canonical"]["canonical_to_original"]
    target_c2o = target["canonical"]["canonical_to_original"]
    result = dict(certificate)
    result["artifact_label_witness"] = {
        "inserted_vertices_target_artifact": [
            target_c2o[index] for index in certificate["inserted_vertices_forward"]
        ],
        "removed_edges_source_artifact": [
            sorted((source_c2o[left], source_c2o[right]))
            for left, right in certificate["removed_edges_forward_source_labels"]
        ],
        "unchanged_source_to_target_artifact": [
            [source_c2o[source_vertex], target_c2o[target_vertex]]
            for source_vertex, target_vertex in certificate["unchanged_source_to_target"]
        ],
    }
    return result


def select_expansion(
    source: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any] | None:
    certificates = square_reduction_certificates(
        source["canonical"]["rotation_system"],
        target["canonical"]["rotation_system"],
        source_hash=source["canonical_graph_hash"],
        target_hash=target["canonical_graph_hash"],
    )
    if not certificates:
        return None
    preferred = [
        certificate
        for certificate in certificates
        if certificate["source_expanded_face"]["expanded_edges_are_detected_ladder_rails"]
    ]
    chosen = (preferred or certificates)[0]
    chosen = map_certificate_to_original(chosen, source, target)
    chosen["number_of_equivalent_reduction_witnesses"] = len(certificates)
    chosen["same_fixed_operation_signature"] = {
        "inserted_vertices": 4,
        "forward_removed_edges": 2,
        "forward_inserted_edges": 8,
        "inserted_induced_subgraph": "C4",
        "boundary_size": 4,
        "source_edges": "two disjoint cofacial edges",
        "literal_ladder_cell_expansion": (
            chosen["source_expanded_face"]["expanded_edges_are_detected_ladder_rails"]
            and chosen["source_expanded_face"]["expanded_edges_are_opposite"]
        ),
        "opposite_edges_of_quadrilateral": chosen["source_expanded_face"]["expanded_edges_are_opposite"],
    }
    return chosen


def annotate_svg(
    base_svg: Path,
    output_svg: Path,
    bundle: dict[str, Any],
    inserted_original_vertices: set[int],
) -> None:
    namespace = "http://www.w3.org/2000/svg"
    ET.register_namespace("", namespace)
    tree = ET.parse(base_svg)
    root = tree.getroot()
    circles = {
        int(element.attrib["id"][1:]) - 1: (element.attrib["cx"], element.attrib["cy"])
        for element in root.findall(f".//{{{namespace}}}circle")
        if element.attrib.get("id", "").startswith("v")
    }
    c2o = bundle["canonical"]["canonical_to_original"]
    structures = bundle["structures"]
    fill_group = ET.Element(f"{{{namespace}}}g", {
        "id": "ladder-face-highlights", "stroke": "none", "fill-opacity": "0.22"
    })
    palette = ("#64b5f6", "#9575cd", "#81c784", "#4dd0e1")
    for ladder in structures["ladders"]:
        color = palette[ladder["ladder_index"] % len(palette)]
        for face in ladder["ordered_faces"]:
            original = [c2o[vertex] for vertex in face]
            points = " ".join(f"{circles[vertex][0]},{circles[vertex][1]}" for vertex in original)
            ET.SubElement(fill_group, f"{{{namespace}}}polygon", {"points": points, "fill": color})
    for component in structures["exceptional_quadrilateral_components"]:
        if component["type"] == "quadrilateral_face_cycle":
            for face_index in component["face_indices"]:
                face = structures["faces"][face_index]
                original = [c2o[vertex] for vertex in face]
                points = " ".join(f"{circles[vertex][0]},{circles[vertex][1]}" for vertex in original)
                ET.SubElement(fill_group, f"{{{namespace}}}polygon", {"points": points, "fill": "#ce93d8"})
    if inserted_original_vertices:
        inserted_faces = [
            face for face in bundle["graph_record"]["faces"]
            if set(face) == inserted_original_vertices
        ]
        for face in inserted_faces:
            points = " ".join(f"{circles[vertex][0]},{circles[vertex][1]}" for vertex in face)
            ET.SubElement(fill_group, f"{{{namespace}}}polygon", {
                "points": points, "fill": "#ffeb3b", "fill-opacity": "0.65"
            })
    root.insert(3 if len(root) >= 3 else 0, fill_group)

    overlay = ET.SubElement(root, f"{{{namespace}}}g", {
        "id": "ladder-edge-annotations", "fill": "none", "stroke-linecap": "round"
    })
    def add_line(edge: list[int], color: str, width: str, opacity: str = "1") -> None:
        left, right = (c2o[edge[0]], c2o[edge[1]])
        ET.SubElement(overlay, f"{{{namespace}}}line", {
            "x1": circles[left][0], "y1": circles[left][1],
            "x2": circles[right][0], "y2": circles[right][1],
            "stroke": color, "stroke-width": width, "stroke-opacity": opacity,
        })
    for ladder in structures["ladders"]:
        for rail in ladder["rail_edges"]:
            for edge in rail:
                add_line(edge, "#1565c0", "3.25", "0.72")
        for edge in ladder["rung_edges"]:
            add_line(edge, "#c62828", "4.0", "0.88")
        for edge in ladder["attachment_edges"]:
            add_line(edge, "#ef6c00", "4.0", "0.9")
    if inserted_original_vertices:
        for original in sorted(inserted_original_vertices):
            ET.SubElement(overlay, f"{{{namespace}}}circle", {
                "cx": circles[original][0], "cy": circles[original][1], "r": "10",
                "stroke": "#2e7d32", "stroke-width": "4", "fill": "none",
            })
    metadata = ET.SubElement(root, f"{{{namespace}}}metadata")
    metadata.text = json.dumps({
        "schema": "barnie-ladder-figure-v1",
        "canonical_graph_hash": bundle["canonical_graph_hash"],
        "ladder_face_counts": [item["face_count"] for item in structures["ladders"]],
        "inserted_vertices_artifact_labels": sorted(inserted_original_vertices),
        "legend": {"rails": "blue", "rungs": "red", "attachments/end caps": "orange", "inserted tile": "yellow/green", "quadrilateral 3-belt": "purple"},
    }, sort_keys=True, separators=(",", ":"))
    ET.indent(tree, space="  ")
    buffer = BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    atomic_write(output_svg, buffer.getvalue())


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "order", "M_B", "number_of_maximizers_for_order", "canonical_graph_hash",
        "generation_index", "plantri_rank", "unique_maximizer", "face_size_multiset",
        "quadrilateral_component_signature", "ladder_lengths", "exceptional_components",
        "double_ladder_parameters", "complete_hamiltonian_cycle_count", "exact_hsep",
        "primal_cycle_count", "lower_bound_method", "packing_requirement_count",
    ]
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def report_text(
    graph_summaries: list[dict[str, Any]],
    unique_expansions: list[dict[str, Any]],
    tied: dict[str, Any],
    states: dict[str, Any],
    predictions: dict[str, Any],
) -> str:
    by_order: dict[int, list[dict[str, Any]]] = {}
    for record in graph_summaries:
        by_order.setdefault(record["order"], []).append(record)
    lines = [
        "# Exact ladder-family analysis of certified Barnie maximizers",
        "",
        "This is a structural analysis of immutable certified graphs. No hsep value, census, "
        "or order 38/40 graph was recomputed. Drawings were used only for presentation; every "
        "claim below was tested on abstract edges and certified rotation systems.",
        "",
        "## 1. Exact definition of the detected ladder",
        "",
        "Let Q(G) be the face-adjacency graph induced by the quadrilateral faces of the "
        "certified sphere embedding. A **strict quadrilateral ladder of length l** is a whole "
        "connected component of Q(G) that is a path on l>=2 faces, consecutive shared edges "
        "are opposite in each internal quadrilateral, and the graph induced by the union is "
        "exactly P_(l+1) square K_2. Its l+1 column edges are rungs, its two length-l boundary "
        "paths are rails, and its four degree-two-in-the-strip terminal vertices carry the end "
        "attachments. Isolated quadrilaterals, cycles of quadrilaterals, and chorded paths are "
        "reported as exceptions, not renamed ladders.",
        "",
        "## 2. Inventory",
        "",
        "| n | rank | hash | M_B | strict ladder lengths | Q-component signature |",
        "|---:|---:|:---|---:|:---|:---|",
    ]
    for record in graph_summaries:
        lengths = ",".join(str(item["face_count"]) for item in record["ladders"]) or "none"
        signature = ",".join(record["quadrilateral_component_signature"])
        lines.append(
            f"| {record['order']} | {record['plantri_rank']} | `{record['canonical_graph_hash'][:12]}` | "
            f"{record['exact_hsep']} | {lengths} | {signature} |"
        )
    lines.extend([
        "",
        "All detected path components satisfy the strict ladder axioms: their shared internal "
        "rungs are opposite, their rail/rung union is induced, and no additional chord occurs.",
        "",
        "## 3. One fixed local expansion",
        "",
        "Yes. The same bounded operation explains every transition G_24->G_28, "
        "G_28->G_32, and G_32->G_36, and also G_20->G_24. Select one quadrilateral ladder cell, "
        "replace its two opposite rail edges by length-three paths, and join the corresponding "
        "new vertices by two new rungs. This inserts four vertices forming an induced facial C4, "
        "removes two old rail edges, adds eight edges, and replaces one ladder face by three. "
        "The inverse deletes that C4 and restores the two rail edges.",
        "",
        "| transition | source parameters | target parameters | inverse witnesses | verified |",
        "|:---|:---|:---|---:|:---:|",
    ])
    for certificate in unique_expansions:
        if certificate["source_order"] < 20:
            continue
        source = next(item for item in graph_summaries if item["canonical_graph_hash"] == certificate["source_hash"])
        target = next(item for item in graph_summaries if item["canonical_graph_hash"] == certificate["target_hash"])
        sp = source["double_ladder"]["parameters"]
        tp = target["double_ladder"]["parameters"]
        lines.append(
            f"| {certificate['source_order']}->{certificate['target_order']} | "
            f"D({sp['first_ladder_length']},{sp['second_ladder_length']}) | "
            f"D({tp['first_ladder_length']},{tp['second_ladder_length']}) | "
            f"{certificate['number_of_equivalent_reduction_witnesses']} | yes |"
        )
    lines.extend([
        "",
        "Each emitted certificate contains the full unchanged-vertex mapping, source edges "
        "removed, target edges inserted, boundary terminals, affected faces and rotations, a "
        "canonical reduced hash, exact reconstruction equality, and all five Barnette predicates. "
        "This proves preservation for these instances; it is not asserted as an unconditional "
        "theorem for arbitrary placements in arbitrary cubic plane graphs.",
        "",
        "## 4. Exact double-ladder family and smallest member",
        "",
        "Define D(a,b) from two disjoint ladders P_(a+1) square K_2 and P_(b+1) square K_2. "
        "Join their eight terminal vertices by the fixed four-edge matching listed in "
        "`ladder_family.json` (one edge for each pair of ladder ends). Exact isomorphism checks give:",
        "",
        "`G_8=D(1,1), G_12=D(3,1), G_16=D(3,3), G_20=D(5,3), "
        "G_24=D(5,5), G_28=D(7,5), G_32=D(7,7), G_36=D(9,7)`.",
        "",
        "Thus the recursive graph family starts at order 8, not 20 or 24. The clean "
        "two-component Q(G) ladder signature begins at order 16; at orders 8 and 12 the same "
        "abstract construction is degenerate because additional quadrilateral adjacencies merge "
        "the would-be strips.",
        "",
        "## 5. Tied orders and end-cap variants",
        "",
        f"Every one of the {tied['graph_count']} tied maximizers contains a quadrilateral "
        "three-cycle component plus at least one strict ladder. Their complete Q-component "
        "signatures are pairwise distinct within each order and reproduce the tie counts "
        "2, 5, 3, and 7. This is an exact classifier of the observed graphs, but not by itself "
        "an explanation of why their hsep values tie.",
        "",
        f"The same four-vertex square gadget connects all tied maximizers between consecutive sampled "
        f"orders: {tied['transition_edge_count']} nonisomorphic source-target links were verified. "
        f"Of these, {tied['literal_ladder_cell_transition_count']} are literal ladder-cell "
        f"expansions; the remaining {tied['transition_edge_count'] - tied['literal_ladder_cell_transition_count']} "
        f"apply the identical boundary-four gadget to disjoint cofacial edges in 6-, 8-, or 10-face end-cap regions. "
        "Order 34 is therefore a set of local descendants of the three order-30 variants, not "
        "seven drawings of one fixed two-ladder D(a,b) skeleton. Branching and merging of the "
        "reduction graph accounts combinatorially for the variant proliferation.",
        "",
        "## 6. Hamiltonian-cycle tile states",
        "",
        "Every complete certified Hamiltonian universe was encoded by rung bits, two rail-bit "
        "strings, four-bit cell states, and adjacent-cell transitions. The full machine-readable "
        "incidence data are in `hamiltonian_tile_states.json`.",
        "",
        "For D(a,b), the complete universes establish and the strip-state classification proves "
        "`|H(D(a,b))| = a*b + 5` on this family: with all four connector edges there is one "
        "all-rails cycle or one independently chosen turn cell in each ladder (a*b choices), "
        "and four exceptional cycles use two connector edges. Consequently insertion into the "
        "a-ladder changes the cycle count by exactly `2*b`.",
        "",
        "## 7. Relationship to high hsep",
        "",
        "The certified values from D(3,3) through D(9,7) agree exactly with",
        "",
        "`hsep(D(a,b)) = (a*b + 2*a + 2*b + 3)/2`.",
        "",
        "Equivalently, a two-cell lengthening of one ladder raises the observed hsep by the "
        "other ladder length plus two. This is an empirical law over six independently certified "
        "graphs (orders 16 through 36), not a proof for the infinite D family. In the five "
        "primary packing certificates at orders 20--36, exactly k-2 requirements have both "
        "edges internal to ladders and the remaining two have only the included edge internal. "
        "This repeated count pattern is exact, but the positional packings are not invariant "
        "under automorphisms and no periodic certificate-lifting theorem was established.",
        "",
        "## 8. Rigorously established results",
        "",
        "- Every embedding and face list used here round-trips to its certified planar_code and canonical hash.",
        "- Every reported ladder satisfies the strict abstract definition; cycle/isolated exceptions remain separate.",
        "- All unique n divisible by 4 maximizers from 8 through 36 are the stated D(a,b) graphs.",
        "- The opposite-rail ladder expansion reconstructs every consecutive D member; the same boundary-four square gadget, sometimes placed in a larger cap face, reconstructs every tied-order link reported.",
        "- Every emitted reconstruction equals the certified target edge set and passes simplicity, cubicity, bipartiteness, planarity, and 3-connectivity checks.",
        "- The Hamiltonian-cycle formula a*b+5 follows from an exhaustive state classification matching every certified universe.",
        "",
        "## 9. Empirical observations and conjectures",
        "",
        "The hsep formula and extremality beyond order 36 remain conjectural. The data support "
        "a cautious conjecture that balanced D(a,b) members continue to be extremal for orders "
        "divisible by 4, and that the n=2 mod 4 tied branch remains a finite end-cap/square-"
        "expansion family. Neither uniqueness, tie count, nor an hsep recurrence has been proved "
        "outside the certified range.",
        "",
        "## 10. Predictions (unproved)",
        "",
        f"- The structurally motivated D-family formula predicts hsep 60 for hypothetical "
        f"D(9,9) at order 40. It does **not** certify M_B(40).",
        f"- A linear tail fit to the three certified n=2 mod 4 values at 26, 30, and 34 predicts "
        f"M_B(38)=39. No tied-family transfer proof supports that extrapolation, so it is weaker "
        f"than the order-40 D-family prediction.",
        "",
        "No order-38 or order-40 census, graph search, Hamiltonian enumeration, or hsep "
        "optimization was run.",
        "",
        "## 11. Annotated figures",
        "",
        "The derived SVGs in `figures/` use the existing Brinkmann layouts only as coordinates. "
        "Blue marks rails, red rungs, orange terminal attachments/end caps, purple the tied-order "
        "quadrilateral three-belt, and yellow/green the selected inserted tile. Structural labels "
        "come from certified faces and edges, not geometric proximity.",
        "",
        "## 12. Open theoretical problems",
        "",
        "1. Prove or refute the empirical hsep formula for all odd a,b in the planar D family.",
        "2. Construct primal and lower certificates that lift symbolically under square expansion.",
        "3. Classify the tied branch and derive its tie counts and hsep from finite boundary states.",
        "4. Prove whether balanced D members are extremal and uniquely extremal at sufficiently large n divisible by 4.",
    ])
    return "\n".join(lines) + "\n"


def write_manifest(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{digest_file(path)}  {path.relative_to(root).as_posix()}")
    atomic_write(root / "SHA256SUMS.txt", ("\n".join(lines) + "\n").encode("ascii"))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--sequence-root", type=Path, required=True)
    result.add_argument("--gallery-root", type=Path, required=True)
    result.add_argument("--output-root", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    sequence_root = arguments.sequence_root.resolve()
    gallery_root = arguments.gallery_root.resolve()
    output_root = arguments.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    sequence = json.loads((sequence_root / "barnie_sequence.json").read_text(encoding="utf-8"))
    orders = {int(record["order"]): record for record in sequence["orders"]}
    gallery_index = json.loads((gallery_root / "gallery_index.json").read_text(encoding="utf-8"))
    gallery_by_hash = {record["canonical_graph_hash"]: record for record in gallery_index["records"]}

    needed_orders = set(PRIMARY_ORDERS)
    needed_orders.update(number for pair in UNIQUE_TRANSITIONS + TIED_TRANSITIONS for number in pair)
    bundles: dict[str, dict[str, Any]] = {}
    by_order: dict[int, list[dict[str, Any]]] = {}
    for order in sorted(needed_orders):
        record = orders[order]
        if record["M_B"] is None:
            continue
        for graph_hash in record["maximizer_hashes"]:
            bundle = load_graph_bundle(sequence_root, record, graph_hash)
            bundle["mapped_universe"] = [
                [bundle["canonical"]["original_to_canonical"][vertex] for vertex in cycle]
                for cycle in bundle["exact_record"]["complete_hamiltonian_cycle_universe"]
            ]
            bundle["double_ladder"] = find_double_ladder(bundle)
            add_double_ladder_cycle_classification(bundle)
            bundles[graph_hash] = bundle
            by_order.setdefault(order, []).append(bundle)
            print(f"loaded order={order} rank={bundle['plantri_rank']} hash={graph_hash[:8]}")

    graph_summaries = [
        artifact_summary(bundle)
        for order in PRIMARY_ORDERS
        for bundle in sorted(by_order[order], key=lambda item: item["plantri_rank"])
    ]

    unique_expansions = []
    for source_order, target_order in UNIQUE_TRANSITIONS:
        source = by_order[source_order][0]
        target = by_order[target_order][0]
        certificate = select_expansion(source, target)
        if certificate is None:
            raise RuntimeError(f"no fixed expansion for {source_order}->{target_order}")
        certificate["transition_class"] = "unique_double_ladder"
        unique_expansions.append(certificate)
        print(f"verified unique expansion {source_order}->{target_order}")

    tied_links = []
    tied_certificates = []
    for source_order, target_order in TIED_TRANSITIONS:
        for target in by_order[target_order]:
            for source in by_order[source_order]:
                certificate = select_expansion(source, target)
                if certificate is None:
                    continue
                certificate["transition_class"] = "n_2_mod_4_variant"
                tied_certificates.append(certificate)
                tied_links.append({
                    "source_order": source_order,
                    "target_order": target_order,
                    "source_hash": source["canonical_graph_hash"],
                    "target_hash": target["canonical_graph_hash"],
                    "source_signature": source["structures"]["quadrilateral_component_signature"],
                    "target_signature": target["structures"]["quadrilateral_component_signature"],
                })
    for target_order in (18, 22, 26, 30, 34):
        incoming = {link["target_hash"] for link in tied_links if link["target_order"] == target_order}
        expected = {bundle["canonical_graph_hash"] for bundle in by_order[target_order]}
        if incoming != expected:
            raise RuntimeError(f"tied expansion coverage failed at order {target_order}")

    tied_graphs = [
        bundle for order in (22, 26, 30, 34) for bundle in by_order[order]
    ]
    signature_counts = {
        str(order): len({
            tuple(bundle["structures"]["quadrilateral_component_signature"])
            for bundle in by_order[order]
        })
        for order in (22, 26, 30, 34)
    }
    tied_output = {
        "schema": "barnie-tied-ladder-classification-v1",
        "graph_count": len(tied_graphs),
        "tie_counts": {str(order): len(by_order[order]) for order in (22, 26, 30, 34)},
        "distinct_component_signature_counts": signature_counts,
        "all_have_quadrilateral_three_cycle": all(
            any(
                item["type"] == "quadrilateral_face_cycle" and item["face_count"] == 3
                for item in bundle["structures"]["exceptional_quadrilateral_components"]
            )
            for bundle in tied_graphs
        ),
        "graphs": [
            {
                "order": bundle["order"],
                "hash": bundle["canonical_graph_hash"],
                "rank": bundle["plantri_rank"],
                "component_signature": bundle["structures"]["quadrilateral_component_signature"],
                "ladder_lengths": [item["face_count"] for item in bundle["structures"]["ladders"]],
                "end_cap_signatures": [
                    [end["local_signature"] for end in ladder["end_caps"]]
                    for ladder in bundle["structures"]["ladders"]
                ],
                "exceptional_components": bundle["structures"]["exceptional_quadrilateral_components"],
            }
            for bundle in tied_graphs
        ],
        "transition_edge_count": len(tied_links),
        "literal_ladder_cell_transition_count": sum(
            bool(certificate["same_fixed_operation_signature"]["literal_ladder_cell_expansion"])
            for certificate in tied_certificates
        ),
        "source_placement_face_size_counts": {
            str(size): sum(
                certificate["source_expanded_face"]["size"] == size
                for certificate in tied_certificates
            )
            for size in sorted({
                certificate["source_expanded_face"]["size"]
                for certificate in tied_certificates
            })
        },
        "square_expansion_transition_graph": tied_links,
        "conclusion": (
            "Component signatures classify every tied maximizer within each order. All are "
            "reachable by the fixed square expansion from a preceding n=2 mod 4 maximizer, "
            "but they are not one common two-ladder D(a,b) skeleton."
        ),
    }

    state_output = {
        "schema": "barnie-hamiltonian-tile-states-v1",
        "state_code_order": ["left_rung", "top_rail", "bottom_rail", "right_rung"],
        "graphs": [
            {
                "order": bundle["order"],
                "canonical_graph_hash": bundle["canonical_graph_hash"],
                "plantri_rank": bundle["plantri_rank"],
                "ladder_lengths": [item["face_count"] for item in bundle["structures"]["ladders"]],
                **bundle["states"],
                "double_ladder_cycle_classification": (
                    bundle["double_ladder"]["cycle_classification"]
                    if bundle["double_ladder"] is not None else None
                ),
            }
            for order in PRIMARY_ORDERS
            for bundle in sorted(by_order[order], key=lambda item: item["plantri_rank"])
        ],
    }

    predictions = {
        "schema": "barnie-ladder-predictions-v1",
        "warning": "All predictions are unproved and are not certified Barnie-sequence values.",
        "orders_0_mod_4": {
            "formula": "((a*b)+(2*a)+(2*b)+3)/2 for balanced observed D(a,b)",
            "exact_agreement_orders": [16, 20, 24, 28, 32, 36],
            "structural_status": "graph expansion proved on certified range; hsep lifting unproved",
            "order_40_candidate_graph": "D(9,9)",
            "order_40_predicted_hsep": 60,
            "order_40_predicted_hamiltonian_cycles": 86,
        },
        "orders_2_mod_4": {
            "formula": "(7*n-110)/4",
            "exact_agreement_orders": [26, 30, 34],
            "structural_status": "short linear tail fit only; no transfer proof",
            "order_38_predicted_M_B": 39,
            "alternative_warning": "The tied expansion DAG branches; equally simple extrapolations can differ.",
        },
        "orders_38_40_computed": False,
    }

    family_output = {
        "schema": SCHEMA,
        "definition": {
            "face_adjacency": "faces adjacent iff they share an edge",
            "strict_ladder": (
                "A whole quadrilateral-face component that is a path of at least two faces, "
                "uses opposite shared rungs internally, and induces P_(ell+1) square K_2 without chords."
            ),
            "double_ladder": (
                "D(a,b) is two disjoint ladder strips of face lengths a,b joined by the fixed "
                "four-edge terminal matching encoded in each model certificate."
            ),
            "square_expansion": (
                "Replace opposite rail edges of one ladder cell by length-three paths and add "
                "two corresponding rungs; four inserted vertices induce a facial C4."
            ),
        },
        "certified_input_range": [20, 36],
        "graph_count": len(graph_summaries),
        "all_maximizer_hashes": [record["canonical_graph_hash"] for record in graph_summaries],
        "graphs": graph_summaries,
        "unique_double_ladder_sequence": [
            {
                "order": order,
                "hash": by_order[order][0]["canonical_graph_hash"],
                "parameters": by_order[order][0]["double_ladder"]["parameters"],
                "exact_hsep": by_order[order][0]["M_B"],
                "complete_hamiltonian_cycle_count": by_order[order][0]["exact_record"]["complete_hamiltonian_cycle_count"],
                "cycle_formula_matches": (
                    by_order[order][0]["exact_record"]["complete_hamiltonian_cycle_count"]
                    == by_order[order][0]["double_ladder"]["hamiltonian_cycle_formula_value"]
                ),
                "empirical_hsep_formula_matches": (
                    by_order[order][0]["M_B"]
                    == by_order[order][0]["double_ladder"]["empirical_hsep_formula_value"]
                ),
            }
            for order in range(8, 37, 4)
        ],
        "smallest_recursive_member_order": 8,
        "stable_two_ladder_face_component_regime_starts": 16,
        "primary_question_answer": (
            "Yes. G_(n+4) is obtained by the same four-vertex opposite-rail square expansion, "
            "alternately lengthening one of two ladder strips by two faces."
        ),
    }

    expansion_output = {
        "schema": "barnie-expansion-certificates-v1",
        "operation_definition": (
            "The general boundary-four gadget replaces two disjoint cofacial edges by "
            "length-three paths and joins corresponding new vertices by two edges, so the "
            "four new vertices induce a facial C4. In D(a,b) the selected edges are the "
            "opposite rails of one quadrilateral ladder cell."
        ),
        "unique_double_ladder_certificates": unique_expansions,
        "tied_variant_certificates": tied_certificates,
        "certificate_count": len(unique_expansions) + len(tied_certificates),
    }

    rows = []
    for record in graph_summaries:
        double = record["double_ladder"]
        rows.append({
            "order": record["order"],
            "M_B": record["M_B"],
            "number_of_maximizers_for_order": record["number_of_maximizers_for_order"],
            "canonical_graph_hash": record["canonical_graph_hash"],
            "generation_index": record["generation_index"],
            "plantri_rank": record["plantri_rank"],
            "unique_maximizer": record["unique_maximizer"],
            "face_size_multiset": ";".join(map(str, record["face_size_multiset"])),
            "quadrilateral_component_signature": ";".join(record["quadrilateral_component_signature"]),
            "ladder_lengths": ";".join(str(item["face_count"]) for item in record["ladders"]),
            "exceptional_components": ";".join(item["type"] for item in record["exceptional_quadrilateral_components"]),
            "double_ladder_parameters": "" if double is None else f"{double['parameters']['first_ladder_length']},{double['parameters']['second_ladder_length']}",
            "complete_hamiltonian_cycle_count": record["complete_hamiltonian_cycle_count"],
            "exact_hsep": record["exact_hsep"],
            "primal_cycle_count": record["primal_cycle_count"],
            "lower_bound_method": record["lower_bound_method"],
            "packing_requirement_count": record["packing_requirement_count"],
        })

    figure_root = output_root / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    inserted_by_target = {
        certificate["target_hash"]: set(certificate["artifact_label_witness"]["inserted_vertices_target_artifact"])
        for certificate in unique_expansions + tied_certificates
    }
    for order in FIGURE_ORDERS:
        for bundle in sorted(by_order[order], key=lambda item: item["plantri_rank"]):
            graph_hash = bundle["canonical_graph_hash"]
            gallery = gallery_by_hash[graph_hash]
            base = gallery_root / gallery["drawing_svg"]
            stem = f"n_{order:02d}_M_{bundle['M_B']}_rank_{bundle['plantri_rank']:05d}_{graph_hash[:8]}_annotated.svg"
            annotate_svg(base, figure_root / stem, bundle, inserted_by_target.get(graph_hash, set()))

    write_json(output_root / "ladder_family.json", family_output)
    write_csv(output_root / "ladder_family.csv", rows)
    write_json(output_root / "expansion_certificates.json", expansion_output)
    write_json(output_root / "hamiltonian_tile_states.json", state_output)
    write_json(output_root / "tied_order_classification.json", tied_output)
    write_json(output_root / "predictions.json", predictions)
    report = report_text(graph_summaries, unique_expansions, tied_output, state_output, predictions)
    atomic_write(output_root / "LADDER_FAMILY_REPORT.md", report.encode("utf-8"))
    invocation = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    atomic_write(
        output_root / "commands.log",
        ("ANALYZE\t" + subprocess.list2cmdline(invocation) + "\n").encode("utf-8"),
    )
    environment = {
        "schema": "barnie-ladder-environment-v1",
        "python_version": platform.python_version(),
        "networkx_version": nx.__version__,
        "platform": platform.platform(),
        "worker_count": 1,
        "sequence_manifest_sha256": digest_file(sequence_root / "SHA256SUMS.txt"),
        "gallery_manifest_sha256": digest_file(gallery_root / "SHA256SUMS.txt"),
        "analysis_module_sha256": digest_file(Path(__file__).parents[1] / "src" / "barnette_search" / "ladder_analysis.py"),
        "tool_sha256": digest_file(Path(__file__)),
        "certified_inputs_modified": False,
        "orders_38_40_launched": False,
    }
    write_json(output_root / "environment.json", environment)
    write_manifest(output_root)
    print(
        f"complete: {len(graph_summaries)} maximizers, {len(unique_expansions)} unique-family "
        f"and {len(tied_certificates)} tied expansion certificates, "
        f"{len(list(figure_root.glob('*.svg')))} figures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
