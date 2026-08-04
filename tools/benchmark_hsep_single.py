"""Exact, certificate-first hsep benchmark for one planar-code graph.

The producer is deliberately single-graph and single-process.  It reuses the
established Hamiltonian enumerator and SAT/set-cover routines, writes a complete
cycle universe, and invokes the separate standard-library verifier before
declaring the result exact.
"""

from __future__ import annotations

import argparse
import gc
import gzip
from hashlib import sha256
from importlib import metadata as importlib_metadata
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any, Sequence

import psutil

from barnette_search.barnie_sequence import (
    EXACT_SCHEMA,
    _graph_record,
    cubic_lym_lower_bound,
    deterministic_greedy_cover,
    exhaustive_cover_feasible,
    greedy_packing_lower_bound,
)
from barnette_search.hsep_order36 import (
    _cycle_coverers,
    cycle_edge_indexes,
    enumerate_hamiltonian_cycles,
    requirement_pairs,
    verify_cover_edges,
)


UNIVERSE_SCHEMA = "barnette-single-hsep-universe-v1"
BENCHMARK_SCHEMA = "barnette-single-hsep-benchmark-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def write_text_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def write_json_new(path: Path, value: Any) -> None:
    write_text_new(path, canonical_json(value) + "\n")


def write_gzip_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            stream.write(payload)


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def solve_minimum_set_cover_rc2(
    edges: tuple[tuple[int, int], ...], universe: tuple[tuple[int, ...], ...]
) -> tuple[int, ...]:
    """Return an exact minimum set cover using PySAT's RC2 MaxSAT optimizer."""
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF

    coverers = _cycle_coverers(edges, universe)
    if any(not row for row in coverers):
        raise RuntimeError("Hamiltonian universe cannot separate every edge pair")
    formula = WCNF()
    for row in coverers:
        formula.append([index + 1 for index in row])
    for index in range(len(universe)):
        formula.append([-(index + 1)], weight=1)
    with RC2(formula, solver="g3", adapt=True, exhaust=True, verbose=0) as optimizer:
        model = set(optimizer.compute() or ())
    selected = tuple(index for index in range(len(universe)) if index + 1 in model)
    if not selected:
        raise RuntimeError("RC2 returned no set-cover family")
    return selected


def solve_maximum_packing_rc2(
    edges: tuple[tuple[int, int], ...], universe: tuple[tuple[int, ...], ...]
) -> tuple[tuple[int, int], ...]:
    """Return an exact maximum requirement packing using PySAT RC2."""
    from pysat.card import CardEnc, EncType
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF

    requirements = requirement_pairs(len(edges))
    edge_index = {edge: index for index, edge in enumerate(edges)}
    all_indexes = set(range(len(edges)))
    formula = WCNF()
    top_id = len(requirements)
    for cycle in universe:
        selected = cycle_edge_indexes(cycle, edge_index)
        covered = [
            index + 1
            for index, (required, forbidden) in enumerate(requirements)
            if required in selected and forbidden in all_indexes - selected
        ]
        encoding = CardEnc.atmost(
            lits=covered,
            bound=1,
            top_id=top_id,
            encoding=EncType.seqcounter,
        )
        for clause in encoding.clauses:
            formula.append(list(clause))
        top_id = max(top_id, encoding.nv)
    for index in range(len(requirements)):
        formula.append([index + 1], weight=1)
    with RC2(formula, solver="g3", adapt=True, exhaust=True, verbose=0) as optimizer:
        model = set(optimizer.compute() or ())
    return tuple(
        requirement
        for index, requirement in enumerate(requirements, start=1)
        if index in model
    )


def build_exact_certificate(
    graph_record: dict[str, Any],
    universe: tuple[tuple[int, ...], ...],
    *,
    existing_greedy_upper_bound: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Optimize hsep and return a certificate plus detailed solver trials."""
    edges = tuple(tuple(map(int, edge)) for edge in graph_record["edges"])
    order = int(graph_record["graph_order"])
    optimization_started = perf_counter()

    greedy_indexes = deterministic_greedy_cover(edges, universe)
    greedy_family = tuple(universe[index] for index in greedy_indexes)
    complete, _ = verify_cover_edges(edges, greedy_family)
    if not complete:
        raise RuntimeError("deterministic complete-universe greedy cover is incomplete")

    greedy_packing = greedy_packing_lower_bound(edges, universe)
    lym_lower = cubic_lym_lower_bound(order)
    initial_lower = max(lym_lower, len(greedy_packing))
    print("RC2_SET_COVER_START", flush=True)
    set_cover_started = perf_counter()
    selected = solve_minimum_set_cover_rc2(edges, universe)
    set_cover_seconds = perf_counter() - set_cover_started
    optimum = len(selected)
    print(f"RC2_SET_COVER_DONE {optimum} {set_cover_seconds:.6f}", flush=True)
    if not (initial_lower <= optimum <= len(greedy_indexes)):
        raise RuntimeError("RC2 optimum violates independently established bounds")

    print("RC2_PACKING_START", flush=True)
    packing_started = perf_counter()
    if len(greedy_packing) == optimum:
        maximum_packing = greedy_packing
        packing_backend = "deterministic_greedy_matching_certificate"
    else:
        maximum_packing = solve_maximum_packing_rc2(edges, universe)
        packing_backend = "PySAT RC2 maximum packing"
    packing_seconds = perf_counter() - packing_started
    print(
        f"RC2_PACKING_DONE {len(maximum_packing)} {packing_seconds:.6f}",
        flush=True,
    )

    exclusion_bound = optimum - 1
    exhaustive_seconds: float | None = None
    if len(maximum_packing) == optimum:
        packing = maximum_packing
        lower_method = "packing"
        exclusion_result = "EXCLUDED_BY_MATCHING_PACKING"
    else:
        packing = None
        exhaustive_started = perf_counter()
        feasible = exhaustive_cover_feasible(edges, universe, exclusion_bound)
        exhaustive_seconds = perf_counter() - exhaustive_started
        if feasible:
            raise RuntimeError("standalone search did not exclude hsep-1")
        lower_method = "standalone_exhaustive_set_cover"
        exclusion_result = "UNSAT"

    family = tuple(universe[index] for index in selected)
    complete, covered = verify_cover_edges(edges, family)
    if not complete:
        raise RuntimeError("optimal primal family is incomplete")

    certificate = {
        "schema": EXACT_SCHEMA,
        "generation_index": graph_record["generation_index"],
        "plantri_rank": graph_record["plantri_rank"],
        "canonical_graph_hash": graph_record["canonical_graph_hash"],
        "graph_order": order,
        "edge_count": len(edges),
        "complete_hamiltonian_cycle_count": len(universe),
        "hsep_lower_bound": optimum,
        "hsep_upper_bound": optimum,
        "exact_hsep": optimum,
        "proof_status": (
            "exact_primal_packing"
            if lower_method == "packing"
            else "exact_primal_exhaustive_lower_bound"
        ),
        "lower_bound_method": lower_method,
        "primal_cycle_count": len(family),
        "primal_cycles": [list(cycle) for cycle in family],
        "packing_requirement_count": len(packing) if packing is not None else len(greedy_packing),
        "packing_requirements": [
            list(item) for item in (packing if packing is not None else greedy_packing)
        ],
        "existing_greedy_upper_bound": existing_greedy_upper_bound,
        "greedy_complete_universe_cover_size": len(greedy_indexes),
        "covered_ordered_edge_pairs": covered,
    }
    details = {
        "optimization_runtime_seconds": perf_counter() - optimization_started,
        "set_cover_backend": "PySAT RC2 minimum set cover over Glucose3",
        "set_cover_runtime_seconds": set_cover_seconds,
        "packing_backend": packing_backend,
        "maximum_packing_size": len(maximum_packing),
        "hsep_minus_one_bound": exclusion_bound,
        "hsep_minus_one_result": exclusion_result,
        "packing_solver_runtime_seconds": packing_seconds,
        "standalone_exhaustive_runtime_seconds": exhaustive_seconds,
        "cubic_incidence_lym_lower_bound": lym_lower,
        "greedy_packing_size": len(greedy_packing),
    }
    return certificate, details


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    process = psutil.Process()

    planar_code = args.planar_code.resolve().read_bytes()
    graph_record = _graph_record(args.generation_index, planar_code, args.expected_order)
    if graph_record["canonical_graph_hash"] != args.expected_hash:
        raise RuntimeError(
            f"canonical hash mismatch: {graph_record['canonical_graph_hash']} != {args.expected_hash}"
        )
    write_json_new(output / "graph_certificate.json", graph_record)

    edges = tuple(tuple(map(int, edge)) for edge in graph_record["edges"])
    enumeration_started = perf_counter()
    universe = tuple(sorted(enumerate_hamiltonian_cycles(edges, args.expected_order)))
    enumeration_seconds = perf_counter() - enumeration_started
    if not universe:
        raise RuntimeError("complete enumeration returned no Hamiltonian cycles")
    print(f"ENUMERATION_DONE {len(universe)} {enumeration_seconds:.6f}", flush=True)
    universe_document = {
        "schema": UNIVERSE_SCHEMA,
        "canonical_graph_hash": args.expected_hash,
        "generation_index": args.generation_index,
        "graph_order": args.expected_order,
        "cycle_count": len(universe),
        "cycles": [list(cycle) for cycle in universe],
    }
    universe_payload = (canonical_json(universe_document) + "\n").encode("ascii")
    write_text_new(output / "hamiltonian_universe.json", universe_payload.decode("ascii"))
    write_gzip_new(output / "hamiltonian_universe.json.gz", universe_payload)

    certificate, optimization = build_exact_certificate(
        graph_record,
        universe,
        existing_greedy_upper_bound=args.existing_greedy_upper_bound,
    )
    write_json_new(output / "hsep_certificate.json", certificate)
    write_json_new(output / "solver_trials.json", optimization)

    producer_peak = process.memory_info().peak_wset
    del universe, universe_document
    gc.collect()

    verifier = Path(__file__).with_name("verify_hsep_single_benchmark.py").resolve()
    verifier_started = perf_counter()
    completed = subprocess.run(
        [sys.executable, str(verifier), str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    verifier_seconds = perf_counter() - verifier_started
    write_text_new(output / "verifier.stdout.txt", completed.stdout)
    write_text_new(output / "verifier.stderr.txt", completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"independent verifier failed with exit code {completed.returncode}")
    verification = json.loads((output / "independent_verification.json").read_text(encoding="utf-8"))
    if verification.get("verified") is not True:
        raise RuntimeError("independent verifier did not certify the result")

    universe_plain = output / "hamiltonian_universe.json"
    universe_gzip = output / "hamiltonian_universe.json.gz"
    result = {
        "schema": BENCHMARK_SCHEMA,
        "status": "EXACT_VERIFIED",
        "canonical_graph_hash": args.expected_hash,
        "generation_index": args.generation_index,
        "plantri_rank": args.generation_index + 1,
        "graph_order": args.expected_order,
        "hamiltonian_cycle_count": certificate["complete_hamiltonian_cycle_count"],
        "exact_hsep": certificate["exact_hsep"],
        "existing_greedy_upper_bound": args.existing_greedy_upper_bound,
        "complete_universe_greedy_upper_bound": certificate[
            "greedy_complete_universe_cover_size"
        ],
        "enumeration_runtime_seconds": enumeration_seconds,
        "optimization_runtime_seconds": optimization["optimization_runtime_seconds"],
        "verifier_runtime_seconds": verifier_seconds,
        "total_runtime_seconds": perf_counter() - started,
        "producer_peak_ram_bytes": producer_peak,
        "verifier_peak_ram_bytes": verification["peak_ram_bytes"],
        "peak_ram_bytes": max(producer_peak, verification["peak_ram_bytes"]),
        "uncompressed_universe_bytes": universe_plain.stat().st_size,
        "compressed_universe_bytes": universe_gzip.stat().st_size,
        "lower_bound_certificate_type": certificate["lower_bound_method"],
        "hsep_minus_one_result": optimization["hsep_minus_one_result"],
        "solver": "PySAT RC2 MaxSAT over Glucose3",
        "solver_package": "python-sat",
        "solver_package_version": package_version("python-sat"),
        "python_version": sys.version,
        "psutil_version": package_version("psutil"),
        "input_planar_code": str(args.planar_code.resolve()),
        "input_planar_code_sha256": sha256(planar_code).hexdigest(),
    }
    write_json_new(output / "benchmark_result.json", result)

    manifest_paths = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    manifest = "".join(f"{file_sha256(path)}  {path.name}\n" for path in manifest_paths)
    write_text_new(output / "SHA256SUMS.txt", manifest)
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planar-code", type=Path, required=True)
    parser.add_argument("--expected-hash", required=True)
    parser.add_argument("--generation-index", type=int, required=True)
    parser.add_argument("--existing-greedy-upper-bound", type=int, required=True)
    parser.add_argument("--expected-order", type=int, default=32)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(parse_args(argv))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
