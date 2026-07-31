"""Structural primal families for the certified double-ladder chain.

The module only reads existing complete Hamiltonian universes and certificates.
It does not enumerate graphs or cycles and does not run an hsep optimiser.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import gzip
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .double_ladder_packing import (
    BARNIE_HASH,
    EdgeCoordinate,
    PackingDataset,
    coverage_indices,
    edge_coordinate,
    expansion_edge_paths,
    graph_automorphisms,
    load_chain,
    parse_turn_key,
)
from .double_ladder_prediction_test import cycle_edges, normalize_cycle


EXCEPTION_KEYS = ("X0011", "X1100", "X0101", "X1010")


@dataclass(frozen=True)
class PrimalDataset:
    graph: PackingDataset
    primal_indices: tuple[int, ...]
    primal_source: Path

    @property
    def primal_keys(self) -> tuple[str, ...]:
        keys = self.graph.cycle_keys
        return tuple(keys[index] for index in self.primal_indices)


def _load_barnie_primal(dataset: PackingDataset, sequence_root: Path) -> tuple[int, ...]:
    ladder_family = json.loads(
        (sequence_root / "ladder-analysis" / "ladder_family.json").read_text(
            encoding="utf-8"
        )
    )
    record = next(
        item for item in ladder_family["graphs"] if item["canonical_graph_hash"] == BARNIE_HASH
    )
    original_to_canonical = tuple(
        map(int, record["canonical_embedding"]["original_to_canonical"])
    )
    exact_path = sequence_root / "order_36" / "exact_certificates.jsonl.gz"
    with gzip.open(exact_path, "rt", encoding="utf-8") as source:
        exact = next(json.loads(line) for line in source if BARNIE_HASH in line)
    universe_index = {cycle: index for index, cycle in enumerate(dataset.cycles)}
    result = []
    for cycle in exact["primal_cycles"]:
        mapped = normalize_cycle(original_to_canonical[int(vertex)] for vertex in cycle)
        result.append(universe_index[mapped])
    return tuple(result)


def load_primal_chain(
    sequence_root: Path, prediction_root: Path
) -> tuple[PrimalDataset, ...]:
    graphs = load_chain(sequence_root, prediction_root)
    result = [
        PrimalDataset(
            graphs[0],
            _load_barnie_primal(graphs[0], sequence_root),
            sequence_root / "order_36" / "exact_certificates.jsonl.gz",
        )
    ]
    for graph in graphs[1:]:
        path = graph.graph_directory / "primal_hsep_certificate.json"  # type: ignore[operator]
        record = json.loads(path.read_text(encoding="utf-8"))
        result.append(
            PrimalDataset(
                graph,
                tuple(map(int, record["primal_cycle_indices"])),
                path,
            )
        )
    return tuple(result)


def symbolic_family_keys(a: int, b: int) -> tuple[str, ...]:
    """The four exceptions, boundary turns, and odd interior parity class."""
    if a < 3 or b < 3 or a % 2 != 1 or b % 2 != 1:
        raise ValueError("symbolic primal family requires odd a,b >= 3")
    turns = [
        f"T({i},{j})"
        for i in range(a)
        for j in range(b)
        if i in (0, a - 1)
        or j in (0, b - 1)
        or (0 < i < a - 1 and 0 < j < b - 1 and (i + j) % 2 == 1)
    ]
    return (*EXCEPTION_KEYS, *turns)


def family_formula(a: int, b: int) -> int:
    if a < 3 or b < 3 or a % 2 != 1 or b % 2 != 1:
        raise ValueError("family formula requires odd a,b >= 3")
    return ((a + 2) * (b + 2) - 1) // 2


def symbolic_family_indices(dataset: PackingDataset) -> tuple[int, ...]:
    index = {key: ordinal for ordinal, key in enumerate(dataset.cycle_keys)}
    return tuple(index[key] for key in symbolic_family_keys(dataset.a, dataset.b))


def selected_signature(
    dataset: PackingDataset, selected_indices: Sequence[int], edge_index: int
) -> tuple[int, ...]:
    edge = dataset.edges[edge_index]
    return tuple(
        selected_ordinal
        for selected_ordinal, cycle_index in enumerate(selected_indices)
        if edge in cycle_edges(dataset.cycles[cycle_index])
    )


def signature_records(
    dataset: PackingDataset, selected_indices: Sequence[int]
) -> tuple[dict[str, Any], ...]:
    selected_keys = tuple(dataset.cycle_keys[index] for index in selected_indices)
    records = []
    for edge_index, edge in enumerate(dataset.edges):
        signature = selected_signature(dataset, selected_indices, edge_index)
        mask = sum(1 << index for index in signature)
        coordinate = edge_coordinate(dataset.graph, edge)
        records.append(
            {
                "edge_index": edge_index,
                "edge": list(edge),
                "coordinate": coordinate.as_dict(),
                "edge_class": edge_class(coordinate),
                "signature_indices": list(signature),
                "signature_cycle_classes": [selected_keys[index] for index in signature],
                "signature_size": len(signature),
                "signature_hex": hex(mask),
            }
        )
    return tuple(records)


def edge_class(coordinate: EdgeCoordinate) -> str:
    if coordinate.kind == "connector":
        return "connector"
    if coordinate.kind == "rung":
        return f"{coordinate.ladder}-rung"
    return f"{coordinate.ladder}-rail-{coordinate.rail}"


def antichain_analysis(
    dataset: PackingDataset, selected_indices: Sequence[int]
) -> dict[str, Any]:
    signatures = [
        frozenset(selected_signature(dataset, selected_indices, edge_index))
        for edge_index in range(len(dataset.edges))
    ]
    equality_failures = []
    containment_failures = []
    witnesses = []
    selected_keys = tuple(dataset.cycle_keys[index] for index in selected_indices)
    for left in range(len(signatures)):
        for right in range(left + 1, len(signatures)):
            if signatures[left] == signatures[right]:
                equality_failures.append([left, right])
            if signatures[left] <= signatures[right] or signatures[right] <= signatures[left]:
                containment_failures.append([left, right])
            left_witness = min(signatures[left] - signatures[right], default=None)
            right_witness = min(signatures[right] - signatures[left], default=None)
            witnesses.append(
                {
                    "left_edge_index": left,
                    "right_edge_index": right,
                    "left_not_right_cycle_ordinal": left_witness,
                    "left_not_right_cycle_class": (
                        selected_keys[left_witness] if left_witness is not None else None
                    ),
                    "right_not_left_cycle_ordinal": right_witness,
                    "right_not_left_cycle_class": (
                        selected_keys[right_witness] if right_witness is not None else None
                    ),
                }
            )
    ordered_covered = sum(
        bool(signatures[left] - signatures[right])
        for left in range(len(signatures))
        for right in range(len(signatures))
        if left != right
    )
    return {
        "edge_count": len(dataset.edges),
        "selected_cycle_count": len(selected_indices),
        "ordered_edge_pair_requirement_count": len(dataset.edges) * (len(dataset.edges) - 1),
        "ordered_requirements_covered": ordered_covered,
        "distinct_signature_count": len(set(signatures)),
        "all_signatures_distinct": not equality_failures,
        "signatures_form_antichain": not containment_failures,
        "equality_failures": equality_failures,
        "containment_failures": containment_failures,
        "signature_size_distribution": dict(sorted(Counter(map(len, signatures)).items())),
        "pair_witnesses": witnesses,
    }


def symbolic_edge_incidence(
    edge: tuple[Any, ...], cycle_key: str, a: int, b: int
) -> bool:
    """Closed incidence formulas used by the general proof and tests.

    Edges are ``(L,'rail',cell,side)``, ``(L,'rung',boundary)``, or
    ``('C',index)``.
    """
    turn = parse_turn_key(cycle_key)
    if turn is not None:
        i, j = turn
        if edge[0] == "C":
            return True
        coordinate = i if edge[0] == "A" else j
        if edge[1] == "rail":
            return coordinate != edge[2]
        return coordinate in (edge[2] - 1, edge[2])
    if cycle_key not in EXCEPTION_KEYS:
        raise ValueError(f"unsupported selected cycle class {cycle_key}")
    if edge[0] == "C":
        return cycle_key[1:][int(edge[1])] == "1"
    ladder, kind = edge[:2]
    if cycle_key == "X0011":
        if ladder == "A":
            return kind == "rail" or (kind == "rung" and edge[2] == 0)
        return kind == "rung" or (
            kind == "rail" and int(edge[3]) == int(edge[2]) % 2
        )
    if cycle_key == "X1100":
        if ladder == "A":
            return kind == "rail" or (kind == "rung" and edge[2] == a)
        return kind == "rung" or (
            kind == "rail" and int(edge[3]) != int(edge[2]) % 2
        )
    if cycle_key == "X0101":
        if ladder == "A":
            return kind == "rung" or (
                kind == "rail" and int(edge[3]) == int(edge[2]) % 2
            )
        return kind == "rail" or (kind == "rung" and edge[2] == 0)
    if ladder == "A":  # X1010
        return kind == "rung" or (
            kind == "rail" and int(edge[3]) != int(edge[2]) % 2
        )
    return kind == "rail" or (kind == "rung" and edge[2] == b)


def symbolic_edges(a: int, b: int) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        [("A", "rail", cell, side) for cell in range(a) for side in (0, 1)]
        + [("A", "rung", boundary) for boundary in range(a + 1)]
        + [("B", "rail", cell, side) for cell in range(b) for side in (0, 1)]
        + [("B", "rung", boundary) for boundary in range(b + 1)]
        + [("C", index) for index in range(4)]
    )


def symbolic_antichain_check(a: int, b: int) -> dict[str, Any]:
    family = symbolic_family_keys(a, b)
    signatures = {
        edge: frozenset(
            index
            for index, cycle_key in enumerate(family)
            if symbolic_edge_incidence(edge, cycle_key, a, b)
        )
        for edge in symbolic_edges(a, b)
    }
    failures = []
    items = tuple(signatures)
    for left_index, left in enumerate(items):
        for right in items[left_index + 1 :]:
            if signatures[left] <= signatures[right] or signatures[right] <= signatures[left]:
                failures.append([list(left), list(right)])
    return {
        "a": a,
        "b": b,
        "family_size": len(family),
        "formula_value": family_formula(a, b),
        "edge_count": len(items),
        "distinct_signature_count": len(set(signatures.values())),
        "antichain": not failures,
        "failures": failures,
    }


def injected_cycle_key(key: str, axis: str) -> str:
    turn = parse_turn_key(key)
    if turn is None:
        return key
    i, j = turn
    if axis == "A" and i > 0:
        i += 2
    if axis == "B" and j > 0:
        j += 2
    return f"T({i},{j})"


def structural_lift(source: PrimalDataset, target: PrimalDataset, axis: str) -> dict[str, Any]:
    source_keys = set(source.primal_keys)
    target_keys = set(target.primal_keys)
    mapped = {injected_cycle_key(key, axis) for key in source_keys}
    new = sorted(target_keys - mapped)
    missing = sorted(mapped - target_keys)
    return {
        "axis": axis,
        "source_family_size": len(source_keys),
        "target_family_size": len(target_keys),
        "mapped_source_class_count": len(mapped),
        "mapped_source_classes_missing_from_target": missing,
        "new_target_cycle_classes": new,
        "new_target_cycle_count": len(new),
        "expected_increment": source.graph.a + 2 if axis == "B" else source.graph.b + 2,
        "full_structural_nesting": not missing and len(mapped) == len(source_keys),
    }


def direct_cycle_lift_map(
    source: PrimalDataset,
    target: PrimalDataset,
    certificate_path: Path,
    source_automorphism: dict[int, int] | None = None,
    target_automorphism: dict[int, int] | None = None,
) -> dict[int, int]:
    """Map cycles that survive by literal replacement of selected source edges."""
    source_graph = source.graph
    target_graph = target.graph
    paths = expansion_edge_paths(
        source_graph, target_graph, json.loads(certificate_path.read_text(encoding="utf-8"))
    )
    source_automorphism = source_automorphism or {
        vertex: vertex for vertex in range(len(source_graph.graph.rotation))
    }
    target_automorphism = target_automorphism or {
        vertex: vertex for vertex in range(len(target_graph.graph.rotation))
    }
    source_edge_index = {edge: index for index, edge in enumerate(source_graph.edges)}
    target_edge_index = {edge: index for index, edge in enumerate(target_graph.edges)}
    target_cycle_index = {
        frozenset(cycle_edges(cycle)): index for index, cycle in enumerate(target_graph.cycles)
    }
    result = {}
    for cycle_index in source.primal_indices:
        selected_target_edges = set()
        for edge in cycle_edges(source_graph.cycles[cycle_index]):
            transformed = tuple(
                sorted((source_automorphism[edge[0]], source_automorphism[edge[1]]))
            )
            transformed_index = source_edge_index[transformed]
            for target_index in paths[transformed_index]:
                target_edge = target_graph.edges[target_index]
                final_edge = tuple(
                    sorted(
                        (
                            target_automorphism[target_edge[0]],
                            target_automorphism[target_edge[1]],
                        )
                    )
                )
                selected_target_edges.add(target_edge_index[final_edge])
        edge_key = frozenset(target_graph.edges[index] for index in selected_target_edges)
        if edge_key in target_cycle_index:
            result[cycle_index] = target_cycle_index[edge_key]
    return result


def primal_alignment(
    source: PrimalDataset, target: PrimalDataset, certificate_path: Path
) -> dict[str, Any]:
    target_selected = set(target.primal_indices)
    literal = direct_cycle_lift_map(source, target, certificate_path)
    literal_hits = {
        source_index: target_index
        for source_index, target_index in literal.items()
        if target_index in target_selected
    }
    source_automorphisms = graph_automorphisms(source.graph)
    target_automorphisms = graph_automorphisms(target.graph)
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    paths = expansion_edge_paths(source.graph, target.graph, certificate)
    source_edge_index = {edge: index for index, edge in enumerate(source.graph.edges)}
    target_edge_index = {edge: index for index, edge in enumerate(target.graph.edges)}
    source_cycle_edges = {
        cycle_index: tuple(
            source_edge_index[edge] for edge in cycle_edges(source.graph.cycles[cycle_index])
        )
        for cycle_index in source.primal_indices
    }
    target_cycle_index = {
        frozenset(target_edge_index[edge] for edge in cycle_edges(cycle)): index
        for index, cycle in enumerate(target.graph.cycles)
    }
    source_edge_permutations = []
    for automorphism in source_automorphisms:
        source_edge_permutations.append(
            tuple(
                source_edge_index[
                    tuple(sorted((automorphism[edge[0]], automorphism[edge[1]])))
                ]
                for edge in source.graph.edges
            )
        )
    target_edge_permutations = []
    for automorphism in target_automorphisms:
        target_edge_permutations.append(
            tuple(
                target_edge_index[
                    tuple(sorted((automorphism[edge[0]], automorphism[edge[1]])))
                ]
                for edge in target.graph.edges
            )
        )
    best: dict[int, int] = {}
    best_pair = (source_automorphisms[0], target_automorphisms[0])
    for source_ordinal, left in enumerate(source_automorphisms):
        source_permutation = source_edge_permutations[source_ordinal]
        for target_ordinal, right in enumerate(target_automorphisms):
            target_permutation = target_edge_permutations[target_ordinal]
            hits = {}
            for cycle_index, selected_edges in source_cycle_edges.items():
                mapped = frozenset(
                    target_permutation[target_edge]
                    for source_edge in selected_edges
                    for target_edge in paths[source_permutation[source_edge]]
                )
                target_cycle = target_cycle_index.get(mapped)
                if target_cycle is not None and target_cycle in target_selected:
                    hits[cycle_index] = target_cycle
            signature = (
                tuple(left[index] for index in sorted(left)),
                tuple(right[index] for index in sorted(right)),
            )
            best_signature = (
                tuple(best_pair[0][index] for index in sorted(best_pair[0])),
                tuple(best_pair[1][index] for index in sorted(best_pair[1])),
            )
            if len(hits) > len(best) or (len(hits) == len(best) and signature < best_signature):
                best = hits
                best_pair = (left, right)
    return {
        "source": source.graph.label,
        "target": target.graph.label,
        "literal_raw_vertex_sequence_overlap": 0,
        "literal_direct_geometric_lift_count": len(literal_hits),
        "literal_direct_lifts": [
            {
                "source_cycle_index": left,
                "source_cycle_class": source.graph.cycle_keys[left],
                "target_cycle_index": right,
                "target_cycle_class": target.graph.cycle_keys[right],
            }
            for left, right in sorted(literal_hits.items())
        ],
        "source_automorphism_count": len(source_automorphisms),
        "target_automorphism_count": len(target_automorphisms),
        "maximum_automorphism_aligned_direct_lift_count": len(best),
        "best_source_automorphism": [[key, best_pair[0][key]] for key in sorted(best_pair[0])],
        "best_target_automorphism": [[key, best_pair[1][key]] for key in sorted(best_pair[1])],
    }


def normalize_primal(dataset: PrimalDataset) -> dict[str, Any]:
    symbolic = symbolic_family_indices(dataset.graph)
    selected = set(dataset.primal_indices)
    symbolic_set = set(symbolic)
    records = []
    for ordinal, cycle_index in enumerate(dataset.primal_indices):
        key = dataset.graph.cycle_keys[cycle_index]
        turn = parse_turn_key(key)
        records.append(
            {
                "ordinal": ordinal,
                "cycle_index": cycle_index,
                "cycle_class": key,
                "kind": (
                    "connector_exception"
                    if key.startswith("X")
                    else "boundary_turn"
                    if turn is not None
                    and (
                        turn[0] in (0, dataset.graph.a - 1)
                        or turn[1] in (0, dataset.graph.b - 1)
                    )
                    else "odd_interior_turn"
                ),
                "turn_coordinates": list(turn) if turn is not None else None,
                "turn_parity": sum(turn) % 2 if turn is not None else None,
                "normalized_cycle": list(dataset.graph.cycles[cycle_index]),
            }
        )
    return {
        "label": dataset.graph.label,
        "canonical_graph_hash": dataset.graph.graph.graph_hash,
        "parameters": {"a": dataset.graph.a, "b": dataset.graph.b},
        "primal_source": str(dataset.primal_source),
        "primal_size": len(dataset.primal_indices),
        "formula_value": family_formula(dataset.graph.a, dataset.graph.b),
        "selected_cycle_class_distribution": dict(
            sorted(Counter(record["kind"] for record in records).items())
        ),
        "exactly_equals_symbolic_family": selected == symbolic_set,
        "missing_symbolic_cycle_classes": sorted(
            dataset.graph.cycle_keys[index] for index in symbolic_set - selected
        ),
        "extra_original_cycle_classes": sorted(
            dataset.graph.cycle_keys[index] for index in selected - symbolic_set
        ),
        "cycles": records,
    }
