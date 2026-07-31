"""Certificate-first uniqueness audit for order-36 Barnette graphs.

This module deliberately keeps certificate production separate from the
established flexibility and validation implementations.  Greedy witness
families are upper bounds only.  Exact values are recorded only when matching
primal and packing certificates are available and independently checkable
against a complete Hamiltonian-cycle universe.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from importlib import metadata as importlib_metadata
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
from time import perf_counter
from typing import Any, Iterable, Iterator, Sequence

from .all_edge_flexibility import analyze_all_edge_pair_flexibility
from .planar_code import (
    canonical_graph_hash,
    encode_planar_code,
    iter_planar_code,
)
from .plantri import detect_plantri_version, locate_plantri, stream_barnette_graphs
from .validation import validate_barnette_graph


ORDER = 36
EDGE_COUNT = 54
REQUIREMENT_COUNT = EDGE_COUNT * (EDGE_COUNT - 1)
EXPECTED_GRAPH_COUNT = 15_374
BARNIE_HASH = "2f96ada16c46cd2bd038b97d5af44f46ed14522cba1edf3fa041d66e02107bcc"
SCHEMA = "barnette-hsep-order36-certificate-v1"
METADATA_SCHEMA = "barnette-hsep-order36-metadata-v1"


def canonical_json(value: Any) -> str:
    """Return the byte-stable JSON representation used by audit artifacts."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_cycle(cycle: Iterable[int]) -> tuple[int, ...]:
    """Remove closure and normalize rotation and reversal presentation."""
    values = tuple(int(vertex) for vertex in cycle)
    if len(values) >= 2 and values[0] == values[-1]:
        values = values[:-1]
    if len(values) < 3 or len(set(values)) != len(values):
        raise ValueError("cycle must contain at least three distinct vertices")
    variants: list[tuple[int, ...]] = []
    for oriented in (values, tuple(reversed(values))):
        minimum = min(oriented)
        for index, vertex in enumerate(oriented):
            if vertex == minimum:
                variants.append(oriented[index:] + oriented[:index])
    return min(variants)


def edge_list_from_graph(graph: Any) -> tuple[tuple[int, int], ...]:
    return tuple(sorted((min(int(u), int(v)), max(int(u), int(v))) for u, v in graph.edges()))


def cycle_edge_indexes(
    cycle: Sequence[int], edge_index: dict[tuple[int, int], int]
) -> frozenset[int]:
    selected: set[int] = set()
    for left, right in zip(cycle, cycle[1:] + cycle[:1]):
        edge = (min(left, right), max(left, right))
        try:
            selected.add(edge_index[edge])
        except KeyError as error:
            raise ValueError(f"cycle uses non-edge {edge}") from error
    return frozenset(selected)


def requirement_pairs(edge_count: int) -> tuple[tuple[int, int], ...]:
    return tuple(
        (required, forbidden)
        for required in range(edge_count)
        for forbidden in range(edge_count)
        if required != forbidden
    )


def verify_cover_edges(
    edges: Sequence[tuple[int, int]], cycles: Sequence[Sequence[int]]
) -> tuple[bool, int]:
    edge_index = {edge: index for index, edge in enumerate(edges)}
    covered: set[tuple[int, int]] = set()
    all_indexes = set(range(len(edges)))
    for cycle in cycles:
        selected = cycle_edge_indexes(tuple(cycle), edge_index)
        for required in selected:
            for forbidden in all_indexes - selected:
                covered.add((required, forbidden))
    total = len(edges) * (len(edges) - 1)
    return len(covered) == total, len(covered)


def _connected_subset(vertices: set[int], adjacency: Sequence[frozenset[int]]) -> bool:
    if not vertices:
        return True
    start = min(vertices)
    reached = {start}
    pending = [start]
    while pending:
        vertex = pending.pop()
        for neighbor in adjacency[vertex] & vertices:
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    return reached == vertices


def enumerate_hamiltonian_cycles(
    edges: Sequence[tuple[int, int]], order: int
) -> Iterator[tuple[int, ...]]:
    """Enumerate undirected Hamiltonian cycles once in deterministic order."""
    adjacency_mutable = [set() for _ in range(order)]
    for left, right in edges:
        adjacency_mutable[left].add(right)
        adjacency_mutable[right].add(left)
    adjacency = tuple(frozenset(row) for row in adjacency_mutable)
    all_vertices = set(range(order))
    start = 0
    path = [start]
    visited = {start}

    def feasible(current: int) -> bool:
        remaining = all_vertices - visited
        first = path[1]
        if not remaining:
            return start in adjacency[current] and first < current
        if not adjacency[current] & remaining:
            return False
        if not any(first < vertex for vertex in adjacency[start] & remaining):
            return False
        available = remaining | {start, current}
        if any(len(adjacency[vertex] & available) < 2 for vertex in remaining):
            return False
        return _connected_subset(remaining, adjacency)

    def search(current: int) -> Iterator[tuple[int, ...]]:
        if len(path) == order:
            if start in adjacency[current] and path[1] < current:
                yield tuple(path)
            return
        candidates = sorted(
            adjacency[current] - visited,
            key=lambda vertex: (len(adjacency[vertex] - visited), vertex),
        )
        for candidate in candidates:
            visited.add(candidate)
            path.append(candidate)
            if feasible(candidate):
                yield from search(candidate)
            path.pop()
            visited.remove(candidate)

    for first in sorted(adjacency[start]):
        visited.add(first)
        path.append(first)
        if feasible(first):
            yield from search(first)
        path.pop()
        visited.remove(first)


def _cycle_coverers(
    edges: Sequence[tuple[int, int]], cycles: Sequence[Sequence[int]]
) -> tuple[tuple[int, ...], ...]:
    edge_index = {edge: index for index, edge in enumerate(edges)}
    requirements = requirement_pairs(len(edges))
    positions = {pair: index for index, pair in enumerate(requirements)}
    coverers: list[list[int]] = [[] for _ in requirements]
    all_indexes = set(range(len(edges)))
    for cycle_index, cycle in enumerate(cycles):
        selected = cycle_edge_indexes(tuple(cycle), edge_index)
        for required in selected:
            for forbidden in all_indexes - selected:
                coverers[positions[(required, forbidden)]].append(cycle_index)
    return tuple(tuple(row) for row in coverers)


def solve_set_cover(
    edges: Sequence[tuple[int, int]],
    cycles: Sequence[Sequence[int]],
    bound: int,
) -> tuple[int, ...] | None:
    """Return a deterministic SAT set cover of size at most ``bound``."""
    from pysat.card import CardEnc, EncType
    from pysat.solvers import Solver

    if bound < 0:
        return None
    coverers = _cycle_coverers(edges, cycles)
    if any(not row for row in coverers):
        return None
    clauses = [[cycle_index + 1 for cycle_index in row] for row in coverers]
    top_id = len(cycles)
    if len(cycles) > bound:
        encoding = CardEnc.atmost(
            lits=list(range(1, len(cycles) + 1)),
            bound=bound,
            top_id=top_id,
            encoding=EncType.seqcounter,
        )
        clauses.extend(map(list, encoding.clauses))
    with Solver(name="g3", bootstrap_with=clauses) as solver:
        if not solver.solve():
            return None
        model = set(solver.get_model() or ())
    selected = tuple(index for index in range(len(cycles)) if index + 1 in model)
    if len(selected) > bound:
        raise RuntimeError("set-cover solver violated its cardinality bound")
    return selected


def solve_packing_lower_bound(
    edges: Sequence[tuple[int, int]],
    cycles: Sequence[Sequence[int]],
    size: int,
) -> tuple[tuple[int, int], ...] | None:
    """Find requirements such that every listed cycle covers at most one."""
    requirements = requirement_pairs(len(edges))
    supports = _cycle_coverers(edges, cycles)
    used_cycles: set[int] = set()
    greedy_indexes: list[int] = []
    for requirement_index, support in sorted(
        enumerate(supports), key=lambda item: (len(item[1]), item[1], item[0])
    ):
        if support and not used_cycles.intersection(support):
            greedy_indexes.append(requirement_index)
            used_cycles.update(support)
            if len(greedy_indexes) == size:
                return tuple(requirements[index] for index in greedy_indexes)

    # The deterministic support-mask greedy is only a certificate finder.  A
    # miss is not an impossibility proof, so retain the exact SAT fallback.
    from pysat.card import CardEnc, EncType
    from pysat.solvers import Solver

    edge_index = {edge: index for index, edge in enumerate(edges)}
    all_indexes = set(range(len(edges)))
    clauses: list[list[int]] = []
    top_id = len(requirements)
    for cycle in cycles:
        selected = cycle_edge_indexes(tuple(cycle), edge_index)
        covered = [
            req_index + 1
            for req_index, (required, forbidden) in enumerate(requirements)
            if required in selected and forbidden in all_indexes - selected
        ]
        encoding = CardEnc.atmost(
            lits=covered,
            bound=1,
            top_id=top_id,
            encoding=EncType.seqcounter,
        )
        clauses.extend(map(list, encoding.clauses))
        top_id = max(top_id, encoding.nv)
    exact = CardEnc.equals(
        lits=list(range(1, len(requirements) + 1)),
        bound=size,
        top_id=top_id,
        encoding=EncType.seqcounter,
    )
    clauses.extend(map(list, exact.clauses))
    with Solver(name="g3", bootstrap_with=clauses) as solver:
        if not solver.solve():
            return None
        model = set(solver.get_model() or ())
    chosen = tuple(
        requirement
        for index, requirement in enumerate(requirements, start=1)
        if index in model
    )
    if len(chosen) != size:
        raise RuntimeError("packing solver violated its cardinality constraint")
    return chosen


@dataclass(frozen=True, slots=True)
class SourceRecord:
    generation_index: int
    canonical_graph_hash: str
    face_size_multiset: tuple[int, ...]
    greedy_size: int


def load_source_records(path: Path) -> tuple[SourceRecord, ...]:
    opener = gzip.open if ".gz" in path.suffixes else Path.open
    values: list[SourceRecord] = []
    with opener(path, "rt", encoding="utf-8") as source:  # type: ignore[arg-type]
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("requested_vertex_count") != ORDER:
                raise ValueError(f"source line {line_number} is not order {ORDER}")
            analysis = record["all_edge_pairs"]
            values.append(
                SourceRecord(
                    generation_index=int(record["generation_index"]),
                    canonical_graph_hash=str(record["canonical_graph_hash"]),
                    face_size_multiset=tuple(map(int, record["face_size_multiset"])),
                    greedy_size=int(analysis["number_of_witness_cycles"]),
                )
            )
    values.sort(key=lambda item: item.generation_index)
    if len(values) != EXPECTED_GRAPH_COUNT:
        raise ValueError(
            f"expected {EXPECTED_GRAPH_COUNT} order-36 source rows, found {len(values)}"
        )
    if [item.generation_index for item in values] != list(range(EXPECTED_GRAPH_COUNT)):
        raise ValueError("source generation indices are not contiguous")
    if len({item.canonical_graph_hash for item in values}) != EXPECTED_GRAPH_COUNT:
        raise ValueError("source canonical hashes are not unique")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class GenerationTask:
    source: SourceRecord
    planar_code: bytes


def _certificate_record(task: GenerationTask) -> dict[str, Any]:
    [embedded] = iter_planar_code(BytesIO(task.planar_code), require_header=True)
    graph = embedded.graph
    validation = validate_barnette_graph(graph)
    if not validation.valid:
        raise RuntimeError(f"generated graph is not Barnette: {validation.rejection_reasons}")
    graph_hash = canonical_graph_hash(embedded)
    if graph_hash != task.source.canonical_graph_hash:
        raise RuntimeError("generated graph hash differs from source census")
    if tuple(embedded.face_size_multiset) != task.source.face_size_multiset:
        raise RuntimeError("generated face multiset differs from source census")

    result = analyze_all_edge_pair_flexibility(
        graph,
        retain_pair_details=False,
        retain_witness_cycles=True,
        cross_check_backtracking=False,
    )
    if not result.property_satisfied or result.witnesses is None:
        raise RuntimeError("all-edge greedy generation did not produce a complete family")
    cycles = tuple(
        sorted(
            {
                normalize_cycle(witness.cycle)
                for witness in result.witnesses
                if witness.cycle is not None
            }
        )
    )
    if len(cycles) != task.source.greedy_size:
        raise RuntimeError(
            f"greedy count changed for {graph_hash}: "
            f"source={task.source.greedy_size}, regenerated={len(cycles)}"
        )
    edges = edge_list_from_graph(graph)
    complete, covered = verify_cover_edges(edges, cycles)
    if not complete or covered != REQUIREMENT_COUNT:
        raise RuntimeError("regenerated greedy family does not cover all requirements")
    status = "barnie_greedy_pending_exact" if graph_hash == BARNIE_HASH else (
        "verified_le48_greedy" if len(cycles) <= 48 else "tail_pending_bound48"
    )
    return {
        "schema": SCHEMA,
        "generation_index": task.source.generation_index,
        "plantri_rank": task.source.generation_index + 1,
        "canonical_graph_hash": graph_hash,
        "graph_order": ORDER,
        "edge_count": len(edges),
        "face_size_multiset": list(task.source.face_size_multiset),
        "planar_code_base64": base64.b64encode(task.planar_code).decode("ascii"),
        "planar_code_sha256": sha256(task.planar_code).hexdigest(),
        "edges": [list(edge) for edge in edges],
        "source_greedy_size": task.source.greedy_size,
        "cycle_generation_method": "deterministic_all_edge_greedy_glucose3",
        "cover_size": len(cycles),
        "cycles": [list(cycle) for cycle in cycles],
        "covered_ordered_edge_pairs": covered,
        "status": status,
        "exact_hsep": None,
        "packing_lower_bound": None,
        "complete_hamiltonian_cycle_universe": None,
    }


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="ascii", newline="\n")
    os.replace(temporary, path)


def _load_record(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(value, dict):
        raise ValueError(f"record is not an object: {path}")
    return value


def _resolve_tail_record(record: dict[str, Any], *, initial_pool_limit: int) -> dict[str, Any]:
    edges = tuple(tuple(map(int, edge)) for edge in record["edges"])
    initial_cycles = tuple(tuple(map(int, cycle)) for cycle in record["cycles"])
    pool = set(initial_cycles)
    selected = solve_set_cover(edges, tuple(sorted(pool)), 48)
    if selected is not None and record["canonical_graph_hash"] != BARNIE_HASH:
        ordered = tuple(sorted(pool))
        chosen = tuple(ordered[index] for index in selected)
        record.update(
            status="verified_le48_greedy_pool",
            cover_size=len(chosen),
            cycles=[list(cycle) for cycle in chosen],
            cycle_generation_method="set_cover_over_regenerated_greedy_pool",
        )
        return record

    enumerator = enumerate_hamiltonian_cycles(edges, ORDER)
    exhausted = True
    new_since_solve = 0
    for cycle in enumerator:
        normalized = normalize_cycle(cycle)
        if normalized not in pool:
            pool.add(normalized)
            new_since_solve += 1
        if new_since_solve >= 8:
            ordered = tuple(sorted(pool))
            selected = solve_set_cover(edges, ordered, 48)
            if selected is not None and record["canonical_graph_hash"] != BARNIE_HASH:
                chosen = tuple(ordered[index] for index in selected)
                record.update(
                    status="verified_le48_augmented_pool",
                    cover_size=len(chosen),
                    cycles=[list(item) for item in chosen],
                    cycle_generation_method="deterministic_enumeration_prefix_set_cover",
                    augmented_pool_size=len(ordered),
                )
                return record
            new_since_solve = 0
        if len(pool) >= initial_pool_limit:
            exhausted = False
            break

    ordered = tuple(sorted(pool))
    selected = solve_set_cover(edges, ordered, 48)
    if selected is not None and record["canonical_graph_hash"] != BARNIE_HASH:
        chosen = tuple(ordered[index] for index in selected)
        record.update(
            status="verified_le48_augmented_pool",
            cover_size=len(chosen),
            cycles=[list(item) for item in chosen],
            cycle_generation_method="deterministic_enumeration_prefix_set_cover",
            augmented_pool_size=len(ordered),
        )
        return record
    if not exhausted:
        record.update(
            status="tail_needs_complete_enumeration",
            augmented_pool_size=len(ordered),
        )
        return record

    # The prefix iterator exhausted, so ``ordered`` is the complete universe.
    exact_cover: tuple[int, ...] | None = None
    exact_value: int | None = None
    for bound in range(49, len(ordered) + 1):
        exact_cover = solve_set_cover(edges, ordered, bound)
        if exact_cover is not None:
            exact_value = bound
            break
    if exact_cover is None or exact_value is None:
        raise RuntimeError("complete Hamiltonian universe has no separating cover")
    packing = solve_packing_lower_bound(edges, ordered, exact_value)
    if packing is None:
        record.update(
            status="exact_unresolved_missing_packing",
            complete_hamiltonian_cycle_universe=[list(item) for item in ordered],
            complete_hamiltonian_cycle_count=len(ordered),
            optimization_upper_bound=exact_value,
        )
        return record
    chosen = tuple(ordered[index] for index in exact_cover)
    record.update(
        status=(
            "barnie_exact_verified_pending_independent"
            if record["canonical_graph_hash"] == BARNIE_HASH
            else "non_barnie_exact_ge49_pending_independent"
        ),
        cover_size=len(chosen),
        cycles=[list(item) for item in chosen],
        cycle_generation_method="complete_enumeration_exact_set_cover",
        exact_hsep=exact_value,
        packing_lower_bound=[list(item) for item in packing],
        complete_hamiltonian_cycle_universe=[list(item) for item in ordered],
        complete_hamiltonian_cycle_count=len(ordered),
    )
    return record


def _version(package: str) -> str | None:
    try:
        return importlib_metadata.version(package)
    except importlib_metadata.PackageNotFoundError:
        return None


def _git_facts(root: Path) -> dict[str, Any]:
    def run(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    try:
        return {
            "commit": run("rev-parse", "HEAD"),
            "status_porcelain": run("status", "--short"),
        }
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "status_porcelain": None}


def _write_canonical_jsonl(records_dir: Path, output: Path) -> str:
    temporary = output.with_name(output.name + ".tmp")
    digest = sha256()
    with temporary.open("wb") as destination:
        for index in range(EXPECTED_GRAPH_COUNT):
            record = _load_record(records_dir / f"{index:05d}.json")
            data = (canonical_json(record) + "\n").encode("ascii")
            destination.write(data)
            digest.update(data)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, output)
    return digest.hexdigest()


def _summaries(records_dir: Path, output_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    statuses = Counter()
    covers = Counter()
    for index in range(EXPECTED_GRAPH_COUNT):
        record = _load_record(records_dir / f"{index:05d}.json")
        statuses[record["status"]] += 1
        covers[int(record["cover_size"])] += 1
        rows.append(
            {
                "plantri_rank": record["plantri_rank"],
                "generation_index": record["generation_index"],
                "canonical_graph_hash": record["canonical_graph_hash"],
                "source_greedy_size": record["source_greedy_size"],
                "cover_size": record["cover_size"],
                "status": record["status"],
                "exact_hsep": record.get("exact_hsep"),
            }
        )
    csv_path = output_dir / "global_summary.csv"
    with csv_path.open("w", encoding="ascii", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    barnie = next(row for row in rows if row["canonical_graph_hash"] == BARNIE_HASH)
    non_barnie_bad = [
        row
        for row in rows
        if row["canonical_graph_hash"] != BARNIE_HASH
        and not str(row["status"]).startswith("verified_le48")
    ]
    conclusion = (
        "BARNIE_49_UNIQUE_ORDER36_MAXIMUM"
        if barnie["exact_hsep"] == 49 and not non_barnie_bad
        else "UNRESOLVED"
    )
    summary = {
        "schema": "barnette-hsep-order36-global-summary-v1",
        "graph_count": len(rows),
        "non_barnie_graph_count": len(rows) - 1,
        "barnie_hash": BARNIE_HASH,
        "barnie_exact_hsep": barnie["exact_hsep"],
        "status_distribution": dict(sorted(statuses.items())),
        "cover_size_distribution": {str(k): v for k, v in sorted(covers.items())},
        "unresolved_non_barnie_count": len(non_barnie_bad),
        "unresolved_non_barnie_hashes": [row["canonical_graph_hash"] for row in non_barnie_bad],
        "conclusion": conclusion,
    }
    _atomic_json(output_dir / "global_summary.json", summary)
    return summary


def _write_sha256s(output_dir: Path) -> None:
    excluded = {"SHA256SUMS.txt"}
    paths = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name not in excluded and ".work" not in path.parts
    )
    lines = [f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}" for path in paths]
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def run_audit(
    *,
    source_path: Path,
    output_dir: Path,
    plantri_executable: Path,
    workers: int,
    resume: bool,
    initial_pool_limit: int,
    repo_root: Path,
) -> dict[str, Any]:
    if not 1 <= workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / ".work"
    records_dir = work_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    configuration = {
        "schema": METADATA_SCHEMA,
        "source_path": str(source_path.resolve()),
        "source_sha256": sha256_file(source_path),
        "order": ORDER,
        "expected_graph_count": EXPECTED_GRAPH_COUNT,
        "barnie_hash": BARNIE_HASH,
        "workers": workers,
        "initial_pool_limit": initial_pool_limit,
    }
    config_path = work_dir / "configuration.json"
    if config_path.exists():
        existing = _load_record(config_path)
        logical_keys = set(configuration) - {"workers"}
        if any(existing.get(key) != configuration[key] for key in logical_keys):
            raise ValueError("resume configuration differs from existing audit")
        if not resume:
            raise FileExistsError("audit work exists; pass --resume")
    else:
        _atomic_json(config_path, configuration)

    source_records = load_source_records(source_path)
    source_by_index = {item.generation_index: item for item in source_records}
    version = detect_plantri_version(locate_plantri(plantri_executable))
    started = datetime.now(timezone.utc)
    started_perf = perf_counter()
    futures: dict[Any, int] = {}

    def collect(done: Iterable[Any]) -> None:
        for future in done:
            index = futures.pop(future)
            record = future.result()
            _atomic_json(records_dir / f"{index:05d}.json", record)

    executor = ProcessPoolExecutor(max_workers=workers)
    generated = 0
    try:
        with stream_barnette_graphs(version, ORDER) as stream:
            for index, embedded in enumerate(stream):
                generated += 1
                source = source_by_index.get(index)
                if source is None:
                    raise RuntimeError("plantri produced more than the expected graph count")
                graph_hash = canonical_graph_hash(embedded)
                if graph_hash != source.canonical_graph_hash:
                    raise RuntimeError(f"census mismatch at generation index {index}")
                destination = records_dir / f"{index:05d}.json"
                if destination.exists():
                    existing = _load_record(destination)
                    if existing.get("canonical_graph_hash") != graph_hash:
                        raise RuntimeError(f"resume record mismatch at index {index}")
                    continue
                task = GenerationTask(
                    source=source,
                    planar_code=encode_planar_code(embedded.rotation_system),
                )
                futures[executor.submit(_certificate_record, task)] = index
                if len(futures) >= 2 * workers:
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    collect(done)
            if futures:
                done, _ = wait(futures)
                collect(done)
            plantri_stderr = stream.stderr_text
    finally:
        executor.shutdown(wait=True, cancel_futures=False)
    if generated != EXPECTED_GRAPH_COUNT:
        raise RuntimeError(f"plantri generated {generated}, expected {EXPECTED_GRAPH_COUNT}")

    tail_paths: list[Path] = []
    for index in range(EXPECTED_GRAPH_COUNT):
        path = records_dir / f"{index:05d}.json"
        record = _load_record(path)
        if record["canonical_graph_hash"] == BARNIE_HASH or record["source_greedy_size"] > 48:
            if not str(record["status"]).startswith("verified_le48") and not (
                record["canonical_graph_hash"] == BARNIE_HASH and record.get("exact_hsep") == 49
            ):
                tail_paths.append(path)

    # Tail work is intentionally separate from census-wide greedy generation.
    tail_futures: dict[Any, Path] = {}
    with ProcessPoolExecutor(max_workers=workers) as tail_executor:
        for path in tail_paths:
            record = _load_record(path)
            tail_futures[tail_executor.submit(
                _resolve_tail_record, record, initial_pool_limit=initial_pool_limit
            )] = path
        for future in tail_futures:
            path = tail_futures[future]
            _atomic_json(path, future.result())

    unresolved_complete = [
        records_dir / f"{index:05d}.json"
        for index in range(EXPECTED_GRAPH_COUNT)
        if _load_record(records_dir / f"{index:05d}.json")["status"]
        == "tail_needs_complete_enumeration"
    ]
    for path in unresolved_complete:
        record = _load_record(path)
        _atomic_json(path, _resolve_tail_record(record, initial_pool_limit=10**9))

    certificates_path = output_dir / "order36_certificates.jsonl"
    canonical_digest = _write_canonical_jsonl(records_dir, certificates_path)
    summary = _summaries(records_dir, output_dir)
    metadata = {
        **configuration,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": perf_counter() - started_perf,
        "plantri": {
            "version": version.version,
            "executable": str(version.executable),
            "executable_sha256": version.executable_sha256,
            "command": [str(version.executable), "-b", "-c3", "-d", "20", "-"],
            "stderr": plantri_stderr,
        },
        "solver": {
            "greedy": "PySAT Glucose3 constrained Hamiltonian session",
            "set_cover": "PySAT Glucose3 with sequential-cardinality bound",
            "packing": "PySAT Glucose3 with sequential-cardinality constraints",
            "random_seed": None,
        },
        "environment": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "networkx": _version("networkx"),
            "python_sat": _version("python-sat"),
            "barnette_search": _version("barnette-search"),
        },
        "git": _git_facts(repo_root),
        "canonical_uncompressed_certificates_sha256": canonical_digest,
        "canonical_uncompressed_certificates_bytes": certificates_path.stat().st_size,
        "summary_conclusion": summary["conclusion"],
        "barnie_exact_source": {
            "review_bundle": "E:/barnette-2f96-review.zip",
            "review_bundle_sha256": (
                sha256_file(Path("E:/barnette-2f96-review.zip"))
                if Path("E:/barnette-2f96-review.zip").exists()
                else None
            ),
            "imported_exact_certificates": False,
            "note": "review bundle lacked primal/lower files; exact certificates regenerated",
        },
    }
    _atomic_json(output_dir / "order36_metadata.json", metadata)
    _write_sha256s(output_dir)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plantri", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--initial-pool-limit", type=int, default=256)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_audit(
        source_path=args.source,
        output_dir=args.output_dir,
        plantri_executable=args.plantri,
        workers=args.workers,
        resume=args.resume,
        initial_pool_limit=args.initial_pool_limit,
        repo_root=Path.cwd(),
    )
    print(canonical_json(summary))
    return 0 if summary["conclusion"] != "UNRESOLVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
