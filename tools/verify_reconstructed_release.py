"""Read-only standard-library verifier for the reconstructed public data package.

Run with the adjacent, unchanged verify_barnie_sequence.py:
    python verify_reconstructed_release.py PATH_TO_EXTRACTED_PACKAGE
"""

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import argparse
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import platform
import sys
from time import perf_counter


def verify_hashes(root):
    seen = set()
    for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        relative = Path(name)
        target = (root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(root.resolve()):
            raise ValueError("manifest path escapes package")
        if name in seen or len(digest) != 64:
            raise ValueError("invalid or repeated manifest entry")
        seen.add(name)
        if sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"hash mismatch: {name}")
    if not seen:
        raise ValueError("empty manifest")
    return len(seen)


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "reconstructed_release_core", Path(__file__).with_name("verify_barnie_sequence.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("missing adjacent independent verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_graph(root, verifier):
    verify_hashes(root)
    graph = json.loads((root / "graph_certificate.json").read_text(encoding="utf-8"))
    certificate = json.loads((root / "hsep_certificate.json").read_text(encoding="utf-8"))
    plain = (root / "hamiltonian_universe.json").read_bytes()
    if gzip.decompress((root / "hamiltonian_universe.json.gz").read_bytes()) != plain:
        raise ValueError("Hamiltonian universe encodings disagree")
    universe = json.loads(plain)
    order, index = int(graph["graph_order"]), int(graph["generation_index"])
    graph_hash, edges = verifier.verify_graph_record(graph, index, order)
    if universe["canonical_graph_hash"] != graph_hash or universe["cycle_count"] != len(universe["cycles"]):
        raise ValueError("universe identity/count mismatch")
    exact_record = dict(certificate, complete_hamiltonian_cycle_universe=universe["cycles"])
    exact = verifier.verify_exact(exact_record, edges, order)
    if certificate.get("hsep_lower_bound") != exact or certificate.get("hsep_upper_bound") != exact:
        raise ValueError("bounds do not agree with verified optimum")
    benchmark = json.loads((root / "benchmark_result.json").read_text(encoding="utf-8"))
    if benchmark.get("status") != "EXACT_VERIFIED" or benchmark.get("exact_hsep") != exact:
        raise ValueError("benchmark summary disagrees with certificate")
    return {"order": order, "generation_index": index, "canonical_graph_hash": graph_hash,
            "exact_hsep": exact, "hamiltonian_cycles": len(universe["cycles"])}


def verify_graph_path(path):
    return verify_graph(path, load_verifier())


def verify(root, workers=1):
    start = perf_counter()
    verify_hashes(root)
    verifier = load_verifier()
    rows = []
    identities = set()
    directories = [p.parent for p in sorted(root.rglob("graph_certificate.json"))]
    executor = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    checked = executor.map(verify_graph_path, directories) if executor else map(verify_graph_path, directories)
    for directory, row in zip(directories, checked):
        if row["canonical_graph_hash"] in identities:
            raise ValueError("duplicate isomorphism class in release package")
        identities.add(row["canonical_graph_hash"])
        row["directory"] = directory.relative_to(root).as_posix()
        rows.append(row)
        print(f"Verified {len(rows)}: n={row['order']}, hsep={row['exact_hsep']}", file=sys.stderr, flush=True)
    if executor:
        executor.shutdown()
    counts = Counter(row["order"] for row in rows)
    expected = {8: 1, 12: 1, 14: 1, 16: 2, 18: 2, 20: 8, 22: 8, 24: 32, 26: 39, 32: 3}
    if dict(counts) != expected:
        raise ValueError(f"unexpected release inventory: {dict(counts)}")
    for order in (8, 12, 14, 16, 18, 20, 22, 24):
        indices = sorted(row["generation_index"] for row in rows if row["order"] == order)
        if indices != list(range(verifier.REFERENCE_COUNTS[order])):
            raise ValueError("small-census generation indices are not complete")
    return {"verified": True, "python": sys.version, "platform": platform.platform(),
            "solver": "standard-library exhaustive verification", "seed": None,
            "seconds": perf_counter() - start, "workers": workers, "graphs": rows,
            "scope": "All 55 classes through order 24 against reference census counts; 39/57 classes at 26; three graph-specific results at 32. No complete census claim above 24."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.root.resolve(), args.workers), indent=2))
    except (ValueError, KeyError, OSError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
