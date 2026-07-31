# Barnette hsep manuscript draft

This directory contains a technically serious initial manuscript draft. It is
not a submitted paper and makes no novelty claim. Thomas Bauer is the sole
current author placeholder.

## Build

A current TeX Live or MiKTeX installation with `latexmk`, `pdflatex`, BibTeX,
and the packages listed in `main.tex` is required. From this directory run:

```console
latexmk -pdf main.tex
```

On the drafting machine, MiKTeX is installed per user. `latexmk` uses the Perl
runtime supplied by Git for Windows; a PowerShell session that does not already
find that runtime can prepare the process-local path with:

```powershell
$env:Path = "$env:LOCALAPPDATA\Programs\MiKTeX\miktex\bin\x64;C:\Program Files\Git\usr\bin;$env:Path"
latexmk -pdf main.tex
```

The `latexmkrc` file places the PDF and auxiliary files in `generated/`. Clean
with `latexmk -C main.tex`. The manuscript does not read the external result
directories at build time. On 2026-08-01 the draft compiled successfully with
MiKTeX 25.12 to a 16-page PDF. The final log contained no undefined citations,
undefined references, overfull boxes, or underfull boxes, and all pages were
visually inspected.

## Structure

- `main.tex`: document setup and section order.
- `sections/`: abstract, definitions, computational method, certified
  extremal sequence, double ladders, Hamiltonian structure, exact symbolic
  bounds, prospective confirmations, open conjectures, reproducibility, and
  conclusion.
- `tables/`: compact data copied from certified summaries.
- `figures/`: selected small PNG/SVG derivatives copied from immutable gallery
  outputs; no external drawing source is included.
- `bibliography.bib`: one software-guide entry verified from the repository and
  explicit placeholders for the outstanding literature review.
- `generated/`: LaTeX build output only.

## Immutable external evidence

The draft was prepared from these read-only packages:

```text
E:\barnette-results\barnie-sequence
E:\barnette-results\barnie-sequence\gallery
E:\barnette-results\barnie-sequence\ladder-analysis
E:\barnette-results\double-ladder-prediction-test
E:\barnette-results\double-ladder-packing-lift
E:\barnette-results\double-ladder-primal-lift
```

Their result corpora are intentionally not duplicated here. Relevant manifest
hashes are stated in `sections/reproducibility.tex`.

## Status of claims

- **Proved in the draft:** the signature-antichain equivalence; the primal and
  packing certificate principle; preservation of Barnette properties under the
  specified facial square insertion; the Barnette property and face formula
  for `D(a,b)` with positive odd parameters; the complete Hamiltonian-cycle
  classification `|H(D(a,b))|=ab+5`; the symbolic packing lower bound; the
  signature-antichain upper bound; and therefore
  `hsep(D(a,b))=((a+2)(b+2)-1)/2` for odd `a,b >= 3`.
- **Exhaustively certified finite results:** the complete extremal sequence on
  nonempty orders 8--36, all maximizers and ties, the eight census-range
  double-ladder identifications, seven exact family expansions, the finite
  Hamiltonian-cycle counts, the tied-order structural classification, and the
  graph-specific prospective certificates for `D(9,9)`, `D(11,9)`, and
  `D(11,11)`.
- **Structurally verified observations:** strict ladder components, the local
  tile-state classification on the emitted complete universes, and the 25 tied
  expansion links.
- **Prospective finite confirmations:** the prediction-locked values for
  `D(9,9)`, `D(11,9)`, and `D(11,11)`. They agree with the general theorems
  but make no order-level extremal claim.
- **Open or conjectural:** extremality and uniqueness beyond order 36, the
  structure of the tied branch, and the order-38 linear extrapolation. In
  particular, the paper does not claim `M_B(40)=60`.

## Outstanding mathematical and literature work

1. Have a graph theorist audit the direct 3-connectivity proof and the precise
   embedding convention in the face proposition.
2. Have the parameterized rail/rung recurrence, packing construction, and
   eight signature cases independently audited.
3. Classify the tied branch by finite boundary states.
4. Develop an order-level method for the open balanced-double-ladder extremal
   conjecture.
5. Perform a systematic peer-reviewed literature review covering separating
   systems, completely separating systems, edge separation by cycles,
   Hamiltonian-cycle covers, Barnette censuses, and reducible configurations.
6. Replace all bibliography TODOs with source-checked entries and adjust the
   terminology before making any novelty claim.
7. Recompile and inspect every page after substantive revisions, especially for
   overfull boxes, float placement, and bibliography formatting.

## Instructions for a future collaborator

Start by reading `AGENTS.md`, `docs/hsep.md`, this README, and the certified
reports. Verify the immutable manifests and run the standalone sequence
verifier before changing numerical statements. Keep finite certification,
ordinary proof, observation, and conjecture visibly separate. Do not edit the
external packages in place. Record any changed data provenance and rerun the
full test suite. Do not add an author, affiliation, acknowledgment, citation,
or established operation name without explicit consent and source checking.

## Draft AI-assistance disclosure

AI tools assisted with software development, data analysis, drafting, and
language editing. All mathematical certificates are independently checkable.
The author remains responsible for definitions, claims, proofs, source
verification, and the final manuscript.
