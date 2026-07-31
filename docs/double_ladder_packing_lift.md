# Double-ladder packing-certificate lift

This document records the compact, repository-tracked summary of the immutable
analysis package at `E:\barnette-results\double-ladder-packing-lift`. The large
cycle universes and generated JSON reports remain outside the repository.

## Scope and integrity

Only the existing complete Hamiltonian universes of the following four graphs
were read. No census, graph search, Hamiltonian enumeration, or unrestricted
hsep optimization was run.

| graph | canonical graph hash | cycles | exact hsep |
|---|---|---:|---:|
| `D(9,7)` | `2f96ada16c46cd2bd038b97d5af44f46ed14522cba1edf3fa041d66e02107bcc` | 68 | 49 |
| `D(9,9)` | `dafd27f31c9e2fc0aa19e8c82786bd4679509f82b6835703c784046b22e0b201` | 86 | 60 |
| `D(11,9)` | `296435b31ef80b1811ea6fc31d6d513ed9edbf1d245343d208dac14388c8928f` | 104 | 71 |
| `D(11,11)` | `8848c2d7817bd238837b07b97054802e6f968a04e0c70ec6b142c12e9ed28c28` | 126 | 84 |

All six relevant source manifests passed. The generated package contains 25
manifested files. Its `SHA256SUMS.txt` has SHA-256
`188800bd2a8b0835216f6fa9c78eb4673e5b3bc24d1dc216bc3a7d619986f31e`.
The standalone verifier reports `PACKING_LIFT_PACKAGE_VERIFIED`.

The nonidentity `original_to_canonical` relabelling of `D(9,7)` is applied
before interpreting its edge-index requirements. Cross-graph comparisons use
the certified expansion maps rather than raw canonical labels.

## Exact finite structure

For a requirement `r=(e,f)`, let

```text
Cov(r) = {C : e belongs to C and f does not belong to C}.
```

Every one of the four immutable optimal packings has the same structural
decomposition:

- four singleton supports, one for each two-connector exception cycle;
- one singleton for every boundary turn cycle, totalling `2a+2b-4`;
- a domino tiling of the interior `(a-2) x (b-2)` turn grid after deleting one
  majority-parity cell.

Every domino requirement covers exactly two adjacent turn cycles. These
supports are pairwise disjoint and leave precisely the all-rails cycle and one
interior turn cycle uncovered.

| graph | singleton supports | domino supports | uncovered turn |
|---|---:|---:|---|
| `D(9,7)` | 32 | 17 | `T(3,5)` |
| `D(9,9)` | 36 | 24 | `T(1,5)` |
| `D(11,9)` | 40 | 31 | `T(5,3)` |
| `D(11,11)` | 44 | 40 | `T(5,5)` |

The conflict-graph summaries cover all ordered edge-pair requirements: 2,862,
3,540, 4,290, and 5,112 candidate vertices respectively.

## Alignment and lift

The immutable solver-selected certificates are not uniformly nested.

| transition | certified path-aware overlap | best after all graph automorphisms |
|---|---:|---:|
| `D(9,7) -> D(9,9)` | 26/49 | 33/49 |
| `D(9,9) -> D(11,9)` | 34/60 | 46/60 |
| `D(11,9) -> D(11,11)` | 71/71 | 71/71 |

A deterministic alternative packing is fully path-aware nested in every
transition. A deleted rail edge may be represented by the corresponding edge
of its certified three-edge replacement path. Exception requirements are
anchored on the ladder not being expanded.

For `b -> b+2`, the two inserted turn-grid columns require four boundary
singletons and `a-2` interior dominoes, giving the exact increment `a+2`.
For `a -> a+2`, four boundary singletons and `b-2` dominoes give `b+2`.

| transition | new singletons | new dominoes | increment |
|---|---:|---:|---:|
| `D(9,7) -> D(9,9)` | 4 | 7 | 11 |
| `D(9,9) -> D(11,9)` | 4 | 7 | 11 |
| `D(11,9) -> D(11,11)` | 4 | 9 | 13 |

## General lower-bound construction

Let `r_L(t)` denote rung `t` of ladder `L`, and let `ell_L(t,s)` denote rail
`s` in cell `t`. For odd `a,b >= 3`, use:

1. four ordered rail/rung comparisons isolating the four exception cycles;
2. endpoint-rung/alternating-rail comparisons isolating all boundary turns;
3. `(r_A(p),ell_B(j,0))` for each selected vertical interior domino
   `{T(p-1,j),T(p,j)}`;
4. `(r_B(q),ell_A(i,0))` for each selected horizontal interior domino
   `{T(i,q-1),T(i,q)}`.

The rail/rung degree recurrence classifies the Hamiltonian cycles as one
all-rails cycle, `ab` turn-pair cycles, and four connector exceptions. The
requirements above partition all but two of these cycles into disjoint
supports. Their number is

```text
4 + (2a+2b-4) + ((a-2)(b-2)-1)/2
  = ((a+2)(b+2)-1)/2.
```

Consequently,

```text
hsep(D(a,b)) >= ((a+2)(b+2)-1)/2
```

for all odd `a,b >= 3`. This is a lower-bound theorem only. Equality still
requires a parameterized Hamiltonian edge-separating family of the same size.
No novelty claim is made.

## Reproduction

```console
python tools/analyze_double_ladder_packings.py ^
  --sequence-root E:\barnette-results\barnie-sequence ^
  --prediction-root E:\barnette-results\double-ladder-prediction-test ^
  --output-root E:\barnette-results\double-ladder-packing-lift ^
  --repo .

python tools/verify_double_ladder_packing_lift.py ^
  E:\barnette-results\double-ladder-packing-lift --check-manifest

python -m pytest tests\test_double_ladder_packing.py ^
  tests\test_double_ladder_prediction_test.py -q
```

The verifier uses only Python's standard library. It rechecks graph and cycle
validity, both stored and structural packings, every coverage set, pairwise
disjointness, expansion paths, immutable source hashes, and the output
manifest. Completeness of the cycle universes is inherited by hash from the
pre-existing independently verified packages rather than recomputed.
