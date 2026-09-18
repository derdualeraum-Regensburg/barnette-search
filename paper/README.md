# Barnette hsep manuscript draft

This directory contains a public manuscript draft. It is not peer-reviewed or a
submitted paper and makes no absolute novelty claim. Thomas Bauer is the sole
author.

**Data availability:** the original external proof packages were lost in an
accidental drive deletion. Release v0.9.0 provides a newly calculated complete
census package through order 36 and new exact certificates for three larger
double ladders. The new hashes and runtime records are distinct from the deleted
historical files; see [`../docs/data_availability.md`](../docs/data_availability.md).
The general double-ladder proof and its self-contained regression checker remain
available independently of the census data.

## Build

Section 10 integrates the quantitative three-edge splice lemma with its
complete proof, state-dependent refinement, scalar bound, cube-insertion
corollary, and limits. The former Conjecture 10.2 is now Conjecture 11.2.
The separate unreviewed note [`quantitative_splice.tex`](quantitative_splice.tex)
is retained as the original derivation; the integrated manuscript is the
current presentation. The [independent audit](../artifacts/splice_lemma_20260917/README.md)
checks 36 small labelled examples. Neither the audit nor manuscript compilation
depends on the completed census reconstruction. Build the separate note with
`latexmk -pdf quantitative_splice.tex`.

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

The 2026-09-17 splice integration produces a 21-page PDF. The 148 targeted
mathematical regression tests pass, including independent verification of the
cube cycles printed in the manuscript. All rendered pages were inspected;
the final LaTeX log has no undefined references or citations and no overfull
or underfull boxes. Sources, PDF hash, commands and results are recorded in
[`manuscript_integration_review.json`](../artifacts/splice_lemma_20260917/manuscript_integration_review.json).

The 2026-09-18 data-availability revision records the completed v0.9.0
recalculation: all 22,263 census graphs through order 36 and the exact
graph-specific certificates for `D(9,9)`, `D(11,9)`, and `D(11,11)`. The
release verifier passed on 333 files in 560.39 seconds. The full software suite
passed with 597 tests and 10 explicit environment or historical-package skips.
The corrected 21-page PDF has SHA-256
`ed5300bab497fb09f9833ea3505a23c2d414d6ebe7dbe0b29c9a99d21c79aa89`;
all pages were rendered and visually inspected, and the LaTeX log contains no
undefined references, overfull boxes, or underfull boxes.

## Structure

The separate research note [`four_port_induction.tex`](four_port_induction.tex)
develops nine-state four-port composition, a requirement-preserving reduction
of compatible products, and a conditional lift-and-repair induction criterion.
Its [bounded audit](../artifacts/four_port_20260917/README.md) includes positive
and negative separation cases. The note does not prove Conjecture 11.2 and is
not inserted into the main manuscript. Build with
`latexmk -pdf four_port_induction.tex` from this directory.

The subsequent [16-vertex diagnosis](../artifacts/four_port_step1_20260917/README.md)
certifies hsep 12 for the four labelled D(3,3) examples where the original
four-port construction gave 13. It identifies redundancy across entire
state blocks as the missing ingredient; it does not settle Conjecture 11.2.

The [square-reduction follow-up](../artifacts/square_reduction_20260918/README.md)
gives a conditional inverse criterion, a complete local lifting table, and
an exact description of the missing separation requirements after lifting.
Its bounded 16-to-20-vertex example needs a reserve witness from outside the
old optimal family and achieves a verified 17-cycle upper certificate.

- `main.tex`: document setup and section order.
- `sections/`: abstract, definitions, related work, computational method, certified
  extremal sequence, double ladders, Hamiltonian structure, exact symbolic
  bounds, prospective confirmations, quantitative three-edge splicing, open
  conjectures, reproducibility, and
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
  `hsep(D(a,b))=((a+2)(b+2)-1)/2` for odd `a,b >= 3`; quantitative
  three-edge gluing for finite separating families, its projection lower
  bound, scalar upper bound, and cube-insertion corollary.
- **Recalculated finite results (see data availability above):** the complete
  extremal sequence on nonempty orders 8--36, all maximizers and ties, the eight
  census-range double-ladder identifications, the finite Hamiltonian-cycle
  counts, and exact graph-specific certificates for `D(9,9)`, `D(11,9)`, and
  `D(11,11)`.
- **Structurally verified observations:** strict ladder components, the local
  tile-state classification on the emitted complete universes, and the 25 tied
  expansion links.
- **Historical prediction lock and new confirmations:** the originally frozen
  values for `D(9,9)`, `D(11,9)`, and `D(11,11)` agree with the new exact
  certificates and the general theorems but make no order-level extremal claim.
- **Open or conjectural:** extremality and uniqueness beyond order 36, the
  structure of the tied branch, and the order-38 linear extrapolation. In
  particular, the paper does not claim `M_B(40)=60`.

## Outstanding mathematical and literature work

1. Have a graph theorist audit the direct 3-connectivity proof and the precise
   embedding convention in the face proposition.
2. Have the parameterized rail/rung recurrence, packing construction, and
   eight signature cases independently audited.
3. Independently audit the quantitative splice proof and investigate the
   literature priority of its bounds; classify the tied branch by finite boundary states.
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
