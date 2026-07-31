"""Combinatorial ladder analysis for certified Barnie-sequence maximizers.

This module is deliberately independent of drawing coordinates.  It operates
on abstract edges and certified sphere rotation systems; SVG annotation is a
downstream presentation step.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from itertools import combinations
import json
from typing import Any, Iterable, Sequence

import networkx as nx


Edge = tuple[int, int]
Rotation = tuple[tuple[int, ...], ...]


def normalized_edge(left: int, right: int) -> Edge:
    return (left, right) if left < right else (right, left)


def trace_faces(rotation: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    """Trace the left facial walks of a sphere rotation system."""
    rows = tuple(tuple(row) for row in rotation)
    unused = {(u, v) for u, row in enumerate(rows) for v in row}
    faces: list[tuple[int, ...]] = []
    while unused:
        start = min(unused)
        dart = start
        face: list[int] = []
        while True:
            if dart not in unused:
                if dart != start:
                    raise ValueError("rotation does not define facial walks")
                break
            unused.remove(dart)
            left, right = dart
            face.append(left)
            row = rows[right]
            position = row.index(left)
            dart = (right, row[(position - 1) % len(row)])
        faces.append(tuple(face))
    return tuple(faces)


def canonicalize_embedding(rotation: Sequence[Sequence[int]]) -> dict[str, Any]:
    """Return the least rooted rotation code and a labeling/orientation witness."""
    rows = tuple(tuple(row) for row in rotation)
    candidates: list[tuple[Any, ...]] = []
    for root in range(len(rows)):
        for first in rows[root]:
            for direction in (1, -1):
                labels = {root: 0, first: 1}
                parents = {root: first, first: root}
                vertices = [root, first]
                code: list[tuple[int, ...]] = []
                position = 0
                while position < len(vertices):
                    vertex = vertices[position]
                    neighbors = rows[vertex]
                    anchor = neighbors.index(parents[vertex])
                    ordered = tuple(
                        neighbors[(anchor + direction * offset) % len(neighbors)]
                        for offset in range(len(neighbors))
                    )
                    for neighbor in ordered:
                        if neighbor not in labels:
                            labels[neighbor] = len(labels)
                            parents[neighbor] = vertex
                            vertices.append(neighbor)
                    code.append(tuple(labels[neighbor] for neighbor in ordered))
                    position += 1
                candidates.append(
                    (
                        tuple(code),
                        tuple(vertices),
                        root,
                        first,
                        direction,
                        labels,
                    )
                )
    code, vertices, root, first, direction, labels = min(
        candidates, key=lambda item: (item[0], item[1], item[2:5])
    )
    payload = json.dumps(code, separators=(",", ":")).encode("ascii")
    return {
        "rotation_system": code,
        "faces": trace_faces(code),
        "original_to_canonical": tuple(labels[index] for index in range(len(rows))),
        "canonical_to_original": vertices,
        "root_edge_original": (root, first),
        "orientation_direction": direction,
        "canonical_graph_hash": sha256(payload).hexdigest(),
    }


def graph_from_rotation(rotation: Sequence[Sequence[int]]) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(range(len(rotation)))
    graph.add_edges_from(
        normalized_edge(vertex, neighbor)
        for vertex, row in enumerate(rotation)
        for neighbor in row
        if vertex < neighbor
    )
    return graph


def edge_to_faces(faces: Sequence[Sequence[int]]) -> dict[Edge, list[int]]:
    result: dict[Edge, list[int]] = defaultdict(list)
    for face_index, face in enumerate(faces):
        for left, right in zip(face, face[1:] + face[:1]):
            result[normalized_edge(left, right)].append(face_index)
    return dict(result)


def _face_edge(face: Sequence[int], index: int) -> Edge:
    position = index % len(face)
    return normalized_edge(face[position], face[(position + 1) % len(face)])


def _opposite_edge(face: Sequence[int], edge: Edge) -> Edge:
    if len(face) != 4:
        raise ValueError("opposite edges are used only for quadrilaterals")
    position = next(index for index in range(4) if _face_edge(face, index) == edge)
    return _face_edge(face, position + 2)


def _across_face_neighbor(
    face: Sequence[int], current_edge: Edge, next_edge: Edge, vertex: int
) -> int:
    face_edges = {_face_edge(face, index) for index in range(len(face))}
    for neighbor in face:
        if (
            neighbor not in current_edge
            and normalized_edge(vertex, neighbor) in face_edges
            and neighbor in next_edge
        ):
            return neighbor
    raise ValueError("quadrilateral strip does not have opposite rungs")


def _ordered_path(component: set[int], adjacency: dict[int, dict[int, Edge]]) -> list[int]:
    start = min(index for index in component if len(adjacency[index]) == 1)
    ordered: list[int] = []
    previous: int | None = None
    current: int | None = start
    while current is not None:
        ordered.append(current)
        following = [item for item in adjacency[current] if item != previous]
        previous, current = current, following[0] if following else None
    return ordered


def _ladder_columns(
    faces: Sequence[Sequence[int]],
    ordered_faces: list[int],
    adjacency: dict[int, dict[int, Edge]],
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    shared = [
        adjacency[ordered_faces[index]][ordered_faces[index + 1]]
        for index in range(len(ordered_faces) - 1)
    ]
    first_rung = _opposite_edge(faces[ordered_faces[0]], shared[0])
    columns: list[tuple[int, int]] = [first_rung]
    current_rung = first_rung
    for index, face_index in enumerate(ordered_faces):
        next_rung = (
            shared[index]
            if index < len(shared)
            else _opposite_edge(faces[face_index], shared[-1])
        )
        face = faces[face_index]
        columns.append(
            tuple(
                _across_face_neighbor(face, current_rung, next_rung, vertex)
                for vertex in current_rung
            )
        )
        current_rung = next_rung

    variants = []
    for reverse in (False, True):
        candidate_columns = tuple(reversed(columns)) if reverse else tuple(columns)
        candidate_faces = tuple(reversed(ordered_faces)) if reverse else tuple(ordered_faces)
        variants.append((candidate_columns, candidate_faces))
        variants.append(
            (tuple((bottom, top) for top, bottom in candidate_columns), candidate_faces)
        )
    return min(variants, key=lambda item: (item[0], item[1]))


def _other_face_size(
    edge: Edge,
    own_face: int,
    faces: Sequence[Sequence[int]],
    incidence: dict[Edge, list[int]],
) -> int:
    others = [index for index in incidence[edge] if index != own_face]
    if len(others) != 1:
        raise ValueError("each sphere edge must have exactly two incident faces")
    return len(faces[others[0]])


def detect_quadrilateral_structures(
    rotation: Sequence[Sequence[int]],
) -> dict[str, Any]:
    """Inventory maximal quadrilateral-face components and strict ladders.

    A strict ladder is a connected component of the quadrilateral face-
    adjacency graph which is a path of length at least two, whose consecutive
    shared edges are opposite in each internal face, and whose induced union is
    exactly P_(ell+1) square K_2.  Cycle and isolated components are retained as
    explicit exceptions rather than being called ladders.
    """
    rows = tuple(tuple(row) for row in rotation)
    faces = trace_faces(rows)
    graph = graph_from_rotation(rows)
    incidence = edge_to_faces(faces)
    quadrilaterals = {index for index, face in enumerate(faces) if len(face) == 4}
    adjacency: dict[int, dict[int, Edge]] = {index: {} for index in quadrilaterals}
    for edge, incident in incidence.items():
        if len(incident) == 2 and all(index in quadrilaterals for index in incident):
            left, right = incident
            adjacency[left][right] = edge
            adjacency[right][left] = edge

    components: list[set[int]] = []
    unseen = set(quadrilaterals)
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        pending = [start]
        component: set[int] = set()
        while pending:
            face = pending.pop()
            component.add(face)
            for neighbor in adjacency[face]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    pending.append(neighbor)
        components.append(component)

    ladders: list[dict[str, Any]] = []
    exceptional: list[dict[str, Any]] = []
    all_edges = {normalized_edge(left, right) for left, right in graph.edges()}
    for component in components:
        degrees = sorted(len(adjacency[index]) for index in component)
        is_path = (
            len(component) >= 2
            and degrees.count(1) == 2
            and all(degree in (1, 2) for degree in degrees)
        )
        is_cycle = len(component) >= 3 and all(degree == 2 for degree in degrees)
        if not is_path:
            exceptional.append(
                {
                    "type": "quadrilateral_face_cycle" if is_cycle else "isolated_quadrilateral" if len(component) == 1 else "branched_quadrilateral_component",
                    "face_indices": sorted(component),
                    "face_count": len(component),
                    "face_adjacency_degrees": degrees,
                    "vertices": sorted(set().union(*(set(faces[index]) for index in component))),
                }
            )
            continue

        initially_ordered = _ordered_path(component, adjacency)
        columns, ordered_faces = _ladder_columns(faces, initially_ordered, adjacency)
        rungs = [normalized_edge(*column) for column in columns]
        top_rail = [
            normalized_edge(columns[index][0], columns[index + 1][0])
            for index in range(len(columns) - 1)
        ]
        bottom_rail = [
            normalized_edge(columns[index][1], columns[index + 1][1])
            for index in range(len(columns) - 1)
        ]
        union_edges = set(rungs + top_rail + bottom_rail)
        union_vertices = set().union(*(set(faces[index]) for index in component))
        chords = sorted(
            edge
            for edge in all_edges
            if edge[0] in union_vertices
            and edge[1] in union_vertices
            and edge not in union_edges
        )
        expected_vertices = 2 * (len(component) + 1)
        expected_edges = 3 * len(component) + 1
        strict = (
            not chords
            and len(union_vertices) == expected_vertices
            and len(union_edges) == expected_edges
        )
        if not strict:
            exceptional.append(
                {
                    "type": "nonstrict_quadrilateral_path",
                    "face_indices": list(ordered_faces),
                    "face_count": len(component),
                    "vertices": sorted(union_vertices),
                    "additional_chords": [list(edge) for edge in chords],
                }
            )
            continue

        attachments = []
        end_signatures = []
        for end, column_index, cell_index in (
            ("left", 0, 0),
            ("right", -1, len(ordered_faces) - 1),
        ):
            column = columns[column_index]
            outside_edges = []
            outside_neighbors = []
            for vertex in column:
                outside = sorted(set(rows[vertex]) - union_vertices)
                if len(outside) != 1:
                    raise ValueError("strict ladder terminal must have one external neighbor")
                outside_neighbors.append(outside[0])
                outside_edges.append(normalized_edge(vertex, outside[0]))
            attachments.extend(outside_edges)
            rail_index = 0 if end == "left" else len(top_rail) - 1
            own_face = ordered_faces[cell_index]
            side_sizes = (
                _other_face_size(top_rail[rail_index], own_face, faces, incidence),
                _other_face_size(bottom_rail[rail_index], own_face, faces, incidence),
            )
            terminal_size = _other_face_size(
                rungs[column_index], own_face, faces, incidence
            )
            rotations = []
            rail_neighbor_column = columns[1] if end == "left" else columns[-2]
            for rail, vertex in enumerate(column):
                roles = {}
                roles[column[1 - rail]] = "terminal_rung"
                roles[rail_neighbor_column[rail]] = "rail"
                roles[outside_neighbors[rail]] = "attachment"
                rotations.append([roles[neighbor] for neighbor in rows[vertex]])
            end_signatures.append(
                {
                    "end": end,
                    "terminal_vertices": list(column),
                    "terminal_rung": list(rungs[column_index]),
                    "attachment_edges": [list(edge) for edge in outside_edges],
                    "outside_neighbors": outside_neighbors,
                    "outside_neighbors_adjacent": graph.has_edge(*outside_neighbors),
                    "outside_face_size_across_terminal_rung": terminal_size,
                    "outside_face_sizes_across_first_rails": list(side_sizes),
                    "terminal_vertex_rotation_roles": rotations,
                    "local_signature": [terminal_size, *sorted(side_sizes), int(graph.has_edge(*outside_neighbors))],
                }
            )

        cell_states = []
        for index, face_index in enumerate(ordered_faces):
            cell_states.append(
                {
                    "cell_index": index,
                    "face_index": face_index,
                    "vertices": list(faces[face_index]),
                    "left_rung": list(rungs[index]),
                    "top_rail": list(top_rail[index]),
                    "bottom_rail": list(bottom_rail[index]),
                    "right_rung": list(rungs[index + 1]),
                }
            )
        ladders.append(
            {
                "face_count": len(component),
                "ordered_face_indices": list(ordered_faces),
                "ordered_faces": [list(faces[index]) for index in ordered_faces],
                "columns": [list(column) for column in columns],
                "rung_edges": [list(edge) for edge in rungs],
                "internal_rung_edges": [list(edge) for edge in rungs[1:-1]],
                "terminal_rung_edges": [list(rungs[0]), list(rungs[-1])],
                "rail_paths": [
                    [columns[index][0] for index in range(len(columns))],
                    [columns[index][1] for index in range(len(columns))],
                ],
                "rail_edges": [
                    [list(edge) for edge in top_rail],
                    [list(edge) for edge in bottom_rail],
                ],
                "boundary_terminals": [list(columns[0]), list(columns[-1])],
                "attachment_edges": [list(edge) for edge in sorted(set(attachments))],
                "vertices": sorted(union_vertices),
                "induced": not chords,
                "additional_chords": [list(edge) for edge in chords],
                "end_caps": end_signatures,
                "cells": cell_states,
            }
        )

    ladders.sort(key=lambda item: (-item["face_count"], item["columns"]))
    for index, ladder in enumerate(ladders):
        ladder["ladder_index"] = index
    exceptional.sort(key=lambda item: (item["type"], item["face_indices"]))
    return {
        "faces": [list(face) for face in faces],
        "face_size_multiset": sorted(map(len, faces)),
        "quadrilateral_face_count": len(quadrilaterals),
        "face_adjacency_edges": [
            {"faces": list(sorted(incident)), "shared_edge": list(edge)}
            for edge, incident in sorted(incidence.items())
            if len(incident) == 2
        ],
        "ladders": ladders,
        "exceptional_quadrilateral_components": exceptional,
        "quadrilateral_component_signature": sorted(
            [f"P{item['face_count']}" for item in ladders]
            + [
                ("C" if item["type"] == "quadrilateral_face_cycle" else "I" if item["type"] == "isolated_quadrilateral" else "X")
                + str(item["face_count"])
                for item in exceptional
            ],
            reverse=True,
        ),
    }


def add_ladder_reversal_automorphisms(
    rotation: Sequence[Sequence[int]], structures: dict[str, Any]
) -> int:
    """Annotate ladders with exact abstract-graph reversal automorphisms."""
    graph = graph_from_rotation(rotation)
    automorphisms = list(nx.algorithms.isomorphism.GraphMatcher(graph, graph).isomorphisms_iter())
    face_sets = [frozenset(face) for face in structures["faces"]]
    for ladder in structures["ladders"]:
        sequence = [face_sets[index] for index in ladder["ordered_face_indices"]]
        reversed_sequence = list(reversed(sequence))
        witnesses = []
        for mapping in automorphisms:
            image = [frozenset(mapping[vertex] for vertex in face) for face in sequence]
            if image == reversed_sequence:
                witnesses.append([mapping[index] for index in range(len(rotation))])
        ladder["reversal_automorphism_exists"] = bool(witnesses)
        ladder["reversal_automorphism_witness"] = min(witnesses) if witnesses else None
    return len(automorphisms)


def double_ladder_graph(first_length: int, second_length: int) -> nx.Graph:
    """Construct the observed double-ladder D(a,b), for odd positive a,b."""
    if first_length < 1 or second_length < 1:
        raise ValueError("ladder lengths must be positive")
    graph = nx.Graph()
    for name, length in (("A", first_length), ("B", second_length)):
        for column in range(length + 1):
            graph.add_edge((name, column, 0), (name, column, 1))
        for column in range(length):
            for rail in (0, 1):
                graph.add_edge((name, column, rail), (name, column + 1, rail))
    graph.add_edges_from(
        (
            (("A", 0, 0), ("B", 0, 0)),
            (("A", 0, 1), ("B", second_length, 0)),
            (("A", first_length, 0), ("B", 0, 1)),
            (("A", first_length, 1), ("B", second_length, 1)),
        )
    )
    return graph


def barnette_properties(graph: nx.Graph) -> dict[str, bool]:
    return {
        "simple": not graph.is_multigraph() and nx.number_of_selfloops(graph) == 0,
        "cubic": all(degree == 3 for _, degree in graph.degree()),
        "bipartite": nx.is_bipartite(graph),
        "planar": nx.check_planarity(graph)[0],
        "three_connected": graph.number_of_nodes() >= 4 and nx.node_connectivity(graph) >= 3,
    }


def graph_canonical_hash(graph: nx.Graph) -> str:
    """Canonical hash a 3-connected planar graph via a fresh sphere embedding."""
    planar, embedding = nx.check_planarity(graph)
    if not planar:
        raise ValueError("cannot hash a nonplanar graph as a Barnette graph")
    vertices = sorted(graph)
    labels = {vertex: index for index, vertex in enumerate(vertices)}
    rotation = tuple(
        tuple(labels[neighbor] for neighbor in embedding.neighbors_cw_order(vertex))
        for vertex in vertices
    )
    return canonicalize_embedding(rotation)["canonical_graph_hash"]


def _pairings(vertices: Iterable[int]) -> Iterable[tuple[Edge, Edge]]:
    values = set(vertices)
    first = min(values)
    for second in sorted(values - {first}):
        remaining = sorted(values - {first, second})
        yield normalized_edge(first, second), normalized_edge(*remaining)


def square_reduction_certificates(
    source_rotation: Sequence[Sequence[int]],
    target_rotation: Sequence[Sequence[int]],
    *,
    source_hash: str,
    target_hash: str,
) -> list[dict[str, Any]]:
    """Enumerate bounded inverse square-tile reductions target -> source."""
    source_rows = tuple(tuple(row) for row in source_rotation)
    target_rows = tuple(tuple(row) for row in target_rotation)
    source_graph = graph_from_rotation(source_rows)
    target_graph = graph_from_rotation(target_rows)
    source_faces = trace_faces(source_rows)
    target_faces = trace_faces(target_rows)
    source_incidence = edge_to_faces(source_faces)
    source_structures = detect_quadrilateral_structures(source_rows)
    source_rail_edges = {
        normalized_edge(*edge)
        for ladder in source_structures["ladders"]
        for rail in ladder["rail_edges"]
        for edge in rail
    }
    certificates = []
    seen: set[tuple[Any, ...]] = set()
    for target_face_index, face in enumerate(target_faces):
        if len(face) != 4 or len(set(face)) != 4:
            continue
        inserted = tuple(sorted(face))
        induced = target_graph.subgraph(inserted)
        if induced.number_of_edges() != 4 or any(degree != 2 for _, degree in induced.degree()):
            continue
        boundary_neighbors = []
        for vertex in inserted:
            outside = sorted(set(target_graph[vertex]) - set(inserted))
            if len(outside) != 1:
                break
            boundary_neighbors.append(outside[0])
        else:
            if len(set(boundary_neighbors)) != 4:
                continue
            for restored in _pairings(boundary_neighbors):
                reduced = target_graph.copy()
                reduced.remove_nodes_from(inserted)
                if any(reduced.has_edge(*edge) for edge in restored):
                    continue
                reduced.add_edges_from(restored)
                properties = barnette_properties(reduced)
                if not all(properties.values()):
                    continue
                matcher = nx.algorithms.isomorphism.GraphMatcher(reduced, source_graph)
                for target_to_source in matcher.isomorphisms_iter():
                    source_edges = tuple(
                        sorted(
                            normalized_edge(target_to_source[left], target_to_source[right])
                            for left, right in restored
                        )
                    )
                    common_faces = sorted(
                        set(source_incidence[source_edges[0]])
                        & set(source_incidence[source_edges[1]])
                    )
                    if len(common_faces) != 1:
                        continue
                    common_face = source_faces[common_faces[0]]
                    positions = [
                        next(
                            index
                            for index in range(len(common_face))
                            if _face_edge(common_face, index) == edge
                        )
                        for edge in source_edges
                    ]
                    opposite_quadrilateral_edges = (
                        len(common_face) == 4
                        and (positions[0] - positions[1]) % 4 == 2
                    )
                    key = (inserted, restored, source_edges)
                    if key in seen:
                        continue
                    seen.add(key)
                    unchanged_source_to_target = {
                        source: target for target, source in target_to_source.items()
                    }
                    inserted_edges = sorted(
                        normalized_edge(left, right)
                        for left, right in target_graph.edges()
                        if left in inserted or right in inserted
                    )
                    reconstructed = nx.relabel_nodes(
                        source_graph, unchanged_source_to_target, copy=True
                    )
                    reconstructed.remove_edges_from(
                        [
                            normalized_edge(
                                unchanged_source_to_target[left],
                                unchanged_source_to_target[right],
                            )
                            for left, right in source_edges
                        ]
                    )
                    reconstructed.add_nodes_from(inserted)
                    reconstructed.add_edges_from(inserted_edges)
                    reconstructed_edges = {
                        normalized_edge(left, right) for left, right in reconstructed.edges()
                    }
                    target_edges = {
                        normalized_edge(left, right) for left, right in target_graph.edges()
                    }
                    affected_source = sorted(
                        set(source_incidence[source_edges[0]])
                        | set(source_incidence[source_edges[1]])
                    )
                    affected_target = sorted(
                        index
                        for index, boundary in enumerate(target_faces)
                        if set(boundary) & set(inserted)
                    )
                    boundary = []
                    for vertex in inserted:
                        outside = next(
                            neighbor for neighbor in target_graph[vertex] if neighbor not in inserted
                        )
                        boundary.append(
                            {
                                "inserted_vertex": vertex,
                                "target_terminal": outside,
                                "source_terminal": target_to_source[outside],
                            }
                        )
                    certificates.append(
                        {
                            "schema": "barnie-square-expansion-certificate-v1",
                            "source_hash": source_hash,
                            "target_hash": target_hash,
                            "source_order": len(source_rows),
                            "target_order": len(target_rows),
                            "operation": "two-edge facial square expansion",
                            "removed_vertices_inverse": list(inserted),
                            "inserted_vertices_forward": list(inserted),
                            "restored_edges_inverse_target_labels": [list(edge) for edge in restored],
                            "removed_edges_forward_source_labels": [list(edge) for edge in source_edges],
                            "inserted_edges_forward_target_labels": [list(edge) for edge in inserted_edges],
                            "boundary_terminals": boundary,
                            "unchanged_source_to_target": [
                                [source, unchanged_source_to_target[source]]
                                for source in sorted(unchanged_source_to_target)
                            ],
                            "source_expanded_face": {
                                "face_index": common_faces[0],
                                "vertices": list(common_face),
                                "size": len(common_face),
                                "expanded_edges_are_opposite": opposite_quadrilateral_edges,
                                "expanded_edge_boundary_positions": positions,
                                "expanded_edges_are_disjoint": not bool(set(source_edges[0]) & set(source_edges[1])),
                                "expanded_edges_are_detected_ladder_rails": all(
                                    edge in source_rail_edges for edge in source_edges
                                ),
                            },
                            "target_tile_face": {
                                "face_index": target_face_index,
                                "vertices": list(face),
                                "induced_four_cycle": True,
                            },
                            "affected_faces_before": [
                                {"face_index": index, "vertices": list(source_faces[index]), "size": len(source_faces[index])}
                                for index in affected_source
                            ],
                            "affected_faces_after": [
                                {"face_index": index, "vertices": list(target_faces[index]), "size": len(target_faces[index])}
                                for index in affected_target
                            ],
                            "reduced_graph_canonical_hash": graph_canonical_hash(reduced),
                            "canonical_hash_matches_source": graph_canonical_hash(reduced) == source_hash,
                            "reconstruction_edge_set_matches_target": reconstructed_edges == target_edges,
                            "reduced_barnette_properties": properties,
                            "reconstructed_target_barnette_properties": barnette_properties(reconstructed),
                            "source_boundary_rotations": {
                                str(vertex): list(source_rows[vertex])
                                for edge in source_edges for vertex in edge
                            },
                            "target_affected_rotations": {
                                str(vertex): list(target_rows[vertex])
                                for vertex in sorted(set(inserted) | set(boundary_neighbors))
                            },
                        }
                    )
                    break
    return sorted(
        certificates,
        key=lambda item: (
            item["inserted_vertices_forward"],
            item["restored_edges_inverse_target_labels"],
            item["removed_edges_forward_source_labels"],
        ),
    )


def ladder_edge_roles(structures: dict[str, Any]) -> dict[Edge, list[dict[str, Any]]]:
    roles: dict[Edge, list[dict[str, Any]]] = defaultdict(list)
    for ladder in structures["ladders"]:
        index = ladder["ladder_index"]
        for position, edge in enumerate(ladder["rung_edges"]):
            roles[normalized_edge(*edge)].append(
                {"ladder_index": index, "role": "rung", "position": position}
            )
        for rail_index, rail in enumerate(ladder["rail_edges"]):
            for position, edge in enumerate(rail):
                roles[normalized_edge(*edge)].append(
                    {"ladder_index": index, "role": f"rail_{rail_index}", "position": position}
                )
        for edge in ladder["attachment_edges"]:
            roles[normalized_edge(*edge)].append(
                {"ladder_index": index, "role": "attachment", "position": None}
            )
    return dict(roles)


def cycle_edge_set(cycle: Sequence[int]) -> set[Edge]:
    return {
        normalized_edge(left, right)
        for left, right in zip(cycle, cycle[1:] + cycle[:1])
    }


def hamiltonian_ladder_states(
    structures: dict[str, Any],
    edges: Sequence[Sequence[int]],
    universe: Sequence[Sequence[int]],
    primal_cycles: Sequence[Sequence[int]],
    packing_requirements: Sequence[Sequence[int]],
    lower_bound_method: str,
) -> dict[str, Any]:
    """Encode the complete certified cycle universe on every strict ladder."""
    normalized_edges = [normalized_edge(*edge) for edge in edges]
    edge_indexes = {edge: index for index, edge in enumerate(normalized_edges)}
    roles = ladder_edge_roles(structures)
    universe_keys = {tuple(cycle): index for index, cycle in enumerate(universe)}
    cycle_records = []
    cell_state_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    for cycle_index, cycle in enumerate(universe):
        selected = cycle_edge_set(cycle)
        ladder_patterns = []
        for ladder in structures["ladders"]:
            rungs = [normalized_edge(*edge) for edge in ladder["rung_edges"]]
            rails = [
                [normalized_edge(*edge) for edge in rail]
                for rail in ladder["rail_edges"]
            ]
            rung_bits = "".join("1" if edge in selected else "0" for edge in rungs)
            rail_bits = [
                "".join("1" if edge in selected else "0" for edge in rail)
                for rail in rails
            ]
            cells = []
            for position in range(ladder["face_count"]):
                code = (
                    rung_bits[position]
                    + rail_bits[0][position]
                    + rail_bits[1][position]
                    + rung_bits[position + 1]
                )
                cells.append(code)
                cell_state_counts[code] += 1
            for left, right in zip(cells, cells[1:]):
                transition_counts[f"{left}->{right}"] += 1
            ladder_patterns.append(
                {
                    "ladder_index": ladder["ladder_index"],
                    "rung_bits": rung_bits,
                    "rail_bits": rail_bits,
                    "cell_state_codes": cells,
                }
            )
        selected_indexes = sorted(edge_indexes[edge] for edge in selected)
        cycle_records.append(
            {
                "cycle_index": cycle_index,
                "selected_edge_indices": selected_indexes,
                "ladder_patterns": ladder_patterns,
            }
        )

    primal_indices = []
    for cycle in primal_cycles:
        key = tuple(cycle)
        if key not in universe_keys:
            raise ValueError("primal cycle is absent from complete universe")
        primal_indices.append(universe_keys[key])

    localized_requirements = []
    location_counts: Counter[str] = Counter()
    for requirement_index, (include_index, exclude_index) in enumerate(packing_requirements):
        include_edge = normalized_edges[include_index]
        exclude_edge = normalized_edges[exclude_index]
        include_roles = roles.get(include_edge, [])
        exclude_roles = roles.get(exclude_edge, [])
        include_internal = [role for role in include_roles if role["role"] != "attachment"]
        exclude_internal = [role for role in exclude_roles if role["role"] != "attachment"]
        classification = (
            "both_internal_ladder"
            if include_internal and exclude_internal
            else "include_internal_ladder_only"
            if include_internal
            else "exclude_internal_ladder_only"
            if exclude_internal
            else "outside_ladders"
        )
        location_counts[classification] += 1
        localized_requirements.append(
            {
                "requirement_index": requirement_index,
                "include_edge_index": include_index,
                "include_edge": list(include_edge),
                "include_ladder_roles": include_roles,
                "include_internal_ladder_roles": include_internal,
                "exclude_edge_index": exclude_index,
                "exclude_edge": list(exclude_edge),
                "exclude_ladder_roles": exclude_roles,
                "exclude_internal_ladder_roles": exclude_internal,
                "classification": classification,
            }
        )
    return {
        "complete_cycle_count": len(universe),
        "cycle_records": cycle_records,
        "admissible_observed_cell_state_counts": dict(sorted(cell_state_counts.items())),
        "observed_adjacent_cell_transition_counts": dict(sorted(transition_counts.items())),
        "primal_cycle_indices": primal_indices,
        "lower_bound_method": lower_bound_method,
        "stored_packing_requirement_count": len(packing_requirements),
        "packing_requirement_location_counts": dict(sorted(location_counts.items())),
        "packing_requirement_locations": localized_requirements,
    }


def double_ladder_cycle_formula(first_length: int, second_length: int) -> int:
    """Number of Hamiltonian cycles in D(a,b) for the observed odd parameters."""
    return first_length * second_length + 5


def empirical_double_ladder_hsep(first_length: int, second_length: int) -> int:
    """Certified-range empirical formula; not a general hsep theorem."""
    numerator = (
        first_length * second_length
        + 2 * first_length
        + 2 * second_length
        + 3
    )
    if numerator % 2:
        raise ValueError("formula is integral only for the intended odd lengths")
    return numerator // 2
