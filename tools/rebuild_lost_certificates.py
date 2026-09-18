"""Resumable reconstruction driver; established solvers/verifiers stay unchanged.

Run with a frozen source snapshot and PYTHONPATH pointing to its src directory.
Outputs are new calculations, not byte-for-byte restorations of lost packages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def check_configuration(root, configuration, resume):
    path = root / "configuration.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous != configuration:
            raise ValueError("configuration differs from the saved reconstruction")
        if not resume:
            raise FileExistsError("reconstruction exists; use --resume")
    else:
        write_json(path, configuration)


def produce_order(root, order, plantri, workers):
    from barnette_search import barnie_sequence as sequence
    target = root / "barnie-sequence"
    if order % 2:
        sequence._write_empty_order(target, order, "cubic graphs have even order", workers)
    else:
        # The generic exact-order producer also supports order 36, without
        # importing the lost historical order-36 source package.
        sequence.process_exact_order(target, order, plantri, workers, True)


def prepare_ladder(root, a, b):
    import networkx as nx
    from barnette_search.ladder_analysis import double_ladder_graph
    from barnette_search.planar_code import encode_planar_code, iter_planar_code, canonical_graph_hash
    from barnette_search.all_edge_flexibility import analyze_all_edge_pair_flexibility
    from io import BytesIO

    graph = nx.convert_node_labels_to_integers(double_ladder_graph(a, b))
    planar, embedding = nx.check_planarity(graph)
    if not planar:
        raise ValueError("constructed double ladder is not planar")
    rotation = tuple(tuple(embedding.neighbors_cw_order(v)) for v in range(len(graph)))
    payload = encode_planar_code(rotation)
    [embedded] = iter_planar_code(BytesIO(payload), require_header=True)
    directory = root / "ladder-inputs" / f"D_{a}_{b}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "graph.planar_code").write_bytes(payload)
    greedy = analyze_all_edge_pair_flexibility(
        graph, retain_pair_details=False, retain_witness_cycles=False,
        cross_check_backtracking=False,
    )
    if not greedy.property_satisfied:
        raise ValueError("no separating family constructed")
    write_json(directory / "input.json", {
        "a": a, "b": b, "order": len(graph),
        "canonical_graph_hash": canonical_graph_hash(embedded),
        "greedy_upper_bound": greedy.number_of_witness_cycles,
        "planar_code_sha256": sha256(payload).hexdigest(),
        "generation_index_scope": "0 identifies this constructed input; not a census rank",
    })


def terminate_tree(process):
    try:
        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        for item in reversed(descendants):
            try:
                item.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs(descendants + [parent], timeout=5)
        for item in alive:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    process.wait()


def run(args):
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    status_path = root / "status.json"
    if status_path.exists():
        previous = json.loads(status_path.read_text(encoding="utf-8"))
        try:
            old = psutil.Process(previous["pid"])
            if old.create_time() == previous.get("process_created"):
                raise RuntimeError("this reconstruction already has a running controller")
        except psutil.NoSuchProcess:
            pass
    state = {"pid": os.getpid(), "process_created": psutil.Process().create_time(),
             "started_utc": now(), "status": "running", "stage": "initializing"}
    scripts = Path(__file__).resolve().parent
    check_configuration(root, {
        "orders": args.orders, "workers": args.workers, "include_large_ladders": not args.no_large,
        "plantri": str(args.plantri.resolve()),
        "plantri_sha256": sha256(args.plantri.read_bytes()).hexdigest(),
        "source_sha256": {
            str(path.relative_to(scripts.parent)): sha256(path.read_bytes()).hexdigest()
            for folder in (scripts, scripts.parent / "src")
            for path in sorted(folder.rglob("*.py"))
        },
    }, args.resume)
    sequence_root = root / "barnie-sequence"
    completed = root / "completed"
    completed.mkdir(exist_ok=True)
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    if args.resume and (root / "PAUSE").exists():
        (root / "PAUSE").unlink()

    def stage(name, command):
        marker = completed / (name + ".json")
        if marker.exists():
            return
        state.update(stage=name, command=command, updated_utc=now())
        write_json(status_path, state)
        print(now(), "START", name, flush=True)
        started = time.perf_counter()
        with (logs / (name + ".log")).open("a", encoding="utf-8") as log:
            log.write("\n" + now() + " " + subprocess.list2cmdline(command) + "\n")
            log.flush()
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            state["child_pid"] = child.pid
            try:
                while child.poll() is None:
                    state["updated_utc"] = now()
                    write_json(status_path, state)
                    if (root / "PAUSE").exists():
                        terminate_tree(child)
                        state.update(status="paused", updated_utc=now())
                        write_json(status_path, state)
                        raise InterruptedError("paused; completed graph checkpoints retained")
                    time.sleep(2)
            except BaseException:
                if child.poll() is None:
                    terminate_tree(child)
                raise
            if child.returncode:
                raise RuntimeError(f"{name} failed, exit {child.returncode}; see {logs / (name + '.log')}")
        write_json(marker, {"finished_utc": now(), "command": command,
                            "seconds": time.perf_counter() - started})
        print(now(), "DONE", name, flush=True)

    try:
        for order in args.orders:
            stage(f"produce-{order:02d}", [sys.executable, str(Path(__file__).resolve()),
                  "--root", str(root), "--plantri", str(args.plantri.resolve()),
                  "--workers", str(args.workers), "--produce-order", str(order)])
            stage(f"verify-{order:02d}", [sys.executable, str(scripts / "verify_barnie_sequence.py"),
                  str(sequence_root), "--order", str(order), "--check-manifest",
                  "--report", str(root / "verification" / f"order_{order:02d}.json")])
        if set(args.orders) == set(range(8, 37)):
            from barnette_search import barnie_sequence as sequence
            summaries = []
            for order in range(8, 37):
                path = sequence_root / f"order_{order:02d}" / "order_summary.json"
                summary = json.loads(path.read_text(encoding="utf-8"))
                summary["proof_status"] = "independently_verified_reconstruction" if summary["graph_count"] else "undefined_empty_order"
                write_json(path, summary)
                sequence._manifest(path.parent)
                summaries.append(summary)
            sequence.write_global_outputs(sequence_root, summaries)
            sequence._manifest(sequence_root)
            stage("verify-global", [sys.executable, str(scripts / "verify_barnie_sequence.py"),
                  str(sequence_root), "--check-manifest", "--report", str(root / "verification" / "global.json")])
        if not args.no_large:
            for a, b in ((9, 9), (11, 9), (11, 11)):
                label = f"D_{a}_{b}"
                stage(f"prepare-{label}", [sys.executable, str(Path(__file__).resolve()),
                      "--root", str(root), "--prepare-ladder", str(a), str(b)])
                info = json.loads((root / "ladder-inputs" / label / "input.json").read_text())
                # Each failed attempt stays intact; a new attempt never overwrites it.
                destination = root / "double-ladders" / label
                attempt = 1
                while (destination / f"attempt-{attempt}").exists():
                    attempt += 1
                stage(f"certify-{label}", [sys.executable, str(scripts / "benchmark_hsep_single.py"),
                      "--planar-code", str(root / "ladder-inputs" / label / "graph.planar_code"),
                      "--expected-hash", info["canonical_graph_hash"], "--generation-index", "0",
                      "--expected-order", str(info["order"]), "--existing-greedy-upper-bound",
                      str(info["greedy_upper_bound"]), "--output", str(destination / f"attempt-{attempt}")])
        state.update(status="completed", updated_utc=now(), stage="all queued certificates verified")
        write_json(status_path, state)
    except InterruptedError:
        return 0
    except BaseException as error:
        state.update(status="failed", error=str(error), updated_utc=now())
        write_json(status_path, state)
        raise
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plantri", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--orders", type=int, nargs="+", default=list(range(26, 37)) + list(range(8, 26)))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-large", action="store_true")
    parser.add_argument("--produce-order", type=int)
    parser.add_argument("--prepare-ladder", type=int, nargs=2)
    args = parser.parse_args()
    if args.prepare_ladder:
        prepare_ladder(args.root, *args.prepare_ladder)
        return 0
    if args.plantri is None:
        parser.error("--plantri is required")
    if any(order not in range(8, 37) for order in args.orders):
        parser.error("orders must be between 8 and 36")
    if args.produce_order is not None:
        produce_order(args.root, args.produce_order, args.plantri, args.workers)
        return 0
    (args.root / "verification").mkdir(parents=True, exist_ok=True)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
