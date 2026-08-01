from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

import networkx as nx


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "build_bauer_double_ladder_layout_study.py"
SPEC = importlib.util.spec_from_file_location("bauer_layout_study", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

from barnette_search.planar_code import encode_planar_code, iter_planar_code  # noqa: E402


class LayoutStudyTests(unittest.TestCase):
    def cube(self):
        labels = {
            0: ("A", 0, 0), 1: ("A", 0, 1),
            2: ("A", 1, 0), 3: ("A", 1, 1),
            4: ("B", 0, 0), 5: ("B", 0, 1),
            6: ("B", 1, 0), 7: ("B", 1, 1),
        }
        edges = [
            (0, 1), (2, 3), (0, 2), (1, 3),
            (4, 5), (6, 7), (4, 6), (5, 7),
            (0, 4), (1, 6), (2, 5), (3, 7),
        ]
        graph = nx.Graph(edges)
        planar, embedding = nx.check_planarity(graph)
        self.assertTrue(planar)
        rotation = tuple(tuple(embedding.neighbors_cw_order(v)) for v in range(8))
        code = encode_planar_code(rotation)
        embedded = next(iter_planar_code(__import__("io").BytesIO(code), require_header=True))
        return MODULE.GraphData(
            label="D(1,1)", stem="D_1_1", a=1, b=1, order=8, edge_count=12,
            graph_hash="0" * 64, edges=[MODULE.edge(*item) for item in edges],
            faces=[list(face) for face in embedded.faces],
            face_size_multiset=[4] * 6, labels=labels, planar_code=code,
            planar_code_sha256="1" * 64, exact_hsep=6, hamiltonian_cycle_count=6,
            status="test", certified_extremal=True, source_files=[], inserted_vertices=[])

    def desired_positions(self):
        return {
            0: (-0.8, 0.8), 1: (-0.8, 0.5), 2: (0.8, 0.8), 3: (0.8, 0.5),
            4: (-0.9, -0.4), 5: (-0.6, -0.8), 6: (0.9, -0.4), 7: (0.6, -0.8),
        }

    def test_cap_identifiers_and_directed_face_orientation(self):
        graph = self.cube()
        records = MODULE.cap_records(graph)
        self.assertEqual({record["structural_id"] for record in records},
                         {"A_rail_0", "A_rail_1", "B_rail_0", "B_rail_1"})
        # Repository face cycles follow the right side of their listed darts;
        # planar_draw cf selects the left side, so selecting darts are reversed.
        faces_by_right_dart = {}
        for face in graph.faces:
            for i, u in enumerate(face):
                faces_by_right_dart[(u, face[(i + 1) % len(face)])] = MODULE.canonical_cycle(face)
        for record in records:
            target = MODULE.canonical_cycle(record["boundary"])
            for u, v in record["selecting_directed_edges"]:
                self.assertEqual(faces_by_right_dart[(v, u)], target)
                self.assertNotEqual(faces_by_right_dart[(u, v)], target)

    def test_certified_rotation_and_structural_labels_verify(self):
        checked = MODULE.verify_certified_embedding(self.cube())
        self.assertTrue(all(checked["checks"].values()))

    def test_global_transform_preserves_all_distances(self):
        graph = self.cube()
        raw = self.desired_positions()
        first, *_ = MODULE.rotate_reflect(graph, raw, 0, False)
        second, *_ = MODULE.rotate_reflect(graph, raw, 2, False)
        for u, v in graph.edges:
            self.assertAlmostEqual(math.dist(first[u], first[v]), math.dist(second[u], second[v]))

    def test_scoring_prefers_top_oriented_ladder(self):
        graph = self.cube()
        good = self.desired_positions()
        bad = {v: (y, x) for v, (x, y) in good.items()}
        good_components, good_total = MODULE.score_candidate(
            graph, good, "B_rail_0", False, False)
        bad_components, bad_total = MODULE.score_candidate(
            graph, bad, "A_rail_0", False, False)
        self.assertEqual(good_components["cap_face_choice"], 0.0)
        self.assertGreater(bad_components["cap_face_choice"], 0.0)
        self.assertLess(good_total, bad_total)

    def test_crossing_detection(self):
        graph = self.cube()
        nx_graph = nx.Graph(graph.edges)
        _, embedding = nx.check_planarity(nx_graph)
        layout = nx.combinatorial_embedding_to_pos(embedding)
        planar = {v: (float(layout[v][0]), float(layout[v][1])) for v in layout}
        self.assertEqual(MODULE.crossing_count(graph, planar), 0)
        maximum = 0
        for u in planar:
            for v in planar:
                crossed = dict(planar)
                crossed[u], crossed[v] = crossed[v], crossed[u]
                maximum = max(maximum, MODULE.crossing_count(graph, crossed))
        self.assertGreater(maximum, 0)

    def test_candidate_generation_is_deterministic(self):
        graph = self.cube()
        face = next(record for record in MODULE.cap_records(graph)
                    if record["structural_id"] == "B_rail_0")
        dart = tuple(face["selecting_directed_edges"][0])
        layout = MODULE.EngineLayout(graph, "B_rail_0", face["cap_index"],
                                     face["boundary"], dart, "", self.desired_positions(), [], "")
        first = MODULE.generate_candidates(graph, [layout])
        second = MODULE.generate_candidates(graph, [layout])
        self.assertEqual([item.candidate_id for item in first],
                         [item.candidate_id for item in second])
        self.assertEqual([item.total for item in first], [item.total for item in second])
        self.assertEqual(len(first), 32)

    def test_dynamic_programming_is_deterministic(self):
        graph = self.cube()
        face = next(record for record in MODULE.cap_records(graph)
                    if record["structural_id"] == "B_rail_0")
        dart = tuple(face["selecting_directed_edges"][0])
        layout = MODULE.EngineLayout(graph, "B_rail_0", face["cap_index"],
                                     face["boundary"], dart, "", self.desired_positions(), [], "")
        candidates = MODULE.generate_candidates(graph, [layout])
        first, cost1, _ = MODULE.optimize_sequence([candidates, candidates])
        second, cost2, _ = MODULE.optimize_sequence([candidates, candidates])
        self.assertEqual([item.candidate_id for item in first],
                         [item.candidate_id for item in second])
        self.assertEqual(cost1, cost2)

    def test_constrained_refinement_preserves_convex_outer_face_and_planarity(self):
        graph = self.cube()
        face = next(record for record in MODULE.cap_records(graph)
                    if record["structural_id"] == "B_rail_0")
        dart = tuple(face["selecting_directed_edges"][0])
        layout = MODULE.EngineLayout(graph, "B_rail_0", face["cap_index"],
                                     face["boundary"], dart, "", self.desired_positions(), [], "")
        candidate = next(item for item in MODULE.generate_candidates(graph, [layout])
                         if item.reverse_a and item.reverse_b)
        refined, metadata = MODULE.refine_coordinates(candidate)
        self.assertEqual(MODULE.crossing_count(graph, refined), 0)
        self.assertTrue(metadata["outer_face_convex"])
        for rail in (0, 1):
            vertices = MODULE.rail_vertices(graph, "A", rail,
                                            candidate.reverse_a, candidate.reverse_b)
            self.assertLess(max(refined[v][1] for v in vertices)
                            - min(refined[v][1] for v in vertices), 1.0e-10)


if __name__ == "__main__":
    unittest.main()
