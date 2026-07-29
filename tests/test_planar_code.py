"""Unit tests for the independent streaming planar-code parser."""

from io import BytesIO

import networkx as nx
import pytest

from barnette_search.planar_code import (
    PLANAR_CODE_HEADER,
    PlanarCodeError,
    canonical_graph_hash,
    encode_planar_code,
    iter_planar_code,
)


def _rotation(graph: nx.Graph) -> tuple[tuple[int, ...], ...]:
    planar, embedding = nx.check_planarity(graph)
    assert planar
    return tuple(
        tuple(embedding.neighbors_cw_order(v)) for v in range(len(graph))
    )


def test_round_trip_preserves_cube_rotation_and_faces() -> None:
    rotation = _rotation(nx.cubical_graph())
    [decoded] = iter_planar_code(BytesIO(encode_planar_code(rotation)))

    assert decoded.rotation_system == rotation
    assert set(decoded.graph.edges()) == set(nx.cubical_graph().edges())
    assert decoded.face_size_multiset == (4, 4, 4, 4, 4, 4)


def test_stream_can_contain_multiple_graphs_under_one_header() -> None:
    triangle = _rotation(nx.complete_graph(3))
    square = _rotation(nx.cycle_graph(4))
    data = (
        PLANAR_CODE_HEADER
        + encode_planar_code(triangle, include_header=False)
        + encode_planar_code(square, include_header=False)
    )

    decoded = list(iter_planar_code(BytesIO(data), require_header=True))
    assert [item.graph.number_of_nodes() for item in decoded] == [3, 4]


def test_header_is_optional_when_not_required() -> None:
    data = encode_planar_code(_rotation(nx.cycle_graph(5)), include_header=False)
    [decoded] = iter_planar_code(BytesIO(data))
    assert decoded.graph.number_of_nodes() == 5


def test_parser_handles_short_stream_reads() -> None:
    class OneByteAtATime(BytesIO):
        def read(self, size: int = -1) -> bytes:
            return super().read(1 if size != 0 else 0)

    data = encode_planar_code(_rotation(nx.cycle_graph(4)))
    [decoded] = iter_planar_code(OneByteAtATime(data), require_header=True)
    assert decoded.graph.number_of_edges() == 4


def test_missing_required_header_is_rejected() -> None:
    data = encode_planar_code(_rotation(nx.cycle_graph(3)), include_header=False)
    with pytest.raises(PlanarCodeError, match="missing"):
        list(iter_planar_code(BytesIO(data), require_header=True))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (PLANAR_CODE_HEADER + b"\x03\x02", "truncated"),
        (PLANAR_CODE_HEADER + b"\x02\x03\x00\x00", "outside"),
        (PLANAR_CODE_HEADER + b"\x02\x02\x00\x00", "symmetric"),
        (PLANAR_CODE_HEADER + b"\x02\x02\x02\x00\x01\x01\x00", "repeated"),
        (PLANAR_CODE_HEADER + b"\x01\x01\x00", "self-loop"),
        (
            PLANAR_CODE_HEADER
            + b"\x04\x02\x00\x01\x00\x04\x00\x03\x00",
            "disconnected",
        ),
        (
            PLANAR_CODE_HEADER
            + b"\x06"
            + b"\x04\x05\x06\x00" * 3
            + b"\x01\x02\x03\x00" * 3,
            "cellular sphere",
        ),
    ],
)
def test_malformed_records_are_rejected(payload: bytes, message: str) -> None:
    with pytest.raises(PlanarCodeError, match=message):
        list(iter_planar_code(BytesIO(payload), require_header=True))


def test_zero_vertex_marker_is_rejected() -> None:
    with pytest.raises(PlanarCodeError, match="zero vertices"):
        list(iter_planar_code(BytesIO(PLANAR_CODE_HEADER + b"\x00")))


def test_canonical_hash_ignores_labels_and_embedding_reflection() -> None:
    graph = nx.cubical_graph()
    rotation = _rotation(graph)
    [first] = iter_planar_code(BytesIO(encode_planar_code(rotation)))

    relabeling = {vertex: (7 - vertex) for vertex in graph}
    relabeled = nx.relabel_nodes(graph, relabeling)
    second_rotation = _rotation(relabeled)
    mirrored = tuple(tuple(reversed(row)) for row in second_rotation)
    [second] = iter_planar_code(BytesIO(encode_planar_code(mirrored)))

    assert canonical_graph_hash(first) == canonical_graph_hash(second)
