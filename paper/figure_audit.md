# Figure audit

Date: 2026-08-01

## Figures retained in the main manuscript

| Figure | Source | Data/status represented | Coordinate provenance and verification |
|---|---|---|---|
| Local facial-square insertion | TikZ in `sections/double_ladders.tex` | Deterministic replacement of edges `uv` and `xy` by a new facial 4-cycle with vertices `p,q,r,s` | Mathematical before/after schematic, not graph-layout coordinates. Labels and incidences were checked against the stated operation. |
| Complete 11-member double-ladder family | `figures/bauer_layout/extended_double_ladder_family.pdf` | `D(1,1)` through `D(9,7)` are the eight certified unique maximizers at the relevant orders through 36; `D(9,9)`, `D(11,9)`, and `D(11,11)` have exact graph-specific values but no claimed global extremality | Refined presentation coordinates preserving each certified abstract graph, rotation system, face structure, structural labels, order, and hsep value. The selected drawings have zero crossings. |
| Packing lower-bound grid | TikZ in `sections/exact_hsep.tex` | General symbolic lower-bound construction | Generated from the proved turn-grid construction; not a graph layout. |
| Parity separating-family grid | TikZ in `sections/exact_hsep.tex` | General symbolic upper-bound construction | Generated from the proved turn-grid construction; not a graph layout. |
| Local-lift grid | TikZ in `sections/exact_hsep.tex` | General symbolic square-insertion lift | Generated from the proved turn-grid construction; not a graph layout. |
| Tied order-22 examples | `figures/tied22a.png` and `figures/tied22b.png` | Two certified order-22 maximizers | Existing certified gallery derivatives; retained to distinguish the tied branch from the double-ladder recurrence. |

The complete family plate appears exactly once, immediately after the exact
family result. Its caption separates the census-certified claims from the
three prospective graph-specific confirmations.

## Figures removed from the main manuscript

| File or occurrence | Reason for removal | Retained status |
|---|---|---|
| `figures/bauer_layout/certified_bauer_family.pdf` | Its eight graphs duplicate the certified subset of the complete 11-member plate | Kept in the repository as a verified derivative and provenance artifact. |
| `figures/bauer_layout/square_insertion_sequence.pdf` | A multi-graph sequence was unnecessary for explaining the local operation | Kept as a verified derivative; replaced in the manuscript by the compact TikZ schematic. |
| Second occurrence of `extended_double_ladder_family.pdf` in the prospective section | Exact duplicate of the complete family plate | Removed entirely; the prospective section now uses only its table and text. |
| Legacy `d*.png` family images and `square_insertion_d55.png` | Inconsistent or redundant presentation relative to the verified plate | Provenance files only; not included by `main.tex`. |

The supplementary `outer_face_comparison.pdf` and
`raw_vs_normalized_layout.pdf` were also intentionally left outside the main
argument.

## Bauer layout-package checks

- 12,672 candidate variants were evaluated.
- All 400 cap-selecting directed edges were exercised, confirming the
  `cf x y` left-face convention.
- `B_rail_0` was selected as the exterior structural face for all eleven
  graphs.
- Constrained refinement was required for every selected graph; the complete
  plate is not presented as raw drawing-program output.
- The final drawings have horizontal ladder-A rails, boundary-following ladder
  B, convex outer faces, a consistent insertion orientation, and zero
  crossings.
- The verified refinement and transition costs, package hashes, and external
  source hash are recorded in `reproducibility_supplement.tex`.

## Render audit

The final 17-page PDF was rendered to PNG and inspected page by page. Labels,
orders, hsep values, and certification wording are readable; no figure is
clipped; the mathematical schematics remain legible; and no graph beyond order
36 is labeled a certified global maximizer.
