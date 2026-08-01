#!/usr/bin/env python3
"""Standard-library verifier for the Bauer double-ladder gallery."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(root: Path) -> int:
    expected: dict[str, str] = {}
    for line in (root / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
        digest, relative = line.split("  ", 1)
        if relative in expected:
            raise ValueError(f"duplicate manifest entry: {relative}")
        expected[relative] = digest
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    if set(expected) != actual_files:
        missing = sorted(actual_files - set(expected))
        extra = sorted(set(expected) - actual_files)
        raise ValueError(f"manifest file-set mismatch; missing={missing}, extra={extra}")
    for relative, digest in expected.items():
        if sha256_file(root / relative) != digest:
            raise ValueError(f"manifest checksum mismatch: {relative}")
    return len(expected)


def parse_svg_graph(path: Path) -> tuple[set[int], set[tuple[int, int]], dict[str, int]]:
    tree = ET.parse(path)
    vertices: set[int] = set()
    edges: set[tuple[int, int]] = set()
    classes: dict[str, int] = {}
    for element in tree.iter():
        vertex = element.attrib.get("data-vertex")
        if vertex is not None:
            value = int(vertex)
            if value in vertices:
                raise ValueError(f"duplicate vertex in {path}: {value}")
            vertices.add(value)
        if "data-u" in element.attrib:
            edge = tuple(sorted((int(element.attrib["data-u"]), int(element.attrib["data-v"]))))
            if edge in edges:
                raise ValueError(f"duplicate graph edge in {path}: {edge}")
            edges.add(edge)
            name = element.attrib["data-class"]
            classes[name] = classes.get(name, 0) + 1
    return vertices, edges, classes


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"invalid PNG: {path}")
    return struct.unpack(">II", data[16:24])


def verify_graph(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    expected_vertices = set(range(int(record["order"])))
    expected_edges = {tuple(edge) for edge in record["canonical_edges"]}
    output: dict[str, Any] = {"label": record["label"], "status": "pass"}
    for variant in ("clean", "annotated"):
        svg = root / record[f"{variant}_svg"]
        vertices, edges, classes = parse_svg_graph(svg)
        if vertices != expected_vertices or edges != expected_edges:
            raise ValueError(f"SVG graph mismatch: {svg}")
        if set(classes) != {"a_rail", "a_rung", "b_rail", "b_rung", "connector"}:
            raise ValueError(f"incomplete edge classification: {svg}: {classes}")
        if classes["connector"] != 4:
            raise ValueError(f"connector count is not four: {svg}")
        pdf = root / record[f"{variant}_pdf"]
        payload = pdf.read_bytes()
        if not payload.startswith(b"%PDF-1.4") or not payload.rstrip().endswith(b"%%EOF"):
            raise ValueError(f"invalid PDF envelope: {pdf}")
        png = root / record[f"{variant}_png"]
        dimensions = png_dimensions(png)
        if min(dimensions) < 2000:
            raise ValueError(f"PNG is not high resolution: {png}: {dimensions}")
        output[f"{variant}_png_dimensions"] = list(dimensions)
    annotation = json.loads((root / record["annotation_json"]).read_text(encoding="utf-8"))
    if len(annotation["cap_faces"]) != 4:
        raise ValueError(f"cap-face annotation mismatch: {record['label']}")
    expected_insertions = 0 if record["label"] == "D(1,1)" else 4
    if len(annotation["inserted_vertices"]) != expected_insertions:
        raise ValueError(f"insertion annotation mismatch: {record['label']}")
    return output


def verify(root: Path) -> dict[str, Any]:
    manifest_count = verify_manifest(root)
    metadata = json.loads((root / "graph_metadata.json").read_text(encoding="utf-8"))
    graphs = metadata["graphs"]
    if len(graphs) != 11:
        raise ValueError(f"expected 11 graph records, found {len(graphs)}")
    expected_labels = ["D(1,1)", "D(3,1)", "D(3,3)", "D(5,3)", "D(5,5)",
                       "D(7,5)", "D(7,7)", "D(9,7)", "D(9,9)", "D(11,9)", "D(11,11)"]
    if [record["label"] for record in graphs] != expected_labels:
        raise ValueError("graph order/label sequence mismatch")
    results = [verify_graph(root, record) for record in graphs]
    composite_files = sorted((root / "composite").glob("*"))
    if len(composite_files) != 18:
        raise ValueError(f"expected 18 composite files, found {len(composite_files)}")
    for path in composite_files:
        if path.suffix == ".png" and min(png_dimensions(path)) < 1000:
            raise ValueError(f"composite PNG too small: {path}")
        if path.suffix == ".svg":
            ET.parse(path)
        if path.suffix == ".pdf":
            payload = path.read_bytes()
            if not payload.startswith(b"%PDF") or not payload.rstrip().endswith(b"%%EOF"):
                raise ValueError(f"invalid composite PDF: {path}")
    return {"schema": "bauer-double-ladder-gallery-verification-v1", "status": "pass",
            "manifest_file_count": manifest_count, "graph_count": len(graphs),
            "composite_file_count": len(composite_files), "graphs": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify(args.root.resolve())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"PASS: {result['graph_count']} graphs, {result['composite_file_count']} composite files, {result['manifest_file_count']} manifested files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
