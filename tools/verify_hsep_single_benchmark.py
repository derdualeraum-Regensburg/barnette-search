"""Independent verifier for a single-graph exact hsep benchmark bundle."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Sequence

import psutil


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def load_sequence_verifier() -> Any:
    path = Path(__file__).with_name("verify_barnie_sequence.py")
    spec = importlib.util.spec_from_file_location("independent_barnie_sequence_verifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the independent Barnie-sequence verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(root: Path) -> dict[str, Any]:
    started = perf_counter()
    process = psutil.Process()
    independent = load_sequence_verifier()
    graph = json.loads((root / "graph_certificate.json").read_text(encoding="utf-8"))
    certificate = json.loads((root / "hsep_certificate.json").read_text(encoding="utf-8"))
    plain = (root / "hamiltonian_universe.json").read_bytes()
    with gzip.open(root / "hamiltonian_universe.json.gz", "rb") as stream:
        compressed_payload = stream.read()
    if plain != compressed_payload:
        raise ValueError("compressed and uncompressed Hamiltonian universes differ")
    universe = json.loads(plain)
    if universe.get("cycle_count") != len(universe.get("cycles", [])):
        raise ValueError("cycle-universe counter mismatch")
    if universe.get("canonical_graph_hash") != graph.get("canonical_graph_hash"):
        raise ValueError("universe graph identity mismatch")

    order = int(graph["graph_order"])
    generation_index = int(graph["generation_index"])
    graph_hash, edges = independent.verify_graph_record(graph, generation_index, order)
    exact_record = dict(certificate)
    exact_record["complete_hamiltonian_cycle_universe"] = universe["cycles"]
    exact = independent.verify_exact(exact_record, edges, order)
    if certificate.get("hsep_lower_bound") != exact or certificate.get("hsep_upper_bound") != exact:
        raise ValueError("exact value does not match both stored bounds")
    peak = process.memory_info().peak_wset
    return {
        "schema": "barnette-single-hsep-independent-verification-v1",
        "verified": True,
        "canonical_graph_hash": graph_hash,
        "generation_index": generation_index,
        "graph_order": order,
        "hamiltonian_cycle_count": len(universe["cycles"]),
        "exact_hsep": exact,
        "lower_bound_method": certificate["lower_bound_method"],
        "hsep_minus_one_excluded": True,
        "complete_universe_independently_reenumerated": True,
        "runtime_seconds": perf_counter() - started,
        "peak_ram_bytes": peak,
    }


def write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(value) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args.root.resolve())
        write_new(args.root.resolve() / "independent_verification.json", result)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
