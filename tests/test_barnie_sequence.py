"""Focused tests for the multi-order Barnie-sequence pipeline."""

import base64
import importlib.util
from io import BytesIO
from pathlib import Path

import networkx as nx

from barnette_search.barnie_sequence import (
    _exact_record,
    _graph_record,
    _upgrade_exact_record,
    count_perfect_matchings,
    cubic_lym_lower_bound,
    deterministic_greedy_cover,
    exhaustive_cover_feasible,
    sperner_lower_bound,
    theoretical_bounds,
)
from barnette_search.hsep_order36 import edge_list_from_graph, enumerate_hamiltonian_cycles
from barnette_search.planar_code import encode_planar_code, iter_planar_code


def _cube_planar_code() -> bytes:
    graph = nx.cubical_graph()
    planar, embedding = nx.check_planarity(graph)
    assert planar
    rotation = tuple(tuple(embedding.neighbors_cw_order(vertex)) for vertex in range(8))
    return encode_planar_code(rotation)


def _standalone():
    path = Path(__file__).parents[1] / "tools" / "verify_barnie_sequence.py"
    specification = importlib.util.spec_from_file_location("standalone_barnie", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_theoretical_bounds_use_antichains_and_cubic_incidence() -> None:
    assert sperner_lower_bound(12) == 6
    assert cubic_lym_lower_bound(8) == 6
    assert theoretical_bounds(8) == {
        "edge_count": 12,
        "sperner_antichain_lower_bound": 6,
        "cubic_incidence_lym_lower_bound": 6,
    }
    assert theoretical_bounds(9)["edge_count"] is None


def test_cube_exact_record_has_matching_six_certificates() -> None:
    graph_record = _graph_record(0, _cube_planar_code(), 8)
    exact = _exact_record(graph_record)
    assert exact["exact_hsep"] == 6
    assert exact["complete_hamiltonian_cycle_count"] == 6
    assert exact["primal_cycle_count"] == 6
    assert exact["packing_requirement_count"] == 6


def test_cube_greedy_cover_and_perfect_matchings() -> None:
    graph = nx.cubical_graph()
    edges = edge_list_from_graph(graph)
    cycles = tuple(sorted(enumerate_hamiltonian_cycles(edges, 8)))
    assert len(deterministic_greedy_cover(edges, cycles)) == 6
    assert not exhaustive_cover_feasible(edges, cycles, 5)
    assert exhaustive_cover_feasible(edges, cycles, 6)
    assert count_perfect_matchings(edges, 8) == 9


def test_standalone_verifies_general_cube_graph_and_exact_record() -> None:
    verifier = _standalone()
    graph_record = _graph_record(0, _cube_planar_code(), 8)
    graph_hash, edges = verifier.verify_graph_record(graph_record, 0, 8)
    assert graph_hash == graph_record["canonical_graph_hash"]
    exact = _exact_record(graph_record)
    assert verifier.verify_exact(exact, edges, 8) == 6
    data = base64.b64decode(graph_record["planar_code_base64"])
    [embedded] = iter_planar_code(BytesIO(data), require_header=True)
    assert len(embedded.faces) == 6


def test_early_exact_checkpoint_upgrade_is_payload_guarded() -> None:
    upgraded = _upgrade_exact_record({
        "proof_status": "exact_primal_packing",
        "exact_hsep": 6,
        "packing_requirement_count": 6,
    })
    assert upgraded["lower_bound_method"] == "packing"
