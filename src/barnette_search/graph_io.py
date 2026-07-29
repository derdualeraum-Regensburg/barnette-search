"""Input helpers for NetworkX and graph6 graphs."""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TypeAlias

import networkx as nx

NetworkXGraph: TypeAlias = nx.Graph | nx.DiGraph | nx.MultiGraph | nx.MultiDiGraph
GraphInput: TypeAlias = NetworkXGraph | str | bytes | PathLike[str]


def graph_from_graph6_string(data: str | bytes) -> nx.Graph:
    """Decode one graph6 record from a string or ASCII bytes."""
    try:
        encoded = data.encode("ascii") if isinstance(data, str) else data
    except UnicodeEncodeError as error:
        raise ValueError("graph6 data must contain only ASCII characters") from error

    records = [line.strip() for line in encoded.splitlines() if line.strip()]
    if len(records) != 1:
        raise ValueError("expected exactly one non-empty graph6 record")
    try:
        return nx.from_graph6_bytes(records[0])
    except (IndexError, ValueError, nx.NetworkXException) as error:
        raise ValueError("invalid graph6 record") from error


def graph_from_graph6_file(path: str | PathLike[str]) -> nx.Graph:
    """Read exactly one graph6 record from *path*."""
    try:
        records = nx.read_graph6(Path(path))
    except (IndexError, ValueError, nx.NetworkXException) as error:
        raise ValueError("invalid graph6 file") from error
    if isinstance(records, list):
        if len(records) != 1:
            raise ValueError("expected exactly one graph in the graph6 file")
        return records[0]
    return records


def load_graph(source: GraphInput) -> NetworkXGraph:
    """Load a NetworkX graph, graph6 string/bytes, or graph6 file path.

    String values are treated as graph6 data. Use a ``Path`` (or another
    ``PathLike`` object) for files so that string graph6 data is unambiguous.
    NetworkX graph objects are returned unchanged.
    """
    if isinstance(source, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)):
        return source
    if isinstance(source, PathLike):
        return graph_from_graph6_file(source)
    if isinstance(source, (str, bytes)):
        return graph_from_graph6_string(source)
    raise TypeError(
        "source must be a NetworkX graph, graph6 string/bytes, or PathLike file"
    )
