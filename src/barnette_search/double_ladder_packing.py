"""Structural analysis of certified double-ladder packing certificates.

This module deliberately consumes existing complete Hamiltonian universes.  It
does not enumerate graphs, Hamiltonian cycles, or solve hsep.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import networkx as nx

from .double_ladder_prediction_test import (
    ConstructedGraph,
    classify_cycles,
    cycle_edges,
    load_certified_source,
    normalize_cycle,
)


BARNIE_HASH = "2f96ada16c46cd2bd038b97d5af44f46ed14522cba1edf3fa041d66e02107bcc"


@dataclass(frozen=True, order=True)
class EdgeCoordinate:
    """A label-independent edge coordinate in D(a,b)."""

    kind: str
    ladder: str | None = None
    index: int | None = None
    rail: int | None = None
    endpoints: tuple[tuple[str, int, int], tuple[str, int, int]] | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind}
        if self.ladder is not None:
            result["ladder"] = self.ladder
        if self.index is not None:
            result["index"] = self.index
        if self.rail is not None:
            result["rail"] = self.rail
        if self.endpoints is not None:
            result["model_endpoints"] = [list(item) for item in self.endpoints]
        return result

    def key(self) -> tuple[Any, ...]:
        return (self.kind, self.ladder, self.index, self.rail, self.endpoints)


@dataclass
class PackingDataset:
    label: str
    a: int
    b: int
    graph: ConstructedGraph
    cycles: tuple[tuple[int, ...], ...]
    requirements: tuple[tuple[int, int], ...]
    graph_directory: Path | None
    source_files: dict[str, Path]

    @property
    def edges(self) -> tuple[tuple[int, int], ...]:
        return self.graph.edges

    @property
    def cycle_edge_sets(self) -> tuple[frozenset[tuple[int, int]], ...]:
        return tuple(cycle_edges(cycle) for cycle in self.cycles)

    @property
    def edge_coordinates(self) -> tuple[EdgeCoordinate, ...]:
        return tuple(edge_coordinate(self.graph, edge) for edge in self.edges)

    @property
    def cycle_keys(self) -> tuple[str, ...]:
        records = classify_cycles(self.graph, self.cycles)["cycle_records"]
        return tuple(cycle_key(record) for record in records)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def edge_coordinate(graph: ConstructedGraph, edge: tuple[int, int]) -> EdgeCoordinate:
    left, right = (graph.model_by_vertex[edge[0]], graph.model_by_vertex[edge[1]])
    if left[0] == right[0] and left[1] == right[1]:
        return EdgeCoordinate("rung", left[0], left[1])
    if left[0] == right[0] and left[2] == right[2] and abs(left[1] - right[1]) == 1:
        return EdgeCoordinate("rail", left[0], min(left[1], right[1]), left[2])
    return EdgeCoordinate("connector", endpoints=tuple(sorted((left, right))))


def cycle_key(record: dict[str, Any]) -> str:
    classification = record["classification"]
    if classification == "all_rails":
        return "R"
    if classification == "paired_cell_turns":
        left, right = record["turn_cells"]
        return f"T({left},{right})"
    if classification == "two_connector_exception":
        return f"X{record['connector_bits']}"
    raise ValueError(f"unclassified Hamiltonian cycle: {record}")


def parse_turn_key(key: str) -> tuple[int, int] | None:
    if not key.startswith("T(") or not key.endswith(")"):
        return None
    left, right = key[2:-1].split(",")
    return int(left), int(right)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def _find_jsonl(path: Path, graph_hash: str) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        matches = [json.loads(line) for line in source if graph_hash in line]
    if len(matches) != 1:
        raise ValueError(f"expected one {graph_hash} record in {path}, found {len(matches)}")
    return matches[0]


def load_barnie_dataset(sequence_root: Path) -> PackingDataset:
    ladder_path = sequence_root / "ladder-analysis" / "ladder_family.json"
    graph = load_certified_source(ladder_path)
    family = _read_json(ladder_path)
    family_record = next(
        record for record in family["graphs"] if record["canonical_graph_hash"] == BARNIE_HASH
    )
    original_to_canonical = tuple(
        map(int, family_record["canonical_embedding"]["original_to_canonical"])
    )
    order_root = sequence_root / "order_36"
    graph_path = order_root / "graph_certificates.jsonl.gz"
    exact_path = order_root / "exact_certificates.jsonl.gz"
    graph_record = _find_jsonl(graph_path, BARNIE_HASH)
    exact_record = _find_jsonl(exact_path, BARNIE_HASH)
    original_edges = tuple(tuple(map(int, edge)) for edge in graph_record["edges"])
    edge_index = {edge: index for index, edge in enumerate(graph.edges)}
    cycles = tuple(
        normalize_cycle(original_to_canonical[vertex] for vertex in cycle)
        for cycle in exact_record["complete_hamiltonian_cycle_universe"]
    )
    requirements = []
    for included, excluded in exact_record["packing_requirements"]:
        source_e = original_edges[int(included)]
        source_f = original_edges[int(excluded)]
        mapped_e = tuple(sorted(original_to_canonical[vertex] for vertex in source_e))
        mapped_f = tuple(sorted(original_to_canonical[vertex] for vertex in source_f))
        requirements.append((edge_index[mapped_e], edge_index[mapped_f]))
    return PackingDataset(
        "D(9,7)",
        9,
        7,
        graph,
        cycles,
        tuple(requirements),
        None,
        {
            "graph_certificate_collection": graph_path,
            "exact_certificate_collection": exact_path,
            "ladder_family": ladder_path,
            "structural_cycle_classification": sequence_root
            / "ladder-analysis"
            / "hamiltonian_tile_states.json",
            "order_manifest": order_root / "SHA256SUMS.txt",
            "order_independent_verification": order_root / "independent_verification.json",
        },
    )


def load_prediction_dataset(root: Path, directory: str, a: int, b: int) -> PackingDataset:
    graph_directory = root / directory
    graph_record = _read_json(graph_directory / "graph.json")
    lower = _read_json(graph_directory / "lower_bound_certificate.json")
    model = {
        int(vertex): (str(value[0]), int(value[1]), int(value[2]))
        for vertex, value in graph_record["model_vertex_labels"]
    }
    graph = ConstructedGraph(
        str(graph_record["label"]),
        a,
        b,
        tuple(tuple(map(int, row)) for row in graph_record["rotation_system"]),
        str(graph_record["canonical_graph_hash"]),
        model,
    )
    universe_record = _read_gzip_json(graph_directory / "hamiltonian_cycles.json.gz")
    cycles = tuple(tuple(map(int, cycle)) for cycle in universe_record["cycles"])
    requirements = tuple(tuple(map(int, item)) for item in lower["packing_requirements"])
    names = (
        "graph.json",
        "canonical_edges.json",
        "embedding_faces.json",
        "hamiltonian_cycles.json.gz",
        "structural_cycle_classes.json",
        "lower_bound_certificate.json",
        "primal_hsep_certificate.json",
        "expansion_certificate.json",
        "independent_verification.json",
        "SHA256SUMS.txt",
    )
    return PackingDataset(
        graph.label,
        a,
        b,
        graph,
        cycles,
        requirements,
        graph_directory,
        {name: graph_directory / name for name in names},
    )


def load_chain(sequence_root: Path, prediction_root: Path) -> tuple[PackingDataset, ...]:
    return (
        load_barnie_dataset(sequence_root),
        load_prediction_dataset(prediction_root, "D_9_9", 9, 9),
        load_prediction_dataset(prediction_root, "D_11_9", 11, 9),
        load_prediction_dataset(prediction_root, "D_11_11", 11, 11),
    )


def coverage_indices(dataset: PackingDataset, requirement: tuple[int, int]) -> tuple[int, ...]:
    included, excluded = (dataset.edges[index] for index in requirement)
    return tuple(
        index
        for index, selected in enumerate(dataset.cycle_edge_sets)
        if included in selected and excluded not in selected
    )


def coverage_keys(dataset: PackingDataset, requirement: tuple[int, int]) -> tuple[str, ...]:
    keys = dataset.cycle_keys
    return tuple(keys[index] for index in coverage_indices(dataset, requirement))


def requirement_record(
    dataset: PackingDataset,
    requirement: tuple[int, int],
    *,
    ordinal: int | None = None,
    inserted_edges: set[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    included, excluded = requirement
    coordinates = dataset.edge_coordinates
    support = coverage_keys(dataset, requirement)
    inserted_edges = inserted_edges or set()

    def edge_details(index: int) -> dict[str, Any]:
        coordinate = coordinates[index]
        if coordinate.kind == "rail":
            edge_class = (
                f"{'first' if coordinate.ladder == 'A' else 'second'}-ladder-"
                f"{'upper' if coordinate.rail == 0 else 'lower'}-rail"
            )
        elif coordinate.kind == "rung":
            edge_class = f"{'first' if coordinate.ladder == 'A' else 'second'}-ladder-rung"
        else:
            edge_class = "connector/cap"
        length = dataset.a if coordinate.ladder == "A" else dataset.b
        boundary = coordinate.kind == "connector" or (
            coordinate.kind == "rung" and coordinate.index in (0, length)
        )
        return {
            "edge_index": index,
            "edge": list(dataset.edges[index]),
            "coordinate": coordinate.as_dict(),
            "edge_class": edge_class,
            "is_cap_or_boundary_edge": boundary,
            "is_inserted_gadget_edge": dataset.edges[index] in inserted_edges,
        }

    turns = [parse_turn_key(key) for key in support]
    if len(support) == 1:
        if support[0].startswith("X"):
            coverage_shape = "single_connector_exception"
        elif turns[0] is not None and (
            turns[0][0] in (0, dataset.a - 1) or turns[0][1] in (0, dataset.b - 1)
        ):
            coverage_shape = "single_boundary_turn"
        else:
            coverage_shape = "single_cycle"
    elif len(support) == 2 and all(turn is not None for turn in turns):
        first, second = turns  # type: ignore[misc]
        coverage_shape = (
            "adjacent_turn_domino"
            if abs(first[0] - second[0]) + abs(first[1] - second[1]) == 1
            else "two_turn_set"
        )
    else:
        coverage_shape = "other"
    result = {
        "included_edge_index": included,
        "excluded_edge_index": excluded,
        "included_edge": list(dataset.edges[included]),
        "excluded_edge": list(dataset.edges[excluded]),
        "included_coordinate": coordinates[included].as_dict(),
        "excluded_coordinate": coordinates[excluded].as_dict(),
        "relative_index_displacement": (
            coordinates[excluded].index - coordinates[included].index
            if coordinates[included].index is not None
            and coordinates[excluded].index is not None
            and coordinates[included].ladder == coordinates[excluded].ladder
            else None
        ),
        "parity": {
            "included_index": (
                coordinates[included].index % 2
                if coordinates[included].index is not None
                else None
            ),
            "excluded_index": (
                coordinates[excluded].index % 2
                if coordinates[excluded].index is not None
                else None
            ),
        },
        "coverage_size": len(support),
        "coverage_cycle_classes": list(support),
        "coverage_shape": coverage_shape,
        "included_edge_details": edge_details(included),
        "excluded_edge_details": edge_details(excluded),
        "touches_inserted_gadget": (
            dataset.edges[included] in inserted_edges or dataset.edges[excluded] in inserted_edges
        ),
    }
    if ordinal is not None:
        result["ordinal"] = ordinal
    return result


def packing_summary(dataset: PackingDataset, requirements: Sequence[tuple[int, int]]) -> dict[str, Any]:
    supports = [coverage_keys(dataset, requirement) for requirement in requirements]
    flat = [key for support in supports for key in support]
    turn_singletons = [
        support[0]
        for support in supports
        if len(support) == 1 and parse_turn_key(support[0]) is not None
    ]
    boundary_turns = [
        key
        for key in turn_singletons
        if (lambda pair: pair[0] in (0, dataset.a - 1) or pair[1] in (0, dataset.b - 1))(
            parse_turn_key(key)  # type: ignore[arg-type]
        )
    ]
    dominoes = []
    for support in supports:
        pairs = [parse_turn_key(key) for key in support]
        if len(pairs) == 2 and all(pair is not None for pair in pairs):
            first, second = pairs  # type: ignore[misc]
            if abs(first[0] - second[0]) + abs(first[1] - second[1]) == 1:
                dominoes.append(support)
    expected = ((dataset.a + 2) * (dataset.b + 2) - 1) // 2
    return {
        "packing_size": len(requirements),
        "formula_value": expected,
        "support_size_distribution": dict(sorted(Counter(map(len, supports)).items())),
        "coverage_sets_pairwise_disjoint": len(flat) == len(set(flat)),
        "covered_cycle_count": len(set(flat)),
        "uncovered_cycle_classes": sorted(set(dataset.cycle_keys) - set(flat)),
        "exception_singleton_count": sum(
            len(support) == 1 and support[0].startswith("X") for support in supports
        ),
        "boundary_turn_singleton_count": len(boundary_turns),
        "interior_adjacent_domino_count": len(dominoes),
        "all_doubletons_are_adjacent_turn_dominoes": len(dominoes)
        == sum(len(support) == 2 for support in supports),
    }


def coordinate_index(dataset: PackingDataset, coordinate: EdgeCoordinate) -> int:
    matches = [
        index for index, candidate in enumerate(dataset.edge_coordinates) if candidate == coordinate
    ]
    if len(matches) != 1:
        raise ValueError(f"edge coordinate {coordinate} has {len(matches)} matches in {dataset.label}")
    return matches[0]


def structural_requirement(
    dataset: PackingDataset, included: EdgeCoordinate, excluded: EdgeCoordinate
) -> tuple[int, int]:
    return coordinate_index(dataset, included), coordinate_index(dataset, excluded)


def exception_requirements(dataset: PackingDataset, anchor: str = "A") -> list[tuple[int, int]]:
    """Four singleton requirements, anchored on one unexpanded ladder."""
    length = dataset.a if anchor == "A" else dataset.b
    return [
        structural_requirement(
            dataset, EdgeCoordinate("rung", anchor, 0), EdgeCoordinate("rung", anchor, 1)
        ),
        structural_requirement(
            dataset,
            EdgeCoordinate("rung", anchor, length),
            EdgeCoordinate("rung", anchor, length - 1),
        ),
        structural_requirement(
            dataset, EdgeCoordinate("rail", anchor, 0, 0), EdgeCoordinate("rail", anchor, 0, 1)
        ),
        structural_requirement(
            dataset, EdgeCoordinate("rail", anchor, 0, 1), EdgeCoordinate("rail", anchor, 0, 0)
        ),
    ]


def boundary_requirements(dataset: PackingDataset) -> list[tuple[int, int]]:
    result = []
    # Rows i=0 and i=a-1, including all four turn-grid corners.
    for j in range(dataset.b):
        result.append(
            structural_requirement(
                dataset,
                EdgeCoordinate("rung", "A", 0),
                EdgeCoordinate("rail", "B", j, j % 2),
            )
        )
        result.append(
            structural_requirement(
                dataset,
                EdgeCoordinate("rung", "A", dataset.a),
                EdgeCoordinate("rail", "B", j, 1 - j % 2),
            )
        )
    # Columns j=0 and j=b-1, excluding corners already handled above.
    for i in range(1, dataset.a - 1):
        result.append(
            structural_requirement(
                dataset,
                EdgeCoordinate("rung", "B", 0),
                EdgeCoordinate("rail", "A", i, i % 2),
            )
        )
        result.append(
            structural_requirement(
                dataset,
                EdgeCoordinate("rung", "B", dataset.b),
                EdgeCoordinate("rail", "A", i, 1 - i % 2),
            )
        )
    return result


def far_corner_domino_requirements(dataset: PackingDataset) -> list[tuple[int, int]]:
    """Tile the interior turn grid except T(a-2,b-2)."""
    result = []
    # Pair A rows 1-2, 3-4, ... through a-3, in every interior B column.
    for rung in range(2, dataset.a - 2 + 1, 2):
        if rung > dataset.a - 3:
            break
        for j in range(1, dataset.b - 1):
            result.append(
                structural_requirement(
                    dataset,
                    EdgeCoordinate("rung", "A", rung),
                    EdgeCoordinate("rail", "B", j, 0),
                )
            )
    # Pair B columns in the final interior A row, leaving the far corner.
    final_i = dataset.a - 2
    for rung in range(2, dataset.b - 2 + 1, 2):
        if rung > dataset.b - 3:
            break
        result.append(
            structural_requirement(
                dataset,
                EdgeCoordinate("rung", "B", rung),
                EdgeCoordinate("rail", "A", final_i, 0),
            )
        )
    return result


def canonical_structural_packing(
    dataset: PackingDataset, *, anchor: str = "A"
) -> tuple[tuple[int, int], ...]:
    requirements = (
        exception_requirements(dataset, anchor)
        + boundary_requirements(dataset)
        + far_corner_domino_requirements(dataset)
    )
    if len(requirements) != len(set(requirements)):
        raise ValueError("canonical packing contains duplicate requirements")
    return tuple(requirements)


def candidate_conflict_summary(dataset: PackingDataset) -> dict[str, Any]:
    masks = []
    support_sizes: Counter[int] = Counter()
    for included in range(len(dataset.edges)):
        for excluded in range(len(dataset.edges)):
            if included == excluded:
                continue
            support = coverage_indices(dataset, (included, excluded))
            if not support:
                continue
            mask = sum(1 << index for index in support)
            masks.append(mask)
            support_sizes[len(support)] += 1
    degree = [0] * len(masks)
    conflict_edges = 0
    for left in range(len(masks)):
        for right in range(left + 1, len(masks)):
            if masks[left] & masks[right]:
                conflict_edges += 1
                degree[left] += 1
                degree[right] += 1
    return {
        "candidate_definition": "all nonempty ordered edge-pair coverage sets",
        "candidate_vertex_count": len(masks),
        "conflict_edge_count": conflict_edges,
        "support_size_distribution": dict(sorted(support_sizes.items())),
        "degree_minimum": min(degree),
        "degree_maximum": max(degree),
        "degree_mean": sum(degree) / len(degree),
        "distinct_coverage_set_count": len(set(masks)),
    }


def graph_automorphisms(dataset: PackingDataset) -> tuple[dict[int, int], ...]:
    matcher = nx.algorithms.isomorphism.GraphMatcher(dataset.graph.graph, dataset.graph.graph)
    mappings = tuple(dict(mapping) for mapping in matcher.isomorphisms_iter())
    return tuple(sorted(mappings, key=lambda item: tuple(item[index] for index in sorted(item))))


def expansion_edge_paths(
    source: PackingDataset, target: PackingDataset, certificate: dict[str, Any]
) -> dict[int, tuple[int, ...]]:
    """Map every source edge to its certified target edge or replacement path."""
    vertex_map = {int(left): int(right) for left, right in certificate["unchanged_source_to_target"]}
    deleted = {
        tuple(sorted(map(int, edge))) for edge in certificate["deleted_edges_source_labels"]
    }
    inserted_edges = {
        tuple(sorted(map(int, edge))) for edge in certificate["inserted_edges_target_labels"]
    }
    target_index = {edge: index for index, edge in enumerate(target.edges)}
    result = {}
    for edge_index, edge in enumerate(source.edges):
        mapped_endpoints = (vertex_map[edge[0]], vertex_map[edge[1]])
        if edge not in deleted:
            mapped = tuple(sorted(mapped_endpoints))
            result[edge_index] = (target_index[mapped],)
            continue
        paths = []
        for path in nx.all_simple_paths(
            target.graph.graph, mapped_endpoints[0], mapped_endpoints[1], cutoff=3
        ):
            path_edges = tuple(
                tuple(sorted((left, right))) for left, right in zip(path, path[1:])
            )
            if len(path_edges) == 3 and set(path_edges) <= inserted_edges:
                paths.append(path_edges)
        if len(paths) != 1:
            raise ValueError(f"expected one inserted length-three path for {edge}, found {paths}")
        result[edge_index] = tuple(target_index[item] for item in paths[0])
    return result


def expansion_map_record(
    source: PackingDataset, target: PackingDataset, certificate_path: Path
) -> dict[str, Any]:
    certificate = _read_json(certificate_path)
    if certificate["source_canonical_hash"] != source.graph.graph_hash:
        raise ValueError("expansion certificate source hash mismatch")
    if certificate["target_canonical_hash"] != target.graph.graph_hash:
        raise ValueError("expansion certificate target hash mismatch")
    paths = expansion_edge_paths(source, target, certificate)
    deleted_indexes = [index for index, path in paths.items() if len(path) > 1]
    path_records = []
    for index in deleted_indexes:
        path_records.append(
            {
                "source_edge_index": index,
                "source_edge": list(source.edges[index]),
                "source_coordinate": source.edge_coordinates[index].as_dict(),
                "target_path_edge_indices": list(paths[index]),
                "target_path_edges": [list(target.edges[item]) for item in paths[index]],
                "target_path_coordinates": [
                    target.edge_coordinates[item].as_dict() for item in paths[index]
                ],
            }
        )
    return {
        "source": source.label,
        "target": target.label,
        "source_hash": source.graph.graph_hash,
        "target_hash": target.graph.graph_hash,
        "selected_ladder": certificate["selected_ladder"],
        "selected_cell": certificate["selected_cell"],
        "operation": certificate["operation"],
        "unchanged_vertex_map": certificate["unchanged_source_to_target"],
        "unchanged_vertex_count": len(certificate["unchanged_source_to_target"]),
        "deleted_source_edges": certificate["deleted_edges_source_labels"],
        "inserted_target_vertices": certificate["inserted_vertices_target_labels"],
        "inserted_target_edges": certificate["inserted_edges_target_labels"],
        "source_edge_to_target_paths": [
            {
                "source_edge_index": index,
                "target_path_edge_indices": list(path),
            }
            for index, path in sorted(paths.items())
        ],
        "replacement_path_details": path_records,
        "certificate_checks": certificate["checks"],
        "certificate_path": str(certificate_path),
        "certificate_sha256": sha256_file(certificate_path),
    }


def _mapped_requirement_options(
    requirement: tuple[int, int],
    source: PackingDataset,
    target: PackingDataset,
    paths: dict[int, tuple[int, ...]],
    source_automorphism: dict[int, int],
    target_automorphism: dict[int, int],
) -> set[tuple[int, int]]:
    source_edge_index = {edge: index for index, edge in enumerate(source.edges)}
    target_edge_index = {edge: index for index, edge in enumerate(target.edges)}
    transformed = []
    for index in requirement:
        edge = source.edges[index]
        mapped_edge = tuple(sorted((source_automorphism[edge[0]], source_automorphism[edge[1]])))
        mapped_index = source_edge_index[mapped_edge]
        target_choices = []
        for target_index in paths[mapped_index]:
            target_edge = target.edges[target_index]
            final_edge = tuple(
                sorted((target_automorphism[target_edge[0]], target_automorphism[target_edge[1]]))
            )
            target_choices.append(target_edge_index[final_edge])
        transformed.append(target_choices)
    return {(left, right) for left in transformed[0] for right in transformed[1] if left != right}


def requirement_alignment(
    source: PackingDataset,
    target: PackingDataset,
    certificate_path: Path,
    *,
    source_requirements: Sequence[tuple[int, int]] | None = None,
    target_requirements: Sequence[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Exhaust exact graph-automorphism alignments of two requirement sets."""
    source_requirements = tuple(source_requirements or source.requirements)
    target_requirements = tuple(target_requirements or target.requirements)
    certificate = _read_json(certificate_path)
    paths = expansion_edge_paths(source, target, certificate)
    source_aut = graph_automorphisms(source)
    target_aut = graph_automorphisms(target)
    identity_source = {vertex: vertex for vertex in range(len(source.graph.rotation))}
    identity_target = {vertex: vertex for vertex in range(len(target.graph.rotation))}
    target_ordinals = {requirement: index for index, requirement in enumerate(target_requirements)}
    raw_source_pairs = {
        (source.edges[included], source.edges[excluded])
        for included, excluded in source_requirements
    }
    raw_target_pairs = {
        (target.edges[included], target.edges[excluded])
        for included, excluded in target_requirements
    }
    source_coordinates = source.edge_coordinates
    target_coordinates = target.edge_coordinates
    structural_source_pairs = {
        (source_coordinates[included], source_coordinates[excluded])
        for included, excluded in source_requirements
    }
    structural_target_pairs = {
        (target_coordinates[included], target_coordinates[excluded])
        for included, excluded in target_requirements
    }

    def deterministic_matching(neighbors: list[list[int]]) -> dict[int, int]:
        matched_target: dict[int, int] = {}

        def augment(source_ordinal: int, seen: set[int]) -> bool:
            for target_ordinal in neighbors[source_ordinal]:
                if target_ordinal in seen:
                    continue
                seen.add(target_ordinal)
                if target_ordinal not in matched_target or augment(
                    matched_target[target_ordinal], seen
                ):
                    matched_target[target_ordinal] = source_ordinal
                    return True
            return False

        for source_ordinal in range(len(neighbors)):
            augment(source_ordinal, set())
        return {source: target for target, source in matched_target.items()}

    def score(left: dict[int, int], right: dict[int, int]) -> tuple[int, dict[int, int]]:
        neighbors = []
        for requirement in source_requirements:
            options = _mapped_requirement_options(
                requirement, source, target, paths, left, right
            )
            neighbors.append(
                sorted(target_ordinals[option] for option in options if option in target_ordinals)
            )
        matching = deterministic_matching(neighbors)
        return len(matching), matching

    literal_score, literal_matching = score(identity_source, identity_target)
    best_score = -1
    best_matching: dict[int, int] = {}
    best_pair = (identity_source, identity_target)
    for left in source_aut:
        for right in target_aut:
            candidate_score, matching = score(left, right)
            signature = (
                tuple(left[index] for index in sorted(left)),
                tuple(right[index] for index in sorted(right)),
            )
            best_signature = (
                tuple(best_pair[0][index] for index in sorted(best_pair[0])),
                tuple(best_pair[1][index] for index in sorted(best_pair[1])),
            )
            if candidate_score > best_score or (
                candidate_score == best_score and signature < best_signature
            ):
                best_score = candidate_score
                best_matching = matching
                best_pair = (left, right)
    return {
        "source": source.label,
        "target": target.label,
        "source_requirement_count": len(source_requirements),
        "target_requirement_count": len(target_requirements),
        "source_automorphism_count": len(source_aut),
        "target_automorphism_count": len(target_aut),
        "raw_canonical_endpoint_pair_coincidence": len(raw_source_pairs & raw_target_pairs),
        "unshifted_structural_coordinate_pair_overlap": len(
            structural_source_pairs & structural_target_pairs
        ),
        "literal_path_aware_ordered_requirement_overlap": literal_score,
        "literal_source_to_target_matching": [
            [source_ordinal, literal_matching[source_ordinal]]
            for source_ordinal in sorted(literal_matching)
        ],
        "maximum_automorphism_aligned_ordered_requirement_overlap": best_score,
        "automorphism_aligned_source_to_target_matching": [
            [source_ordinal, best_matching[source_ordinal]]
            for source_ordinal in sorted(best_matching)
        ],
        "source_automorphism": [[key, best_pair[0][key]] for key in sorted(best_pair[0])],
        "target_automorphism": [[key, best_pair[1][key]] for key in sorted(best_pair[1])],
        "full_literal_nesting": literal_score == len(source_requirements),
        "full_automorphism_aligned_nesting": best_score == len(source_requirements),
        "literal_new_target_requirement_ordinals": sorted(
            set(range(len(target_requirements))) - set(literal_matching.values())
        ),
        "path_convention": (
            "an edge unaffected by insertion has one image; each deleted rail edge may be "
            "represented by any of the three edges of its certified replacement path"
        ),
        "raw_overlap_warning": (
            "raw endpoint and unshifted coordinate coincidences are reported only as requested; "
            "the certified path-aware map is the meaningful cross-graph comparison"
        ),
    }


def verify_manifest(path: Path) -> dict[str, Any]:
    root = path.parent
    missing = []
    mismatches = []
    checked = 0
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        expected, relative = raw.split(None, 1)
        relative = relative.strip().lstrip("*")
        target = root / Path(relative.replace("/", "\\"))
        if not target.is_file():
            missing.append(relative)
            continue
        actual = sha256_file(target)
        checked += 1
        if actual != expected:
            mismatches.append({"path": relative, "expected": expected, "actual": actual})
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "entries_checked": checked,
        "missing": missing,
        "mismatches": mismatches,
        "status": "pass" if not missing and not mismatches else "fail",
    }


def shifted_turn_key(key: str, axis: str) -> str:
    pair = parse_turn_key(key)
    if pair is None:
        return key
    i, j = pair
    if axis == "A" and i > 0:
        i += 2
    if axis == "B" and j > 0:
        j += 2
    return f"T({i},{j})"


def support_block(requirement_record_value: dict[str, Any]) -> frozenset[str]:
    return frozenset(requirement_record_value["coverage_cycle_classes"])


def block_alignment(
    source_records: Sequence[dict[str, Any]],
    target_records: Sequence[dict[str, Any]],
    axis: str,
) -> dict[str, Any]:
    mapped = [
        frozenset(shifted_turn_key(key, axis) for key in record["coverage_cycle_classes"])
        for record in source_records
    ]
    target = [support_block(record) for record in target_records]
    overlap = sum(block in set(target) for block in mapped)
    return {
        "mapping": "turn coordinate 0 is retained; positive coordinates shift by two",
        "mapped_source_block_count": len(mapped),
        "exact_target_coverage_block_overlap": overlap,
        "all_source_blocks_found": overlap == len(mapped),
        "missing_mapped_blocks": [sorted(block) for block in mapped if block not in set(target)],
    }


def packing_formula(a: int, b: int) -> int:
    if a % 2 != 1 or b % 2 != 1 or min(a, b) < 3:
        raise ValueError("packing formula construction requires odd a,b >= 3")
    return ((a + 2) * (b + 2) - 1) // 2
