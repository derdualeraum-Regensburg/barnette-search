"""Independent embedding-based analysis of quadrilateral ladder strips.

This module is intentionally independent of ``barnette_search.ladder_analysis``:
it does not import it and never touches it, so it has zero coupling with the
hsep certificate-adjacent ``double_ladder_packing`` / ``double_ladder_primal``
code paths. Face tracing and rotation canonicalization below are fresh,
self-contained reimplementations of standard techniques already used
elsewhere in this repository.

A "strict ladder strip" is found by tracing the mandatory continuation rule
through the quadrilateral face-adjacency structure of a sphere embedding:
entering a quadrilateral face over one edge, the strip may only continue over
the *opposite* edge of that same face. Every quadrilateral face has exactly
two opposite-edge "slots" (edge pairs (0,2) and (1,3) in its cyclic boundary).
Building a graph ``H`` whose nodes are the relevant ``(face, slot)`` pairs and
whose edges connect slots sharing a quadrilateral-quadrilateral boundary edge
gives a graph where every node has degree at most 2 (a slot has only two
edges), so ``H`` always decomposes into simple paths and simple cycles. This
strand/"polychord" decomposition technique is standard in quadrilateral-mesh
literature; the field names here are provisional project terminology and no
novelty is claimed (see AGENTS.md).

Path components of H are only *candidate* open strips: a single H path can
revisit the same quadrilateral face through its other slot, or contain a
"chord" between non-consecutive faces. Both conditions are hereditary
(removing elements cannot introduce a new repeat or a new chord), so for each
raw path there is a unique family of inclusion-maximal valid sub-sequences,
computed with the same sliding-window technique used for "longest substring
without repeating characters". Cycle components of H count as closed strict
ladder strips only if their face projection is itself simple and chord-free;
otherwise they are reported separately as diagnostic-only degenerate closed
polychords, never decomposed and never used in any ladder metric.

``double_ladder_score`` and ``double_ladder_score_times_2`` are purely
descriptive structural statistics. They are NOT a lower bound on hsep and
must never be reported as an hsep value.
"""

from __future__ import annotations

from typing import Any, Sequence

Edge = tuple[int, int]
Rotation = tuple[tuple[int, ...], ...]
HNode = tuple[int, int]


def normalized_edge(left: int, right: int) -> Edge:
    return (left, right) if left < right else (right, left)


def trace_faces(rotation: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    """Trace the facial walks of a sphere rotation system."""
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


def _canonicalize_rotation(rotation: Rotation) -> dict[str, Any]:
    """Least rooted-rotation code, used only as an index-independent tie-break key."""
    rows = rotation
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
                candidates.append((tuple(code), tuple(vertices), root, first, direction, labels))
    code, vertices, root, first, direction, labels = min(
        candidates, key=lambda item: (item[0], item[1], item[2:5])
    )
    return {"original_to_canonical": tuple(labels[index] for index in range(len(rows)))}


def _canonical_face_key(face: tuple[int, ...], vertex_map: tuple[int, ...]) -> tuple[int, ...]:
    relabeled = tuple(vertex_map[v] for v in face)
    n = len(relabeled)
    forward = [tuple(relabeled[(i + k) % n] for i in range(n)) for k in range(n)]
    backward_source = tuple(reversed(relabeled))
    backward = [tuple(backward_source[(i + k) % n] for i in range(n)) for k in range(n)]
    return min(forward + backward)


def _classify_components(
    quad_indices: list[int], plain_adjacency: dict[int, set[int]]
) -> tuple[list[dict[str, Any]], dict[int, int]]:
    visited: set[int] = set()
    components: list[dict[str, Any]] = []
    face_to_component: dict[int, int] = {}
    for start in quad_indices:
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        component: set[int] = set()
        while stack:
            node = stack.pop()
            component.add(node)
            for neighbor in plain_adjacency[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        degrees = [len(plain_adjacency[index]) for index in component]
        size = len(component)
        if size == 1:
            component_type = "isolated"
        elif all(degree == 2 for degree in degrees) and size >= 3:
            component_type = "cycle"
        elif sorted(degrees).count(1) == 2 and all(degree in (1, 2) for degree in degrees):
            component_type = "path"
        else:
            component_type = "branch"
        component_index = len(components)
        for face_index in component:
            face_to_component[face_index] = component_index
        components.append({"size": size, "type": component_type, "faces": sorted(component)})
    components.sort(key=lambda item: (-item["size"], item["type"], item["faces"]))
    return components, face_to_component


def _maximal_valid_windows(
    sequence: list[int], plain_adjacency: dict[int, set[int]]
) -> list[tuple[int, int]]:
    """Inclusion-maximal windows with no repeated face and no non-consecutive chord."""

    def is_valid(left: int, right: int) -> bool:
        window = sequence[left : right + 1]
        if len(set(window)) != len(window):
            return False
        for x in range(len(window)):
            for y in range(x + 2, len(window)):
                if window[y] in plain_adjacency.get(window[x], ()):
                    return False
        return True

    m = len(sequence)
    right_bound = [0] * m
    for left in range(m):
        candidate = left
        best = left
        while candidate < m and is_valid(left, candidate):
            best = candidate
            candidate += 1
        right_bound[left] = best
    windows = []
    for left in range(m):
        if left == 0 or right_bound[left - 1] < right_bound[left]:
            windows.append((left, right_bound[left]))
    return windows


def _trace_h_components(
    h_adjacency: dict[HNode, list[HNode]],
) -> tuple[list[list[int]], list[list[int]]]:
    visited: set[HNode] = set()
    open_paths: list[list[int]] = []
    closed_cycles: list[list[int]] = []

    for node in sorted(h_adjacency):
        if node in visited or len(h_adjacency[node]) != 1:
            continue
        sequence = [node]
        visited.add(node)
        previous: HNode | None = None
        current = node
        while True:
            neighbors = h_adjacency[current]
            candidates = [item for item in neighbors if item != previous]
            if not candidates or candidates[0] in visited:
                break
            next_node = candidates[0]
            sequence.append(next_node)
            visited.add(next_node)
            previous, current = current, next_node
            if len(h_adjacency[current]) == 1:
                break
        open_paths.append([item[0] for item in sequence])

    for node in sorted(h_adjacency):
        if node in visited:
            continue
        start = node
        sequence = [node]
        visited.add(node)
        previous = None
        current = node
        while True:
            neighbors = h_adjacency[current]
            candidates = [item for item in neighbors if item != previous]
            next_node = candidates[0]
            if next_node == start:
                break
            sequence.append(next_node)
            visited.add(next_node)
            previous, current = current, next_node
        closed_cycles.append([item[0] for item in sequence])

    return open_paths, closed_cycles


def _is_simple_chordfree_cycle(sequence: list[int], plain_adjacency: dict[int, set[int]]) -> bool:
    if len(set(sequence)) != len(sequence):
        return False
    m = len(sequence)
    for x in range(m):
        for y in range(x + 1, m):
            if y == x + 1 or (x == 0 and y == m - 1):
                continue
            if sequence[y] in plain_adjacency.get(sequence[x], ()):
                return False
    return True


def compute_ladder_parameters(rotation: Sequence[Sequence[int]]) -> dict[str, Any]:
    """Compute all embedding-based ladder structural parameters for one graph."""
    rotation = tuple(tuple(row) for row in rotation)
    faces = trace_faces(rotation)
    quad_indices = [index for index, face in enumerate(faces) if len(face) == 4]
    face_count_4 = len(quad_indices)

    edge_to_faces: dict[Edge, list[int]] = {}
    for index, face in enumerate(faces):
        for left, right in zip(face, face[1:] + face[:1]):
            edge_to_faces.setdefault(normalized_edge(left, right), []).append(index)

    quad_set = set(quad_indices)
    plain_adjacency: dict[int, set[int]] = {index: set() for index in quad_indices}
    for incident in edge_to_faces.values():
        if len(incident) == 2:
            first, second = incident
            if first in quad_set and second in quad_set:
                plain_adjacency[first].add(second)
                plain_adjacency[second].add(first)

    component_types, face_to_component = _classify_components(quad_indices, plain_adjacency)
    branch_vertex_count = sum(1 for index in quad_indices if len(plain_adjacency[index]) >= 3)
    isolated_quadrilateral_count = sum(
        1 for index in quad_indices if len(plain_adjacency[index]) == 0
    )

    slot_edges: dict[int, tuple[list[Edge], list[Edge]]] = {}
    for index in quad_indices:
        face = faces[index]
        boundary = [normalized_edge(face[k], face[(k + 1) % 4]) for k in range(4)]
        slot_edges[index] = ([boundary[0], boundary[2]], [boundary[1], boundary[3]])

    def quad_neighbor_via_edge(quad_index: int, edge: Edge) -> int | None:
        others = [other for other in edge_to_faces[edge] if other != quad_index]
        if not others:
            return None
        other = others[0]
        return other if other in quad_set else None

    def slot_of_edge(quad_index: int, edge: Edge) -> int:
        return 0 if edge in slot_edges[quad_index][0] else 1

    h_adjacency: dict[HNode, list[HNode]] = {}
    for index in quad_indices:
        for slot in (0, 1):
            neighbors: list[HNode] = []
            for edge in slot_edges[index][slot]:
                neighbor_face = quad_neighbor_via_edge(index, edge)
                if neighbor_face is not None:
                    neighbors.append((neighbor_face, slot_of_edge(neighbor_face, edge)))
            if neighbors:
                h_adjacency[(index, slot)] = neighbors

    raw_open_paths, raw_closed_cycles = _trace_h_components(h_adjacency)

    strict_ladder_strips: list[dict[str, Any]] = []
    for sequence in raw_open_paths:
        for left, right in _maximal_valid_windows(sequence, plain_adjacency):
            if right - left + 1 < 2:
                continue
            window = sequence[left : right + 1]
            strict_ladder_strips.append(
                {
                    "face_sequence": window,
                    "faces": sorted(set(window)),
                    "length": right - left + 1,
                }
            )

    closed_ladder_strip_lengths: list[int] = []
    degenerate_closed_polychord_lengths: list[int] = []
    for sequence in raw_closed_cycles:
        if _is_simple_chordfree_cycle(sequence, plain_adjacency):
            closed_ladder_strip_lengths.append(len(sequence))
        else:
            degenerate_closed_polychord_lengths.append(len(sequence))
    closed_ladder_strip_lengths.sort(reverse=True)
    degenerate_closed_polychord_lengths.sort(reverse=True)

    canonical = _canonicalize_rotation(rotation)
    vertex_map = canonical["original_to_canonical"]

    def canonical_strip_key(strip: dict[str, Any]) -> tuple[tuple[int, ...], ...]:
        forward = tuple(
            _canonical_face_key(faces[index], vertex_map) for index in strip["face_sequence"]
        )
        backward = tuple(reversed(forward))
        return min(forward, backward)

    strict_ladder_strips.sort(key=lambda strip: (-strip["length"], canonical_strip_key(strip)))
    strict_ladder_lengths_all = [strip["length"] for strip in strict_ladder_strips]

    ladder_face_coverage = len({face for strip in strict_ladder_strips for face in strip["faces"]})
    ladder_face_fraction = ladder_face_coverage / face_count_4 if face_count_4 else 0.0
    ladder_max = max(strict_ladder_lengths_all, default=0)
    ladder_strip_count = len(strict_ladder_strips)
    ladder_component_count = len(
        {
            face_to_component[face]
            for strip in strict_ladder_strips
            for face in strip["faces"]
        }
    )

    best_pair: tuple[Any, ...] | None = None
    for i in range(len(strict_ladder_strips)):
        for j in range(i + 1, len(strict_ladder_strips)):
            left_strip = strict_ladder_strips[i]
            right_strip = strict_ladder_strips[j]
            if set(left_strip["faces"]).isdisjoint(right_strip["faces"]):
                a, b = sorted((left_strip["length"], right_strip["length"]), reverse=True)
                product = (a + 2) * (b + 2)
                canonical_pair_key = tuple(
                    sorted((canonical_strip_key(left_strip), canonical_strip_key(right_strip)))
                )
                candidate = (product, a, b, canonical_pair_key)
                if best_pair is None or candidate[:3] > best_pair[:3] or (
                    candidate[:3] == best_pair[:3] and candidate[3] < best_pair[3]
                ):
                    best_pair = candidate

    if best_pair is None:
        best_disjoint_ladder_a = None
        best_disjoint_ladder_b = None
        best_pair_contains_ladder_max = None
        double_ladder_score = None
        double_ladder_score_times_2 = None
        best_disjoint_pair_exists = False
    else:
        _, best_disjoint_ladder_a, best_disjoint_ladder_b, _ = best_pair
        best_pair_contains_ladder_max = best_disjoint_ladder_a == ladder_max
        double_ladder_score_times_2 = (best_disjoint_ladder_a + 2) * (
            best_disjoint_ladder_b + 2
        ) - 1
        double_ladder_score = double_ladder_score_times_2 / 2
        best_disjoint_pair_exists = True

    return {
        "face_count_4": face_count_4,
        "quadrilateral_adjacency_component_types": component_types,
        "quadrilateral_adjacency_branch_vertex_count": branch_vertex_count,
        "isolated_quadrilateral_count": isolated_quadrilateral_count,
        "strict_ladder_strips": [
            {"face_sequence": strip["face_sequence"], "faces": strip["faces"], "length": strip["length"]}
            for strip in strict_ladder_strips
        ],
        "strict_ladder_lengths_all": strict_ladder_lengths_all,
        "closed_ladder_strip_lengths": closed_ladder_strip_lengths,
        "closed_ladder_strip_count": len(closed_ladder_strip_lengths),
        "degenerate_closed_polychord_lengths": degenerate_closed_polychord_lengths,
        "degenerate_closed_polychord_count": len(degenerate_closed_polychord_lengths),
        "ladder_face_coverage": ladder_face_coverage,
        "ladder_face_fraction": ladder_face_fraction,
        "ladder_max": ladder_max,
        "ladder_strip_count": ladder_strip_count,
        "ladder_component_count": ladder_component_count,
        "best_disjoint_pair_exists": best_disjoint_pair_exists,
        "best_disjoint_ladder_a": best_disjoint_ladder_a,
        "best_disjoint_ladder_b": best_disjoint_ladder_b,
        "best_pair_contains_ladder_max": best_pair_contains_ladder_max,
        "ladder_second_disjoint": best_disjoint_ladder_b,
        "double_ladder_score": double_ladder_score,
        "double_ladder_score_times_2": double_ladder_score_times_2,
    }
