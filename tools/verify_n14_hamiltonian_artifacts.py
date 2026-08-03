#!/usr/bin/env python3
"""Independently verify an n=14 Hamiltonian-cycle atlas using the stdlib only."""

from __future__ import annotations

import argparse
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import struct
import sys
from typing import Iterable
import xml.etree.ElementTree as ET


EXPECTED_HASH = "3b52365d8f69db960762343efece3b7510b943660d0fbd6353bb4f4cd7c0f445"
Edge = tuple[int, int]


def edge(value: Iterable[int]) -> Edge:
    left, right = map(int, value)
    return (left, right) if left < right else (right, left)


def write_new(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def connected(vertices: set[int], edges: set[Edge]) -> bool:
    if not vertices:
        return True
    adjacency = {vertex: set() for vertex in vertices}
    for left, right in edges:
        if left in vertices and right in vertices:
            adjacency[left].add(right)
            adjacency[right].add(left)
    reached = {min(vertices)}
    pending = list(reached)
    while pending:
        for neighbor in adjacency[pending.pop()]:
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    return reached == vertices


def barnette_checks(vertices: set[int], edges: set[Edge]) -> dict[str, bool]:
    degrees = {vertex: 0 for vertex in vertices}
    adjacency = {vertex: set() for vertex in vertices}
    for left, right in edges:
        degrees[left] += 1
        degrees[right] += 1
        adjacency[left].add(right)
        adjacency[right].add(left)
    color: dict[int, int] = {}
    bipartite = True
    for root in sorted(vertices):
        if root in color:
            continue
        color[root] = 0
        pending = [root]
        while pending:
            current = pending.pop()
            for neighbor in adjacency[current]:
                if neighbor not in color:
                    color[neighbor] = 1 - color[current]
                    pending.append(neighbor)
                elif color[neighbor] == color[current]:
                    bipartite = False
    three_connected = all(
        connected(vertices - set(removed), edges)
        for size in (0, 1, 2)
        for removed in combinations(vertices, size)
    )
    return {
        "simple": len(edges) == 21 and all(left != right for left, right in edges),
        "cubic": all(value == 3 for value in degrees.values()),
        "connected": connected(vertices, edges),
        "bipartite": bipartite,
        "three_vertex_connected": three_connected,
    }


def svg_data(path: Path) -> tuple[set[Edge], dict[int, tuple[str, str]], set[Edge]]:
    root = ET.parse(path).getroot()
    highlighted: set[Edge] = set()
    positions: dict[int, tuple[str, str]] = {}
    base_edges: set[Edge] = set()
    for element in root.iter():
        kind = element.attrib.get("class")
        if kind == "hamiltonian-edge":
            highlighted.add(edge(map(int, element.attrib["data-edge"].split("-"))))
        elif kind == "graph-edge":
            base_edges.add(edge(map(int, element.attrib["data-edge"].split("-"))))
        elif kind == "vertex":
            positions[int(element.attrib["data-vertex"])] = (
                element.attrib["cx"],
                element.attrib["cy"],
            )
    return highlighted, positions, base_edges


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"invalid PNG: {path}")
    return struct.unpack(">II", data[16:24])


def verify_hsep(
    graph_edges: list[Edge], cycle_edges: list[set[Edge]], certificate: dict
) -> dict[str, object]:
    edge_index = {item: index for index, item in enumerate(graph_edges)}
    all_requirements = {
        (included, excluded)
        for included in range(len(graph_edges))
        for excluded in range(len(graph_edges))
        if included != excluded
    }
    covers: list[set[tuple[int, int]]] = []
    for cycle in cycle_edges:
        present = {edge_index[item] for item in cycle}
        covers.append(
            {(left, right) for left in present for right in range(len(graph_edges)) if right not in present}
        )
    primal = tuple(int(value) - 1 for value in certificate["primal_cycle_indices_one_based"])
    primal_covered = set().union(*(covers[index] for index in primal))
    if primal_covered != all_requirements or len(primal) != 10:
        raise ValueError("invalid hsep primal certificate")

    entries = certificate["lower_bound_entries"]
    expected_masks = {mask for mask in range(1 << len(cycle_edges)) if mask.bit_count() < 10}
    actual_masks = {int(item["cycle_subset_bitmask"]) for item in entries}
    if actual_masks != expected_masks or len(entries) != len(expected_masks):
        raise ValueError("incomplete hsep lower-bound certificate")
    for item in entries:
        mask = int(item["cycle_subset_bitmask"])
        included_edge = edge(item["uncovered_ordered_edge_pair"][0])
        excluded_edge = edge(item["uncovered_ordered_edge_pair"][1])
        requirement = (edge_index[included_edge], edge_index[excluded_edge])
        covered = set().union(*(covers[index] for index in range(len(covers)) if mask & (1 << index))) if mask else set()
        if requirement in covered or requirement[0] == requirement[1]:
            raise ValueError(f"false lower-bound witness for mask {mask}")
    return {
        "exact_hsep": 10,
        "primal_valid": True,
        "lower_bound_valid": True,
        "lower_bound_subsets_verified": len(entries),
    }


def verify(artifact: Path) -> dict[str, object]:
    artifact = artifact.resolve()
    cycles_document = json.loads((artifact / "cycles.json").read_text(encoding="utf-8"))
    graph_record = cycles_document["graph"]
    if graph_record["canonical_graph_hash"] != EXPECTED_HASH:
        raise ValueError("canonical graph hash mismatch")
    vertices = set(range(int(graph_record["order"])))
    graph_edges = sorted(edge(item) for item in graph_record["edges"])
    graph_edge_set = set(graph_edges)
    structural = barnette_checks(vertices, graph_edge_set)
    if not all(structural.values()):
        raise ValueError(f"Barnette checks failed: {structural}")

    cycle_records = cycles_document["cycles"]
    if len(cycle_records) != 12:
        raise ValueError("cycle count is not 12")
    cycle_edge_sets: list[set[Edge]] = []
    canonical_lists: list[tuple[Edge, ...]] = []
    for expected_index, record in enumerate(cycle_records, 1):
        if record["index"] != expected_index:
            raise ValueError("cycle indices are not consecutive")
        closed = tuple(map(int, record["canonical_closed_vertex_sequence"]))
        edges = tuple(sorted(edge(pair) for pair in record["canonical_edge_list"]))
        if edges != tuple(edge(pair) for pair in record["canonical_edge_list"]):
            raise ValueError("cycle edge list is not canonical")
        degrees = {vertex: 0 for vertex in vertices}
        for left, right in edges:
            degrees[left] += 1
            degrees[right] += 1
        if not (
            len(closed) == 15
            and closed[0] == closed[-1]
            and set(closed[:-1]) == vertices
            and len(set(closed[:-1])) == 14
            and len(edges) == 14
            and set(edges) <= graph_edge_set
            and all(value == 2 for value in degrees.values())
            and connected(vertices, set(edges))
            and set(edges) == {edge(pair) for pair in zip(closed, closed[1:])}
        ):
            raise ValueError(f"invalid cycle {expected_index}")
        cycle_edge_sets.append(set(edges))
        canonical_lists.append(edges)
    if canonical_lists != sorted(canonical_lists) or len(set(canonical_lists)) != 12:
        raise ValueError("cycle order or deduplication failed")

    base_highlights, shared_positions, base_edges = svg_data(artifact / "graph_base.svg")
    if base_highlights or base_edges != graph_edge_set or set(shared_positions) != vertices:
        raise ValueError("invalid base SVG")
    file_checks: dict[str, bool] = {}
    for index, expected_edges in enumerate(cycle_edge_sets, 1):
        svg = artifact / f"cycle_{index:02d}.svg"
        png = artifact / f"cycle_{index:02d}.png"
        highlighted, positions, svg_edges = svg_data(svg)
        if highlighted != expected_edges or positions != shared_positions or svg_edges != graph_edge_set:
            raise ValueError(f"SVG/cycle mismatch at cycle {index}")
        if png_dimensions(png) != (900, 900):
            raise ValueError(f"PNG dimension mismatch at cycle {index}")
        file_checks[svg.name] = svg.stat().st_size > 0
        file_checks[png.name] = png.stat().st_size > 0
    overview = artifact / "overview_all_12_cycles.png"
    if png_dimensions(overview) != (1800, 1400):
        raise ValueError("overview PNG dimension mismatch")
    file_checks[overview.name] = overview.stat().st_size > 0

    hsep_certificate = json.loads((artifact / "hsep_certificate.json").read_text(encoding="utf-8"))
    hsep = verify_hsep(graph_edges, cycle_edge_sets, hsep_certificate)
    digest = sha256(
        json.dumps(
            {str(vertex): list(shared_positions[vertex]) for vertex in sorted(shared_positions)},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    return {
        "schema": "barnette-n14-independent-verification-v1",
        "success": True,
        "canonical_graph_hash": EXPECTED_HASH,
        "structural_graph_checks": structural,
        "cycle_count": 12,
        "all_cycles_valid": True,
        "cycles_canonically_sorted_and_distinct": True,
        "all_svg_highlights_match_cycles_json": True,
        "all_svg_coordinates_identical": True,
        "svg_coordinate_string_sha256": digest,
        "all_required_images_nonempty": all(file_checks.values()),
        "file_checks": file_checks,
        "hsep_certificate": hsep,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.artifact)
        write_new(args.artifact.resolve() / "independent_verification.json", result)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
