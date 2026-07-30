"""Independent review of saved strong-flexibility extremal artifacts.

The completed analysis files are immutable inputs. This module reconstructs
every selected graph and constraint universe, uses fresh MiniSat22 and Glucose3
sessions, independently verifies certificates and edge constraints, compares
deterministic metrics, and writes separate resumable review artifacts.
"""

from __future__ import annotations

import argparse
from collections.abc import Hashable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from importlib import metadata
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import queue
import random
import re
import socket
import threading
from time import perf_counter
from typing import Any

import networkx as nx

from .constrained_hamiltonian import find_constrained_hamiltonian_cycle
from .constrained_hamiltonian_sat import ConstrainedHamiltonianSatSession, Edge
from .hamiltonian import verify_hamiltonian_cycle
from .planar_code import canonical_graph_hash, iter_planar_code
from .result_storage import (
    append_checkpoint,
    read_checkpoint,
    read_jsonl,
    write_jsonl_atomic,
)
from .validation import validate_barnette_graph


DEFAULT_SAMPLE_SEED = 20260730
PROTECTED_MODULES = (
    "validation.py",
    "hamiltonian.py",
    "hamiltonian_sat.py",
    "constrained_hamiltonian.py",
    "constrained_hamiltonian_sat.py",
    "planar_code.py",
    "plantri.py",
    "edge_flexibility.py",
    "three_edge_path_flexibility.py",
    "flexibility_common.py",
    "result_storage.py",
)


@dataclass(frozen=True, slots=True)
class ReviewConstraint:
    """One independently reconstructed required/forbidden query."""

    key: Any
    required_edges: tuple[Edge, ...]
    forbidden_edges: tuple[Edge, ...]


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    """All immutable source artifacts and leaderboard provenance for one hash."""

    graph_hash: str
    planar_code_paths: tuple[str, ...]
    embedding_paths: tuple[str, ...]
    report_paths: tuple[str, ...]
    leaderboard_categories: tuple[str, ...]
    original_record: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewOptions:
    """Logical review configuration recorded in metadata."""

    sample_seed: int
    backtracking_timeout_seconds: float
    workers: int


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value


def _edge(left: Hashable, right: Hashable, rank: dict[Hashable, int]) -> Edge:
    return (left, right) if rank[left] < rank[right] else (right, left)


def _deterministic_edges(graph: nx.Graph) -> tuple[Edge, ...]:
    nodes = tuple(graph.nodes())
    rank = {vertex: index for index, vertex in enumerate(nodes)}
    return tuple(
        sorted(
            (_edge(left, right, rank) for left, right in graph.edges()),
            key=lambda item: (rank[item[0]], rank[item[1]]),
        )
    )


def enumerate_all_edge_constraints(graph: nx.Graph) -> tuple[ReviewConstraint, ...]:
    """Independently enumerate all ordered pairs of distinct graph edges."""
    edges = _deterministic_edges(graph)
    return tuple(
        ReviewConstraint(
            key=(required, forbidden),
            required_edges=(required,),
            forbidden_edges=(forbidden,),
        )
        for required in edges
        for forbidden in edges
        if required != forbidden
    )


def enumerate_path_constraints(graph: nx.Graph) -> tuple[ReviewConstraint, ...]:
    """Independently enumerate canonical simple length-three path queries."""
    nodes = tuple(graph.nodes())
    rank = {vertex: index for index, vertex in enumerate(nodes)}
    paths: set[tuple[Hashable, Hashable, Hashable, Hashable]] = set()
    for middle_left, middle_right in _deterministic_edges(graph):
        for outer_left in sorted(
            (v for v in graph.neighbors(middle_left) if v != middle_right),
            key=rank.__getitem__,
        ):
            for outer_right in sorted(
                (v for v in graph.neighbors(middle_right) if v != middle_left),
                key=rank.__getitem__,
            ):
                path = (outer_left, middle_left, middle_right, outer_right)
                if len(set(path)) != 4:
                    continue
                reverse = tuple(reversed(path))
                canonical = min(
                    (path, reverse),
                    key=lambda item: tuple(rank[vertex] for vertex in item),
                )
                paths.add(canonical)
    ordered = sorted(paths, key=lambda item: tuple(rank[v] for v in item))
    return tuple(
        ReviewConstraint(
            key=path,
            required_edges=(_edge(path[1], path[2], rank),),
            forbidden_edges=(
                _edge(path[0], path[1], rank),
                _edge(path[2], path[3], rank),
            ),
        )
        for path in ordered
    )


def _cycle_satisfies(
    cycle: tuple[Hashable, ...], constraint: ReviewConstraint
) -> bool:
    selected = {
        frozenset((left, right)) for left, right in zip(cycle, cycle[1:])
    }
    return all(
        frozenset(edge) in selected for edge in constraint.required_edges
    ) and all(
        frozenset(edge) not in selected for edge in constraint.forbidden_edges
    )


def _certificate_hash(cycle: tuple[Hashable, ...]) -> str:
    payload = json.dumps(tuple(map(repr, cycle)), separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _run_cover(
    graph: nx.Graph,
    constraints: tuple[ReviewConstraint, ...],
    *,
    solver: str,
) -> dict[str, Any]:
    uncovered = set(range(len(constraints)))
    certificate_for: dict[int, tuple[Hashable, ...]] = {}
    query_times: list[float] = []
    newly_covered: list[int] = []
    witness_hashes: list[str] = []
    subtour_iterations = 0
    hardest_key: Any | None = None
    maximum_time = -1.0
    failed_key: Any | None = None
    with ConstrainedHamiltonianSatSession(graph, solver=solver) as session:
        while uncovered:
            index = min(uncovered)
            constraint = constraints[index]
            result = session.solve(
                required_edges=constraint.required_edges,
                forbidden_edges=constraint.forbidden_edges,
            )
            query_times.append(result.runtime_seconds)
            subtour_iterations += result.subtour_iterations
            if result.runtime_seconds > maximum_time:
                maximum_time = result.runtime_seconds
                hardest_key = constraint.key
            if result.cycle is None:
                failed_key = constraint.key
                break
            if not verify_hamiltonian_cycle(graph, result.cycle):
                raise RuntimeError(f"{result.solver_name} returned an invalid cycle")
            if not _cycle_satisfies(result.cycle, constraint):
                raise RuntimeError(
                    f"{result.solver_name} returned a constraint-violating cycle"
                )
            certified = tuple(
                candidate
                for candidate in sorted(uncovered)
                if _cycle_satisfies(result.cycle, constraints[candidate])
            )
            if index not in certified:
                raise RuntimeError("review witness did not certify its trigger")
            for candidate in certified:
                certificate_for[candidate] = result.cycle
            newly_covered.append(len(certified))
            witness_hashes.append(_certificate_hash(result.cycle))
            uncovered.difference_update(certified)
        subtour_constraints = session.cumulative_subtour_constraints
    total = len(constraints)
    witnesses = len(query_times) - int(failed_key is not None)
    return {
        "property_satisfied": not uncovered and failed_key is None,
        "failed_constraint": failed_key,
        "total_constraints": total,
        "number_of_sat_calls": len(query_times),
        "number_of_witness_cycles": witnesses,
        "witness_cover_ratio": witnesses / total if total else 0.0,
        "average_constraints_per_witness": total / witnesses if witnesses else 0.0,
        "maximum_constraints_by_one_witness": max(newly_covered, default=0),
        "total_subtour_iterations": subtour_iterations,
        "total_subtour_constraints": subtour_constraints,
        "total_sat_time_seconds": sum(query_times),
        "median_query_time_seconds": _percentile(query_times, 0.5),
        "p95_query_time_seconds": _percentile(query_times, 0.95),
        "p99_query_time_seconds": _percentile(query_times, 0.99),
        "maximum_query_time_seconds": max(query_times, default=0.0),
        "hardest_constraint": hardest_key,
        "certified_constraint_count": len(certificate_for),
        "sat_certified_constraint_count": len(certificate_for),
        "unsat_proved_constraint_count": int(failed_key is not None),
        "witness_certificate_hashes": witness_hashes,
    }


def deterministic_backtracking_indices(
    total: int,
    *,
    graph_order: int,
    graph_hash: str,
    analysis_name: str,
    hardest_index: int | None,
    seed: int,
) -> tuple[int, ...]:
    """Select exhaustive small-order or fixed-seed large-order checks."""
    if total == 0:
        return ()
    if graph_order <= 24:
        return tuple(range(total))
    mandatory = {0, total - 1}
    if hardest_index is not None:
        mandatory.add(hardest_index)
    available = sorted(set(range(total)) - mandatory)
    digest = sha256(f"{seed}:{graph_hash}:{analysis_name}".encode()).digest()
    random_seed = int.from_bytes(digest[:8], "big")
    generator = random.Random(random_seed)
    sampled = generator.sample(available, min(10, len(available)))
    return tuple(sorted(mandatory | set(sampled)))


def _backtracking_with_timeout(
    graph: nx.Graph,
    constraint: ReviewConstraint,
    timeout_seconds: float,
) -> dict[str, Any]:
    results: queue.Queue[tuple[str, Any, float]] = queue.Queue(maxsize=1)

    def target() -> None:
        started = perf_counter()
        try:
            cycle = find_constrained_hamiltonian_cycle(
                graph,
                required_edges=constraint.required_edges,
                forbidden_edges=constraint.forbidden_edges,
            )
            results.put(("result", cycle, perf_counter() - started))
        except BaseException as error:
            results.put(("error", repr(error), perf_counter() - started))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        return {
            "status": "timeout",
            "satisfiable": None,
            "runtime_seconds": timeout_seconds,
        }
    status, value, runtime = results.get_nowait()
    if status == "error":
        raise RuntimeError(f"backtracking review failed: {value}")
    cycle = value
    if cycle is not None and (
        not verify_hamiltonian_cycle(graph, cycle)
        or not _cycle_satisfies(cycle, constraint)
    ):
        raise RuntimeError("backtracking review returned an invalid certificate")
    return {
        "status": "complete",
        "satisfiable": cycle is not None,
        "runtime_seconds": runtime,
    }


def _metric_mapping(analysis_name: str) -> dict[str, str]:
    average = (
        "average_pairs_certified_per_witness"
        if analysis_name == "all_edge_pairs"
        else "average_paths_certified_per_witness"
    )
    maximum = (
        "maximum_pairs_certified_by_one_witness"
        if analysis_name == "all_edge_pairs"
        else "maximum_paths_certified_by_one_witness"
    )
    total = (
        "total_ordered_edge_pairs"
        if analysis_name == "all_edge_pairs"
        else "number_of_distinct_three_edge_paths"
    )
    return {
        "total_constraints": total,
        "number_of_sat_calls": "number_of_constrained_sat_calls",
        "number_of_witness_cycles": "number_of_witness_cycles",
        "witness_cover_ratio": "witness_cover_ratio",
        "average_constraints_per_witness": average,
        "maximum_constraints_by_one_witness": maximum,
        "total_subtour_iterations": "total_subtour_iterations",
        "total_subtour_constraints": "total_subtour_constraints",
    }


def _deterministic_metric_comparison(
    review: dict[str, Any], original: dict[str, Any], analysis_name: str
) -> tuple[bool, dict[str, dict[str, Any]]]:
    differences: dict[str, dict[str, Any]] = {}
    for review_field, original_field in _metric_mapping(analysis_name).items():
        review_value = review[review_field]
        original_value = original[original_field]
        if review_value != original_value:
            differences[review_field] = {
                "recomputed": review_value,
                "original": original_value,
            }
    return not differences, differences


def _hardest_index(
    constraints: tuple[ReviewConstraint, ...], original: dict[str, Any], analysis: str
) -> int | None:
    field = "hardest_ordered_pair" if analysis == "all_edge_pairs" else "hardest_path"
    target = _freeze(original.get(field))
    for index, constraint in enumerate(constraints):
        if _freeze(constraint.key) == target:
            return index
    return None


def _write_gzip_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, indent=2, sort_keys=True, default=repr)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: Any) -> None:
    payload = (
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    ).encode()
    _write_bytes_atomic(path, payload)


def _protected_module_hashes() -> dict[str, str | None]:
    source_directory = Path(__file__).resolve().parent
    return {
        name: (
            _file_sha256(source_directory / name)
            if (source_directory / name).is_file()
            else None
        )
        for name in PROTECTED_MODULES
    }


def _escalate(
    graph: nx.Graph,
    planar_code: bytes,
    embedding: dict[str, Any],
    graph_hash: str,
    analysis: str,
    constraint: ReviewConstraint,
    output_root: Path,
    timeout_seconds: float,
    reason: str,
) -> str:
    directory = output_root / graph_hash / analysis
    directory.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomic(directory / "graph.planar_code", planar_code)
    _write_gzip_json(directory / "embedding.json.gz", embedding)
    solver_results: dict[str, Any] = {}
    for solver in ("minisat22", "glucose3"):
        with ConstrainedHamiltonianSatSession(graph, solver=solver) as session:
            result = session.solve(
                required_edges=constraint.required_edges,
                forbidden_edges=constraint.forbidden_edges,
            )
            session.export_dimacs(
                directory / f"{solver}.cnf",
                required_edges=constraint.required_edges,
                forbidden_edges=constraint.forbidden_edges,
            )
        solver_results[solver] = asdict(result)
    backtracking = _backtracking_with_timeout(
        graph, constraint, timeout_seconds
    )
    report = {
        "classification": "discrepancy candidate; manual review required",
        "reason": reason,
        "graph_hash": graph_hash,
        "analysis": analysis,
        "constraint": asdict(constraint),
        "solver_results": solver_results,
        "backtracking": backtracking,
        "solver_stdout": "PySAT in-process solvers emit no stdout in this configuration",
        "solver_stderr": "PySAT in-process solvers emit no stderr in this configuration",
    }
    _write_gzip_json(directory / "discrepancy_report.json.gz", report)
    return str(directory)


def _escalate_artifact(
    bundle: ArtifactBundle,
    output_root: Path,
    reason: str,
) -> str:
    """Preserve immutable artifact copies and a report after validation failure."""
    directory = output_root / bundle.graph_hash / "artifact_validation"
    directory.mkdir(parents=True, exist_ok=True)
    copies: dict[str, list[dict[str, Any]]] = {
        "planar_code": [],
        "embedding": [],
        "report": [],
    }
    groups = (
        ("planar_code", bundle.planar_code_paths),
        ("embedding", bundle.embedding_paths),
        ("report", bundle.report_paths),
    )
    for kind, paths in groups:
        for index, raw_path in enumerate(paths):
            source = Path(raw_path)
            target = directory / f"source_{kind}_{index}{source.suffix}"
            content = source.read_bytes()
            _write_bytes_atomic(target, content)
            copies[kind].append(
                {
                    "source_path": str(source),
                    "copied_path": str(target),
                    "sha256": sha256(content).hexdigest(),
                }
            )
    _write_gzip_json(
        directory / "artifact_discrepancy_report.json.gz",
        {
            "classification": "artifact discrepancy; manual review required",
            "reason": reason,
            "graph_hash": bundle.graph_hash,
            "source_leaderboard_categories": bundle.leaderboard_categories,
            "preserved_artifacts": copies,
        },
    )
    return str(directory)


def validate_artifact_bundle(bundle: ArtifactBundle) -> tuple[Any, dict[str, Any]]:
    """Validate duplicate artifacts, hash, embedding, order, and command metadata."""
    planar_paths = tuple(Path(path) for path in bundle.planar_code_paths)
    embedding_paths = tuple(Path(path) for path in bundle.embedding_paths)
    report_paths = tuple(Path(path) for path in bundle.report_paths)
    if not planar_paths or not embedding_paths or not report_paths:
        raise ValueError(f"incomplete artifact bundle for {bundle.graph_hash}")
    planar_hashes = {_file_sha256(path) for path in planar_paths}
    embedding_hashes = {_file_sha256(path) for path in embedding_paths}
    if len(planar_hashes) != 1 or len(embedding_hashes) != 1:
        raise ValueError(f"duplicate artifacts disagree for {bundle.graph_hash}")
    planar_code = planar_paths[0].read_bytes()
    [embedded] = iter_planar_code(BytesIO(planar_code), require_header=True)
    recomputed_hash = canonical_graph_hash(embedded)
    if recomputed_hash != bundle.graph_hash:
        raise ValueError(
            f"canonical hash mismatch: expected {bundle.graph_hash}, got {recomputed_hash}"
        )
    validation = validate_barnette_graph(embedded.graph)
    if not validation.valid:
        raise ValueError(f"artifact is not a Barnette graph: {validation.rejection_reasons}")
    embedding = json.loads(embedding_paths[0].read_text(encoding="utf-8"))
    if embedding.get("canonical_graph_hash") != bundle.graph_hash:
        raise ValueError("embedding canonical hash is missing or incorrect")
    if tuple(map(tuple, embedding.get("rotation_system", ()))) != embedded.rotation_system:
        raise ValueError("stored rotation system does not match planar code")
    if tuple(map(tuple, embedding.get("faces", ()))) != embedded.faces:
        raise ValueError("stored faces do not match planar code")
    if tuple(embedding.get("face_size_multiset", ())) != embedded.face_size_multiset:
        raise ValueError("stored face-size multiset does not match planar code")
    commands = {
        tuple(json.loads(path.read_text(encoding="utf-8"))["plantri_command"])
        for path in embedding_paths
    }
    if len(commands) != 1 or not next(iter(commands)):
        raise ValueError("generating plantri command is missing or inconsistent")
    for path in report_paths:
        report = path.read_text(encoding="utf-8")
        if f"Canonical graph hash: {bundle.graph_hash}" not in report:
            raise ValueError("human-readable report has the wrong graph hash")
        match = re.search(r"Graph order: (\d+)", report)
        if match is None or int(match.group(1)) != embedded.graph.number_of_nodes():
            raise ValueError("human-readable report has the wrong graph order")
        if "plantri command:" not in report:
            raise ValueError("human-readable report lacks the plantri command")
    status = {
        "canonical_hash_matches": True,
        "duplicate_artifacts_match": True,
        "embedding_matches_graph": True,
        "graph_order": embedded.graph.number_of_nodes(),
        "plantri_command": next(iter(commands)),
        "planar_code_sha256": next(iter(planar_hashes)),
        "embedding_sha256": next(iter(embedding_hashes)),
        "validator_result": asdict(validation),
    }
    return embedded, status


def _review_analysis(
    graph: nx.Graph,
    constraints: tuple[ReviewConstraint, ...],
    original: dict[str, Any],
    analysis_name: str,
    graph_hash: str,
    graph_order: int,
    sample_seed: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    minisat = _run_cover(graph, constraints, solver="minisat22")
    glucose = _run_cover(graph, constraints, solver="glucose3")
    engine_agreements = (
        len(constraints)
        if minisat["property_satisfied"] == glucose["property_satisfied"]
        else 0
    )
    metric_match, metric_differences = _deterministic_metric_comparison(
        glucose, original, analysis_name
    )
    original_property = bool(original["property_satisfied"])
    result_agreement = (
        minisat["property_satisfied"]
        == glucose["property_satisfied"]
        == original_property
    )
    hardest = _hardest_index(constraints, original, analysis_name)
    indices = deterministic_backtracking_indices(
        len(constraints),
        graph_order=graph_order,
        graph_hash=graph_hash,
        analysis_name=analysis_name,
        hardest_index=hardest,
        seed=sample_seed,
    )
    agreements = timeouts = 0
    checks: list[dict[str, Any]] = []
    for index in indices:
        result = _backtracking_with_timeout(
            graph, constraints[index], timeout_seconds
        )
        checks.append({"constraint_index": index, "constraint": constraints[index].key, **result})
        if result["status"] == "timeout":
            timeouts += 1
        elif result["satisfiable"] == minisat["property_satisfied"]:
            agreements += 1
    return {
        "constraint_count": len(constraints),
        "minisat22": minisat,
        "glucose3": glucose,
        "minisat22_glucose3_agreements": engine_agreements,
        "original_result_agreement": result_agreement,
        "deterministic_metric_agreement": metric_match,
        "deterministic_metric_differences": metric_differences,
        "timing_comparison": {
            "original_total_sat_time_seconds": original["total_sat_wall_time_seconds"],
            "review_glucose3_total_sat_time_seconds": glucose["total_sat_time_seconds"],
            "review_minisat22_total_sat_time_seconds": minisat["total_sat_time_seconds"],
            "original_maximum_query_time_seconds": original["maximum_query_time_seconds"],
            "review_glucose3_maximum_query_time_seconds": glucose["maximum_query_time_seconds"],
            "review_minisat22_maximum_query_time_seconds": minisat["maximum_query_time_seconds"],
            "original_hardest_constraint": original.get(
                "hardest_ordered_pair"
                if analysis_name == "all_edge_pairs"
                else "hardest_path"
            ),
            "review_glucose3_hardest_constraint": glucose["hardest_constraint"],
            "review_minisat22_hardest_constraint": minisat["hardest_constraint"],
        },
        "backtracking_policy_indices": indices,
        "backtracking_checks": checks,
        "backtracking_check_count": len(indices),
        "backtracking_agreements": agreements,
        "backtracking_timeouts": timeouts,
    }


def _review_worker(
    bundle: ArtifactBundle,
    options: ReviewOptions,
    report_root: str,
) -> dict[str, Any]:
    started = perf_counter()
    try:
        embedded, artifact_status = validate_artifact_bundle(bundle)
    except BaseException as error:
        reason = repr(error)
        report_path = _escalate_artifact(
            bundle, Path(report_root), reason
        )
        return {
            "graph_hash": bundle.graph_hash,
            "source_leaderboard_categories": bundle.leaderboard_categories,
            "artifact_hash_status": False,
            "validator_status": False,
            "overall_review_status": "artifact_discrepancy",
            "error": reason,
            "discrepancy_report_path": report_path,
            "runtime_seconds": perf_counter() - started,
        }
    graph = embedded.graph
    record: dict[str, Any] = {
        "graph_hash": bundle.graph_hash,
        "order": graph.number_of_nodes(),
        "source_leaderboard_categories": bundle.leaderboard_categories,
        "artifact_hash_status": True,
        "embedding_consistency_status": True,
        "validator_status": True,
        "artifact_validation": artifact_status,
    }
    analyses = (
        (
            "all_edge_pairs",
            enumerate_all_edge_constraints(graph),
        ),
        (
            "three_edge_paths",
            enumerate_path_constraints(graph),
        ),
    )
    for analysis_name, constraints in analyses:
        original = bundle.original_record[analysis_name]
        review = _review_analysis(
            graph,
            constraints,
            original,
            analysis_name,
            bundle.graph_hash,
            graph.number_of_nodes(),
            options.sample_seed,
            options.backtracking_timeout_seconds,
        )
        record[analysis_name] = review
        discrepancy = (
            not review["minisat22"]["property_satisfied"]
            or not review["glucose3"]["property_satisfied"]
            or not review["original_result_agreement"]
            or review["minisat22_glucose3_agreements"] != len(constraints)
            or not review["deterministic_metric_agreement"]
            or review["backtracking_agreements"]
            + review["backtracking_timeouts"]
            != review["backtracking_check_count"]
        )
        if discrepancy:
            failed = review["minisat22"].get("failed_constraint")
            target = constraints[0]
            if failed is not None:
                frozen = _freeze(failed)
                target = next(
                    constraint
                    for constraint in constraints
                    if _freeze(constraint.key) == frozen
                )
            path = _escalate(
                graph,
                Path(bundle.planar_code_paths[0]).read_bytes(),
                json.loads(Path(bundle.embedding_paths[0]).read_text(encoding="utf-8")),
                bundle.graph_hash,
                analysis_name,
                target,
                Path(report_root),
                options.backtracking_timeout_seconds,
                "solver, deterministic metric, or backtracking mismatch",
            )
            record["discrepancy_report_path"] = path
            record["overall_review_status"] = "discrepancy_requires_review"
            record["runtime_seconds"] = perf_counter() - started
            return record
    total_checks = sum(record[name]["backtracking_check_count"] for name, _ in analyses)
    total_agreements = sum(record[name]["backtracking_agreements"] for name, _ in analyses)
    total_timeouts = sum(record[name]["backtracking_timeouts"] for name, _ in analyses)
    record.update(
        {
            "all_edge_result_agreement": record["all_edge_pairs"]["original_result_agreement"],
            "three_edge_path_result_agreement": record["three_edge_paths"]["original_result_agreement"],
            "minisat22_glucose3_agreement": all(
                record[name]["minisat22_glucose3_agreements"]
                == record[name]["constraint_count"]
                for name, _ in analyses
            ),
            "number_of_backtracking_checks": total_checks,
            "number_of_backtracking_agreements": total_agreements,
            "number_of_backtracking_timeouts": total_timeouts,
            "deterministic_metric_agreement": all(
                record[name]["deterministic_metric_agreement"]
                for name, _ in analyses
            ),
            "overall_review_status": (
                "verified_with_backtracking_timeouts"
                if total_timeouts
                else "verified"
            ),
            "runtime_seconds": perf_counter() - started,
        }
    )
    if total_timeouts:
        timeout_path = Path(report_root) / bundle.graph_hash / "timeout_report.json.gz"
        timeout_path.parent.mkdir(parents=True, exist_ok=True)
        _write_gzip_json(
            timeout_path,
            {
                "classification": "SAT verified; backtracking checks inconclusive by timeout",
                "graph_hash": bundle.graph_hash,
                "all_edge_timeouts": record["all_edge_pairs"]["backtracking_timeouts"],
                "path_timeouts": record["three_edge_paths"]["backtracking_timeouts"],
            },
        )
        record["timeout_report_path"] = str(timeout_path)
    return record


def discover_artifacts(extremal_directory: Path) -> tuple[ArtifactBundle, ...]:
    """Discover and deduplicate hashes across every saved leaderboard."""
    categories: dict[str, set[str]] = {}
    for leaderboard in sorted(extremal_directory.glob("*/leaderboard_*.csv")):
        analysis = leaderboard.parent.name
        metric = leaderboard.stem.removeprefix("leaderboard_")
        with leaderboard.open("r", encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                graph_hash = row["canonical_graph_hash"]
                categories.setdefault(graph_hash, set()).add(
                    f"{analysis}:{metric}:rank-{row['rank']}"
                )
    source_root = extremal_directory.parent
    originals: dict[str, dict[str, Any]] = {}
    for path in sorted(source_root.glob("barnette_*.strong_flexibility.jsonl*")):
        for record in read_jsonl(path):
            graph_hash = record["canonical_graph_hash"]
            if graph_hash in originals:
                raise ValueError(f"duplicate original graph record: {graph_hash}")
            originals[graph_hash] = record
    bundles: list[ArtifactBundle] = []
    for graph_hash in sorted(categories):
        planar = tuple(
            str(path)
            for path in sorted(extremal_directory.glob(f"*/graphs/{graph_hash}.planar_code"))
        )
        embeddings = tuple(
            str(path)
            for path in sorted(extremal_directory.glob(f"*/graphs/{graph_hash}.embedding.json"))
        )
        reports = tuple(
            str(path)
            for path in sorted(extremal_directory.glob(f"*/graphs/{graph_hash}.txt"))
        )
        if graph_hash not in originals:
            raise ValueError(f"no original result record for {graph_hash}")
        bundles.append(
            ArtifactBundle(
                graph_hash=graph_hash,
                planar_code_paths=planar,
                embedding_paths=embeddings,
                report_paths=reports,
                leaderboard_categories=tuple(sorted(categories[graph_hash])),
                original_record=originals[graph_hash],
            )
        )
    return tuple(bundles)


class _PeakMemoryMonitor:
    def __init__(self) -> None:
        self.peak_bytes: int | None = None
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import psutil
        except ImportError:
            return

        def sample() -> None:
            root = psutil.Process(os.getpid())
            peak = 0
            while not self._stop.wait(0.05):
                total = 0
                try:
                    processes = [root, *root.children(recursive=True)]
                except psutil.Error:
                    processes = []
                for process in processes:
                    try:
                        total += process.memory_info().rss
                    except psutil.Error:
                        pass
                peak = max(peak, total)
                self.samples += 1
            self.peak_bytes = peak

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


def _write_summaries(records: list[dict[str, Any]], output_directory: Path) -> None:
    fields = (
        "graph_hash",
        "order",
        "source_leaderboard_categories",
        "validator_status",
        "artifact_hash_status",
        "all_edge_result_agreement",
        "three_edge_path_result_agreement",
        "minisat22_glucose3_agreement",
        "number_of_backtracking_checks",
        "number_of_backtracking_agreements",
        "number_of_backtracking_timeouts",
        "deterministic_metric_agreement",
        "original_total_sat_time_seconds",
        "minisat22_total_sat_time_seconds",
        "glucose3_total_sat_time_seconds",
        "timing_comparison",
        "overall_review_status",
        "runtime_seconds",
    )
    def write_csv_atomic(
        path: Path, rows: list[dict[str, Any]], fieldnames: Sequence[str]
    ) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(
                    output, fieldnames=fieldnames, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    summary_rows: list[dict[str, Any]] = []
    for record in records:
        row = dict(record)
        if "all_edge_pairs" in record and "three_edge_paths" in record:
            analyses = (record["all_edge_pairs"], record["three_edge_paths"])
            row["original_total_sat_time_seconds"] = sum(
                analysis["timing_comparison"]["original_total_sat_time_seconds"]
                for analysis in analyses
            )
            row["minisat22_total_sat_time_seconds"] = sum(
                analysis["minisat22"]["total_sat_time_seconds"]
                for analysis in analyses
            )
            row["glucose3_total_sat_time_seconds"] = sum(
                analysis["glucose3"]["total_sat_time_seconds"]
                for analysis in analyses
            )
            row["timing_comparison"] = json.dumps(
                {
                    "all_edge_pairs": analyses[0]["timing_comparison"],
                    "three_edge_paths": analyses[1]["timing_comparison"],
                },
                separators=(",", ":"),
            )
        summary_rows.append(row)
    write_csv_atomic(
        output_directory / "verification_summary.csv", summary_rows, fields
    )
    discrepancies = [
        record
        for record in records
        if record["overall_review_status"] != "verified"
    ]
    write_csv_atomic(
        output_directory / "discrepancy_summary.csv",
        discrepancies,
        (
            "graph_hash",
            "order",
            "overall_review_status",
            "error",
            "discrepancy_report_path",
            "timeout_report_path",
        ),
    )


def run_independent_review(
    extremal_directory: Path,
    *,
    output_directory: Path,
    workers: int = 6,
    sample_seed: int = DEFAULT_SAMPLE_SEED,
    backtracking_timeout_seconds: float = 5.0,
    resume: bool = False,
    overwrite: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Review every unique selected extremal graph with independent solver state."""
    if workers < 1 or backtracking_timeout_seconds <= 0:
        raise ValueError("workers and timeout must be positive")
    bundles = discover_artifacts(extremal_directory)
    protected_hashes_before = _protected_module_hashes()
    output_directory.mkdir(parents=True, exist_ok=True)
    final_path = output_directory / "verification_records.jsonl.gz"
    checkpoint_path = output_directory / "verification.checkpoint.jsonl"
    checkpoint_config_path = output_directory / "verification.checkpoint.config.json"
    metadata_path = output_directory / "run_metadata.json"
    if overwrite:
        for path in (
            final_path,
            checkpoint_path,
            checkpoint_config_path,
            metadata_path,
            output_directory / "verification_summary.csv",
            output_directory / "discrepancy_summary.csv",
        ):
            if path.exists():
                path.unlink()
    if final_path.exists() and not resume:
        raise FileExistsError(f"refusing to overwrite {final_path}")
    options = ReviewOptions(sample_seed, backtracking_timeout_seconds, workers)
    logical_config = {
        "extremal_input_directory": str(extremal_directory.resolve()),
        "sample_seed": sample_seed,
        "backtracking_timeout_seconds": backtracking_timeout_seconds,
    }
    if checkpoint_path.exists():
        if not resume:
            raise FileExistsError(
                f"checkpoint exists; pass --resume or --overwrite: {checkpoint_path}"
            )
        if not checkpoint_config_path.exists():
            raise RuntimeError("checkpoint configuration is missing")
        stored_config = json.loads(
            checkpoint_config_path.read_text(encoding="utf-8")
        )
        if stored_config != logical_config:
            raise ValueError("resume configuration does not match checkpoint")
    elif not final_path.exists():
        _write_json_atomic(checkpoint_config_path, logical_config)
    completed_records = list(
        read_jsonl(final_path)
        if final_path.exists()
        else read_checkpoint(checkpoint_path)
    )
    completed = {
        record["graph_hash"]: record for record in completed_records
    }
    if len(completed_records) != len(completed):
        raise RuntimeError("duplicate review records")
    started_at = datetime.now(timezone.utc)
    started = perf_counter()
    monitor = _PeakMemoryMonitor()
    monitor.start()
    executor = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    futures: dict[Future[dict[str, Any]], str] = {}
    try:
        for bundle in bundles:
            if bundle.graph_hash in completed:
                continue
            if executor is None:
                record = _review_worker(bundle, options, str(output_directory / "reports"))
                append_checkpoint(checkpoint_path, record)
                completed[bundle.graph_hash] = record
            else:
                futures[executor.submit(
                    _review_worker,
                    bundle,
                    options,
                    str(output_directory / "reports"),
                )] = bundle.graph_hash
                if len(futures) >= 2 * workers:
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        graph_hash = futures.pop(future)
                        record = future.result()
                        if graph_hash in completed:
                            raise RuntimeError(f"duplicate completed review: {graph_hash}")
                        append_checkpoint(checkpoint_path, record)
                        completed[graph_hash] = record
        if futures:
            done, _ = wait(futures)
            for future in done:
                graph_hash = futures[future]
                record = future.result()
                if graph_hash in completed:
                    raise RuntimeError(f"duplicate completed review: {graph_hash}")
                append_checkpoint(checkpoint_path, record)
                completed[graph_hash] = record
            futures.clear()
    except BaseException:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        if executor is not None:
            executor.shutdown(wait=True)
    finally:
        monitor.stop()
    expected_hashes = {bundle.graph_hash for bundle in bundles}
    if set(completed) != expected_hashes:
        raise RuntimeError("review records do not match discovered artifacts")
    records = [completed[graph_hash] for graph_hash in sorted(completed)]
    write_jsonl_atomic(final_path, records)
    _write_summaries(records, output_directory)
    if checkpoint_path.exists():
        checkpoint_path.unlink()
    checkpoint_config_path.unlink(missing_ok=True)
    versions = {}
    for package in ("barnette-search", "networkx", "python-sat"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    solver_metadata = {
        "python_sat_version": versions["python-sat"],
        "minisat22": {
            "mode": "PySAT embedded backend",
            "external_executable": None,
            "backend_version": "not exposed by the PySAT API",
        },
        "glucose3": {
            "mode": "PySAT embedded backend",
            "external_executable": None,
            "backend_version": "not exposed by the PySAT API",
        },
        "backtracking": "barnette_search.constrained_hamiltonian",
    }
    _write_json_atomic(output_directory / "solver_metadata.json", solver_metadata)
    protected_hashes_after = _protected_module_hashes()
    output_sizes = {
        str(path.relative_to(output_directory)): path.stat().st_size
        for path in sorted(output_directory.rglob("*"))
        if path.is_file() and path != metadata_path
    }
    analysis_names = ("all_edge_pairs", "three_edge_paths")
    constraint_totals = {
        name: sum(record[name]["constraint_count"] for record in records)
        for name in analysis_names
    }
    solver_totals = {
        solver: {
            "sat_calls": sum(
                record[name][solver]["number_of_sat_calls"]
                for record in records
                for name in analysis_names
            ),
            "witness_cycles": sum(
                record[name][solver]["number_of_witness_cycles"]
                for record in records
                for name in analysis_names
            ),
            "certified_constraints": sum(constraint_totals.values()),
        }
        for solver in ("minisat22", "glucose3")
    }
    metadata_record = {
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": perf_counter() - started,
        "extremal_input_directory": str(extremal_directory.resolve()),
        "unique_graph_count": len(bundles),
        "options": asdict(options),
        "solver_metadata": solver_metadata,
        "dependency_versions": versions,
        "machine": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "workers": workers,
            "aggregate_peak_rss_bytes": monitor.peak_bytes,
            "memory_samples": monitor.samples,
        },
        "status_counts": {
            status: sum(record["overall_review_status"] == status for record in records)
            for status in sorted({record["overall_review_status"] for record in records})
        },
        "review_totals": {
            "constraints_by_analysis": constraint_totals,
            "unique_constraint_cases": sum(constraint_totals.values()),
            "solver_totals": solver_totals,
            "minisat22_glucose3_constraint_agreements": sum(
                record[name]["minisat22_glucose3_agreements"]
                for record in records
                for name in analysis_names
            ),
            "backtracking_checks": sum(
                record["number_of_backtracking_checks"] for record in records
            ),
            "backtracking_agreements": sum(
                record["number_of_backtracking_agreements"] for record in records
            ),
            "backtracking_timeouts": sum(
                record["number_of_backtracking_timeouts"] for record in records
            ),
            "exact_deterministic_metric_matches": sum(
                bool(record["deterministic_metric_agreement"])
                for record in records
            ),
        },
        "metric_classification": {
            "exact_deterministic": [
                "constraint count",
                "number of constrained SAT calls",
                "witness-cycle count under deterministic greedy ordering",
                "cover ratio",
                "average constraints per witness",
                "maximum constraints covered by one witness",
                "subtour iterations",
                "subtour constraints",
            ],
            "machine_dependent_report_only": [
                "total SAT time",
                "maximum query time",
                "runtime-defined hardest constraint",
            ],
        },
        "output_file_sizes_bytes_excluding_run_metadata": output_sizes,
        "protected_module_sha256_before": protected_hashes_before,
        "protected_module_sha256_after": protected_hashes_after,
        "protected_modules_unchanged": (
            protected_hashes_before == protected_hashes_after
        ),
    }
    _write_json_atomic(metadata_path, metadata_record)
    return tuple(records)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extremal-dir",
        type=Path,
        default=Path("results/plantri-5.8-strong/extremal"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/plantri-5.8-strong/independent-review"),
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--sample-seed", type=int, default=DEFAULT_SAMPLE_SEED)
    parser.add_argument("--backtracking-timeout", type=float, default=5.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    records = run_independent_review(
        arguments.extremal_dir,
        output_directory=arguments.output_dir,
        workers=arguments.workers,
        sample_seed=arguments.sample_seed,
        backtracking_timeout_seconds=arguments.backtracking_timeout,
        resume=arguments.resume,
        overwrite=arguments.overwrite,
    )
    print(
        f"reviewed {len(records)} unique extremal graphs; "
        f"{sum(record['overall_review_status'] == 'verified' for record in records)} verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
