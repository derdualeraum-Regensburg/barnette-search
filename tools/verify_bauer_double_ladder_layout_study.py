#!/usr/bin/env python3
"""Independent standard-library verifier for the Bauer layout-study package."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "bauer-double-ladder-layout-study-v1"
EXPECTED_LABELS = [
    "D(1,1)", "D(3,1)", "D(3,3)", "D(5,3)", "D(5,5)", "D(7,5)",
    "D(7,7)", "D(9,7)", "D(9,9)", "D(11,9)", "D(11,11)",
]
COMPOSITES = ["certified_bauer_family", "extended_double_ladder_family",
              "square_insertion_sequence", "outer_face_comparison",
              "raw_vs_normalized_layout"]


class VerificationError(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(root: Path) -> int:
    lines = (root / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()
    for line in lines:
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or digest(path) != expected:
            raise VerificationError(f"manifest mismatch: {relative}")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path.name != "SHA256SUMS.txt"}
    listed = {line.split("  ", 1)[1] for line in lines}
    if actual != listed:
        raise VerificationError(f"manifest coverage mismatch: extra={actual-listed}, missing={listed-actual}")
    return len(lines)


def svg_identity(path: Path) -> tuple[set[int], set[tuple[int, int]]]:
    root = ET.parse(path).getroot()
    vertices = {int(item.attrib["data-vertex"]) for item in root.iter()
                if "data-vertex" in item.attrib}
    edges = set()
    for item in root.iter():
        if "data-u" in item.attrib and "data-v" in item.attrib:
            u, v = int(item.attrib["data-u"]), int(item.attrib["data-v"])
            edges.add((u, v) if u < v else (v, u))
    return vertices, edges


def verify_png(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise VerificationError(f"invalid PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if min(width, height) < 1000 or width * height < 3_000_000:
        raise VerificationError(f"PNG is not high resolution: {path} ({width}x{height})")
    return width, height


def verify(root: Path) -> dict[str, Any]:
    required = ["LAYOUT_STUDY_REPORT.md", "candidate_scores.csv", "candidate_scores.json",
                "selected_layouts.json", "layout_overrides.json", "structural_coordinates.json",
                "family_alignment.json", "drawing_verification.json", "commands.log",
                "environment.json", "SHA256SUMS.txt"]
    for name in required:
        if not (root / name).is_file():
            raise VerificationError(f"missing required file: {name}")
    manifest_entries = verify_manifest(root)
    structure = payload(root / "structural_coordinates.json")
    selected = payload(root / "selected_layouts.json")
    checks = payload(root / "drawing_verification.json")
    scores = payload(root / "candidate_scores.json")
    for item in (structure, selected, checks, scores):
        if item.get("schema") != SCHEMA:
            raise VerificationError("schema mismatch")
    if set(structure["graphs"]) != set(EXPECTED_LABELS):
        raise VerificationError("graph sequence mismatch")
    chosen = selected["complete_sequence"]["graphs"]
    if [item["label"] for item in chosen] != EXPECTED_LABELS:
        raise VerificationError("selected graph sequence mismatch")
    if scores["candidate_count"] != 12672:
        raise VerificationError("unexpected candidate count")
    verified = checks.get("selected_drawings", [])
    if checks.get("status") != "pass" or len(verified) != 11:
        raise VerificationError("drawing verification status/count mismatch")
    if any(item["crossing_count"] != 0 for item in verified):
        raise VerificationError("a selected drawing has crossings")

    graph_results = []
    for label, choice, verification in zip(EXPECTED_LABELS, chosen, verified):
        graph = structure["graphs"][label]
        stem = label.replace("(", "_").replace(",", "_").replace(")", "")
        expected_vertices = set(range(graph["order"]))
        expected_edges = {tuple(item["endpoints"]) for item in graph["edges"]}
        if choice["outer_face_structural_id"] != "B_rail_0":
            raise VerificationError(f"unexpected selected cap for {label}")
        if not choice.get("coordinate_refinement_used"):
            raise VerificationError(f"refinement absent for {label}")
        refinement = payload(root / "refined" / f"{stem}.json")
        if refinement["crossing_count"] != 0 or not refinement["outer_face_convex"]:
            raise VerificationError(f"refinement checks failed for {label}")
        for folder in ("normalized", "refined", "annotated"):
            vertices, edges = svg_identity(root / folder / f"{stem}.svg")
            if vertices != expected_vertices or edges != expected_edges:
                raise VerificationError(f"SVG graph identity mismatch: {folder}/{stem}.svg")
            png_size = verify_png(root / folder / f"{stem}.png")
            pdf = root / folder / f"{stem}.pdf"
            if not pdf.read_bytes().startswith(b"%PDF-"):
                raise VerificationError(f"invalid PDF: {pdf}")
        if graph["order"] > 36 and not verification["global_extremality_disclaimer_required"]:
            raise VerificationError(f"missing extremality disclaimer flag for {label}")
        graph_results.append({"label": label, "status": "pass", "png_size": png_size})

    for name in COMPOSITES:
        for suffix in ("pdf", "svg", "png"):
            path = root / "composite" / f"{name}.{suffix}"
            if not path.is_file():
                raise VerificationError(f"missing composite: {path}")
        verify_png(root / "composite" / f"{name}.png")
    return {"schema": SCHEMA, "status": "pass", "manifest_entries": manifest_entries,
            "candidate_count": scores["candidate_count"], "graphs": graph_results,
            "composite_count": len(COMPOSITES)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args.root.resolve())
    except (OSError, ValueError, KeyError, ET.ParseError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
