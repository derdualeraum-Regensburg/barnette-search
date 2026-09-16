"""Serial, resumable exact hsep runner for the nonempty censuses through n=24,
and, via --orders, the explicit strong_flexibility censuses at n=26 and n=28."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
from typing import Any, Sequence, TextIO

from barnette_search.all_edge_flexibility import analyze_all_edge_pair_flexibility
from barnette_search.planar_code import canonical_graph_hash, encode_planar_code
from barnette_search.plantri import detect_plantri_version, stream_barnette_graphs


DEFAULT_ORDERS = tuple(range(8, 25, 2))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(stream: TextIO, message: str) -> None:
    stream.write(f"{utc_now()} {message}\n")
    stream.flush()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_census_files(census: Path, order: int) -> tuple[Path, Path, bool]:
    """Find the plain (n<=24) or gzip strong_flexibility (n=26, n=28) census pair."""
    plain_jsonl = census / f"barnette_{order:02d}.jsonl"
    plain_summary = census / f"barnette_{order:02d}.summary.csv"
    if plain_jsonl.is_file() and plain_summary.is_file():
        return plain_jsonl, plain_summary, False
    strong_jsonl = census / f"barnette_{order:02d}.strong_flexibility.jsonl.gz"
    strong_summary = census / f"barnette_{order:02d}.strong_flexibility.summary.csv"
    if strong_jsonl.is_file() and strong_summary.is_file():
        return strong_jsonl, strong_summary, True
    raise FileNotFoundError(f"missing census files for order {order}")


def load_jsonl(path: Path, order: int, gzipped: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    opener = gzip.open if gzipped else open
    with opener(path, "rt", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if int(record["requested_vertex_count"]) != order:
                raise ValueError(f"{path}:{line_number} has the wrong graph order")
            if "generation_index" in record and int(record["generation_index"]) != line_number - 1:
                raise ValueError(f"{path}:{line_number} has an out-of-sequence generation_index")
            records.append(record)
    hashes = [str(record["canonical_graph_hash"]) for record in records]
    if len(hashes) != len(set(hashes)):
        raise ValueError(f"duplicate canonical hashes in {path}")
    return records


def validate_summary(summary: Path, jsonl: Path, count: int) -> None:
    with summary.open("r", encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 1:
        raise ValueError(f"expected one summary row in {summary}")
    row = rows[0]
    if int(row["generated_count"]) != count or int(row["reference_count"]) != count:
        raise ValueError(f"census count mismatch in {summary}")
    if "jsonl_sha256" in row and row["jsonl_sha256"].lower() != file_sha256(jsonl):
        raise ValueError(f"JSONL SHA-256 mismatch for {jsonl}")


def load_census(census: Path, orders: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for order in orders:
        jsonl, summary, gzipped = resolve_census_files(census, order)
        records = load_jsonl(jsonl, order, gzipped)
        validate_summary(summary, jsonl, len(records))
        if records:
            result[order] = records
    return result


def load_plantri(census: Path):
    metadata_path = census / "run_metadata.json"
    if not metadata_path.is_file():
        metadata_path = census / "strong_flexibility_run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    recorded = metadata["plantri"]
    version = detect_plantri_version(Path(recorded["executable"]))
    if version.version != str(recorded["version"]):
        raise ValueError("plantri version differs from census metadata")
    if version.executable_sha256 != str(recorded["executable_sha256"]):
        raise ValueError("plantri executable SHA-256 differs from census metadata")
    return version


def materialize_order(version: Any, order: int, records: list[dict[str, Any]]) -> list[bytes]:
    planar_codes: list[bytes] = []
    with stream_barnette_graphs(version, order) as generated:
        for index, embedded in enumerate(generated):
            if index >= len(records):
                raise ValueError(f"plantri generated too many order-{order} graphs")
            expected = str(records[index]["canonical_graph_hash"])
            actual = canonical_graph_hash(embedded)
            if actual != expected:
                raise ValueError(
                    f"order {order} generation index {index}: {actual} != {expected}"
                )
            planar_codes.append(encode_planar_code(embedded.rotation_system))
    if len(planar_codes) != len(records):
        raise ValueError(
            f"plantri generated {len(planar_codes)} order-{order} graphs; "
            f"the census contains {len(records)}"
        )
    return planar_codes


def exact_verified(path: Path, order: int, index: int, graph_hash: str) -> bool:
    result_path = path / "benchmark_result.json"
    verification_path = path / "independent_verification.json"
    if not result_path.is_file() or not verification_path.is_file():
        return False
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        result.get("status") == "EXACT_VERIFIED"
        and verification.get("verified") is True
        and int(result.get("graph_order", -1)) == order
        and int(result.get("generation_index", -1)) == index
        and result.get("canonical_graph_hash") == graph_hash
    )


def run_child(command: list[str], stream: TextIO) -> None:
    log(stream, "COMMAND " + subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        stream.write(line)
        stream.flush()
    returncode = process.wait()
    if returncode != 0:
        raise RuntimeError(f"single-graph benchmark exited with status {returncode}")


def execute(args: argparse.Namespace, stream: TextIO) -> None:
    census = args.census.resolve()
    output = args.output.resolve()
    benchmark = Path(__file__).with_name("benchmark_hsep_single.py").resolve()
    verifier = Path(__file__).with_name("verify_hsep_single_benchmark.py").resolve()
    if not benchmark.is_file() or not verifier.is_file():
        raise FileNotFoundError("single-graph benchmark or verifier is missing")

    censuses = load_census(census, args.orders or DEFAULT_ORDERS)
    version = load_plantri(census)
    log(
        stream,
        f"PREFLIGHT_OK orders={','.join(map(str, censuses))} "
        f"graphs={sum(map(len, censuses.values()))} plantri={version.version}",
    )
    if args.preflight:
        for order, records in censuses.items():
            materialize_order(version, order, records)
            log(stream, f"CENSUS_MATCH order={order} graphs={len(records)}")
        return

    output.mkdir(parents=True, exist_ok=True)
    staging_root = output / ".staging"
    staging_root.mkdir(exist_ok=True)
    for order, records in censuses.items():
        planar_codes = materialize_order(version, order, records)
        log(stream, f"CENSUS_MATCH order={order} graphs={len(records)}")
        order_directory = output / f"n{order:02d}"
        order_directory.mkdir(exist_ok=True)
        for index, (record, planar_code) in enumerate(zip(records, planar_codes, strict=True)):
            graph_hash = str(record["canonical_graph_hash"])
            destination = order_directory / f"{index:05d}_{graph_hash}"
            if exact_verified(destination, order, index, graph_hash):
                if not args.resume:
                    raise FileExistsError(f"verified result already exists: {destination}")
                log(stream, f"SKIP_EXACT_VERIFIED order={order} index={index} hash={graph_hash}")
                continue
            if destination.exists():
                raise FileExistsError(f"non-resumable result path exists: {destination}")

            stage = Path(tempfile.mkdtemp(
                prefix=f"n{order:02d}-{index:05d}-{graph_hash[:12]}-",
                dir=staging_root,
            ))
            planar_path = stage / "graph.planar_code"
            planar_path.write_bytes(planar_code)
            from io import BytesIO
            from barnette_search.planar_code import iter_planar_code

            [embedded] = iter_planar_code(BytesIO(planar_code), require_header=True)
            greedy = analyze_all_edge_pair_flexibility(
                embedded.graph,
                retain_pair_details=False,
                retain_witness_cycles=False,
                cross_check_backtracking=False,
                candidate_output_directory=stage / "candidates",
            )
            if not greedy.property_satisfied:
                raise RuntimeError(f"all-edge greedy separation failed for {graph_hash}")
            log(
                stream,
                f"GRAPH_START order={order} index={index} hash={graph_hash} "
                f"greedy={greedy.number_of_witness_cycles}",
            )
            staged_result = stage / "result"
            command = [
                sys.executable,
                str(benchmark),
                "--planar-code", str(planar_path),
                "--expected-hash", graph_hash,
                "--generation-index", str(index),
                "--existing-greedy-upper-bound", str(greedy.number_of_witness_cycles),
                "--expected-order", str(order),
                "--output", str(staged_result),
            ]
            run_child(command, stream)
            if not exact_verified(staged_result, order, index, graph_hash):
                raise RuntimeError(f"child result is not EXACT_VERIFIED for {graph_hash}")
            os.replace(staged_result, destination)
            planar_path.unlink()
            stage.rmdir()
            log(stream, f"GRAPH_COMMIT order={order} index={index} hash={graph_hash}")
    log(stream, "RUN_COMPLETE")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument(
        "--orders", type=int, nargs="+",
        help="explicit graph orders to process (default: 8..24 step 2)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.preflight:
        stream = sys.stdout
        try:
            execute(args, stream)
        except Exception:
            traceback.print_exc(file=stream)
            return 1
        return 0
    if args.log is None:
        print("ERROR: --log is required unless --preflight is used", file=sys.stderr)
        return 2
    args.log.resolve().parent.mkdir(parents=True, exist_ok=True)
    with args.log.resolve().open("a", encoding="utf-8", newline="\n") as stream:
        log(stream, f"RUN_START pid={os.getpid()}")
        try:
            execute(args, stream)
        except Exception:
            log(stream, "FATAL")
            traceback.print_exc(file=stream)
            stream.flush()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
