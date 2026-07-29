"""Reproducible plantri enumeration and exact-solver cross-validation CLI."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path
import platform
from time import perf_counter
from typing import Any, Iterable, Sequence

from .edge_flexibility import analyze_same_face_edge_flexibility
from .hamiltonian import find_hamiltonian_cycle, verify_hamiltonian_cycle
from .hamiltonian_sat import solve_hamiltonian_cycle_sat
from .planar_code import canonical_graph_hash, certificate_hash
from .plantri import (
    PlantriVersion,
    barnette_plantri_command,
    detect_plantri_version,
    locate_plantri,
    stream_barnette_graphs,
)
from .validation import validate_barnette_graph


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
}


@dataclass(frozen=True, slots=True)
class EnumerationSummary:
    """Aggregate facts for one completed vertex order."""

    requested_vertex_count: int
    generated_count: int
    reference_count: int | None
    hamiltonian_count: int
    solver_agreements: int
    sat_runtime_seconds: float
    backtracking_runtime_seconds: float
    total_runtime_seconds: float
    plantri_stderr: str
    jsonl_sha256: str


@dataclass(frozen=True, slots=True)
class EdgeFlexibilityEnumerationSummary:
    """Aggregate same-face edge-flexibility facts for one graph order."""

    requested_vertex_count: int
    generated_count: int
    reference_count: int | None
    graphs_satisfying_complete_property: int
    candidate_graphs_requiring_review: int
    total_ordered_edge_pairs: int
    number_of_sat_calls: int
    number_of_witness_cycles: int
    total_sat_runtime_seconds: float
    maximum_single_query_sat_time_seconds: float
    total_subtour_iterations: int
    total_subtour_constraints: int
    backtracking_queries: int
    backtracking_agreements: int
    backtracking_runtime_seconds: float
    hardest_graph_hash: str | None
    hardest_ordered_pair: object | None
    total_runtime_seconds: float
    plantri_stderr: str
    jsonl_sha256: str


def _dependency_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for distribution in ("barnette-search", "networkx", "python-sat"):
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_summary_csv(
    path: Path, summary: EnumerationSummary | EdgeFlexibilityEnumerationSummary
) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=tuple(asdict(summary)))
        writer.writeheader()
        writer.writerow(asdict(summary))


def enumerate_vertex_count(
    vertex_count: int,
    *,
    plantri_version: PlantriVersion,
    output_directory: Path,
    dependency_versions: dict[str, str | None] | None = None,
    seen_hashes: set[str] | None = None,
    overwrite: bool = False,
) -> EnumerationSummary:
    """Generate, validate, solve, and persist one Barnette graph order."""
    if vertex_count % 2:
        raise ValueError("Barnette vertex counts must be even")
    if vertex_count <= 0:
        raise ValueError("Barnette vertex counts must be positive")

    output_directory.mkdir(parents=True, exist_ok=True)
    stem = f"barnette_{vertex_count:02d}"
    jsonl_path = output_directory / f"{stem}.jsonl"
    partial_path = output_directory / f"{stem}.jsonl.partial"
    summary_path = output_directory / f"{stem}.summary.csv"
    existing = [path for path in (jsonl_path, partial_path, summary_path) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "refusing to overwrite existing enumeration output: "
            + ", ".join(map(str, existing))
        )
    if overwrite:
        for path in existing:
            path.unlink()

    versions = dependency_versions or _dependency_versions()
    run_hashes = seen_hashes if seen_hashes is not None else set()
    command = barnette_plantri_command(plantri_version.executable, vertex_count)
    generated_count = 0
    hamiltonian_count = 0
    solver_agreements = 0
    sat_total = 0.0
    backtracking_total = 0.0
    started = perf_counter()

    with partial_path.open("x", encoding="utf-8", newline="\n") as records:
        with stream_barnette_graphs(plantri_version, vertex_count) as stream:
            for embedded in stream:
                graph = embedded.graph
                if graph.number_of_nodes() != vertex_count:
                    raise RuntimeError(
                        f"plantri returned {graph.number_of_nodes()} vertices "
                        f"for requested order {vertex_count}"
                    )
                validation = validate_barnette_graph(graph)
                if not validation.valid:
                    raise RuntimeError(
                        f"plantri graph {generated_count} failed Barnette validation: "
                        f"{validation.rejection_reasons}"
                    )

                graph_hash = canonical_graph_hash(embedded)
                if graph_hash in run_hashes:
                    raise RuntimeError(
                        f"duplicate canonical graph hash in enumeration run: {graph_hash}"
                    )
                run_hashes.add(graph_hash)

                sat_started = perf_counter()
                sat = solve_hamiltonian_cycle_sat(graph)
                sat_runtime = perf_counter() - sat_started
                sat_total += sat_runtime
                if sat.cycle is not None and not verify_hamiltonian_cycle(graph, sat.cycle):
                    raise RuntimeError("SAT solver returned an invalid certificate")

                backtracking_cycle = None
                backtracking_runtime: float | None = None
                if vertex_count <= 24:
                    backtracking_started = perf_counter()
                    backtracking_cycle = find_hamiltonian_cycle(graph)
                    backtracking_runtime = perf_counter() - backtracking_started
                    backtracking_total += backtracking_runtime
                    if backtracking_cycle is not None and not verify_hamiltonian_cycle(
                        graph, backtracking_cycle
                    ):
                        raise RuntimeError(
                            "backtracking solver returned an invalid certificate"
                        )
                    if sat.satisfiable != (backtracking_cycle is not None):
                        raise RuntimeError(
                            f"exact solvers disagree for graph {graph_hash}"
                        )
                    solver_agreements += 1

                if sat.satisfiable:
                    hamiltonian_count += 1
                record: dict[str, Any] = {
                    "requested_vertex_count": vertex_count,
                    "canonical_graph_hash": graph_hash,
                    "edge_count": graph.number_of_edges(),
                    "planar_face_size_multiset": embedded.face_size_multiset,
                    "validator_result": asdict(validation),
                    "sat_result": {
                        **asdict(sat),
                        "runtime_seconds": sat_runtime,
                    },
                    "sat_encoding_statistics": {
                        "number_of_edge_variables": sat.number_of_edge_variables,
                        "number_of_variables": sat.number_of_variables,
                        "number_of_clauses": sat.number_of_clauses,
                        "number_of_subtour_constraints": sat.number_of_subtour_constraints,
                    },
                    "subtour_iterations": sat.number_of_subtour_iterations,
                    "sat_runtime_seconds": sat_runtime,
                    "backtracking_result": {
                        "executed": vertex_count <= 24,
                        "hamiltonian": (
                            backtracking_cycle is not None
                            if vertex_count <= 24
                            else None
                        ),
                        "cycle": backtracking_cycle,
                        "runtime_seconds": backtracking_runtime,
                    },
                    "hamiltonian_certificate_hash": certificate_hash(sat.cycle),
                    "backtracking_certificate_hash": certificate_hash(
                        backtracking_cycle
                    ),
                    "plantri_version": plantri_version.version,
                    "plantri_executable_sha256": plantri_version.executable_sha256,
                    "plantri_command": command,
                    "python_version": platform.python_version(),
                    "dependency_versions": versions,
                }
                records.write(json.dumps(record, sort_keys=True) + "\n")
                records.flush()
                generated_count += 1

        plantri_stderr = stream.stderr_text

    reference_count = REFERENCE_COUNTS.get(vertex_count)
    if reference_count is not None and generated_count != reference_count:
        raise RuntimeError(
            f"enumeration count mismatch for {vertex_count} vertices: "
            f"generated {generated_count}, expected {reference_count}"
        )
    partial_path.replace(jsonl_path)
    elapsed = perf_counter() - started
    summary = EnumerationSummary(
        requested_vertex_count=vertex_count,
        generated_count=generated_count,
        reference_count=reference_count,
        hamiltonian_count=hamiltonian_count,
        solver_agreements=solver_agreements,
        sat_runtime_seconds=sat_total,
        backtracking_runtime_seconds=backtracking_total,
        total_runtime_seconds=elapsed,
        plantri_stderr=plantri_stderr.strip(),
        jsonl_sha256=_hash_file(jsonl_path),
    )
    _write_summary_csv(summary_path, summary)
    return summary


def run_enumeration(
    vertex_counts: Iterable[int],
    *,
    executable: str | Path | None,
    output_directory: Path,
    allow_other_version: bool = False,
    overwrite: bool = False,
) -> tuple[EnumerationSummary, ...]:
    """Run several orders with one versioned executable and shared hash set."""
    counts = tuple(vertex_counts)
    if not counts:
        raise ValueError("at least one vertex count is required")
    if any(count % 2 for count in counts):
        raise ValueError("Barnette vertex counts must be even")
    path = locate_plantri(executable)
    version = detect_plantri_version(path, allow_other_version=allow_other_version)
    versions = _dependency_versions()
    hashes: set[str] = set()
    started_at = datetime.now(timezone.utc)
    summaries = tuple(
        enumerate_vertex_count(
            count,
            plantri_version=version,
            output_directory=output_directory,
            dependency_versions=versions,
            seen_hashes=hashes,
            overwrite=overwrite,
        )
        for count in counts
    )
    metadata_record = {
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_vertex_counts": counts,
        "plantri": asdict(version),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "dependency_versions": versions,
        "summaries": [asdict(summary) for summary in summaries],
    }
    metadata_path = output_directory / "run_metadata.json"
    if metadata_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {metadata_path}")
    metadata_path.write_text(
        json.dumps(metadata_record, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return summaries


def enumerate_edge_flexibility_vertex_count(
    vertex_count: int,
    *,
    plantri_version: PlantriVersion,
    output_directory: Path,
    dependency_versions: dict[str, str | None] | None = None,
    seen_hashes: set[str] | None = None,
    overwrite: bool = False,
) -> EdgeFlexibilityEnumerationSummary:
    """Enumerate one order into separate edge-flexibility artifacts."""
    if vertex_count <= 0 or vertex_count % 2:
        raise ValueError("Barnette vertex counts must be positive and even")
    output_directory.mkdir(parents=True, exist_ok=True)
    stem = f"barnette_{vertex_count:02d}.edge_flexibility"
    jsonl_path = output_directory / f"{stem}.jsonl"
    partial_path = output_directory / f"{stem}.jsonl.partial"
    summary_path = output_directory / f"{stem}.summary.csv"
    edge_paths = (jsonl_path, partial_path, summary_path)
    existing = [path for path in edge_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "refusing to overwrite existing edge-flexibility output: "
            + ", ".join(map(str, existing))
        )
    if overwrite:
        for path in existing:
            path.unlink()

    versions = dependency_versions or _dependency_versions()
    run_hashes = seen_hashes if seen_hashes is not None else set()
    command = barnette_plantri_command(plantri_version.executable, vertex_count)
    generated = property_graphs = candidate_graphs = 0
    total_pairs = sat_calls = witness_cycles = 0
    total_sat_time = maximum_sat_time = 0.0
    total_subtour_iterations = total_subtour_constraints = 0
    backtracking_queries = backtracking_agreements = 0
    backtracking_time = 0.0
    hardest_graph_hash: str | None = None
    hardest_pair: object | None = None
    started = perf_counter()

    with partial_path.open("x", encoding="utf-8", newline="\n") as records:
        with stream_barnette_graphs(plantri_version, vertex_count) as stream:
            for embedded in stream:
                graph = embedded.graph
                validation = validate_barnette_graph(graph)
                if graph.number_of_nodes() != vertex_count or not validation.valid:
                    raise RuntimeError(
                        f"plantri produced an invalid order-{vertex_count} "
                        f"Barnette graph: {validation.rejection_reasons}"
                    )
                graph_hash = canonical_graph_hash(embedded)
                if graph_hash in run_hashes:
                    raise RuntimeError(
                        f"duplicate canonical graph hash in enumeration run: {graph_hash}"
                    )
                run_hashes.add(graph_hash)

                result = analyze_same_face_edge_flexibility(
                    graph,
                    embedded,
                    cross_check_backtracking=vertex_count <= 24,
                    candidate_output_directory=output_directory / "candidates",
                )
                generated += 1
                property_graphs += int(result.complete_property_holds)
                candidate_graphs += int(result.candidate_requires_review)
                total_pairs += result.total_ordered_same_face_edge_pairs
                sat_calls += result.number_of_sat_calls
                witness_cycles += result.number_of_distinct_witness_cycles
                total_sat_time += result.total_sat_time_seconds
                total_subtour_iterations += result.subtour_iterations
                total_subtour_constraints += result.subtour_constraints
                backtracking_queries += result.backtracking_queries
                backtracking_agreements += result.backtracking_agreements
                backtracking_time += result.backtracking_runtime_seconds
                if (
                    result.maximum_single_query_sat_time_seconds
                    > maximum_sat_time
                ):
                    maximum_sat_time = result.maximum_single_query_sat_time_seconds
                    hardest_graph_hash = graph_hash
                    hardest_pair = result.hardest_ordered_pair

                record = {
                    "requested_vertex_count": vertex_count,
                    "canonical_graph_hash": graph_hash,
                    "edge_count": graph.number_of_edges(),
                    "face_size_multiset": embedded.face_size_multiset,
                    "validator_result": asdict(validation),
                    "edge_flexibility": asdict(result),
                    "plantri_version": plantri_version.version,
                    "plantri_executable_sha256": plantri_version.executable_sha256,
                    "plantri_command": command,
                    "python_version": platform.python_version(),
                    "dependency_versions": versions,
                }
                records.write(
                    json.dumps(record, sort_keys=True, default=repr) + "\n"
                )
                records.flush()
        plantri_stderr = stream.stderr_text

    reference_count = REFERENCE_COUNTS.get(vertex_count)
    if reference_count is not None and generated != reference_count:
        raise RuntimeError(
            f"enumeration count mismatch for {vertex_count} vertices: "
            f"generated {generated}, expected {reference_count}"
        )
    partial_path.replace(jsonl_path)
    summary = EdgeFlexibilityEnumerationSummary(
        requested_vertex_count=vertex_count,
        generated_count=generated,
        reference_count=reference_count,
        graphs_satisfying_complete_property=property_graphs,
        candidate_graphs_requiring_review=candidate_graphs,
        total_ordered_edge_pairs=total_pairs,
        number_of_sat_calls=sat_calls,
        number_of_witness_cycles=witness_cycles,
        total_sat_runtime_seconds=total_sat_time,
        maximum_single_query_sat_time_seconds=maximum_sat_time,
        total_subtour_iterations=total_subtour_iterations,
        total_subtour_constraints=total_subtour_constraints,
        backtracking_queries=backtracking_queries,
        backtracking_agreements=backtracking_agreements,
        backtracking_runtime_seconds=backtracking_time,
        hardest_graph_hash=hardest_graph_hash,
        hardest_ordered_pair=hardest_pair,
        total_runtime_seconds=perf_counter() - started,
        plantri_stderr=plantri_stderr.strip(),
        jsonl_sha256=_hash_file(jsonl_path),
    )
    _write_summary_csv(summary_path, summary)
    return summary


def run_edge_flexibility_enumeration(
    vertex_counts: Iterable[int],
    *,
    executable: str | Path | None,
    output_directory: Path,
    allow_other_version: bool = False,
    overwrite: bool = False,
) -> tuple[EdgeFlexibilityEnumerationSummary, ...]:
    """Run the separate exhaustive edge-flexibility output pipeline."""
    counts = tuple(vertex_counts)
    if not counts or any(count <= 0 or count % 2 for count in counts):
        raise ValueError("provide one or more positive even vertex counts")
    version = detect_plantri_version(
        locate_plantri(executable), allow_other_version=allow_other_version
    )
    versions = _dependency_versions()
    hashes: set[str] = set()
    started_at = datetime.now(timezone.utc)
    summaries = tuple(
        enumerate_edge_flexibility_vertex_count(
            count,
            plantri_version=version,
            output_directory=output_directory,
            dependency_versions=versions,
            seen_hashes=hashes,
            overwrite=overwrite,
        )
        for count in counts
    )
    metadata_path = output_directory / "edge_flexibility_run_metadata.json"
    if metadata_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {metadata_path}")
    metadata_path.write_text(
        json.dumps(
            {
                "started_at_utc": started_at.isoformat(),
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "requested_vertex_counts": counts,
                "plantri": asdict(version),
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "dependency_versions": versions,
                "summaries": [asdict(summary) for summary in summaries],
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return summaries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertices", nargs="+", required=True, type=int)
    parser.add_argument(
        "--plantri",
        help="external plantri executable (or set PLANTRI_EXECUTABLE)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results") / "plantri-5.8"
    )
    parser.add_argument("--allow-other-version", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--test-edge-flexibility",
        action="store_true",
        help="write separate exhaustive same-face edge-flexibility results",
    )
    parser.add_argument("--test-all-edge-pairs", action="store_true")
    parser.add_argument("--test-three-edge-paths", action="store_true")
    parser.add_argument(
        "--output-detail",
        choices=("summary", "candidates", "full"),
        default="summary",
    )
    parser.add_argument("--retain-top-k", type=int, default=25)
    parser.add_argument("--compress-results", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    arguments = _parser().parse_args(argv)
    strong_analysis = (
        arguments.test_all_edge_pairs or arguments.test_three_edge_paths
    )
    if strong_analysis:
        if arguments.test_edge_flexibility:
            raise ValueError(
                "same-face and stronger analyses require separate explicit runs"
            )
        from .flexibility_enumeration import run_strong_flexibility_enumeration

        run_strong_flexibility_enumeration(
            arguments.vertices,
            executable=arguments.plantri,
            output_directory=arguments.output_dir,
            test_all_edge_pairs=arguments.test_all_edge_pairs,
            test_three_edge_paths=arguments.test_three_edge_paths,
            output_detail=arguments.output_detail,
            retain_top_k=arguments.retain_top_k,
            compress_results=arguments.compress_results,
            resume=arguments.resume,
            workers=arguments.workers,
            allow_other_version=arguments.allow_other_version,
            overwrite=arguments.overwrite,
        )
        return 0
    runner = (
        run_edge_flexibility_enumeration
        if arguments.test_edge_flexibility
        else run_enumeration
    )
    summaries = runner(
        arguments.vertices,
        executable=arguments.plantri,
        output_directory=arguments.output_dir,
        allow_other_version=arguments.allow_other_version,
        overwrite=arguments.overwrite,
    )
    for summary in summaries:
        if isinstance(summary, EdgeFlexibilityEnumerationSummary):
            print(
                f"n={summary.requested_vertex_count}: {summary.generated_count} "
                f"graphs, {summary.total_ordered_edge_pairs} ordered pairs, "
                f"{summary.number_of_sat_calls} SAT calls, "
                f"{summary.total_runtime_seconds:.6f}s"
            )
        else:
            print(
                f"n={summary.requested_vertex_count}: {summary.generated_count} "
                f"graphs, {summary.solver_agreements} solver agreements, "
                f"{summary.total_runtime_seconds:.6f}s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
