from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "build_bauer_double_ladder_gallery.py"
SPEC = importlib.util.spec_from_file_location("bauer_gallery", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BauerGalleryTests(unittest.TestCase):
    def cube(self):
        labels = {
            0: ("A", 0, 0), 1: ("A", 0, 1), 2: ("A", 1, 0), 3: ("A", 1, 1),
            4: ("B", 0, 0), 5: ("B", 0, 1), 6: ("B", 1, 0), 7: ("B", 1, 1),
        }
        edges = [(0, 1), (2, 3), (0, 2), (1, 3), (4, 5), (6, 7), (4, 6),
                 (5, 7), (0, 4), (1, 6), (2, 5), (3, 7)]
        faces = [[0, 1, 3, 2], [4, 5, 7, 6], [0, 4, 5, 2],
                 [1, 3, 7, 6], [0, 1, 6, 4], [2, 3, 7, 5]]
        return MODULE.GraphData(
            label="D(1,1)", stem="D_1_1", a=1, b=1, order=8, edge_count=12,
            graph_hash="0" * 64, edges=edges, faces=faces, face_size_multiset=[4] * 6,
            labels=labels, planar_code=b"", planar_code_sha256="1" * 64,
            exact_hsep=6, hamiltonian_cycle_count=6, status="test",
            certified_extremal=True, source_files=[], inserted_vertices=[])

    def test_edge_partition(self):
        graph = self.cube()
        counts = {}
        for edge in graph.edges:
            name = MODULE.classify_edge(graph, edge)
            counts[name] = counts.get(name, 0) + 1
        self.assertEqual(counts, {"a_rung": 2, "a_rail": 2, "b_rung": 2,
                                  "b_rail": 2, "connector": 4})

    def test_cap_faces_and_outer_selection(self):
        graph = self.cube()
        self.assertEqual(len(MODULE.cap_faces(graph)), 4)
        self.assertIn(MODULE.choose_outer_cap(graph), MODULE.cap_faces(graph))

    def test_deterministic_pdf_envelope(self):
        scene = [{"kind": "rect", "x": 0, "y": 0, "w": 100, "h": 100, "fill": "#FFFFFF"},
                 {"kind": "line", "x1": 5, "y1": 5, "x2": 95, "y2": 95,
                  "color": "#000000", "width": 2, "dash": None}]
        first = MODULE.scene_to_pdf(scene, 100, 100)
        second = MODULE.scene_to_pdf(scene, 100, 100)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(b"%PDF-1.4"))
        self.assertTrue(first.rstrip().endswith(b"%%EOF"))

    def test_svg_embeds_exact_graph_identity(self):
        graph = self.cube()
        positions = {v: (float(v % 4), float(v // 4)) for v in graph.labels}
        scene, _, _ = MODULE.graph_scene(graph, positions, annotated=True)
        svg = MODULE.scene_to_svg(scene, 1200, 1200, "test", "test")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.svg"
            path.write_text(svg, encoding="utf-8")
            verifier_path = SCRIPT.with_name("verify_bauer_double_ladder_gallery.py")
            verifier_spec = importlib.util.spec_from_file_location("bauer_verify", verifier_path)
            assert verifier_spec and verifier_spec.loader
            verifier = importlib.util.module_from_spec(verifier_spec)
            sys.modules[verifier_spec.name] = verifier
            verifier_spec.loader.exec_module(verifier)
            vertices, edges, classes = verifier.parse_svg_graph(path)
        self.assertEqual(vertices, set(range(8)))
        self.assertEqual(edges, set(graph.edges))
        self.assertEqual(classes["connector"], 4)


if __name__ == "__main__":
    unittest.main()
