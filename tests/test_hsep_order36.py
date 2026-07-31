"""Certificate and independent-verifier tests for the order-36 audit."""

import base64
from hashlib import sha256
import importlib.util
from pathlib import Path

import networkx as nx

from barnette_search.hsep_order36 import (
    cycle_edge_indexes,
    edge_list_from_graph,
    enumerate_hamiltonian_cycles,
    normalize_cycle,
    solve_packing_lower_bound,
    solve_set_cover,
    verify_cover_edges,
)
from barnette_search.planar_code import (
    canonical_graph_hash,
    encode_planar_code,
    iter_planar_code,
)


def _standalone_module():
    path = Path(__file__).parents[1] / "tools" / "verify_hsep_order36.py"
    specification = importlib.util.spec_from_file_location("standalone_hsep36", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_cycle_normalization_removes_rotation_reversal_and_closure() -> None:
    expected = (0, 1, 2, 3)
    assert normalize_cycle((0, 1, 2, 3)) == expected
    assert normalize_cycle((2, 3, 0, 1, 2)) == expected
    assert normalize_cycle((0, 3, 2, 1, 0)) == expected


def test_cube_complete_cycles_have_matching_six_six_certificates() -> None:
    graph = nx.cubical_graph()
    edges = edge_list_from_graph(graph)
    cycles = tuple(sorted(enumerate_hamiltonian_cycles(edges, 8)))

    assert len(cycles) == 6
    assert solve_set_cover(edges, cycles, 5) is None
    selected = solve_set_cover(edges, cycles, 6)
    assert selected is not None
    family = tuple(cycles[index] for index in selected)
    assert verify_cover_edges(edges, family) == (True, 132)

    packing = solve_packing_lower_bound(edges, cycles, 6)
    assert packing is not None and len(packing) == 6
    edge_index = {edge: index for index, edge in enumerate(edges)}
    all_edges = set(range(len(edges)))
    for cycle in cycles:
        chosen = cycle_edge_indexes(cycle, edge_index)
        assert sum(
            required in chosen and forbidden in all_edges - chosen
            for required, forbidden in packing
        ) <= 1


def test_standalone_verifier_checks_an_explicit_cube_cover(monkeypatch) -> None:
    verifier = _standalone_module()
    monkeypatch.setattr(verifier, "ORDER", 8)
    monkeypatch.setattr(verifier, "EDGE_COUNT", 12)
    monkeypatch.setattr(verifier, "REQUIREMENTS", 132)

    graph = nx.cubical_graph()
    planar = nx.PlanarEmbedding()
    _, embedding = nx.check_planarity(graph)
    rotation = tuple(tuple(embedding.neighbors_cw_order(vertex)) for vertex in range(8))
    data = encode_planar_code(rotation)
    [embedded] = iter_planar_code(__import__("io").BytesIO(data), require_header=True)
    edges = edge_list_from_graph(graph)
    cycles = tuple(sorted(enumerate_hamiltonian_cycles(edges, 8)))
    record = {
        "schema": verifier.SCHEMA,
        "generation_index": 0,
        "plantri_rank": 1,
        "canonical_graph_hash": canonical_graph_hash(embedded),
        "graph_order": 8,
        "edge_count": 12,
        "face_size_multiset": list(embedded.face_size_multiset),
        "planar_code_base64": base64.b64encode(data).decode("ascii"),
        "planar_code_sha256": sha256(data).hexdigest(),
        "edges": [list(edge) for edge in edges],
        "source_greedy_size": 6,
        "cycle_generation_method": "test",
        "cover_size": 6,
        "cycles": [list(cycle) for cycle in cycles],
        "covered_ordered_edge_pairs": 132,
        "status": "verified_le48_test",
        "exact_hsep": None,
        "packing_lower_bound": None,
        "complete_hamiltonian_cycle_universe": None,
    }
    graph_hash, cover_size, status = verifier.verify_record(record, 0)
    assert graph_hash == record["canonical_graph_hash"]
    assert cover_size == 6
    assert status == "verified_le48_test"
