# Barnette hsep manuscript draft

This directory contains a public manuscript draft. It is not peer-reviewed or a
submitted paper and makes no absolute novelty claim. Thomas Bauer is the sole
author.

**Data availability:** the original external proof packages were lost in an
accidental drive deletion. The public release provides reconstructed certificates
through order 24 and selected larger graphs. Original census claims above order
24 remain historical reports pending restoration of the full evidence; see
[`../docs/data_availability.md`](../docs/data_availability.md). The general
double-ladder proof and its self-contained regression checker remain available.

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
directories at build time. On 2026-08-01 the revised draft compiled from a
clean state successfully with MiKTeX 25.12 to a 17-page PDF. The final log contained no
undefined citations, undefined references, overfull boxes, or underfull boxes,
and all pages were visually inspected.

The 2026-09-16 proof revision expands the Hamiltonian-cycle classification,
corrects the two endpoint-recurrence statements, and adds explicit terminal
pairing and connector-state tables. The revised PDF has 18 pages. A full
`latexmk -gg -pdf main.tex` rebuild also regenerates the bibliography; the
configuration handles Git for Windows Perl's path convention when invoking
native MiKTeX BibTeX. All pages were rendered and visually inspected, and the
final LaTeX log has no undefined references or citations and no overfull or
underfull boxes. The test suite passed with 365 tests and five integrations
skipped because their external executables were not configured.

The independent proof checks are in
`tests/test_double_ladder_manuscript_proof.py` and
`../artifacts/proof_audit_20260916/verify_formula.py`. The original audit report
and its source hashes describe the pre-revision manuscript; they are retained
as a historical record. The revision is an argument-based review with finite
checks, not an external expert endorsement or a machine-formalized proof.

## Structure

- `main.tex`: document setup and section order.
- `sections/`: abstract, definitions, related work, computational method, certified
  extremal sequence, double ladders, Hamiltonian structure, exact symbolic
  bounds, prospective confirmations, open conjectures, reproducibility, and
  conclusion.
- `tables/`: compact data copied from certified summaries.
- `figures/`: the single complete Bauer-family plate used by the manuscript,
  verified supplementary derivatives, and selected gallery images; no external
  drawing source is included.
- `bibliography.bib`: fifteen verified literature and software-guide entries.
- `reproducibility_supplement.tex`: detailed hashes, runtimes, commands, and
  layout-verification records kept outside the main narrative.
- `literature_audit.md`, `figure_audit.md`, and `revision_report.md`: revision
  audit trails.
- `generated/`: LaTeX build output only.

## Original external evidence (currently unavailable)

The original draft was prepared from these read-only packages at their
historical locations; these paths no longer identify available downloads:

```text
E:\barnette-results\barnie-sequence
E:\barnette-results\barnie-sequence\gallery
E:\barnette-results\barnie-sequence\ladder-analysis
E:\barnette-results\double-ladder-prediction-test
E:\barnette-results\double-ladder-packing-lift
E:\barnette-results\double-ladder-primal-lift
```

Their result corpora are intentionally not duplicated here. Relevant manifest
hashes are stated in `reproducibility_supplement.tex`.

## Status of claims

- **Proved in the draft:** the signature-antichain equivalence; the primal and
  packing certificate principle; preservation of Barnette properties under the
  specified facial square insertion; the Barnette property and face formula
  for `D(a,b)` with positive odd parameters; the complete Hamiltonian-cycle
  classification `|H(D(a,b))|=ab+5`; the symbolic packing lower bound; the
  signature-antichain upper bound; and therefore
  `hsep(D(a,b))=((a+2)(b+2)-1)/2` for odd `a,b >= 3`.
- **Historically reported finite results (see data availability above):** the complete extremal sequence on
  nonempty orders 8--36, all maximizers and ties, the eight census-range
  double-ladder identifications, seven exact family expansions, the finite
  Hamiltonian-cycle counts, the tied-order structural classification, and the
  graph-specific prospective certificates for `D(9,9)`, `D(11,9)`, and
  `D(11,11)`.
- **Structurally verified observations:** strict ladder components, the local
  tile-state classification on the emitted complete universes, and the 25 tied
  expansion links.
- **Historically reported prospective confirmations:** the prediction-locked values for
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
5. Obtain and inspect the full text of sources, especially Cai (1984), before
   making any definition-level comparison beyond the cautious statement in the
   manuscript.
6. Extend the literature review before journal submission to cover any
   Hamiltonian-cycle-specific separation terminology not represented by the
   verified core bibliography; add Test Cover references if that terminology
   is reintroduced.
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
