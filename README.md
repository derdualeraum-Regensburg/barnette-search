# Barnette Search

This is a small Python research project for checking whether finite graph inputs
satisfy the supplied definition of a **Barnette graph**: undirected, simple,
cubic, bipartite, planar, and 3-vertex-connected.

This first iteration is deliberately limited to a NetworkX-based reference
validator. It does not implement Hamiltonian-cycle detection or SAT solving.

## Installation

Python 3.10 or newer is required. From the repository root, create and activate
a virtual environment if desired, then install the package and test tools:

```console
python -m pip install -e ".[test]"
```

## Usage

Validate a NetworkX graph directly:

```python
import networkx as nx

from barnette_search import validate_barnette_graph

result = validate_barnette_graph(nx.cubical_graph())
print(result.valid)               # True
print(result.number_of_vertices)  # 8
print(result.number_of_edges)     # 12
print(result.rejection_reasons)   # []
```

Graph6 data can be supplied as a string or bytes. A graph6 file can be supplied
as a `pathlib.Path` to the common loader, or read explicitly with
`graph_from_graph6_file`:

```python
from pathlib import Path

from barnette_search import (
    graph_from_graph6_file,
    graph_from_graph6_string,
    validate_barnette_graph,
)

from_text = graph_from_graph6_string("Gl_XIS")
from_file = graph_from_graph6_file(Path("candidate.g6"))

print(validate_barnette_graph(from_text))
print(validate_barnette_graph(from_file))
```

The common loader treats every plain `str` as graph6 data. Wrap filenames in
`Path`, or call `graph_from_graph6_file`, when reading from disk.

Each graph6 file must contain exactly one graph. Graph6 represents simple,
undirected graphs, so self-loops and parallel edges can only be tested through
NetworkX graph objects.

## Running tests

```console
python -m pytest
```

The validator runs every property check and reports all applicable rejection
reasons in a deterministic order. NetworkX graph objects are materialized finite
containers, so accepting such an object (or a decoded graph6 record) supplies
the finiteness condition. For invalid directed inputs, bipartiteness, planarity,
and connectivity checks use the underlying simple undirected graph so those
diagnostics remain deterministic.
