"""Tests for graph6 input helpers."""

from pathlib import Path

import networkx as nx
import pytest

from barnette_search import (
    graph_from_graph6_file,
    graph_from_graph6_string,
    load_graph,
    validate_barnette_graph,
)


def _cube_graph6() -> bytes:
    return nx.to_graph6_bytes(nx.cubical_graph(), header=False).strip()


def test_load_graph6_string() -> None:
    data = _cube_graph6().decode("ascii")
    graph = graph_from_graph6_string(data)

    assert nx.is_isomorphic(graph, nx.cubical_graph())
    assert validate_barnette_graph(data).valid is True


def test_load_graph6_bytes_through_common_loader() -> None:
    graph = load_graph(_cube_graph6())

    assert validate_barnette_graph(graph).valid is True


def test_load_graph6_file(tmp_path: Path) -> None:
    path = tmp_path / "cube.g6"
    path.write_bytes(_cube_graph6() + b"\n")

    graph = graph_from_graph6_file(str(path))

    assert graph.number_of_nodes() == 8
    assert graph.number_of_edges() == 12
    assert validate_barnette_graph(graph).valid is True
    assert validate_barnette_graph(path).valid is True


def test_graph6_file_must_contain_exactly_one_graph(tmp_path: Path) -> None:
    path = tmp_path / "two-cubes.g6"
    record = _cube_graph6()
    path.write_bytes(record + b"\n" + record + b"\n")

    with pytest.raises(ValueError, match="exactly one graph"):
        graph_from_graph6_file(path)


def test_malformed_graph6_file_has_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "malformed.g6"
    path.write_text(">>graph6<<\n", encoding="ascii")

    with pytest.raises(ValueError, match="invalid graph6 file"):
        graph_from_graph6_file(path)


@pytest.mark.parametrize("data", ["", "\n\n"])
def test_graph6_string_must_contain_one_record(data: str) -> None:
    with pytest.raises(ValueError, match="exactly one non-empty graph6 record"):
        graph_from_graph6_string(data)


@pytest.mark.parametrize("data", [">>graph6<<", "~", "not graph6"])
def test_malformed_graph6_string_has_a_clear_error(data: str) -> None:
    with pytest.raises(ValueError, match="invalid graph6 record"):
        graph_from_graph6_string(data)


def test_networkx_graph_is_returned_unchanged() -> None:
    graph = nx.cubical_graph()

    assert load_graph(graph) is graph
