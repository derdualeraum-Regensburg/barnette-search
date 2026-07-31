#!/usr/bin/env python3
"""Build the complete, resumable Barnie maximizer drawing gallery."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draw_single_maximizer import (  # noqa: E402
    DEFAULT_ENGINE_OPTIONS,
    GalleryError,
    atomic_json,
    atomic_write,
    load_certified_maximizer,
    render_one,
    sha256_file,
)


INDEX_FIELDS = (
    "order",
    "M_B",
    "number_of_maximizers_for_order",
    "canonical_graph_hash",
    "hash_prefix",
    "generation_index",
    "plantri_rank",
    "face_size_multiset",
    "exact_hsep",
    "number_of_hamiltonian_cycles",
    "number_of_perfect_matchings",
    "automorphism_group_order",
    "drawing_svg",
    "drawing_png",
    "drawing_tex",
    "drawing_files",
    "unique_maximizer",
)


def _command_line(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def _tool_version(executable: Path) -> str | None:
    try:
        process = subprocess.run(
            [str(executable), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = process.stdout.decode("utf-8", errors="replace").strip()
    return text.splitlines()[0] if text else None


def _windows_file_version(executable: Path) -> str | None:
    if os.name != "nt":
        return None
    escaped = str(executable).replace("'", "''")
    try:
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-Item -LiteralPath '{escaped}').VersionInfo.ProductVersion",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = process.stdout.decode("utf-8", errors="replace").strip()
    return text.splitlines()[0] if process.returncode == 0 and text else None


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise GalleryError(f"invalid PNG output: {path}")
    return struct.unpack(">II", data[16:24])


def render_png(
    svg_path: Path,
    png_path: Path,
    renderer: Path,
    resume_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    renderer_hash = sha256_file(renderer)
    saved_hashes = (resume_metadata or {}).get("output_sha256", {})
    can_resume = (
        (resume_metadata or {}).get("png_renderer_sha256") == renderer_hash
        and saved_hashes.get("svg") == sha256_file(svg_path)
        and isinstance(saved_hashes.get("png"), str)
    )
    if can_resume and png_path.is_file():
        try:
            width, height = _png_dimensions(png_path)
            if (
                (width, height) == (900, 900)
                and sha256_file(png_path) == saved_hashes["png"]
            ):
                return {
                    "path": png_path,
                    "sha256": sha256_file(png_path),
                    "renderer_sha256": renderer_hash,
                    "dimensions": [width, height],
                    "resume_status": "reused",
                    "command": [
                        str(renderer.resolve()),
                        "--headless",
                        "--disable-gpu",
                        "--hide-scrollbars",
                        "--force-device-scale-factor=1",
                        "--window-size=900,900",
                        "--user-data-dir=<temporary-profile>",
                        f"--screenshot={png_path.resolve()}",
                        svg_path.resolve().as_uri(),
                    ],
                }
        except (OSError, GalleryError):
            pass

    png_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_png = png_path.parent / f".{png_path.stem}.tmp.png"
    try:
        temporary_png.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="barnie-edge-profile-") as profile:
            actual_command = [
                str(renderer.resolve()),
                "--headless",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--window-size=900,900",
                f"--user-data-dir={profile}",
                f"--screenshot={temporary_png.resolve()}",
                svg_path.resolve().as_uri(),
            ]
            process = subprocess.run(
                actual_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
        if process.returncode != 0 or not temporary_png.is_file():
            stderr = process.stderr.decode("utf-8", errors="replace").strip()
            raise GalleryError(
                f"PNG renderer returned {process.returncode}: {stderr}"
            )
        width, height = _png_dimensions(temporary_png)
        if (width, height) != (900, 900):
            raise GalleryError(f"unexpected PNG dimensions: {width}x{height}")
        os.replace(temporary_png, png_path)
    finally:
        temporary_png.unlink(missing_ok=True)

    normalized_command = [
        str(renderer.resolve()),
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=900,900",
        "--user-data-dir=<temporary-profile>",
        f"--screenshot={png_path.resolve()}",
        svg_path.resolve().as_uri(),
    ]
    return {
        "path": png_path,
        "sha256": sha256_file(png_path),
        "renderer_sha256": renderer_hash,
        "dimensions": [width, height],
        "resume_status": "rendered",
        "command": normalized_command,
    }


def certified_orders(sequence_root: Path) -> list[dict[str, Any]]:
    sequence_path = sequence_root / "barnie_sequence.json"
    sequence = json.loads(sequence_path.read_text(encoding="utf-8"))
    orders = []
    for record in sequence.get("orders", []):
        if record.get("M_B") is None:
            continue
        order = int(record["order"])
        summary_path = sequence_root / f"order_{order:02d}" / "order_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for field in ("M_B", "number_of_maximizers", "maximizer_hashes"):
            if summary.get(field) != record.get(field):
                raise GalleryError(
                    f"global/order summary mismatch for order {order}, field {field}"
                )
        if summary.get("proof_status") not in {
            "independently_verified_exact_extremal_statement",
            "imported_and_independently_reverified_order36",
        }:
            raise GalleryError(f"order {order} is not independently certified")
        orders.append(summary)
    return sorted(orders, key=lambda item: int(item["order"]))


def index_record(
    summary: dict[str, Any],
    graph: dict[str, Any],
    exact: dict[str, Any],
    render: dict[str, Any],
    png: dict[str, Any] | None,
) -> dict[str, Any]:
    files = dict(render["drawing_files"])
    if png is not None:
        files["png"] = png["path"].relative_to(Path(render["gallery_root"])).as_posix()
    ordered_files = [files[key] for key in ("svg", "png", "tex") if key in files]
    return {
        "order": summary["order"],
        "M_B": summary["M_B"],
        "number_of_maximizers_for_order": summary["number_of_maximizers"],
        "canonical_graph_hash": graph["canonical_graph_hash"],
        "hash_prefix": graph["canonical_graph_hash"][:8],
        "generation_index": graph["generation_index"],
        "plantri_rank": graph["plantri_rank"],
        "face_size_multiset": graph["face_size_multiset"],
        "exact_hsep": exact["exact_hsep"],
        "number_of_hamiltonian_cycles": exact.get("complete_hamiltonian_cycle_count"),
        "number_of_perfect_matchings": exact.get("perfect_matching_count"),
        "automorphism_group_order": exact.get("automorphism_group_order"),
        "drawing_svg": files["svg"],
        "drawing_png": files.get("png"),
        "drawing_tex": files["tex"],
        "drawing_files": ordered_files,
        "unique_maximizer": bool(summary["unique_maximizer"]),
    }


def write_index(gallery_root: Path, records: list[dict[str, Any]]) -> None:
    payload = {
        "schema": "barnie-maximizer-gallery-index-v1",
        "certified_order_count": len({record["order"] for record in records}),
        "drawing_count": len(records),
        "records": records,
    }
    atomic_json(gallery_root / "gallery_index.json", payload)

    rows = []
    for record in records:
        row = dict(record)
        row["face_size_multiset"] = ";".join(map(str, record["face_size_multiset"]))
        row["drawing_files"] = ";".join(record["drawing_files"])
        rows.append(row)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=gallery_root,
        prefix=".gallery_index.", suffix=".tmp"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temporary_name = stream.name
    os.replace(temporary_name, gallery_root / "gallery_index.csv")


def write_report(
    gallery_root: Path,
    summaries: list[dict[str, Any]],
    records: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    environment: dict[str, Any],
) -> None:
    face_lists = [record["face_size_multiset"] for record in records]
    quadrilateral_counts = [faces.count(4) for faces in face_lists]
    largest_faces = [max(faces) for faces in face_lists]
    lines = [
        "# Barnie maximizer gallery",
        "",
        "This gallery is a visualization layer built on top of the already certified "
        "Barnie-sequence results. It does not rerun or alter the hsep certification.",
        "",
        "## Drawing engine and reproduction",
        "",
        "Every layout was produced from the certified `planar_code` embedding by Gunnar "
        "Brinkmann's external C drawing program. The common options are `T n B`: unlabeled "
        "vertices and the program's deterministic best-distance search. Option `T` supplies "
        "the certified planar code in the program's ASCII input form, avoiding Windows CRT "
        "binary-stdin translation. The raw TikZ output "
        "is retained; the wrapper verifies its vertex and edge sets against the certified "
        "graph record and converts the coordinates to SVG. PNG files are raster previews of "
        "those SVGs.",
        "",
        f"External source SHA-256: `{environment['drawing_engine']['source_sha256']}`  ",
        f"Compiled executable SHA-256: `{environment['drawing_engine']['executable_sha256']}`  ",
        f"Compiler: `{environment['compiler']['version']}`",
        "",
        "Compilation command (with the compiler directory prepended to `PATH`):",
        "",
        "```text",
        environment["compiler"]["command_line"],
        "```",
        "",
        "Complete reproduction:",
        "",
        "```text",
        environment["gallery_command_line"],
        "```",
        "",
        "## Certified orders",
        "",
        "| order | M_B(n) | maximizers | unique | drawings |",
        "|---:|---:|---:|:---:|---:|",
    ]
    counts: dict[int, int] = {}
    for record in records:
        counts[int(record["order"])] = counts.get(int(record["order"]), 0) + 1
    for summary in summaries:
        n = int(summary["order"])
        lines.append(
            f"| {n} | {summary['M_B']} | {summary['number_of_maximizers']} | "
            f"{'yes' if summary['unique_maximizer'] else 'no'} | {counts.get(n, 0)} |"
        )
    lines.extend([
        "",
        "Tied orders are represented by every certified maximizer, not by a selected "
        "representative.",
        "",
        "## Visible structural patterns among maximizers",
        "",
        (
            f"Across these {len(records)} drawings, the certified face multisets are "
            f"quadrilateral-rich: the number of 4-faces ranges from "
            f"{min(quadrilateral_counts)} to {max(quadrilateral_counts)}. The largest face "
            f"size in an individual maximizer ranges from {min(largest_faces)} to "
            f"{max(largest_faces)}. The layouts also show substantial variation among tied "
            "maximizers. These observations are descriptive only; the gallery does not by "
            "itself establish a shared construction or classification."
        ),
        "",
        "## Images intended for later expert discussion",
        "",
        "The external drawing program was used intentionally because it derives "
        "mathematically faithful planar layouts from the certified embeddings. The SVGs "
        "and raw TikZ sources are intended for later expert comparison and discussion; "
        "they are not additional optimality certificates.",
        "",
        "## Completion status",
        "",
        f"Rendered and indexed: **{len(records)}** drawings across **{len(summaries)}** "
        "certified nonempty orders.",
    ])
    if failures:
        lines.extend([
            "",
            f"Failures: **{len(failures)}**. See `failures.json` for details.",
        ])
    else:
        lines.extend(["", "Failures: **0**."])
    atomic_write(gallery_root / "GALLERY_REPORT.md", ("\n".join(lines) + "\n").encode("utf-8"))


def write_manifest(gallery_root: Path) -> None:
    entries = []
    for path in sorted(gallery_root.rglob("*"), key=lambda item: item.relative_to(gallery_root).as_posix()):
        if not path.is_file() or path.name == "SHA256SUMS.txt":
            continue
        relative = path.relative_to(gallery_root).as_posix()
        entries.append(f"{sha256_file(path)}  {relative}")
    atomic_write(gallery_root / "SHA256SUMS.txt", ("\n".join(entries) + "\n").encode("ascii"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence-root", type=Path, required=True)
    parser.add_argument("--gallery-root", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--engine-source", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--compat-include", type=Path, required=True)
    parser.add_argument("--png-renderer", type=Path)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--toolchain-url")
    parser.add_argument("--toolchain-sha256")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sequence_root = args.sequence_root.resolve()
    gallery_root = args.gallery_root.resolve()
    engine = args.engine.resolve()
    engine_source = args.engine_source.resolve()
    compiler = args.compiler.resolve()
    compat_include = args.compat_include.resolve()
    png_renderer = args.png_renderer.resolve() if args.png_renderer else None
    gallery_root.mkdir(parents=True, exist_ok=True)

    compilation_command = [
        str(compiler), "-O4", "-std=gnu11", "-I", str(compat_include),
        "-Wl,--stack,67108864",
        "-o", str(engine), str(engine_source), "-lm",
    ]
    invocation = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    environment = {
        "schema": "barnie-maximizer-gallery-environment-v1",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "worker_count": 1,
        "engine_options": list(DEFAULT_ENGINE_OPTIONS),
        "drawing_engine": {
            "name": "Gunnar Brinkmann planar_draw",
            "source_path": str(engine_source),
            "source_sha256": sha256_file(engine_source),
            "executable_path": str(engine),
            "executable_sha256": sha256_file(engine),
        },
        "compiler": {
            "path": str(compiler),
            "version": _tool_version(compiler),
            "command": compilation_command,
            "command_line": _command_line(compilation_command),
            "compatibility_include": str(compat_include),
            "toolchain_download_url": args.toolchain_url,
            "toolchain_download_sha256": args.toolchain_sha256,
        },
        "png_renderer": None if png_renderer is None else {
            "path": str(png_renderer),
            "version": _windows_file_version(png_renderer) or _tool_version(png_renderer),
            "sha256": sha256_file(png_renderer),
        },
        "certification_inputs": {
            "barnie_sequence_json_sha256": sha256_file(sequence_root / "barnie_sequence.json"),
            "barnie_sequence_manifest_sha256": sha256_file(sequence_root / "SHA256SUMS.txt"),
        },
        "gallery_command": invocation,
        "gallery_command_line": _command_line(invocation),
    }

    failures: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    commands = ["COMPILE\t" + environment["compiler"]["command_line"]]
    try:
        summaries = certified_orders(sequence_root)
    except (GalleryError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for summary in summaries:
        order = int(summary["order"])
        for graph_hash in summary["maximizer_hashes"]:
            try:
                graph_summary, graph, exact = load_certified_maximizer(
                    sequence_root, order, graph_hash
                )
                render = render_one(
                    sequence_root=sequence_root,
                    gallery_root=gallery_root,
                    engine=engine,
                    order=order,
                    graph_hash=graph_hash,
                    resume=not args.no_resume,
                )
                render["gallery_root"] = str(gallery_root)
                commands.append(
                    "RENDER\t" + _command_line(render["engine_command"])
                    + f" < planar_code_sha256:{render['planar_code_sha256']}"
                )
                png = None
                if png_renderer is not None:
                    svg_path = gallery_root / render["drawing_files"]["svg"]
                    png_path = svg_path.with_suffix(".png")
                    sidecar = gallery_root / f"order_{order:02d}" / f"{render['stem']}.render.json"
                    resume_metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                    png = render_png(
                        svg_path, png_path, png_renderer, resume_metadata
                    )
                    commands.append("PNG\t" + _command_line(png["command"]))
                    sidecar_data = json.loads(sidecar.read_text(encoding="utf-8"))
                    sidecar_data["drawing_files"]["png"] = png_path.relative_to(gallery_root).as_posix()
                    sidecar_data["output_sha256"]["png"] = png["sha256"]
                    sidecar_data["png_renderer_sha256"] = png["renderer_sha256"]
                    sidecar_data["png_renderer_command"] = png["command"]
                    sidecar_data["png_dimensions"] = png["dimensions"]
                    atomic_json(sidecar, sidecar_data)
                records.append(index_record(graph_summary, graph, exact, render, png))
                print(f"OK order={order} rank={graph['plantri_rank']} hash={graph_hash[:8]}")
            except (GalleryError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                failure = {"order": order, "canonical_graph_hash": graph_hash, "error": str(exc)}
                failures.append(failure)
                print(f"FAIL order={order} hash={graph_hash[:8]}: {exc}", file=sys.stderr)

    records.sort(key=lambda item: (int(item["order"]), int(item["plantri_rank"]), item["canonical_graph_hash"]))
    write_index(gallery_root, records)
    atomic_json(gallery_root / "failures.json", {"schema": "barnie-gallery-failures-v1", "failures": failures})
    atomic_json(gallery_root / "environment.json", environment)
    atomic_write(gallery_root / "commands.log", ("\n".join(commands) + "\n").encode("utf-8"))
    script_copies = (
        (Path(__file__).resolve(), gallery_root / "render_all_maximizers.py"),
        (
            Path(__file__).resolve().with_name("draw_single_maximizer.py"),
            gallery_root / "draw_single_maximizer.py",
        ),
    )
    for source, destination in script_copies:
        if source != destination.resolve():
            shutil.copyfile(source, destination)
    write_report(gallery_root, summaries, records, failures, environment)
    write_manifest(gallery_root)

    expected = sum(int(summary["number_of_maximizers"]) for summary in summaries)
    if failures or len(records) != expected:
        print(f"INCOMPLETE: rendered {len(records)} of {expected}; failures={len(failures)}", file=sys.stderr)
        return 1
    print(f"COMPLETE: rendered {len(records)} maximizers across {len(summaries)} orders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
