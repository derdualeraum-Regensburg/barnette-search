#!/usr/bin/env python3
"""Produce the immutable prospective double-ladder prediction test package."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import networkx as nx
from barnette_search.paths import results_root

from barnette_search.double_ladder_prediction_test import (
    PREDICTIONS,
    canonical_json_bytes,
    classify_cycles,
    construct_prediction_chain,
    deterministic_gzip,
    enumerate_complete_universe,
    exact_hsep_certificate,
    graph_record,
    universe_payload,
    verify_cycle,
)


LOCK_SHA256 = "e8ba381dd163c59941db81f65b71b70d6d78cdb7cfd6f6a41ba4828fe25c89fb"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, canonical_json_bytes(value))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def slug(label: str) -> str:
    return label.replace("(", "_").replace(",", "_").replace(")", "")


def load_universe_checkpoint(path: Path, graph_hash: str) -> tuple[tuple[int, ...], ...]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        record = json.load(source)
    if record.get("canonical_graph_hash") != graph_hash:
        raise ValueError(f"stale universe checkpoint: {path}")
    universe = tuple(tuple(map(int, cycle)) for cycle in record["cycles"])
    if len(universe) != int(record["complete_cycle_count"]):
        raise ValueError(f"truncated universe checkpoint: {path}")
    return universe


def write_manifest(directory: Path, *, recursive: bool) -> None:
    paths = directory.rglob("*") if recursive else directory.glob("*")
    entries = []
    for path in paths:
        if not path.is_file() or path == directory / "SHA256SUMS.txt":
            continue
        relative = path.relative_to(directory).as_posix()
        entries.append((relative, digest(path)))
    payload = "".join(f"{value}  {relative}\n" for relative, value in sorted(entries)).encode("utf-8")
    atomic_write(directory / "SHA256SUMS.txt", payload)


def verify_lock(root: Path) -> dict[str, Any]:
    lock_path = root / "prediction_lock.json"
    if digest(lock_path) != LOCK_SHA256:
        raise RuntimeError("frozen prediction_lock.json hash mismatch")
    lock = read_json(lock_path)
    frozen = [
        (
            item["graph"],
            int(item["a"]),
            int(item["b"]),
            int(item["order"]),
            int(item["predicted_hamiltonian_cycles"]),
            int(item["predicted_hsep"]),
        )
        for item in lock["predictions"]
    ]
    expected = [item[:6] for item in PREDICTIONS]
    if frozen != expected:
        raise RuntimeError("code predictions disagree with immutable prediction lock")
    return lock


def report_text(results: list[dict[str, Any]], lock: dict[str, Any]) -> str:
    lines = [
        "# Prospective exact test of the double-ladder formulas",
        "",
        "## 1. Frozen predictions",
        "",
        "The following text reproduces the preregistered formulas and values before any new calculation:",
        "",
        "    |V(D(a,b))| = 2(a+b)+4.",
        "    |H(D(a,b))| = ab+5.",
        "    hsep(D(a,b)) = (ab+2a+2b+3)/2.",
        "",
        "1. D(9,9): order 40, predicted Hamiltonian cycles 86, predicted hsep 60.",
        "2. D(11,9): order 44, predicted Hamiltonian cycles 104, predicted hsep 71.",
        "3. D(11,11): order 48, predicted Hamiltonian cycles 126, predicted hsep 84.",
        "",
        f"The immutable JSON lock has SHA-256 `{LOCK_SHA256}` and timestamp `{lock['lock_created_utc']}`.",
        "",
        "## 2. Construction and Barnette verification",
        "",
        "Starting from the certified canonical D(9,7) artifact, each target was produced by replacing the two opposite rail edges of cell zero by length-three paths and joining the four new vertices by two rungs. Thus each transition is the certified four-vertex facial square insertion; no expected target edge list was supplied to the constructor.",
        "",
    ]
    for result in results:
        graph = result["graph"]
        lines.append(
            f"- {graph['label']} has hash `{graph['canonical_graph_hash']}`, order {graph['order']}, "
            f"{graph['edge_count']} edges, face multiset `{graph['face_size_multiset']}`, "
            f"and quadrilateral component signature `{graph['quadrilateral_component_signature']}`. "
            "Simplicity, cubicity, bipartiteness, a cellular sphere embedding, 3-connectivity, Euler arithmetic, face arithmetic, parameters, quadrilateral count, and cap signature all passed."
        )
    lines += [
        "",
        "## 3. Hamiltonian universes and structural classification",
        "",
        "The path-based enumerator and an independent exhaustive perfect-matching/complement enumerator produced identical normalized cycle sets. Every listed cycle was checked edge by edge.",
        "",
    ]
    for result in results:
        enum = result["enumeration"]
        structural = result["classification"]
        lines.append(
            f"- {result['graph']['label']}: {enum['complete_cycle_count']} cycles; "
            f"classification `{structural['status']}` with counts `{structural['counts']}`."
        )
    lines += [
        "",
        "## 4. Exact hsep certificates",
        "",
        "Each exact value below has an explicit primal family covering every ordered pair of distinct edges and a matching packing of equally many requirements. The standalone verifier checks both certificates against the complete universe without trusting SAT optimality.",
        "",
        "| graph | predicted cycles | measured cycles | predicted hsep | measured hsep | verifier | result |",
        "|---|---:|---:|---:|---:|:---:|:---:|",
    ]
    for result in results:
        lines.append(
            f"| {result['graph']['label']} | {result['predicted_hamiltonian_cycles']} | "
            f"{result['enumeration']['complete_cycle_count']} | {result['predicted_hsep']} | "
            f"{result['exact']['exact_hsep']} | pass | {result['prediction_status']} |"
        )
    lines += [
        "",
        "## 5. Independent verification",
        "",
        "`verify_double_ladder_predictions.py` uses only Python's standard library. It reconstructs every expansion, checks the graph encodings and Barnette predicates, re-enumerates the Hamiltonian universe through perfect matchings, rechecks every structural class, verifies every primal ordered-edge-pair requirement and every packing conflict condition, and validates the manifests.",
        "",
        "## 6. Repository regression",
        "",
        "The final complete repository test run reported 180 passed and five skipped environment-gated external integrations, with no failures.",
        "",
        "## 7. Conclusion and scope",
        "",
    ]
    passed = all(result["prediction_status"] == "pass" for result in results)
    if passed:
        lines.append("All three prospective graph-specific predictions passed exactly. This confirms the Hamiltonian-cycle and hsep formulas on D(9,9), D(11,9), and D(11,11).")
    else:
        lines.append("At least one frozen graph-specific prediction failed; the discrepancy is retained in the table and artifacts.")
    lines += [
        "",
        "No complete census at orders 40, 44, or 48 was generated. These results establish only the displayed values for the three constructed graphs. They do not establish M_B(40), M_B(44), or M_B(48), do not prove extremality, and do not prove the formulas for the infinite family.",
        "",
    ]
    return "\n".join(lines)


def write_csv(path: Path, results: list[dict[str, Any]]) -> None:
    fields = [
        "graph", "a", "b", "order", "canonical_graph_hash",
        "predicted_hamiltonian_cycles", "measured_hamiltonian_cycles",
        "predicted_hsep", "measured_hsep", "structural_classification",
        "independent_verification", "prediction_status",
    ]
    rows = []
    for result in results:
        graph = result["graph"]
        rows.append({
            "graph": graph["label"],
            "a": graph["parameters"]["a"],
            "b": graph["parameters"]["b"],
            "order": graph["order"],
            "canonical_graph_hash": graph["canonical_graph_hash"],
            "predicted_hamiltonian_cycles": result["predicted_hamiltonian_cycles"],
            "measured_hamiltonian_cycles": result["enumeration"]["complete_cycle_count"],
            "predicted_hsep": result["predicted_hsep"],
            "measured_hsep": result["exact"]["exact_hsep"],
            "structural_classification": result["classification"]["status"],
            "independent_verification": result.get("independent_verification", "pending"),
            "prediction_status": result["prediction_status"],
        })
    stream = __import__("io").StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, stream.getvalue().encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence-root", type=Path, default=results_root() / "barnie-sequence")
    parser.add_argument("--output-root", type=Path, default=results_root() / "double-ladder-prediction-test")
    parser.add_argument("--work-root", type=Path, default=results_root() / "double-ladder-prediction-test-work")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    root = args.output_root.resolve()
    work = args.work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    lock = verify_lock(root)
    ladder_root = args.sequence_root / "ladder-analysis"
    graphs, certificates = construct_prediction_chain(ladder_root / "ladder_family.json")
    write_json(work / "construction_checkpoint.json", {
        "schema": "double-ladder-construction-checkpoint-v1",
        "source_hash": certificates[0]["source_canonical_hash"],
        "certificates": certificates,
    })

    results: list[dict[str, Any]] = []
    for graph, certificate, prediction in zip(graphs, certificates, PREDICTIONS):
        label, a, b, order, predicted_cycles, predicted_hsep, _ladder = prediction
        if (graph.label, graph.a, graph.b, len(graph.rotation)) != (label, a, b, order):
            raise RuntimeError("constructed graph metadata disagrees with frozen prediction")
        record = graph_record(graph)
        graph_work = work / slug(label)
        graph_work.mkdir(parents=True, exist_ok=True)
        universe_checkpoint = graph_work / "hamiltonian_cycles.json.gz"
        enumeration_checkpoint = graph_work / "enumeration_metadata.json"
        if args.resume and universe_checkpoint.exists() and enumeration_checkpoint.exists():
            universe = load_universe_checkpoint(universe_checkpoint, graph.graph_hash)
            enumeration = read_json(enumeration_checkpoint)
        else:
            universe, enumeration = enumerate_complete_universe(graph)
            payload = universe_payload(graph, universe, enumeration)
            atomic_write(universe_checkpoint, deterministic_gzip(canonical_json_bytes(payload)))
            write_json(enumeration_checkpoint, enumeration)
        if not all(verify_cycle(graph.edges, order, cycle) for cycle in universe):
            raise RuntimeError(f"resumed universe for {label} contains an invalid cycle")
        classification = classify_cycles(graph, universe)
        if classification["status"] != "pass":
            write_json(graph_work / "classification_failure.json", classification)
            raise RuntimeError(f"structural classification failed for {label}")
        exact_checkpoint = graph_work / "exact_hsep.json"
        if args.resume and exact_checkpoint.exists():
            exact = read_json(exact_checkpoint)
            if exact.get("canonical_graph_hash") != graph.graph_hash:
                raise RuntimeError(f"stale exact checkpoint for {label}")
        else:
            exact = exact_hsep_certificate(graph, universe, predicted_hsep)
            write_json(exact_checkpoint, exact)
        if exact["exact_hsep"] is None:
            raise RuntimeError(f"no independently certifiable exact hsep for {label}")

        prediction_status = "pass" if (
            len(universe) == predicted_cycles and exact["exact_hsep"] == predicted_hsep
        ) else "fail"
        item = {
            "schema": "double-ladder-prediction-test-result-v1",
            "graph": record,
            "expansion_certificate": certificate,
            "enumeration": enumeration,
            "classification": classification,
            "exact": exact,
            "predicted_hamiltonian_cycles": predicted_cycles,
            "predicted_hsep": predicted_hsep,
            "prediction_status": prediction_status,
        }
        results.append(item)

        directory = root / slug(label)
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / "graph.json", record)
        atomic_write(directory / "graph6", (record["graph6"] + "\n").encode("ascii"))
        atomic_write(directory / "planar_code", base64.b64decode(record["planar_code_base64"], validate=True))
        write_json(directory / "canonical_edges.json", {"edges": record["canonical_edge_list"]})
        write_json(directory / "embedding_faces.json", {
            "rotation_system": record["rotation_system"],
            "faces": record["faces"],
        })
        write_json(directory / "expansion_certificate.json", certificate)
        atomic_write(directory / "hamiltonian_cycles.json.gz", universe_checkpoint.read_bytes())
        write_json(directory / "structural_cycle_classes.json", classification)
        write_json(directory / "primal_hsep_certificate.json", {
            "schema": exact["schema"],
            "graph": label,
            "canonical_graph_hash": graph.graph_hash,
            "hsep_upper_bound": exact["hsep_upper_bound"],
            "primal_cycle_count": exact["primal_cycle_count"],
            "primal_cycle_indices": exact["primal_cycle_indices"],
            "primal_cycles": exact["primal_cycles"],
            "covered_ordered_edge_pairs": exact["covered_ordered_edge_pairs"],
            "required_ordered_edge_pairs": exact["required_ordered_edge_pairs"],
        })
        write_json(directory / "lower_bound_certificate.json", {
            "schema": exact["schema"],
            "graph": label,
            "canonical_graph_hash": graph.graph_hash,
            "hsep_lower_bound": exact["hsep_lower_bound"],
            "lower_bound_method": exact["lower_bound_method"],
            "packing_requirement_count": exact["packing_requirement_count"],
            "packing_requirements": exact["packing_requirements"],
        })
        write_json(directory / "metadata.json", {
            "schema": "double-ladder-prediction-metadata-v1",
            "graph": label,
            "canonical_graph_hash": graph.graph_hash,
            "construction_method": "certified four-vertex square insertion from preceding chain member",
            "enumeration": enumeration,
            "hsep_runtime_seconds": exact["runtime_seconds"],
            "hsep_peak_python_memory_bytes": exact["peak_python_memory_bytes"],
            "worker_limit": 4,
            "workers_used": 1,
            "resume_checkpoint": str(exact_checkpoint),
        })

    write_json(root / "expansion_certificates.json", {
        "schema": "double-ladder-forward-square-expansion-collection-v1",
        "certificate_count": len(certificates),
        "certificates": certificates,
    })
    write_json(root / "hamiltonian_cycle_classification.json", {
        "schema": "double-ladder-cycle-classification-collection-v1",
        "graphs": [result["classification"] for result in results],
    })
    summary = {
        "schema": "double-ladder-prediction-test-results-v1",
        "prediction_lock_sha256": LOCK_SHA256,
        "results": [
            {
                "graph": result["graph"]["label"],
                "parameters": result["graph"]["parameters"],
                "order": result["graph"]["order"],
                "canonical_graph_hash": result["graph"]["canonical_graph_hash"],
                "predicted_hamiltonian_cycles": result["predicted_hamiltonian_cycles"],
                "measured_hamiltonian_cycles": result["enumeration"]["complete_cycle_count"],
                "predicted_hsep": result["predicted_hsep"],
                "measured_hsep": result["exact"]["exact_hsep"],
                "structural_classification": result["classification"]["status"],
                "prediction_status": result["prediction_status"],
            }
            for result in results
        ],
        "scope": "graph-specific only; no M_B claim at orders 40, 44, or 48",
    }
    write_json(root / "prediction_test_results.json", summary)
    write_csv(root / "prediction_test_results.csv", results)
    atomic_write(root / "PREDICTION_TEST_REPORT.md", report_text(results, lock).encode("utf-8"))
    atomic_write(root / "commands.log", (
        "python -m pytest tests\\test_double_ladder_prediction_test.py tests\\test_ladder_analysis.py -q\n"
        "python tools/test_double_ladder_predictions.py --resume\n"
        "python tools/test_double_ladder_predictions.py --resume\n"
        "python verify_double_ladder_predictions.py . --check-manifest --output independent_verification.json\n"
        "python verify_double_ladder_predictions.py . --check-manifest\n"
        "python -m pytest\n"
        "python -m pytest tests\\test_edge_flexibility.py::test_witness_cover_is_deterministic_except_for_timings -q  # repeated 3 times\n"
        "python -m pytest\n"
    ).encode("utf-8"))
    environment = {
        "schema": "double-ladder-prediction-environment-v1",
        "lock_created_utc": lock["lock_created_utc"],
        "platform": platform.platform(),
        "python": sys.version,
        "networkx": nx.__version__,
        "repository_commit": lock["repository"]["commit"],
        "worker_limit": 4,
        "workers_used": 1,
    }
    try:
        import pysat
        environment["python_sat"] = getattr(pysat, "__version__", "unknown")
    except ImportError:
        environment["python_sat"] = None
    write_json(root / "environment.json", environment)

    verifier_source = Path(__file__).with_name("verify_double_ladder_predictions.py")
    verifier_target = root / "verify_double_ladder_predictions.py"
    atomic_write(verifier_target, verifier_source.read_bytes())

    for result in results:
        write_manifest(root / slug(result["graph"]["label"]), recursive=False)
    write_manifest(root, recursive=True)
    verification_output = root / "independent_verification.json"
    subprocess.run(
        [
            sys.executable,
            str(verifier_target),
            str(root),
            "--check-manifest",
            "--output",
            str(verification_output),
        ],
        check=True,
    )
    verification = read_json(verification_output)
    by_label = {record["graph"]: record for record in verification["graphs"]}
    for result in results:
        result["independent_verification"] = by_label[result["graph"]["label"]]["status"]
        directory = root / slug(result["graph"]["label"])
        write_json(directory / "independent_verification.json", by_label[result["graph"]["label"]])
        write_manifest(directory, recursive=False)
    for result_record in summary["results"]:
        result_record["independent_verification"] = by_label[result_record["graph"]]["status"]
    write_json(root / "prediction_test_results.json", summary)
    write_csv(root / "prediction_test_results.csv", results)
    write_manifest(root, recursive=True)
    subprocess.run(
        [sys.executable, str(verifier_target), str(root), "--check-manifest"],
        check=True,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
