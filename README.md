# Barnette Search

This is a small Python research project for checking whether finite graph inputs
satisfy the supplied definition of a **Barnette graph**: undirected, simple,
cubic, bipartite, planar, and 3-vertex-connected.

The project currently provides a NetworkX-based reference validator and a small
exact Hamiltonian-cycle solver. The emphasis is correctness and testability, not
large-instance performance. An independent exact SAT implementation is available
as an optional extra. An external plantri 5.8 integration provides reproducible
small-graph enumeration. ILP and GPU support are not implemented.

## Installation

Python 3.10 or newer is required. Install the base package, optional SAT support,
or the complete development test environment with:

```console
python -m pip install -e .
python -m pip install -e ".[sat]"
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

Use the independent SAT implementation through either its cycle-only or
structured API:

```python
from barnette_search import (
    find_hamiltonian_cycle_sat,
    solve_hamiltonian_cycle_sat,
)

cycle = find_hamiltonian_cycle_sat(graph)
result = solve_hamiltonian_cycle_sat(graph)

print(result.satisfiable)
print(result.solver_name)
print(result.number_of_subtour_iterations)
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

## Exact SAT solver

The optional SAT implementation is independent of the backtracking search and
never calls it. It uses the existing certificate verifier only after extracting
a candidate Hamiltonian cycle. Install it with the `sat` extra; without that
extra, invoking the SAT API raises an explanatory `ImportError` while the rest
of the package remains importable.

For a graph with `m` edges, primary variables 1 through `m` correspond one-to-one
with the undirected edges. At every vertex, PySAT's
`CardEnc.equals(..., bound=2, encoding=EncType.seqcounter)` requires exactly two
incident edge variables. The sequential-counter encoding was chosen as a small,
deterministic reference encoding; it introduces auxiliary variables, so the
total variable count can exceed `m`.

An initial satisfying assignment is a spanning 2-factor and can contain multiple
cycles. After each model, the implementation extracts every selected-edge
component. For every distinct component cut, it incrementally adds the PySAT
cardinality constraint
`sum(delta(S)) >= 2`, then re-solves with Glucose3. Every Hamiltonian cycle enters
and leaves any nonempty proper vertex subset, so it uses at least two edges of
that cut. The constraint therefore preserves every Hamiltonian cycle while
excluding the current disconnected 2-factor. A cut containing fewer than two
available graph edges is represented by an empty clause because its requirement
is immediately impossible. Complementary components share the same cut and
therefore the same inequality.

`HamiltonianSatResult` reports:

- `number_of_edge_variables`: primary input-edge variables;
- `number_of_variables`: final primary plus cardinality-auxiliary variables;
- `number_of_clauses`: all emitted initial and incremental CNF clauses;
- `number_of_subtour_iterations`: model-refinement rounds that added cuts; and
- `number_of_subtour_constraints`: unique component-cut inequalities added.

The SAT input domain matches the reference finder: finite, undirected,
structurally simple NetworkX graphs. Empty graphs, graphs of order one or two,
disconnected graphs, and vertices of degree below two return an unsatisfiable
result directly. Directed graphs, self-loops, and actual parallel edges are
rejected.

## plantri 5.8 enumeration

plantri remains an external program: importing or running this package never
downloads or builds it. The bundled [official guide](tools/plantri/plantri-guide-5.8.txt)
is used to pin the command-line semantics, and [setup notes](tools/plantri/README.md)
record the official source URL, archive digest, Linux/WSL build command, and a
reproducible native-Windows build. The Windows-only patch disables plantri's
internal CPU timer because Windows has no `sys/times.h` and puts stdout in
binary mode to prevent CRLF translation; it does not modify generation code.

Set `PLANTRI_EXECUTABLE` or pass an explicit path. Every invocation executes
`plantri --help`, requires version 5.8 unless `--allow-other-version` is given,
and hashes the executable:

```console
python -m barnette_search.enumeration \
  --plantri /path/to/plantri \
  --vertices 8 10 12 14 16 18 20 22 24 \
  --output-dir results/plantri-5.8
```

For a requested cubic dual with `N` vertices, its primal triangulation has `T`
vertices and `2T-4` faces. Since dual vertices correspond to primal faces,
`N=2T-4`, hence `T=N/2+2`. Odd `N` is therefore rejected. The exact command is:

```text
plantri -b -c3 -d T -
```

The official guide defines `-b` (without `-p`) as Eulerian triangulations,
`-c3` as 3-connected, and states that their duals are 3-connected bipartite
cubic graphs. `-d` writes the dual and the final `-` selects stdout. plantri's
default binary `planar_code` stream retains clockwise adjacency orders. The
Python wrapper drains stderr separately, since plantri writes counts and run
statistics there, and yields one parsed graph at a time.

For Barnette orders 8 through 32, the program requires the generated class
counts `1, 0, 1, 1, 2, 2, 8, 8, 32, 57, 185, 466, 1543`. These are the `all`
column of the guide's 3-connected plane Eulerian triangulation table at primal
orders 6 through 18.
Every generated graph is independently validated, solved by SAT, solved by
backtracking through 24 vertices, and every returned certificate is verified.
Any invalid graph, solver disagreement, duplicate canonical hash, or reference
count mismatch aborts the run clearly.

Each completed order produces JSONL (one record per graph) and a summary CSV.
The records include graph/embedding facts, validator and solver outcomes,
encoding statistics, runtimes, certificate hashes, the full command, executable
hash, and Python/dependency versions. A `run_metadata.json` captures the whole
run. Interrupted or failed output remains named `.partial`; existing completed
files are protected unless `--overwrite` is explicitly supplied.

## Same-face edge flexibility

The constrained reference APIs force selected edge variables with SAT
assumptions or enforce the same conditions in an independent backtracking
search:

```python
from barnette_search import (
    analyze_same_face_edge_flexibility,
    find_constrained_hamiltonian_cycle,
    solve_constrained_hamiltonian_cycle_sat,
)

sat_result = solve_constrained_hamiltonian_cycle_sat(
    graph,
    required_edges=((0, 1),),
    forbidden_edges=((2, 3),),
)
reference_cycle = find_constrained_hamiltonian_cycle(
    graph,
    required_edges=((0, 1),),
    forbidden_edges=((2, 3),),
)
flexibility = analyze_same_face_edge_flexibility(graph, embedding)
```

`ConstrainedHamiltonianSatSession` retains only globally valid subtour cuts
between queries. Required and forbidden edges remain per-query assumptions.
Every SAT and backtracking certificate is checked by the existing independent
certificate verifier and by a separate edge-constraint check.

The same-face analysis deduplicates ordered edge pairs across faces while
retaining every producing face index. Its deterministic greedy cover solves the
first uncovered pair, then assigns the resulting witness to every other pair it
certifies. `witness_cover_ratio` is the number of distinct witnesses divided by
the total number of ordered pairs; `ordered_pairs_per_witness` reports the
inverse compression measure. Through 24 vertices, every ordered pair is also
decided by the independent constrained backtracker.

If SAT reports an unsatisfiable pair or the methods disagree, normal processing
for that graph stops. The analyzer writes the graph and face embedding, exact
DIMACS queries, a MiniSat22 rerun, the independent backtracking result, and a
report explicitly marked for manual review.

Run the separate enumeration mode with:

```console
python -m barnette_search.enumeration \
  --plantri /path/to/plantri \
  --vertices 8 10 12 14 16 18 20 22 24 26 28 30 32 \
  --test-edge-flexibility \
  --output-dir results/plantri-5.8
```

It writes `*.edge_flexibility.jsonl`, corresponding summary CSV files, and
`edge_flexibility_run_metadata.json`. These names are separate from and never
overwrite the ordinary Hamiltonicity results.

## Benchmarking

After installing the `sat` or `test` extra, the benchmark script compares median
backtracking and SAT runtimes on fixed graph families and seeded random graphs.
It verifies outcomes but makes no timing assertions:

```console
python benchmarks/benchmark_hamiltonian.py --repeats 3
```

## Running tests

```console
python -m pytest
```

The default suite does not require plantri. To run its marked integration test:

```console
PLANTRI_EXECUTABLE=/path/to/plantri python -m pytest -m plantri_integration
```

The validator runs every property check and reports all applicable rejection
reasons in a deterministic order. NetworkX graph objects are materialized finite
containers, so accepting such an object (or a decoded graph6 record) supplies
the finiteness condition.

The backtracking finder has exponential worst-case running time and recursive
depth proportional to the number of vertices. The SAT formulation can require
many models, cut rounds, auxiliary variables, and clauses before proving an
answer. Both implementations are intended only as references for small graphs.
The embedding-based canonical hash is rigorous for the validated 3-connected
planar domain, whose sphere embedding is unique up to reflection; it is not
advertised as a general-purpose graph canonizer. Enumeration remains bounded by
plantri generation cost, exact-solver cost, and JSONL storage.
