# Barnette Search

This is a small Python research project for checking whether finite graph inputs
satisfy the supplied definition of a **Barnette graph**: undirected, simple,
cubic, bipartite, planar, and 3-vertex-connected.

The project currently provides a NetworkX-based reference validator and a small
exact Hamiltonian-cycle solver. The emphasis is correctness and testability, not
large-instance performance. SAT, ILP, GPU, and external solver integrations are
not implemented.

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

Find and independently verify a Hamiltonian cycle:

```python
from barnette_search import find_hamiltonian_cycle, verify_hamiltonian_cycle

graph = nx.cubical_graph()
cycle = find_hamiltonian_cycle(graph)

assert cycle is not None
assert verify_hamiltonian_cycle(graph, cycle)
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

## Validator semantics

The validator never replaces an invalid input with a cleaned graph. It reports
directedness, self-loops, and actual parallel edges from the original object.
A `MultiGraph` with no loops or repeated endpoint pair represents a simple graph
and is not rejected solely because of its container type.

The remaining properties have these precise meanings:

- Cubicity uses `graph.degree()` on the original object. Each parallel copy
  contributes to degree, a loop contributes twice, and directed degree is total
  in-degree plus out-degree.
- Bipartiteness uses `networkx.is_bipartite` on the original object. NetworkX
  considers predecessors and successors for directed inputs, ignores edge
  multiplicity, and rejects any graph containing a loop.
- Planarity uses `networkx.check_planarity` on the original object. NetworkX's
  planarity algorithm explicitly tests the loop-free simple undirected skeleton;
  direction, loops, and parallel copies do not change topological planarity.
- Three-vertex-connectivity is an undirected property. The validator requires at
  least four vertices and checks connectivity after every deletion of zero, one,
  or two vertices using native subgraph views. Directed inputs fail this property;
  loops and multiplicity remain present but do not change vertex cuts.

For `MultiDiGraph`, parallel edges mean repeated arcs with the same ordered
endpoints. A reciprocal pair by itself is not parallel. Counts always describe
the original object, with each stored edge, arc, loop, or parallel copy counted
once.

## Exact Hamiltonian solver

`find_hamiltonian_cycle` accepts materialized, undirected, structurally simple
NetworkX graphs. Directed graphs, loops, and actual parallel edges raise
`ValueError`; non-NetworkX inputs raise `TypeError`. A returned tuple contains
every vertex once and repeats its first vertex at the end. Simple cycles require
at least three vertices, so graphs with zero, one, or two vertices return `None`.

The solver performs exact depth-first backtracking. It fixes the first node in
NetworkX insertion order as the start, removing rotational symmetry, and uses
insertion ranks to retain one of the two reversal orientations. It applies only
necessary-condition pruning:

- the input must be connected, have minimum degree two, and be biconnected;
- the partial path endpoint and fixed start must retain suitable continuation
  and closing neighbors;
- every unvisited vertex must retain two available cycle neighbors; and
- the subgraph induced by unvisited vertices must remain connected, since those
  vertices must form one consecutive segment in a completed cycle.

The certificate verifier does not call the finder. It independently checks the
length, closure, vertex set and uniqueness, unknown vertices, and every cycle
edge. Invalid certificates return `False`; unsupported graph domains raise the
same input exceptions as the finder.

## Running tests

```console
python -m pytest
```

The validator runs every property check and reports all applicable rejection
reasons in a deterministic order. NetworkX graph objects are materialized finite
containers, so accepting such an object (or a decoded graph6 record) supplies
the finiteness condition.

The Hamiltonian finder has exponential worst-case running time and recursive
depth proportional to the number of vertices. It is intended only as a reference
for small graphs.
