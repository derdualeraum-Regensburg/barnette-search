#!/usr/bin/env python3
"""Independently verify the v0.9 recalculated certificate release."""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import platform
import sys
from time import perf_counter


EXPECTED_LADDERS = {
    "D_9_9": (40, 60),
    "D_11_9": (44, 71),
    "D_11_11": (48, 84),
}


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_release_manifest(root: Path) -> int:
    manifest = root / "SHA256SUMS.txt"
    expected_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    listed: set[str] = set()
    for number, line in enumerate(manifest.read_text(encoding="ascii").splitlines(), 1):
        try:
            expected, name = line.split("  ", 1)
        except ValueError as error:
            raise ValueError(f"bad release manifest line {number}") from error
        relative = Path(name)
        target = (root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(root.resolve()):
            raise ValueError("release manifest path escapes package")
        if name in listed or len(expected) != 64:
            raise ValueError("invalid or repeated release manifest entry")
        if not target.is_file() or digest(target) != expected:
            raise ValueError(f"release manifest mismatch: {name}")
        listed.add(name)
    if listed != expected_files:
        missing = sorted(expected_files - listed)
        stale = sorted(listed - expected_files)
        raise ValueError(f"release manifest inventory mismatch: unlisted={missing}, absent={stale}")
    return len(listed)


def load_core(root: Path):
    path = root / "verify_barnie_sequence.py"
    spec = importlib.util.spec_from_file_location("recalculated_release_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("missing adjacent census verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_ladder(directory: Path, core, expected_order: int, expected_hsep: int) -> dict:
    core.verify_manifest(directory)
    graph = json.loads((directory / "graph_certificate.json").read_text(encoding="utf-8"))
    certificate = json.loads((directory / "hsep_certificate.json").read_text(encoding="utf-8"))
    plain = (directory / "hamiltonian_universe.json").read_bytes()
    if gzip.decompress((directory / "hamiltonian_universe.json.gz").read_bytes()) != plain:
        raise ValueError(f"Hamiltonian universe encodings disagree: {directory.parent.name}")
    universe = json.loads(plain)
    graph_hash, edges = core.verify_graph_record(graph, 0, expected_order)
    if universe.get("canonical_graph_hash") != graph_hash:
        raise ValueError("ladder universe graph identity mismatch")
    cycles = universe.get("cycles", [])
    if universe.get("cycle_count") != len(cycles):
        raise ValueError("ladder Hamiltonian-cycle count mismatch")
    exact_record = dict(certificate, complete_hamiltonian_cycle_universe=cycles)
    exact = core.verify_exact(exact_record, edges, expected_order)
    if exact != expected_hsep:
        raise ValueError(f"unexpected exact hsep for {directory.parent.name}: {exact}")
    if certificate.get("hsep_lower_bound") != exact or certificate.get("hsep_upper_bound") != exact:
        raise ValueError("ladder bounds do not agree")
    stored = json.loads((directory / "independent_verification.json").read_text(encoding="utf-8"))
    if not stored.get("verified") or stored.get("exact_hsep") != exact:
        raise ValueError("stored ladder verification disagrees")
    return {
        "name": directory.parent.name,
        "order": expected_order,
        "canonical_graph_hash": graph_hash,
        "hamiltonian_cycle_count": len(cycles),
        "exact_hsep": exact,
        "verified": True,
    }


def verify(root: Path) -> dict:
    started = perf_counter()
    file_count = verify_release_manifest(root)
    core = load_core(root)
    census = core.verify_all(root / "barnie-sequence", True)
    if not census.get("verified"):
        raise ValueError("census verification failed")
    ladders = []
    identities = set()
    for name, (order, exact) in EXPECTED_LADDERS.items():
        row = verify_ladder(root / "double-ladders" / name / "attempt-1", core, order, exact)
        if row["canonical_graph_hash"] in identities:
            raise ValueError("duplicate ladder graph identity")
        identities.add(row["canonical_graph_hash"])
        ladders.append(row)
    return {
        "schema": "barnette-recalculated-release-verification-v1",
        "verified": True,
        "scope": "Complete Barnette census certificates for orders 8 through 36 and exact graph-specific certificates for D(9,9), D(11,9), and D(11,11).",
        "release_manifest_files_verified": file_count,
        "census": census,
        "double_ladders": ladders,
        "python": sys.version,
        "platform": platform.platform(),
        "solver": "standard-library exhaustive certificate verification",
        "seed": None,
        "runtime_seconds": perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.root.resolve())
    except Exception as error:
        print(json.dumps({"verified": False, "error": str(error)}, sort_keys=True))
        return 1
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8", newline="\n")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
