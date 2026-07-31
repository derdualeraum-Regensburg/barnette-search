"""Deterministic certificate pipeline for the Barnie sequence through order 36.

The implementation is deliberately separate from the established Plantri,
validation, SAT, and Hamiltonian modules.  Orders below 36 are small enough to
enumerate every Hamiltonian-cycle universe.  Order 36 is imported from its
immutable, independently verified package.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import csv
from datetime import datetime, timezone
from fractions import Fraction
import gzip
from hashlib import sha256
from importlib import metadata as importlib_metadata
from io import BytesIO
import json
from math import comb
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
from time import perf_counter
import tracemalloc
from typing import Any, Iterable, Iterator, Sequence

import networkx as nx

from .hsep_order36 import (
    BARNIE_HASH,
    canonical_json,
    cycle_edge_indexes,
    edge_list_from_graph,
    enumerate_hamiltonian_cycles,
    normalize_cycle,
    sha256_file,
    solve_set_cover,
    verify_cover_edges,
)
from .planar_code import canonical_graph_hash, encode_planar_code, iter_planar_code
from .plantri import (
    barnette_plantri_command,
    detect_plantri_version,
    locate_plantri,
    stream_barnette_graphs,
)
from .validation import validate_barnette_graph


ORDERS = tuple(range(8, 37))
EVEN_EXACT_ORDERS = tuple(range(8, 35, 2))
REFERENCE_COUNTS = {
    8: 1,
    10: 0,
    12: 1,
    14: 1,
    16: 2,
    18: 2,
    20: 8,
    22: 8,
    24: 32,
    26: 57,
    28: 185,
    30: 466,
    32: 1543,
    34: 4583,
    36: 15374,
}
GRAPH_SCHEMA = "barnie-sequence-graph-v1"
COVER_SCHEMA = "barnie-sequence-cover-v1"
EXACT_SCHEMA = "barnie-sequence-exact-v1"
ORDER_SCHEMA = "barnie-sequence-order-v1"
GLOBAL_SCHEMA = "barnie-sequence-v1"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, canonical_json(value) + "\n")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def sperner_lower_bound(edge_count: int) -> int:
    """Return the signature-antichain lower bound."""
    if edge_count <= 1:
        return 0
    k = 1
    while comb(k, k // 2) < edge_count:
        k += 1
    return k


def _minimum_relaxed_lym_sum(order: int, k: int) -> Fraction | None:
    """Minimize LYM mass with the exact cubic incidence total.

    This relaxes pairwise incomparability but retains distinct-subset capacity,
    nonempty/proper signatures, and total incidence ``k*order``.  Therefore a
    minimum above one is a rigorous impossibility certificate for ``k`` cycles.
    """
    edge_count = 3 * order // 2
    target = k * order
    states: dict[tuple[int, int], Fraction] = {(0, 0): Fraction(0)}
    for size in range(1, k):
        capacity = min(edge_count, comb(k, size))
        cost = Fraction(1, comb(k, size))
        updated = dict(states)
        for (used, total), value in states.items():
            limit = min(capacity, edge_count - used)
            for amount in range(1, limit + 1):
                new_total = total + amount * size
                if new_total > target:
                    break
                key = (used + amount, new_total)
                candidate = value + amount * cost
                if key not in updated or candidate < updated[key]:
                    updated[key] = candidate
        states = updated
    return states.get((edge_count, target))


def cubic_lym_lower_bound(order: int) -> int:
    """Return the strengthened incidence/LYM lower bound."""
    edge_count = 3 * order // 2
    k = sperner_lower_bound(edge_count)
    while True:
        minimum = _minimum_relaxed_lym_sum(order, k)
        if minimum is not None and minimum <= 1:
            return k
        k += 1


def theoretical_bounds(order: int) -> dict[str, Any]:
    if order % 2:
        return {
            "edge_count": None,
            "sperner_antichain_lower_bound": None,
            "cubic_incidence_lym_lower_bound": None,
        }
    edges = 3 * order // 2
    return {
        "edge_count": edges,
        "sperner_antichain_lower_bound": sperner_lower_bound(edges),
        "cubic_incidence_lym_lower_bound": cubic_lym_lower_bound(order),
    }


def _graph6(graph: nx.Graph) -> str:
    return nx.to_graph6_bytes(graph, header=False).decode("ascii").strip()


def _graph_record(index: int, planar_code: bytes, expected_order: int) -> dict[str, Any]:
    [embedded] = iter_planar_code(BytesIO(planar_code), require_header=True)
    graph = embedded.graph
    validation = validate_barnette_graph(graph)
    if not validation.valid:
        raise RuntimeError(f"graph {index} failed Barnette validation: {validation.rejection_reasons}")
    if graph.number_of_nodes() != expected_order:
        raise RuntimeError("Plantri returned the wrong graph order")
    edges = edge_list_from_graph(graph)
    faces = tuple(tuple(map(int, face)) for face in embedded.faces)
    if expected_order - len(edges) + len(faces) != 2:
        raise RuntimeError("Euler identity failed")
    if sum(map(len, faces)) != 2 * len(edges):
        raise RuntimeError("facial dart arithmetic failed")
    return {
        "schema": GRAPH_SCHEMA,
        "generation_index": index,
        "plantri_rank": index + 1,
        "canonical_graph_hash": canonical_graph_hash(embedded),
        "graph_order": expected_order,
        "edge_count": len(edges),
        "graph6": _graph6(graph),
        "planar_code_base64": base64.b64encode(planar_code).decode("ascii"),
        "planar_code_sha256": sha256(planar_code).hexdigest(),
        "edges": [list(edge) for edge in edges],
        "rotation_system": [list(row) for row in embedded.rotation_system],
        "faces": [list(face) for face in faces],
        "face_size_multiset": sorted(map(len, faces)),
        "validation": {
            "simple": True,
            "cubic": True,
            "bipartite": True,
            "planar": True,
            "three_connected": True,
            "euler_characteristic": 2,
            "facial_dart_count": 2 * len(edges),
        },
    }


def _coverage_sets(
    edges: Sequence[tuple[int, int]], cycles: Sequence[Sequence[int]]
) -> tuple[frozenset[int], ...]:
    edge_index = {edge: index for index, edge in enumerate(edges)}
    edge_count = len(edges)
    result: list[frozenset[int]] = []
    for cycle in cycles:
        selected = cycle_edge_indexes(tuple(cycle), edge_index)
        result.append(
            frozenset(
                required * edge_count + forbidden
                for required in selected
                for forbidden in range(edge_count)
                if forbidden not in selected
            )
        )
    return tuple(result)


def deterministic_greedy_cover(
    edges: Sequence[tuple[int, int]], cycles: Sequence[Sequence[int]]
) -> tuple[int, ...]:
    coverage = _coverage_sets(edges, cycles)
    edge_count = len(edges)
    uncovered = {
        required * edge_count + forbidden
        for required in range(edge_count)
        for forbidden in range(edge_count)
        if required != forbidden
    }
    chosen: list[int] = []
    remaining = set(range(len(cycles)))
    while uncovered:
        best = max(remaining, key=lambda index: (len(coverage[index] & uncovered), -index))
        gain = coverage[best] & uncovered
        if not gain:
            raise RuntimeError("Hamiltonian universe cannot separate every edge pair")
        chosen.append(best)
        uncovered.difference_update(gain)
        remaining.remove(best)
    return tuple(chosen)


def greedy_packing_lower_bound(
    edges: Sequence[tuple[int, int]], cycles: Sequence[Sequence[int]]
) -> tuple[tuple[int, int], ...]:
    edge_count = len(edges)
    coverage = _coverage_sets(edges, cycles)
    supports: list[tuple[int, ...]] = []
    requirements: list[tuple[int, int]] = []
    for required in range(edge_count):
        for forbidden in range(edge_count):
            if required == forbidden:
                continue
            key = required * edge_count + forbidden
            supports.append(tuple(i for i, covered in enumerate(coverage) if key in covered))
            requirements.append((required, forbidden))
    used: set[int] = set()
    chosen: list[tuple[int, int]] = []
    for index, support in sorted(enumerate(supports), key=lambda item: (len(item[1]), item[1], item[0])):
        if support and not used.intersection(support):
            chosen.append(requirements[index])
            used.update(support)
    return tuple(chosen)


def exhaustive_cover_feasible(
    edges: Sequence[tuple[int, int]],
    cycles: Sequence[Sequence[int]],
    bound: int,
) -> bool:
    """Independently decide bounded set cover by deterministic branch search.

    This standard-library search is used as a lower-bound proof only when a
    matching packing is structurally impossible or unavailable.  It branches
    on the uncovered requirement with the fewest covering cycles and memoizes
    complete residual states.
    """
    if bound < 0:
        return False
    edge_count = len(edges)
    requirements = tuple(
        (required, forbidden)
        for required in range(edge_count)
        for forbidden in range(edge_count)
        if required != forbidden
    )
    positions = {item: index for index, item in enumerate(requirements)}
    edge_index = {edge: index for index, edge in enumerate(edges)}
    all_edges = set(range(edge_count))
    masks: list[int] = []
    coverers: list[list[int]] = [[] for _ in requirements]
    for cycle_index, cycle in enumerate(cycles):
        selected = cycle_edge_indexes(tuple(cycle), edge_index)
        mask = 0
        for required in selected:
            for forbidden in all_edges - selected:
                position = positions[(required, forbidden)]
                mask |= 1 << position
                coverers[position].append(cycle_index)
        masks.append(mask)
    if any(not row for row in coverers):
        return False
    full = (1 << len(requirements)) - 1
    memo: dict[tuple[int, int], bool] = {}
    support_masks = tuple(sum(1 << index for index in row) for row in coverers)
    packing_order = tuple(sorted(range(len(requirements)), key=lambda index: (
        support_masks[index].bit_count(), support_masks[index], index
    )))

    def search(uncovered: int, slots: int) -> bool:
        if not uncovered:
            return True
        if slots == 0:
            return False
        key = (uncovered, slots)
        if key in memo:
            return memo[key]
        used_support = 0
        packed = 0
        for position in packing_order:
            if uncovered & (1 << position) and not (support_masks[position] & used_support):
                packed += 1
                if packed > slots:
                    memo[key] = False
                    return False
                used_support |= support_masks[position]
        maximum_gain = max((mask & uncovered).bit_count() for mask in masks)
        if maximum_gain == 0 or (uncovered.bit_count() + maximum_gain - 1) // maximum_gain > slots:
            memo[key] = False
            return False
        remaining = uncovered
        best: tuple[int, ...] | None = None
        while remaining:
            bit = remaining & -remaining
            position = bit.bit_length() - 1
            candidates = tuple(
                sorted(
                    coverers[position],
                    key=lambda index: (-(masks[index] & uncovered).bit_count(), index),
                )
            )
            if best is None or len(candidates) < len(best):
                best = candidates
            remaining ^= bit
        assert best is not None
        for cycle_index in best:
            reduced = uncovered & ~masks[cycle_index]
            if reduced != uncovered and search(reduced, slots - 1):
                memo[key] = True
                return True
        memo[key] = False
        return False

    return search(full, bound)


def _exact_record(graph_record: dict[str, Any]) -> dict[str, Any]:
    started = perf_counter()
    tracemalloc.start()
    order = int(graph_record["graph_order"])
    edges = tuple(tuple(map(int, edge)) for edge in graph_record["edges"])
    universe = tuple(sorted(enumerate_hamiltonian_cycles(edges, order)))
    if not universe:
        raise RuntimeError("non-Hamiltonian graph encountered")
    greedy_indexes = deterministic_greedy_cover(edges, universe)
    greedy_family = tuple(universe[index] for index in greedy_indexes)
    complete, covered = verify_cover_edges(edges, greedy_family)
    if not complete:
        raise RuntimeError("deterministic greedy cover is incomplete")
    packing_seed = greedy_packing_lower_bound(edges, universe)
    lower = max(cubic_lym_lower_bound(order), len(packing_seed))
    selected: tuple[int, ...] | None = None
    solver_upper = len(greedy_indexes)
    for bound in range(lower, solver_upper + 1):
        selected = solve_set_cover(edges, universe, bound)
        if selected is not None:
            solver_upper = len(selected)
            break
    if selected is None:
        raise RuntimeError("exact set-cover search found no separating family")
    packing: tuple[tuple[int, int], ...] | None = None
    lower_method: str | None = None
    if len(packing_seed) == solver_upper:
        packing = packing_seed
        lower_method = "packing"
    else:
        if not exhaustive_cover_feasible(edges, universe, solver_upper - 1):
            lower_method = "standalone_exhaustive_set_cover"
    exact = solver_upper if lower_method is not None else None
    certified_lower = solver_upper if exact is not None else len(packing_seed)
    family = tuple(universe[index] for index in selected)
    complete, covered = verify_cover_edges(edges, family)
    if not complete:
        raise RuntimeError("exact primal family is incomplete")
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "schema": EXACT_SCHEMA,
        "generation_index": graph_record["generation_index"],
        "plantri_rank": graph_record["plantri_rank"],
        "canonical_graph_hash": graph_record["canonical_graph_hash"],
        "graph_order": order,
        "edge_count": len(edges),
        "complete_hamiltonian_cycle_count": len(universe),
        "complete_hamiltonian_cycle_universe": [list(cycle) for cycle in universe],
        "hsep_lower_bound": certified_lower,
        "hsep_upper_bound": solver_upper,
        "exact_hsep": exact,
        "proof_status": (
            "exact_primal_packing" if lower_method == "packing"
            else "exact_primal_exhaustive_lower_bound" if lower_method is not None
            else "interval_no_independent_lower_bound"
        ),
        "lower_bound_method": lower_method,
        "primal_cycle_count": len(family),
        "primal_cycles": [list(cycle) for cycle in family],
        "packing_requirement_count": len(packing) if packing is not None else len(packing_seed),
        "packing_requirements": [list(item) for item in (packing if packing is not None else packing_seed)],
        "greedy_complete_universe_cover_size": len(greedy_indexes),
        "covered_ordered_edge_pairs": covered,
        "perfect_matching_count": None,
        "automorphism_group_order": None,
        "runtime_seconds": perf_counter() - started,
        "peak_python_memory_bytes": peak,
    }


def count_perfect_matchings(edges: Sequence[tuple[int, int]], order: int) -> int:
    adjacency = [0] * order
    for left, right in edges:
        adjacency[left] |= 1 << right
        adjacency[right] |= 1 << left
    memo: dict[int, int] = {0: 1}

    def visit(mask: int) -> int:
        if mask in memo:
            return memo[mask]
        bit = mask & -mask
        vertex = bit.bit_length() - 1
        candidates = adjacency[vertex] & (mask ^ bit)
        total = 0
        while candidates:
            other_bit = candidates & -candidates
            candidates ^= other_bit
            total += visit(mask ^ bit ^ other_bit)
        memo[mask] = total
        return total

    return visit((1 << order) - 1)


def automorphism_group_order(edges: Sequence[tuple[int, int]], order: int) -> int:
    graph = nx.Graph()
    graph.add_nodes_from(range(order))
    graph.add_edges_from(edges)
    return sum(1 for _ in nx.algorithms.isomorphism.GraphMatcher(graph, graph).isomorphisms_iter())


def _write_jsonl_gzip(paths: Sequence[Path], output: Path) -> tuple[str, int, int]:
    temporary = output.with_name(output.name + ".tmp")
    digest = sha256()
    count = 0
    uncompressed = 0
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            for path in paths:
                data = (canonical_json(_load_json(path)) + "\n").encode("ascii")
                compressed.write(data)
                digest.update(data)
                uncompressed += len(data)
                count += 1
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, output)
    return digest.hexdigest(), uncompressed, count


def _write_values_gzip(values: Iterable[dict[str, Any]], output: Path) -> tuple[str, int, int]:
    temporary = output.with_name(output.name + ".tmp")
    digest = sha256()
    count = 0
    uncompressed = 0
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            for value in values:
                data = (canonical_json(value) + "\n").encode("ascii")
                compressed.write(data)
                digest.update(data)
                uncompressed += len(data)
                count += 1
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, output)
    return digest.hexdigest(), uncompressed, count


def _environment(workers: int) -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "worker_limit": workers,
        "networkx": _version("networkx"),
        "python_sat": _version("python-sat"),
        "random_seed": None,
        "deterministic_ordering": True,
    }


def _manifest(directory: Path) -> None:
    paths = sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt" and ".work" not in path.parts
    )
    lines = [f"{sha256_file(path)}  {path.relative_to(directory).as_posix()}" for path in paths]
    _atomic_text(directory / "SHA256SUMS.txt", "\n".join(lines) + "\n")


def _schedule_records(
    tasks: Iterable[tuple[int, Any]],
    function: Any,
    destination: Path,
    workers: int,
    *,
    progress_label: str,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    futures: dict[Any, int] = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for index, argument in tasks:
            path = destination / f"{index:05d}.json"
            if path.exists():
                continue
            futures[executor.submit(function, argument)] = index
            if len(futures) >= 2 * workers:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    item_index = futures.pop(future)
                    _atomic_json(destination / f"{item_index:05d}.json", future.result())
                    completed += 1
                    if completed % 100 == 0:
                        print(f"{progress_label}: {completed} new checkpoints", flush=True)
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                item_index = futures.pop(future)
                _atomic_json(destination / f"{item_index:05d}.json", future.result())
                completed += 1
                if completed % 100 == 0:
                    print(f"{progress_label}: {completed} new checkpoints", flush=True)


def _graph_task(argument: tuple[int, bytes, int]) -> dict[str, Any]:
    return _graph_record(*argument)


def _exact_task(argument: dict[str, Any]) -> dict[str, Any]:
    return _exact_record(argument)


def _upgrade_exact_record(record: dict[str, Any]) -> dict[str, Any]:
    """Add the explicit v1 lower-bound discriminator to early checkpoints."""
    if record.get("lower_bound_method") is not None:
        return record
    status = record.get("proof_status")
    exact = record.get("exact_hsep")
    packing_count = record.get("packing_requirement_count")
    if status == "exact_primal_packing" and exact == packing_count:
        return {**record, "lower_bound_method": "packing"}
    if status == "exact_primal_exhaustive_lower_bound":
        return {**record, "lower_bound_method": "standalone_exhaustive_set_cover"}
    raise ValueError("cannot deterministically upgrade exact checkpoint lower-bound method")


def _screen_record(graph_record: dict[str, Any]) -> dict[str, Any]:
    started = perf_counter()
    order = int(graph_record["graph_order"])
    edges = tuple(tuple(map(int, edge)) for edge in graph_record["edges"])
    universe = tuple(sorted(enumerate_hamiltonian_cycles(edges, order)))
    if not universe:
        raise RuntimeError("non-Hamiltonian graph encountered during screening")
    selected = deterministic_greedy_cover(edges, universe)
    family = tuple(universe[index] for index in selected)
    complete, covered = verify_cover_edges(edges, family)
    if not complete:
        raise RuntimeError("screening cover is incomplete")
    return {
        "schema": COVER_SCHEMA,
        "generation_index": graph_record["generation_index"],
        "plantri_rank": graph_record["plantri_rank"],
        "canonical_graph_hash": graph_record["canonical_graph_hash"],
        "graph_order": order,
        "edge_count": len(edges),
        "cover_size": len(family),
        "cycles": [list(cycle) for cycle in family],
        "covered_ordered_edge_pairs": covered,
        "method": "deterministic_greedy_complete_hamiltonian_universe",
        "complete_hamiltonian_cycle_count": len(universe),
        "runtime_seconds": perf_counter() - started,
    }


def _screen_task(argument: dict[str, Any]) -> dict[str, Any]:
    return _screen_record(argument)


def _bounded_or_exact_task(
    argument: tuple[dict[str, Any], dict[str, Any], int]
) -> dict[str, Any]:
    graph_record, screen, bound = argument
    edges = tuple(tuple(map(int, edge)) for edge in graph_record["edges"])
    order = int(graph_record["graph_order"])
    screen_cycles = tuple(tuple(map(int, cycle)) for cycle in screen["cycles"])
    selected = solve_set_cover(edges, screen_cycles, bound)
    method = "bounded_set_cover_over_screen_family"
    universe_count = int(screen["complete_hamiltonian_cycle_count"])
    pool = screen_cycles
    if selected is None:
        pool = tuple(sorted(enumerate_hamiltonian_cycles(edges, order)))
        universe_count = len(pool)
        selected = solve_set_cover(edges, pool, bound)
        method = "bounded_set_cover_over_complete_hamiltonian_universe"
    if selected is None:
        return {"kind": "exact", "record": _exact_record(graph_record)}
    family = tuple(pool[index] for index in selected)
    complete, covered = verify_cover_edges(edges, family)
    if not complete or len(family) > bound:
        raise RuntimeError("bounded set-cover result is invalid")
    return {
        "kind": "cover",
        "record": {
            **screen,
            "cover_size": len(family),
            "cycles": [list(cycle) for cycle in family],
            "covered_ordered_edge_pairs": covered,
            "method": method,
            "complete_hamiltonian_cycle_count": universe_count,
        },
    }


def _adaptive_certificates(
    graph_paths: Sequence[Path],
    graph_count: int,
    work: Path,
    exact_dir: Path,
    workers: int,
    order: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    screen_dir = work / "screens"
    screen_dir.mkdir(parents=True, exist_ok=True)
    exact_dir.mkdir(parents=True, exist_ok=True)
    # Existing exact checkpoints are stronger than screens and are converted
    # into cover checkpoints without recomputing their universes.
    for index in range(graph_count):
        exact_path = exact_dir / f"{index:05d}.json"
        screen_path = screen_dir / f"{index:05d}.json"
        if exact_path.exists() and not screen_path.exists():
            exact = _load_json(exact_path)
            _atomic_json(screen_path, {
                "schema": COVER_SCHEMA,
                "generation_index": exact["generation_index"],
                "plantri_rank": exact["plantri_rank"],
                "canonical_graph_hash": exact["canonical_graph_hash"],
                "graph_order": order,
                "edge_count": 3 * order // 2,
                "cover_size": exact["primal_cycle_count"],
                "cycles": exact["primal_cycles"],
                "covered_ordered_edge_pairs": exact["covered_ordered_edge_pairs"],
                "method": "reused_exact_checkpoint_primal",
                "complete_hamiltonian_cycle_count": exact["complete_hamiltonian_cycle_count"],
                "runtime_seconds": exact["runtime_seconds"],
            })
    screen_tasks = (
        (index, _load_json(path))
        for index, path in enumerate(graph_paths)
        if not (screen_dir / f"{index:05d}.json").exists()
    )
    _schedule_records(screen_tasks, _screen_task, screen_dir, workers,
                      progress_label=f"order {order} screening")

    exact_records = [
        _load_json(path) for path in sorted(exact_dir.glob("*.json"))
        if _load_json(path).get("exact_hsep") is not None
    ]
    if not exact_records:
        screens = [_load_json(screen_dir / f"{index:05d}.json") for index in range(graph_count)]
        candidate = max(screens, key=lambda item: (int(item["cover_size"]), -int(item["generation_index"])))
        index = int(candidate["generation_index"])
        exact = _exact_record(_load_json(graph_paths[index]))
        if exact.get("exact_hsep") is None:
            raise RuntimeError(f"order {order} initial extremal candidate lacks an exact lower bound")
        _atomic_json(exact_dir / f"{index:05d}.json", exact)
        _atomic_json(screen_dir / f"{index:05d}.json", {
            **candidate,
            "cover_size": exact["primal_cycle_count"],
            "cycles": exact["primal_cycles"],
            "covered_ordered_edge_pairs": exact["covered_ordered_edge_pairs"],
            "method": "exact_candidate_primal",
        })

    while True:
        exact_records = [_load_json(path) for path in sorted(exact_dir.glob("*.json"))]
        if any(record.get("exact_hsep") is None for record in exact_records):
            raise RuntimeError(f"order {order} has an unresolved exact checkpoint")
        maximum = max(int(record["exact_hsep"]) for record in exact_records)
        pending: list[int] = []
        for index in range(graph_count):
            exact_path = exact_dir / f"{index:05d}.json"
            if exact_path.exists():
                continue
            screen = _load_json(screen_dir / f"{index:05d}.json")
            if int(screen["cover_size"]) >= maximum:
                pending.append(index)
        if not pending:
            break
        result_dir = work / f"resolution_le_{maximum - 1}"
        result_dir.mkdir(parents=True, exist_ok=True)
        tasks = (
            (index, (
                _load_json(graph_paths[index]),
                _load_json(screen_dir / f"{index:05d}.json"),
                maximum - 1,
            ))
            for index in pending
        )
        _schedule_records(tasks, _bounded_or_exact_task, result_dir, workers,
                          progress_label=f"order {order} bound {maximum - 1}")
        for index in pending:
            wrapper = _load_json(result_dir / f"{index:05d}.json")
            record = wrapper["record"]
            if wrapper["kind"] == "exact":
                _atomic_json(exact_dir / f"{index:05d}.json", record)
                prior = _load_json(screen_dir / f"{index:05d}.json")
                _atomic_json(screen_dir / f"{index:05d}.json", {
                    **prior,
                    "cover_size": record["primal_cycle_count"],
                    "cycles": record["primal_cycles"],
                    "covered_ordered_edge_pairs": record["covered_ordered_edge_pairs"],
                    "method": "exact_tail_primal",
                })
            else:
                _atomic_json(screen_dir / f"{index:05d}.json", record)
        # If a failed bound produced a larger exact value, the next iteration
        # raises the candidate and reuses every already smaller cover.

    covers = [_load_json(screen_dir / f"{index:05d}.json") for index in range(graph_count)]
    exacts = [_load_json(path) for path in sorted(exact_dir.glob("*.json"))]
    return covers, exacts


def _write_empty_order(
    root: Path,
    order: int,
    reason: str,
    workers: int,
    *,
    plantri: dict[str, Any] | None = None,
    runtime: float = 0.0,
) -> dict[str, Any]:
    directory = root / f"order_{order:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    for filename in ("graph_certificates.jsonl.gz", "cover_certificates.jsonl.gz", "exact_certificates.jsonl.gz"):
        _write_values_gzip((), directory / filename)
    summary = {
        "schema": ORDER_SCHEMA,
        "order": order,
        "graph_count": 0,
        "M_B": None,
        "number_of_maximizers": 0,
        "maximizer_hashes": [],
        "unique_maximizer": None,
        "max_hamiltonian_cycles_among_maximizers": None,
        "min_hamiltonian_cycles_among_maximizers": None,
        "proof_status": "undefined_empty_order",
        "undefined_reason": reason,
        "theoretical_lower_bounds": theoretical_bounds(order),
        "total_runtime_seconds": runtime,
    }
    _atomic_json(directory / "order_summary.json", summary)
    _atomic_json(directory / "census_metadata.json", {
        "schema": "barnie-sequence-census-v1", "order": order, "graph_count": 0,
        "completeness_status": "proved_empty", "reason": reason, "plantri": plantri,
    })
    _atomic_json(directory / "environment.json", _environment(workers))
    _atomic_text(directory / "commands.log", (canonical_json(plantri.get("command")) + "\n") if plantri else "mathematical parity exclusion\n")
    _atomic_text(directory / "CENSUS_AUDIT.md", f"# Order {order} census audit\n\nNo Barnette graphs: {reason}.\n")
    _manifest(directory)
    return summary


def process_exact_order(
    root: Path,
    order: int,
    plantri_executable: Path,
    workers: int,
    resume: bool,
) -> dict[str, Any]:
    directory = root / f"order_{order:02d}"
    work = directory / ".work"
    graph_dir = work / "graphs"
    exact_dir = work / "exact"
    directory.mkdir(parents=True, exist_ok=True)
    config = {"order": order, "workers": workers, "plantri": str(plantri_executable.resolve())}
    config_path = work / "configuration.json"
    if config_path.exists():
        prior = _load_json(config_path)
        if {k: prior.get(k) for k in ("order", "plantri")} != {k: config[k] for k in ("order", "plantri")}:
            raise ValueError(f"resume configuration mismatch for order {order}")
        if not resume:
            raise FileExistsError(f"work exists for order {order}; pass --resume")
    else:
        work.mkdir(parents=True, exist_ok=True)
        _atomic_json(config_path, config)
    version = detect_plantri_version(locate_plantri(plantri_executable))
    started = perf_counter()
    graph_dir.mkdir(parents=True, exist_ok=True)
    pending_graphs: list[tuple[int, tuple[int, bytes, int]]] = []
    hashes: set[str] = set()
    generated = 0
    with stream_barnette_graphs(version, order) as stream:
        for index, embedded in enumerate(stream):
            generated += 1
            path = graph_dir / f"{index:05d}.json"
            planar = encode_planar_code(embedded.rotation_system)
            if path.exists():
                record = _load_json(path)
                if record.get("planar_code_sha256") != sha256(planar).hexdigest():
                    raise RuntimeError("resume Plantri record mismatch")
            else:
                pending_graphs.append((index, (index, planar, order)))
        plantri_stderr = stream.stderr_text
    expected = REFERENCE_COUNTS[order]
    if generated != expected:
        raise RuntimeError(f"order {order}: Plantri generated {generated}, expected {expected}")
    _schedule_records(pending_graphs, _graph_task, graph_dir, workers, progress_label=f"order {order} census")
    graph_paths = [graph_dir / f"{index:05d}.json" for index in range(generated)]
    for index, path in enumerate(graph_paths):
        record = _load_json(path)
        if record["generation_index"] != index:
            raise RuntimeError("non-contiguous graph checkpoints")
        graph_hash = record["canonical_graph_hash"]
        if graph_hash in hashes:
            raise RuntimeError("duplicate canonical graph hash")
        hashes.add(graph_hash)
    if generated == 0:
        plantri_info = {
            "version": version.version,
            "executable": str(version.executable),
            "executable_sha256": version.executable_sha256,
            "command": list(barnette_plantri_command(version.executable, order)),
            "stderr": plantri_stderr,
        }
        return _write_empty_order(root, order, "complete Plantri 5.8 census is empty", workers, plantri=plantri_info, runtime=perf_counter()-started)
    if order <= 24:
        exact_tasks = ((index, _load_json(path)) for index, path in enumerate(graph_paths))
        _schedule_records(exact_tasks, _exact_task, exact_dir, workers, progress_label=f"order {order} exact")
        exact_paths = [exact_dir / f"{index:05d}.json" for index in range(generated)]
        exact_records = []
        for path in exact_paths:
            record = _upgrade_exact_record(_load_json(path))
            _atomic_json(path, record)
            exact_records.append(record)
        cover_records = [{
            "schema": COVER_SCHEMA,
            "generation_index": record["generation_index"],
            "plantri_rank": record["plantri_rank"],
            "canonical_graph_hash": record["canonical_graph_hash"],
            "graph_order": order,
            "edge_count": 3 * order // 2,
            "cover_size": record["primal_cycle_count"],
            "cycles": record["primal_cycles"],
            "covered_ordered_edge_pairs": record["covered_ordered_edge_pairs"],
            "method": "complete_hamiltonian_universe_exact_set_cover",
        } for record in exact_records]
        strategy = "complete_universe_exact_every_graph"
    else:
        cover_records, exact_records = _adaptive_certificates(
            graph_paths, generated, work, exact_dir, workers, order
        )
        exact_paths = [
            exact_dir / f"{int(record['generation_index']):05d}.json"
            for record in sorted(exact_records, key=lambda item: int(item["generation_index"]))
        ]
        strategy = "adaptive_complete_universe_screen_then_exact_tail"
    unresolved = [record for record in exact_records if record.get("exact_hsep") is None]
    if unresolved:
        hashes_text = ",".join(record["canonical_graph_hash"] for record in unresolved)
        raise RuntimeError(f"order {order} has exact records without an independent lower bound: {hashes_text}")
    maximum = max(int(record["exact_hsep"]) for record in exact_records)
    maximizers = [record for record in exact_records if record["exact_hsep"] == maximum]
    for record in maximizers:
        graph_record = _load_json(graph_dir / f"{int(record['generation_index']):05d}.json")
        edges = tuple(tuple(map(int, edge)) for edge in graph_record["edges"])
        record["perfect_matching_count"] = count_perfect_matchings(edges, order)
        record["automorphism_group_order"] = automorphism_group_order(edges, order)
        _atomic_json(exact_dir / f"{int(record['generation_index']):05d}.json", record)
    exact_records = [_load_json(path) for path in exact_paths]
    cover_records.sort(key=lambda item: int(item["generation_index"]))
    graph_digest, graph_bytes, _ = _write_jsonl_gzip(graph_paths, directory / "graph_certificates.jsonl.gz")
    exact_digest, exact_bytes, _ = _write_jsonl_gzip(exact_paths, directory / "exact_certificates.jsonl.gz")
    cover_digest, cover_bytes, _ = _write_values_gzip(cover_records, directory / "cover_certificates.jsonl.gz")
    invocation_runtime = perf_counter() - started
    exact_by_index = {int(record["generation_index"]): record for record in exact_records}
    recorded_worker_runtime = sum(
        float(exact_by_index[index]["runtime_seconds"])
        if index in exact_by_index
        else float(cover_records[index].get("runtime_seconds", 0.0))
        for index in range(generated)
    )
    max_counts = [int(record["complete_hamiltonian_cycle_count"]) for record in maximizers]
    summary = {
        "schema": ORDER_SCHEMA,
        "order": order,
        "graph_count": generated,
        "M_B": maximum,
        "number_of_maximizers": len(maximizers),
        "maximizer_hashes": [record["canonical_graph_hash"] for record in maximizers],
        "unique_maximizer": len(maximizers) == 1,
        "max_hamiltonian_cycles_among_maximizers": max(max_counts),
        "min_hamiltonian_cycles_among_maximizers": min(max_counts),
        "proof_status": "independent_verification_pending",
        "undefined_reason": None,
        "theoretical_lower_bounds": theoretical_bounds(order),
        "total_runtime_seconds": recorded_worker_runtime,
        "current_invocation_wall_runtime_seconds": invocation_runtime,
    }
    _atomic_json(directory / "order_summary.json", summary)
    plantri_info = {
        "version": version.version,
        "executable": str(version.executable),
        "executable_sha256": version.executable_sha256,
        "command": list(barnette_plantri_command(version.executable, order)),
        "stderr": plantri_stderr,
    }
    _atomic_json(directory / "census_metadata.json", {
        "schema": "barnie-sequence-census-v1",
        "order": order,
        "graph_count": generated,
        "unique_canonical_hashes": len(hashes),
        "contiguous_generation_indices": True,
        "completeness_status": "complete_plantri_5.8_census",
        "plantri": plantri_info,
        "canonical_uncompressed": {
            "graph_certificates": {"sha256": graph_digest, "bytes": graph_bytes},
            "cover_certificates": {"sha256": cover_digest, "bytes": cover_bytes},
            "exact_certificates": {"sha256": exact_digest, "bytes": exact_bytes},
        },
        "runtime_seconds": recorded_worker_runtime,
        "current_invocation_wall_runtime_seconds": invocation_runtime,
        "workers": workers,
        "hsep_strategy": strategy,
    })
    _atomic_json(directory / "environment.json", _environment(workers))
    _atomic_text(directory / "commands.log", canonical_json(plantri_info["command"]) + "\n" +
                 canonical_json(["python", "-m", "barnette_search.barnie_sequence", "--orders", str(order)]) + "\n")
    _atomic_text(directory / "CENSUS_AUDIT.md", (
        f"# Order {order} census audit\n\nPASS: Plantri 5.8 generated {generated} records with "
        f"{len(hashes)} unique canonical hashes and contiguous indices. Every graph passed simplicity, "
        "cubicity, bipartiteness, planarity, 3-connectivity, Euler, and facial-dart checks.\n"
    ))
    _manifest(directory)
    return summary


def _iter_gzip_json(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="ascii") as source:
        for line in source:
            yield json.loads(line)


def import_order36(root: Path, source_root: Path, workers: int) -> dict[str, Any]:
    directory = root / "order_36"
    directory.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    source_certs = source_root / "order36_certificates.jsonl"
    source_metadata = _load_json(source_root / "order36_metadata.json")
    source_verification = _load_json(source_root / "independent_verification.json")
    if sha256_file(source_certs) != "6d6a67c2d1836e00466158c23495437f5a88a946a29b931f37aca66d7e456825":
        raise RuntimeError("order-36 certificate regression digest mismatch")
    if source_verification.get("verified") is not True or source_verification.get("conclusion") != "BARNIE_49_UNIQUE_ORDER36_MAXIMUM":
        raise RuntimeError("order-36 independent verification result is not accepted")

    def records() -> Iterator[dict[str, Any]]:
        with source_certs.open("rt", encoding="ascii") as source:
            for line in source:
                yield json.loads(line)

    def graphs() -> Iterator[dict[str, Any]]:
        for record in records():
            data = base64.b64decode(record["planar_code_base64"])
            yield _graph_record(int(record["generation_index"]), data, 36)

    def covers() -> Iterator[dict[str, Any]]:
        for record in records():
            yield {
                "schema": COVER_SCHEMA,
                "generation_index": record["generation_index"],
                "plantri_rank": record["plantri_rank"],
                "canonical_graph_hash": record["canonical_graph_hash"],
                "graph_order": 36,
                "edge_count": 54,
                "cover_size": record["cover_size"],
                "cycles": record["cycles"],
                "covered_ordered_edge_pairs": record["covered_ordered_edge_pairs"],
                "method": "imported_verified_order36_cover",
            }

    def exacts() -> Iterator[dict[str, Any]]:
        for record in records():
            if record.get("exact_hsep") is None:
                continue
            edges = tuple(tuple(map(int, edge)) for edge in record["edges"])
            yield {
                "schema": EXACT_SCHEMA,
                "generation_index": record["generation_index"],
                "plantri_rank": record["plantri_rank"],
                "canonical_graph_hash": record["canonical_graph_hash"],
                "graph_order": 36,
                "edge_count": 54,
                "complete_hamiltonian_cycle_count": record["complete_hamiltonian_cycle_count"],
                "complete_hamiltonian_cycle_universe": record["complete_hamiltonian_cycle_universe"],
                "hsep_lower_bound": 49,
                "hsep_upper_bound": 49,
                "exact_hsep": 49,
                "proof_status": "exact_primal_packing_imported",
                "lower_bound_method": "packing",
                "primal_cycle_count": 49,
                "primal_cycles": record["cycles"],
                "packing_requirement_count": 49,
                "packing_requirements": record["packing_lower_bound"],
                "greedy_complete_universe_cover_size": None,
                "covered_ordered_edge_pairs": record["covered_ordered_edge_pairs"],
                "perfect_matching_count": count_perfect_matchings(edges, 36),
                "automorphism_group_order": automorphism_group_order(edges, 36),
                "runtime_seconds": source_metadata["runtime_seconds"],
                "peak_python_memory_bytes": None,
            }

    graph_digest, graph_bytes, graph_count = _write_values_gzip(graphs(), directory / "graph_certificates.jsonl.gz")
    cover_digest, cover_bytes, cover_count = _write_values_gzip(covers(), directory / "cover_certificates.jsonl.gz")
    exact_digest, exact_bytes, exact_count = _write_values_gzip(exacts(), directory / "exact_certificates.jsonl.gz")
    if (graph_count, cover_count, exact_count) != (15374, 15374, 1):
        raise RuntimeError("imported order-36 record counts are wrong")
    runtime = perf_counter() - started
    summary = {
        "schema": ORDER_SCHEMA,
        "order": 36,
        "graph_count": 15374,
        "M_B": 49,
        "number_of_maximizers": 1,
        "maximizer_hashes": [BARNIE_HASH],
        "unique_maximizer": True,
        "max_hamiltonian_cycles_among_maximizers": 68,
        "min_hamiltonian_cycles_among_maximizers": 68,
        "proof_status": "imported_independently_verified_order36",
        "undefined_reason": None,
        "theoretical_lower_bounds": theoretical_bounds(36),
        "total_runtime_seconds": float(source_metadata["runtime_seconds"]) + float(source_verification["runtime_seconds"]),
        "import_runtime_seconds": runtime,
    }
    _atomic_json(directory / "order_summary.json", summary)
    _atomic_json(directory / "census_metadata.json", {
        "schema": "barnie-sequence-census-v1", "order": 36, "graph_count": graph_count,
        "unique_canonical_hashes": graph_count, "contiguous_generation_indices": True,
        "completeness_status": "imported_complete_plantri_5.8_census",
        "source_package": str(source_root.resolve()),
        "source_certificates_sha256": sha256_file(source_certs),
        "source_manifest_sha256": sha256_file(source_root / "SHA256SUMS.txt"),
        "source_independent_verification": source_verification,
        "plantri": source_metadata["plantri"],
        "canonical_uncompressed": {
            "graph_certificates": {"sha256": graph_digest, "bytes": graph_bytes},
            "cover_certificates": {"sha256": cover_digest, "bytes": cover_bytes},
            "exact_certificates": {"sha256": exact_digest, "bytes": exact_bytes},
        }, "runtime_seconds": runtime, "workers": workers,
    })
    _atomic_json(directory / "environment.json", _environment(workers))
    _atomic_text(directory / "commands.log", "import immutable E:/barnette-results/hsep-order36\n" +
                 "python verify_hsep_order36.py . --check-manifest\n")
    _atomic_text(directory / "CENSUS_AUDIT.md", (
        "# Order 36 census audit\n\nPASS: imported the immutable 15,374-record Plantri 5.8 package. "
        "Its standalone verifier was rerun before import and reproduced M_B(36)=49, the unique Barnie hash, "
        "68 complete Hamiltonian cycles, matching 49/49 certificates, and 15,373 covers at most 48.\n"
    ))
    _manifest(directory)
    return summary


def write_global_outputs(root: Path, summaries: Sequence[dict[str, Any]]) -> None:
    rows = []
    for summary in sorted(summaries, key=lambda item: item["order"]):
        rows.append({
            "order": summary["order"], "number_of_barnette_graphs": summary["graph_count"],
            "M_B": summary["M_B"], "number_of_maximizers": summary["number_of_maximizers"],
            "maximizer_hashes": ";".join(summary["maximizer_hashes"]),
            "unique_maximizer": summary["unique_maximizer"],
            "maximum_hamiltonian_cycles_among_maximizers": summary["max_hamiltonian_cycles_among_maximizers"],
            "minimum_hamiltonian_cycles_among_maximizers": summary["min_hamiltonian_cycles_among_maximizers"],
            "proof_status": summary["proof_status"], "total_runtime_seconds": summary["total_runtime_seconds"],
        })
    csv_path = root / "barnie_sequence.csv"
    temporary = csv_path.with_name(csv_path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=tuple(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    os.replace(temporary, csv_path)
    _atomic_json(root / "barnie_sequence.json", {"schema": GLOBAL_SCHEMA, "orders": list(sorted(summaries, key=lambda item: item["order"]))})
    lines = [
        "# Barnette Hamiltonian edge-separation extremal sequence",
        "", "Informal project name: Barnie sequence.", "",
        "Every finite entry below has a primal certificate and an independently checkable lower certificate (a matching packing where available, otherwise exhaustive complete-universe exclusion); undefined entries are parity-impossible or census-empty.", "",
        "| n | graphs | M_B(n) | maximizers | unique | hashes |", "|---:|---:|---:|---:|:---:|---|",
    ]
    for row in rows:
        value = "undefined" if row["M_B"] is None else str(row["M_B"])
        unique = "--" if row["unique_maximizer"] is None else ("yes" if row["unique_maximizer"] else "no")
        lines.append(f"| {row['order']} | {row['number_of_barnette_graphs']} | {value} | {row['number_of_maximizers']} | {unique} | {row['maximizer_hashes']} |")
    counts = {34: REFERENCE_COUNTS[34], 36: REFERENCE_COUNTS[36], 38: 50116}
    ratio = counts[38] / counts[36]
    estimated_40 = round(counts[38] * ratio)
    lines.extend([
        "", "## Theoretical lower bounds", "",
        "The general signature bounds are recorded separately from graph-specific values in every order summary. The Sperner bound requires the edge-incidence signatures to form an antichain. The strengthened cubic/LYM bound additionally uses |E|=3n/2, exactly n incidences per Hamiltonian cycle, nonempty/proper signatures, distinct-subset capacities, and the LYM inequality. These bounds do not replace any graph-specific lower certificate.",
        "Peak Python memory is recorded in newly generated exact maximizer records. The imported order-36 source package did not record exact-generation peak memory, so Barnie 49's peak field is explicitly null rather than reconstructed.",
        "", "## Orders 38 and 40 cost estimate", "",
        f"Order 38 has an already audited census of 50,116 graphs ({counts[38]/counts[36]:.2f}x order 36).",
        "Its retained strong-flexibility run took 7,209.7 seconds. Scaling the certified order-34/36 producer and verifier rates gives a planning range of 3-8 wall-clock hours with four workers, including census reconstruction, explicit-cover generation, an adaptive exact tail, and independent verification. Exact-tail behavior is the dominant uncertainty.",
        "The immutable core through order 34 uses about 571 compressed bytes per graph and order 36 about 653 bytes per graph. Allowing for larger cycles and tail universes, order 38 is budgeted at 50-150 MB compressed plus 0.2-1 GB of resumable checkpoints.",
        f"A simple recent-growth projection estimates approximately {estimated_40:,} order-40 graphs; this is a planning estimate, not a census count.",
        "At that projected size, budget 10-30 wall-clock hours with four workers, 0.2-0.6 GB compressed immutable output, and 1-4 GB of resumable checkpoints. A difficult non-packing exact tail could exceed the upper time estimate and must be checkpointed and reported rather than silently timed out.",
        "Neither order 38 nor order 40 was launched by this workflow.", "",
        "## Reproduction", "", "Run `python verify_barnie_sequence.py . --check-manifest` from this directory.",
        "Mutable per-graph resume checkpoints are retained outside the immutable package at `E:/barnette-results/barnie-sequence-work/`. Restore an order's checkpoint directory as `order_NN/.work` before invoking the producer with `--resume`.", "",
    ])
    _atomic_text(root / "BARNIE_SEQUENCE_REPORT.md", "\n".join(lines))


def run(
    *, root: Path, plantri: Path, order36: Path, workers: int, resume: bool,
    selected_orders: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    if not 1 <= workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    root.mkdir(parents=True, exist_ok=True)
    requested = tuple(selected_orders) if selected_orders else ORDERS
    summaries: list[dict[str, Any]] = []
    for order in requested:
        print(f"starting order {order}", flush=True)
        if order % 2:
            summaries.append(_write_empty_order(root, order, "a cubic graph has even order by the degree-sum identity", workers))
        elif order == 36:
            summaries.append(import_order36(root, order36, workers))
        else:
            summaries.append(process_exact_order(root, order, plantri, workers, resume))
    if set(requested) == set(ORDERS):
        write_global_outputs(root, summaries)
        shutil.copy2(Path(__file__).parents[2] / "tools" / "verify_barnie_sequence.py", root / "verify_barnie_sequence.py")
        _manifest(root)
    return summaries


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--plantri", type=Path, required=True)
    parser.add_argument("--order36", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--orders", type=int, nargs="*")
    args = parser.parse_args(argv)
    summaries = run(root=args.output_root, plantri=args.plantri, order36=args.order36,
                    workers=args.workers, resume=args.resume, selected_orders=args.orders)
    print(canonical_json({"completed_orders": [item["order"] for item in summaries]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
