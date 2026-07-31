#!/usr/bin/env python3
"""Render one certified Barnie-sequence maximizer with planar_draw."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ENGINE_OPTIONS = ("T", "n", "B")
SVG_SIZE = 900
SVG_PADDING = 45.0

_NODE_RE = re.compile(
    r"^\\node\s+\[[^]]*\]\s+\((\d+)\)\s+at\s+"
    r"\((-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\)\s+\{\};$"
)
_EDGE_RE = re.compile(
    r"^\\draw\s+\[[^]]*\]\s+\((\d+)\)\s+to\s+\((\d+)\);$"
)


class GalleryError(RuntimeError):
    """Raised when certified metadata or drawing output is inconsistent."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_json(path: Path, value: Any) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    atomic_write(path, payload)


def iter_jsonl_gzip(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise GalleryError(f"invalid JSON at {path}:{line_number}: {exc}") from exc


def find_record(path: Path, graph_hash: str) -> dict[str, Any]:
    matches = [
        record
        for record in iter_jsonl_gzip(path)
        if record.get("canonical_graph_hash") == graph_hash
    ]
    if len(matches) != 1:
        raise GalleryError(
            f"expected one record for {graph_hash} in {path}, found {len(matches)}"
        )
    return matches[0]


def load_certified_maximizer(
    sequence_root: Path, order: int, graph_hash: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    order_root = sequence_root / f"order_{order:02d}"
    summary_path = order_root / "order_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("order") != order:
        raise GalleryError(f"order mismatch in {summary_path}")
    if summary.get("M_B") is None:
        raise GalleryError(f"order {order} has no certified finite M_B value")
    hashes = summary.get("maximizer_hashes")
    if not isinstance(hashes, list) or graph_hash not in hashes:
        raise GalleryError(f"{graph_hash} is not a certified maximizer at order {order}")
    if len(hashes) != summary.get("number_of_maximizers"):
        raise GalleryError(f"maximizer count mismatch in {summary_path}")

    graph = find_record(order_root / "graph_certificates.jsonl.gz", graph_hash)
    exact = find_record(order_root / "exact_certificates.jsonl.gz", graph_hash)
    if graph.get("graph_order") != order or exact.get("graph_order") != order:
        raise GalleryError(f"graph order mismatch for {graph_hash}")
    if exact.get("exact_hsep") != summary.get("M_B"):
        raise GalleryError(f"exact hsep mismatch for {graph_hash}")
    for field in ("generation_index", "plantri_rank"):
        if graph.get(field) != exact.get(field):
            raise GalleryError(f"{field} mismatch for {graph_hash}")
    return summary, graph, exact


def decode_planar_code(graph: dict[str, Any]) -> bytes:
    try:
        data = base64.b64decode(graph["planar_code_base64"], validate=True)
    except (KeyError, ValueError) as exc:
        raise GalleryError("invalid planar_code_base64") from exc
    expected = graph.get("planar_code_sha256")
    actual = sha256_bytes(data)
    if actual != expected:
        raise GalleryError(f"planar_code SHA-256 mismatch: {actual} != {expected}")
    if not data.startswith(b">>planar_code<<"):
        raise GalleryError("planar_code header is missing")
    return data


def planar_code_to_ascii(data: bytes) -> bytes:
    """Convert one small binary planar_code record to planar_draw's T format."""
    header = b">>planar_code<<"
    payload = data[len(header):] if data.startswith(header) else data
    if not payload:
        raise GalleryError("empty planar_code payload")
    order = payload[0]
    if order == 0:
        raise GalleryError("wide planar_code is not supported by this gallery wrapper")
    zero_count = 0
    end = None
    for index, value in enumerate(payload[1:], 1):
        if value == 0:
            zero_count += 1
            if zero_count == order:
                end = index + 1
                break
    if end is None or end != len(payload):
        raise GalleryError("planar_code does not contain exactly one complete record")
    return (" ".join(str(value) for value in payload) + "\n").encode("ascii")


def run_engine(
    engine: Path, planar_code: bytes, options: tuple[str, ...]
) -> tuple[str, str, list[str]]:
    command = [str(engine.resolve()), *options]
    engine_input = planar_code_to_ascii(planar_code) if "T" in options else planar_code
    process = subprocess.run(
        command,
        input=engine_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    stderr = process.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if process.returncode != 0:
        raise GalleryError(
            f"drawing engine returned {process.returncode}: {stderr.strip()}"
        )
    try:
        tex = process.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GalleryError("drawing engine emitted non-UTF-8 output") from exc
    tex = tex.replace("\r\n", "\n").replace("\r", "\n")
    if tex.count("\\begin{tikzpicture}") != 1 or tex.count("\\end{tikzpicture}") != 1:
        raise GalleryError("drawing engine did not emit exactly one TikZ drawing")
    return tex, stderr, command


def parse_planar_tikz(tex: str) -> tuple[dict[int, tuple[float, float]], list[tuple[int, int]]]:
    vertices: dict[int, tuple[float, float]] = {}
    edges: list[tuple[int, int]] = []
    for raw_line in tex.splitlines():
        line = raw_line.strip()
        node = _NODE_RE.match(line)
        if node:
            vertex = int(node.group(1))
            if vertex in vertices:
                raise GalleryError(f"duplicate TikZ vertex {vertex}")
            vertices[vertex] = (float(node.group(2)), float(node.group(3)))
            continue
        edge = _EDGE_RE.match(line)
        if edge:
            endpoints = tuple(sorted((int(edge.group(1)), int(edge.group(2)))))
            edges.append(endpoints)
    if not vertices:
        raise GalleryError("no vertices found in TikZ output")
    if not edges:
        raise GalleryError("no edges found in TikZ output")
    if len(edges) != len(set(edges)):
        raise GalleryError("duplicate edges found in TikZ output")
    return vertices, sorted(edges)


def verify_tikz_graph(
    vertices: dict[int, tuple[float, float]],
    edges: list[tuple[int, int]],
    graph: dict[str, Any],
) -> None:
    expected_vertices = set(range(1, int(graph["graph_order"]) + 1))
    if set(vertices) != expected_vertices:
        raise GalleryError("TikZ vertex set does not match the certified graph")
    expected_edges = {
        tuple(sorted((int(u) + 1, int(v) + 1))) for u, v in graph["edges"]
    }
    if set(edges) != expected_edges or len(edges) != int(graph["edge_count"]):
        raise GalleryError("TikZ edge set does not match the certified graph")


def make_svg(
    vertices: dict[int, tuple[float, float]],
    edges: list[tuple[int, int]],
    *,
    title: str,
    description: str,
) -> str:
    xs = [point[0] for point in vertices.values()]
    ys = [point[1] for point in vertices.values()]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    span = max(width, height, 1.0)
    scale = (SVG_SIZE - 2.0 * SVG_PADDING) / span
    used_width = width * scale
    used_height = height * scale
    left = (SVG_SIZE - used_width) / 2.0
    top = (SVG_SIZE - used_height) / 2.0

    transformed: dict[int, tuple[float, float]] = {}
    for vertex, (x, y) in vertices.items():
        transformed[vertex] = (
            left + (x - min(xs)) * scale,
            top + (max(ys) - y) * scale,
        )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_SIZE}" '
            f'height="{SVG_SIZE}" viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" '
            'role="img">'
        ),
        f"  <title>{html.escape(title)}</title>",
        f"  <desc>{html.escape(description)}</desc>",
        '  <rect width="900" height="900" fill="white"/>',
        '  <g fill="none" stroke="#111" stroke-width="2.25" '
        'stroke-linecap="round" stroke-linejoin="round">',
    ]
    for u, v in edges:
        x1, y1 = transformed[u]
        x2, y2 = transformed[v]
        lines.append(
            f'    <line x1="{x1:.3f}" y1="{y1:.3f}" '
            f'x2="{x2:.3f}" y2="{y2:.3f}"/>'
        )
    lines.extend(['  </g>', '  <g fill="#111">'])
    for vertex in sorted(transformed):
        x, y = transformed[vertex]
        lines.append(
            f'    <circle id="v{vertex}" data-vertex="{vertex}" '
            f'cx="{x:.3f}" cy="{y:.3f}" r="5.5"/>'
        )
    lines.extend(["  </g>", "</svg>"])
    return "\n".join(lines) + "\n"


def deterministic_stem(summary: dict[str, Any], graph: dict[str, Any]) -> str:
    return (
        f"n_{int(summary['order']):02d}_M_{int(summary['M_B'])}_"
        f"rank_{int(graph['plantri_rank']):05d}_"
        f"{graph['canonical_graph_hash'][:8]}"
    )


def _resume_valid(sidecar: Path, expected: dict[str, Any], files: list[Path]) -> bool:
    if not sidecar.is_file() or not all(path.is_file() for path in files):
        return False
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for key, value in expected.items():
        if metadata.get(key) != value:
            return False
    hashes = metadata.get("output_sha256", {})
    return all(hashes.get(path.suffix.lstrip(".")) == sha256_file(path) for path in files)


def render_one(
    *,
    sequence_root: Path,
    gallery_root: Path,
    engine: Path,
    order: int,
    graph_hash: str,
    options: tuple[str, ...] = DEFAULT_ENGINE_OPTIONS,
    resume: bool = True,
) -> dict[str, Any]:
    summary, graph, exact = load_certified_maximizer(sequence_root, order, graph_hash)
    planar_code = decode_planar_code(graph)
    engine_hash = sha256_file(engine)
    stem = deterministic_stem(summary, graph)
    order_root = gallery_root / f"order_{order:02d}"
    tex_path = order_root / f"{stem}.tex"
    svg_path = order_root / f"{stem}.svg"
    sidecar_path = order_root / f"{stem}.render.json"
    expected = {
        "schema": "barnie-maximizer-render-v1",
        "canonical_graph_hash": graph_hash,
        "planar_code_sha256": graph["planar_code_sha256"],
        "engine_sha256": engine_hash,
        "engine_options": list(options),
        "engine_input_format": "ASCII planar_code (option T)" if "T" in options else "binary planar_code",
    }
    files = [tex_path, svg_path]
    if resume and _resume_valid(sidecar_path, expected, files):
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        metadata["resume_status"] = "reused"
        return metadata

    tex, stderr, command = run_engine(engine, planar_code, options)
    vertices, edges = parse_planar_tikz(tex)
    verify_tikz_graph(vertices, edges, graph)
    title = f"Barnie maximizer n={order}, M_B({order})={summary['M_B']}, rank={graph['plantri_rank']}"
    description = (
        f"Canonical graph SHA-256 {graph_hash}; structurally faithful planar drawing "
        "generated from the certified planar_code embedding."
    )
    svg = make_svg(vertices, edges, title=title, description=description)
    atomic_write(tex_path, tex.encode("utf-8"))
    atomic_write(svg_path, svg.encode("utf-8"))

    metadata = {
        **expected,
        "order": order,
        "M_B": summary["M_B"],
        "generation_index": graph["generation_index"],
        "plantri_rank": graph["plantri_rank"],
        "stem": stem,
        "vertex_count": len(vertices),
        "edge_count": len(edges),
        "engine_command": command,
        "engine_stderr": stderr.strip(),
        "drawing_files": {
            "tex": tex_path.relative_to(gallery_root).as_posix(),
            "svg": svg_path.relative_to(gallery_root).as_posix(),
        },
        "output_sha256": {
            "tex": sha256_file(tex_path),
            "svg": sha256_file(svg_path),
        },
        "resume_status": "rendered",
    }
    atomic_json(sidecar_path, metadata)
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence-root", type=Path, required=True)
    parser.add_argument("--gallery-root", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--graph-hash", required=True)
    parser.add_argument(
        "--engine-option",
        action="append",
        dest="engine_options",
        help="planar_draw option; repeat to override the default 'T n B'",
    )
    parser.add_argument("--no-resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = tuple(args.engine_options or DEFAULT_ENGINE_OPTIONS)
    try:
        result = render_one(
            sequence_root=args.sequence_root.resolve(),
            gallery_root=args.gallery_root.resolve(),
            engine=args.engine.resolve(),
            order=args.order,
            graph_hash=args.graph_hash,
            options=options,
            resume=not args.no_resume,
        )
    except (GalleryError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
