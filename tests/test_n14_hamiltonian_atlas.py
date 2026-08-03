"""Focused tests for n=14 Hamiltonian atlas enumeration and rendering helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import networkx as nx

TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import render_n14_hamiltonian_cycles as atlas  # noqa: E402


def test_cube_enumeration_is_complete_deduplicated_and_deterministic() -> None:
    graph = nx.cubical_graph()
    cycles = atlas.enumerate_cycles_dfs(graph)
    edge_sets = [atlas.canonical_cycle_edges(cycle) for cycle in cycles]
    assert len(cycles) == 6
    assert edge_sets == sorted(edge_sets)
    assert len(set(edge_sets)) == len(edge_sets)
    assert set(edge_sets) == atlas.enumerate_cycles_by_complement_matchings(graph)
    assert all(atlas.validate_cycle(graph, cycle) for cycle in cycles)


def test_svg_highlights_are_exact_and_machine_readable() -> None:
    positions = {0: (100.0, 100.0), 1: (800.0, 100.0), 2: (450.0, 800.0)}
    edges = [(0, 1), (0, 2), (1, 2)]
    selected = {(0, 1), (1, 2)}
    svg = atlas.make_svg(positions, edges, selected, "test", "test", 1)
    assert atlas.svg_highlight_edges(svg) == selected
    assert svg.count('class="graph-edge"') == 3
    assert svg.count('class="hamiltonian-edge"') == 2


def test_pdf_writer_is_deterministic_and_well_formed() -> None:
    canvas = atlas.PdfCanvas(100, 100)
    canvas.line(0, 0, 100, 100, 2, (0, 0, 0))
    canvas.text(50, 50, "test", 12)
    first = canvas.bytes()
    assert first == canvas.bytes()
    assert first.startswith(b"%PDF-1.4")
    assert first.endswith(b"%%EOF\n")
