"""Streaming parser and deterministic utilities for plantri ``planar_code``.

The cyclic neighbor order in each record is retained as a rotation system.
Records are validated as connected, simple plane graphs before they are
returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import BinaryIO, Iterator, Sequence

import networkx as nx


PLANAR_CODE_HEADER = b">>planar_code<<"


class PlanarCodeError(ValueError):
    """Raised when a planar-code stream is truncated or malformed."""


@dataclass(frozen=True, slots=True)
class EmbeddedPlanarGraph:
    """A simple graph together with clockwise neighbors for every vertex."""

    graph: nx.Graph
    rotation_system: tuple[tuple[int, ...], ...]
    faces: tuple[tuple[int, ...], ...]

    @property
    def face_size_multiset(self) -> tuple[int, ...]:
        """Return sorted facial boundary lengths, retaining multiplicity."""
        return tuple(sorted(map(len, self.faces)))


class _BufferedReader:
    def __init__(self, stream: BinaryIO, prefix: bytes = b"") -> None:
        self.stream = stream
        self.prefix = bytearray(prefix)

    def read_exactly(self, size: int, context: str, *, eof_ok: bool = False) -> bytes:
        data = bytearray()
        if self.prefix:
            count = min(size, len(self.prefix))
            data.extend(self.prefix[:count])
            del self.prefix[:count]
        while len(data) < size:
            chunk = self.stream.read(size - len(data))
            if not chunk:
                if eof_ok and not data:
                    return b""
                raise PlanarCodeError(f"truncated planar_code while reading {context}")
            data.extend(chunk)
        return bytes(data)


def _read_value(reader: _BufferedReader, width: int, context: str) -> int:
    return int.from_bytes(reader.read_exactly(width, context), "big")


def _trace_faces(rotation: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    if len(rotation) == 1 and not rotation[0]:
        return ((),)

    unused = {(u, v) for u, row in enumerate(rotation) for v in row}
    faces: list[tuple[int, ...]] = []
    while unused:
        start = min(unused)
        dart = start
        boundary: list[int] = []
        while True:
            if dart not in unused:
                if dart != start:
                    raise PlanarCodeError("rotation system does not define facial walks")
                break
            unused.remove(dart)
            u, v = dart
            boundary.append(u)
            neighbors = rotation[v]
            try:
                position = neighbors.index(u)
            except ValueError as error:  # guarded by symmetry validation
                raise PlanarCodeError("adjacency is not symmetric") from error
            dart = (v, neighbors[(position - 1) % len(neighbors)])
        faces.append(tuple(boundary))
    return tuple(faces)


def _build_embedded_graph(
    rotation: tuple[tuple[int, ...], ...],
) -> EmbeddedPlanarGraph:
    order = len(rotation)
    graph = nx.Graph()
    graph.add_nodes_from(range(order))
    for vertex, neighbors in enumerate(rotation):
        if len(neighbors) != len(set(neighbors)):
            raise PlanarCodeError(f"vertex {vertex + 1} has a repeated neighbor")
        for neighbor in neighbors:
            if not 0 <= neighbor < order:
                raise PlanarCodeError(
                    f"neighbor {neighbor + 1} is outside the range 1..{order}"
                )
            if neighbor == vertex:
                raise PlanarCodeError(f"vertex {vertex + 1} has a self-loop")
            graph.add_edge(vertex, neighbor)

    for vertex, neighbors in enumerate(rotation):
        for neighbor in neighbors:
            if vertex not in rotation[neighbor]:
                raise PlanarCodeError(
                    f"adjacency is not symmetric for edge "
                    f"{vertex + 1}-{neighbor + 1}"
                )
    if order > 1 and not nx.is_connected(graph):
        raise PlanarCodeError("planar_code record is disconnected")
    if sum(map(len, rotation)) != 2 * graph.number_of_edges():
        raise PlanarCodeError("adjacency lists do not encode each edge twice")

    faces = _trace_faces(rotation)
    if order - graph.number_of_edges() + len(faces) != 2:
        raise PlanarCodeError("rotation system is not a cellular sphere embedding")
    return EmbeddedPlanarGraph(graph=graph, rotation_system=rotation, faces=faces)


def iter_planar_code(
    stream: BinaryIO, *, require_header: bool = False
) -> Iterator[EmbeddedPlanarGraph]:
    """Yield validated records from a binary planar-code stream.

    The official plantri 5.8 one-byte representation is supported. Only a small
    prefix is buffered; graph records are yielded one at a time.
    """
    prefix_bytes = bytearray()
    while len(prefix_bytes) < len(PLANAR_CODE_HEADER):
        chunk = stream.read(len(PLANAR_CODE_HEADER) - len(prefix_bytes))
        if not chunk:
            break
        prefix_bytes.extend(chunk)
    prefix = bytes(prefix_bytes)
    has_header = prefix == PLANAR_CODE_HEADER
    if require_header and not has_header:
        raise PlanarCodeError("missing >>planar_code<< header")
    reader = _BufferedReader(stream, b"" if has_header else prefix)

    while True:
        marker = reader.read_exactly(1, "vertex count", eof_ok=True)
        if not marker:
            return
        order = marker[0]
        width = 1
        if order == 0:
            raise PlanarCodeError("a planar_code record cannot have zero vertices")

        rows: list[tuple[int, ...]] = []
        for vertex in range(order):
            neighbors: list[int] = []
            while True:
                value = _read_value(reader, width, f"adjacency list {vertex + 1}")
                if value == 0:
                    break
                if value > order:
                    raise PlanarCodeError(
                        f"neighbor {value} is outside the range 1..{order}"
                    )
                neighbors.append(value - 1)
            rows.append(tuple(neighbors))
        yield _build_embedded_graph(tuple(rows))


def encode_planar_code(
    rotation_system: Sequence[Sequence[int]], *, include_header: bool = True
) -> bytes:
    """Encode a zero-based rotation system; primarily useful for round trips."""
    rotation = tuple(tuple(row) for row in rotation_system)
    embedded = _build_embedded_graph(rotation)
    order = embedded.graph.number_of_nodes()
    if order > 255:
        raise ValueError("plantri planar_code supports at most 255 vertices")
    width = 1
    output = bytearray(PLANAR_CODE_HEADER if include_header else b"")
    output.append(order)
    for row in rotation:
        for neighbor in row:
            output.extend((neighbor + 1).to_bytes(width, "big"))
        output.extend((0).to_bytes(width, "big"))
    return bytes(output)


def canonical_graph_hash(embedded: EmbeddedPlanarGraph) -> str:
    """Hash an abstract 3-connected planar graph independently of its labels.

    A 3-connected planar graph has a unique sphere embedding up to reflection.
    We encode every directed root edge in both orientations and hash the least
    breadth-first rotation code. Callers must validate 3-connectivity first.
    """
    rotation = embedded.rotation_system
    if not rotation or not any(rotation):
        payload = json.dumps(rotation, separators=(",", ":")).encode()
        return sha256(payload).hexdigest()

    candidates: list[tuple[tuple[int, ...], ...]] = []
    for root in range(len(rotation)):
        for first in rotation[root]:
            for direction in (1, -1):
                labels = {root: 0, first: 1}
                parents = {root: first, first: root}
                vertices = [root, first]
                rows: list[tuple[int, ...]] = []
                position = 0
                while position < len(vertices):
                    vertex = vertices[position]
                    neighbors = rotation[vertex]
                    anchor = neighbors.index(parents[vertex])
                    ordered = tuple(
                        neighbors[(anchor + direction * offset) % len(neighbors)]
                        for offset in range(len(neighbors))
                    )
                    for neighbor in ordered:
                        if neighbor not in labels:
                            labels[neighbor] = len(labels)
                            parents[neighbor] = vertex
                            vertices.append(neighbor)
                    rows.append(tuple(labels[neighbor] for neighbor in ordered))
                    position += 1
                if len(labels) != len(rotation):
                    raise ValueError("canonical hashing requires a connected graph")
                candidates.append(tuple(rows))
    canonical = min(candidates)
    payload = json.dumps(canonical, separators=(",", ":")).encode()
    return sha256(payload).hexdigest()


def certificate_hash(cycle: Sequence[int] | None) -> str | None:
    """Hash a cycle after removing start and reversal presentation choices."""
    if cycle is None:
        return None
    values = tuple(cycle)
    if len(values) < 2 or values[0] != values[-1]:
        raise ValueError("certificate must be a closed cycle")
    body = values[:-1]
    variants = []
    for oriented in (body, tuple(reversed(body))):
        variants.extend(oriented[i:] + oriented[:i] for i in range(len(body)))
    canonical = min(variants)
    return sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()
