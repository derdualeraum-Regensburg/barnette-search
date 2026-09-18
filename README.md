# Barnette Search

This Python research project studies finite **Barnette graphs**: undirected,
simple, cubic, bipartite, planar, and 3-vertex-connected graphs. Its main
computational invariant is Hamiltonian edge separation, described precisely in
[`docs/hsep.md`](docs/hsep.md).

The repository provides independent graph validation, exact backtracking and SAT
Hamiltonian-cycle solvers, reproducible plantri 5.8 enumeration, certificate
generation and verification, and structural analysis tools. Correctness,
deterministic output, and independently verifiable certificates take priority
over runtime. ILP and GPU support are not implemented.

**Public research draft; not peer-reviewed.** Release v0.9.0 provides a newly
calculated complete census package through order 36, including `M_B(36) = 49`.
It contains independently
checked separating covers for every one of the 22,263 census graphs and exact
lower certificates for every potential maximizer. It also provides new exact
certificates for D(9,9), D(11,9), and D(11,11). The package records its own
hashes and runtime metadata. See
[data availability](docs/data_availability.md) for the precise scope, verifier,
and release downloads.

The general double-ladder formula has a self-contained proof in the
[manuscript](paper/generated/main.pdf) and independent finite regression checks.

## License and citation

Original software is MIT licensed. The original manuscript, research figures,
and research data are CC BY 4.0 where applicable; third-party material retains
its own terms. See [license scope](LICENSES/README.md),
[third-party notices](THIRD_PARTY_NOTICES.md), and [CITATION.cff](CITATION.cff).

## Installation

Python 3.10 or newer is required. Install the base package, optional SAT support,
or the complete development test environment with:

```console
python -m pip install -e .
python -m pip install -e ".[sat]"
python -m pip install -e ".[test]"
```

External research data defaults to the ignored `results/` directory. Set
`BARNETTE_RESULTS_ROOT` to another directory, or use the relevant tool's explicit
`--sequence-root`, `--prediction-root`, `--census`, or `--output-root` option.
Examples below use `results/`; download and extract the v0.9.0 certificate asset
there when a tool needs the complete recalculated census.

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

## Strong flexibility and compact results

Two stronger exact analyses are available independently of the same-face mode:

- `analyze_all_edge_pair_flexibility` tests every ordered pair of distinct
  graph edges.
- `analyze_three_edge_path_flexibility` tests every simple length-three path,
  deduplicated against its reversal, by requiring its middle edge and
  forbidding both outer edges.

Both use deterministic greedy witness covers over a persistent constrained SAT
session. Returned cycles are checked by the existing certificate verifier and
by an independent required/forbidden-edge check. Optional pair-by-pair
cross-validation uses the independent constrained backtracker.

The compact multi-analysis command is:

```console
python -m barnette_search.enumeration \
  --vertices 8 10 12 14 16 18 20 22 24 26 28 30 32 \
  --plantri /path/to/plantri \
  --output-dir results/strong-flexibility \
  --test-all-edge-pairs \
  --test-three-edge-paths \
  --output-detail summary \
  --retain-top-k 25 \
  --compress-results \
  --workers 6 \
  --resume
```

The three output-detail modes are:

- `summary`: compact per-graph metrics without constraint assignments or full
  witness cycles;
- `candidates`: summary records plus full details for the union of candidate
  graphs and top-K extremal rankings;
- `full`: every constraint-to-witness assignment and witness cycle, intended
  only for small orders and debugging.

Compressed JSONL uses `.jsonl.gz`; `read_jsonl` transparently reads compressed
or plain files. Each order has a separate forced checkpoint. A complete output
is atomically published only after its generated identities and reference count
match. `--resume` skips completed hashes from a compatible checkpoint. Workers
operate on compact planar-code records, own independent solver sessions, and
final records are sorted by plantri generation index.

The `extremal` output contains six separate leaderboards for each analysis,
reproducible planar-code graphs and embeddings, human-readable reports, and
order-level minimum/median/mean/p95/p99/maximum tables. Timing leaderboards are
explicitly marked as machine-dependent.

An UNSAT result or solver disagreement is never automatically classified as a
counterexample. The review pipeline retains exact graph labels and embedding,
the constrained Glucose3 and MiniSat22 DIMACS files, structured solver results,
and an independent constrained-backtracking result for manual review.

## Certified maximizer gallery

The gallery tools render every certified maximizer, including every member of a
tie, without generating graphs or recomputing Hamiltonian edge-separation
values. Gunnar Brinkmann's external `planar_draw` source and executable are not
redistributed by this repository. See
[`docs/maximizer_gallery.md`](docs/maximizer_gallery.md) for the pinned drawing
options, Windows compatibility include, deterministic resume behavior, and
artifact checks.

```console
python tools/render_all_maximizers.py ^
  --sequence-root results\barnie-sequence ^
  --gallery-root results\barnie-sequence\gallery ^
  --engine results\barnie-gallery-toolchain\planar_draw.exe ^
  --engine-source tools\planar_draw.c ^
  --compiler path\to\gcc.exe ^
  --compat-include tools\planar_draw_compat
```

The renderer verifies that the vertices and edges parsed from each drawing are
exactly those in the corresponding certified graph record. It writes an index,
report, environment metadata, commands log, per-drawing resume sidecars, and a
SHA-256 manifest outside the repository.

## Ladder-family structural analysis

`tools/analyze_ladder_family.py` performs a read-only structural analysis of the
certified sequence and gallery artifacts. It identifies strict quadrilateral
ladder components, constructs reconstructible four-vertex square-expansion
certificates, classifies Hamiltonian cycles by local ladder-cell states, and
separately records observations about tied maximizers.

```console
python tools/analyze_ladder_family.py ^
  --sequence-root results\barnie-sequence ^
  --gallery-root results\barnie-sequence\gallery ^
  --output-root results\barnie-sequence\ladder-analysis
```

For the unique maximizers at orders divisible by four, the certified graphs form
a double-ladder family `D(a,b)` connected by one fixed square insertion. The
complete certified cycle universes satisfy `|H(D(a,b))| = ab + 5`. The
manuscript proves the general cycle classification and combines a symbolic
packing with a separating family of the same size to establish

```text
hsep(D(a,b)) = ((a+2)(b+2)-1)/2
```

for odd `a,b >= 3`. Global extremality beyond the certified census remains
conjectural. The structural analysis still labels its order-level predictions
for 38 and 40 as unproved and does not enumerate or optimize either order.

## Prospective double-ladder prediction test

`tools/test_double_ladder_predictions.py` performs a preregistered,
graph-specific test of the Hamiltonian-cycle and hsep formulas on three family
members beyond the certified census range. The prediction lock is written
before any new graph construction or Hamiltonian calculation. Starting from the
certified `D(9,7)` artifact, the producer constructs each target only through
the certified four-vertex facial square insertion.

| graph | order | complete Hamiltonian universe | exact hsep |
|---|---:|---:|---:|
| `D(9,9)` | 40 | 86 | 60 |
| `D(11,9)` | 44 | 104 | 71 |
| `D(11,11)` | 48 | 126 | 84 |

Both preregistered formulas match all three graphs. Each exact hsep value has
an explicit separating family and a matching packing lower certificate. A
standalone standard-library verifier reconstructs every expansion, independently
re-enumerates the complete Hamiltonian universe through perfect matchings,
checks the structural cycle classes, verifies every ordered edge-pair
requirement, and validates the manifests.

```console
python tools/test_double_ladder_predictions.py --resume
python results\double-ladder-prediction-test\verify_double_ladder_predictions.py ^
  results\double-ladder-prediction-test --check-manifest
```

The immutable package is written to
`results\double-ladder-prediction-test`; resumable checkpoints are
kept separately in `results\double-ladder-prediction-test-work`.
No complete census was run at orders 40, 44, or 48. Consequently these results
do not establish `M_B(40)`, `M_B(44)`, or `M_B(48)`, and do not prove that the
three graphs are extremal.

## Double-ladder packing lift

`tools/analyze_double_ladder_packings.py` analyzes only the four immutable,
complete Hamiltonian universes

```text
D(9,7) -> D(9,9) -> D(11,9) -> D(11,11).
```

Every stored optimal packing consists of four connector-exception singletons,
all boundary-turn singletons, and a domino tiling of the odd-by-odd interior
turn grid after removing one majority-parity cell. The solver-selected
packings are not uniformly nested: the certified path-aware overlaps are
`26/49`, `34/60`, and `71/71`, and exhaustive automorphism alignment improves
the first two only to `33/49` and `46/60`. A deterministic alternative packing
is fully nested in all three transitions.

Increasing `b` by two adds four boundary singletons and `a-2` dominoes, hence
`a+2` requirements. Increasing `a` by two analogously adds `b+2`. The three
finite increments are therefore `11`, `11`, and `13`. See
[`docs/double_ladder_packing_lift.md`](docs/double_ladder_packing_lift.md) for
the precise construction, proof status, hashes, and verification commands.

```console
python tools/analyze_double_ladder_packings.py ^
  --sequence-root results\barnie-sequence ^
  --prediction-root results\double-ladder-prediction-test ^
  --output-root results\double-ladder-packing-lift ^
  --repo .
python tools/verify_double_ladder_packing_lift.py ^
  results\double-ladder-packing-lift --check-manifest
```

The producer performs no census generation, graph search, Hamiltonian-cycle
enumeration, or unrestricted hsep optimization. The large immutable source
and output packages remain outside the repository and are bound by SHA-256
manifests.

## Manuscript draft

The LaTeX sources and a compiled PDF of the current technical manuscript are in
[`paper/`](paper/). The manuscript keeps finite certification, ordinary proof,
structural observation, and conjecture visibly separate; it is a draft and does
not make a novelty claim.

## Optional cubhamg benchmarking

`cubhamg` is not downloaded, bundled, or required. This repository does not
contain verified official cubhamg command documentation, so the wrapper does
not guess a version or syntax. A caller must provide an explicit executable,
the documentation reference they verified, command arguments containing an
`{input}` placeholder, and unambiguous output patterns. Ambiguous output and
timeouts produce no mathematical conclusion.

`benchmarks/benchmark_cubhamg.py` records executable hashes, separate stdout and
stderr, timeouts, machine metadata, reference-SAT results, and wall times. Its
results are benchmark observations only and do not establish algorithmic
superiority or constitute proofs.

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
