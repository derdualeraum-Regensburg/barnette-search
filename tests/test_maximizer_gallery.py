"""Focused tests for the standalone Barnie maximizer gallery wrappers."""

from __future__ import annotations

import base64
import gzip
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import draw_single_maximizer as gallery  # noqa: E402


CUBE_EDGES = [
    [0, 1], [0, 2], [0, 3], [1, 4], [1, 5], [2, 5],
    [2, 6], [3, 4], [3, 6], [4, 7], [5, 7], [6, 7],
]


def _cube_tex() -> str:
    positions = {
        1: (-70.0, -70.0), 2: (-28.0, -28.0), 3: (70.0, -70.0),
        4: (-70.0, 70.0), 5: (-28.0, 28.0), 6: (28.0, -28.0),
        7: (70.0, 70.0), 8: (28.0, 28.0),
    }
    lines = ["\\documentclass{article}", "\\begin{document}", "\\begin{tikzpicture}[scale=0.07]"]
    for vertex, (x, y) in positions.items():
        lines.append(
            f"\\node [circle,black,draw,fill=black] ({vertex}) at ({x:.1f},{y:.1f}) {{}};"
        )
    for u, v in CUBE_EDGES:
        lines.append(f"\\draw [black] ({u + 1}) to ({v + 1});")
    lines.extend(["\\end{tikzpicture}", "\\end{document}"])
    return "\n".join(lines) + "\n"


def _write_jsonl_gzip(path: Path, record: dict) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def _sequence_fixture(root: Path) -> tuple[str, bytes]:
    graph_hash = "2" * 64
    planar_code = b">>planar_code<<\x08\x00"
    order_root = root / "order_08"
    order_root.mkdir(parents=True)
    summary = {
        "order": 8,
        "M_B": 6,
        "number_of_maximizers": 1,
        "maximizer_hashes": [graph_hash],
        "unique_maximizer": True,
    }
    (order_root / "order_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    graph = {
        "canonical_graph_hash": graph_hash,
        "graph_order": 8,
        "edge_count": 12,
        "edges": CUBE_EDGES,
        "generation_index": 0,
        "plantri_rank": 1,
        "planar_code_base64": base64.b64encode(planar_code).decode("ascii"),
        "planar_code_sha256": gallery.sha256_bytes(planar_code),
        "face_size_multiset": [4] * 6,
    }
    exact = {
        "canonical_graph_hash": graph_hash,
        "graph_order": 8,
        "generation_index": 0,
        "plantri_rank": 1,
        "exact_hsep": 6,
    }
    _write_jsonl_gzip(order_root / "graph_certificates.jsonl.gz", graph)
    _write_jsonl_gzip(order_root / "exact_certificates.jsonl.gz", exact)
    return graph_hash, planar_code


def test_tikz_parser_and_svg_preserve_certified_cube() -> None:
    vertices, edges = gallery.parse_planar_tikz(_cube_tex())
    graph = {"graph_order": 8, "edge_count": 12, "edges": CUBE_EDGES}
    gallery.verify_tikz_graph(vertices, edges, graph)
    svg = gallery.make_svg(vertices, edges, title="cube", description="test")
    assert svg.count("<line ") == 12
    assert svg.count("<circle ") == 8
    assert svg == gallery.make_svg(vertices, edges, title="cube", description="test")


def test_tikz_verification_rejects_changed_edge() -> None:
    vertices, edges = gallery.parse_planar_tikz(_cube_tex())
    edges[0] = (1, 8)
    with pytest.raises(gallery.GalleryError, match="edge set"):
        gallery.verify_tikz_graph(
            vertices, edges, {"graph_order": 8, "edge_count": 12, "edges": CUBE_EDGES}
        )


def test_render_one_reads_certified_planar_code_and_resumes(tmp_path, monkeypatch) -> None:
    sequence_root = tmp_path / "sequence"
    gallery_root = tmp_path / "gallery"
    graph_hash, planar_code = _sequence_fixture(sequence_root)
    engine = tmp_path / "planar_draw.exe"
    engine.write_bytes(b"test engine")
    calls = []

    def fake_engine(path, data, options):
        calls.append((path, data, options))
        return _cube_tex(), "Wrote 1 drawing", [str(path), *options]

    monkeypatch.setattr(gallery, "run_engine", fake_engine)
    first = gallery.render_one(
        sequence_root=sequence_root,
        gallery_root=gallery_root,
        engine=engine,
        order=8,
        graph_hash=graph_hash,
    )
    second = gallery.render_one(
        sequence_root=sequence_root,
        gallery_root=gallery_root,
        engine=engine,
        order=8,
        graph_hash=graph_hash,
    )
    assert calls == [(engine, planar_code, gallery.DEFAULT_ENGINE_OPTIONS)]
    assert first["resume_status"] == "rendered"
    assert second["resume_status"] == "reused"
    assert first["stem"] == "n_08_M_6_rank_00001_22222222"
    assert (gallery_root / first["drawing_files"]["svg"]).is_file()


def test_planar_code_hash_is_checked(tmp_path) -> None:
    graph_hash, _ = _sequence_fixture(tmp_path)
    path = tmp_path / "order_08" / "graph_certificates.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        graph = json.loads(next(stream))
    graph["planar_code_sha256"] = "0" * 64
    with pytest.raises(gallery.GalleryError, match="SHA-256 mismatch"):
        gallery.decode_planar_code(graph)
    assert graph_hash == "2" * 64
