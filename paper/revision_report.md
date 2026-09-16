# Editorial revision report

## Proof revision, 2026-09-16

The Hamiltonian-cycle classification proof now states all endpoint and internal
degree equations, derives the odd-length endpoint compatibility condition, and
distinguishes fixed nonzero rail differences from the unresolved zero case.
The two- and four-connector cases include explicit connectivity arguments,
a terminal-pairing table, and a table of the four exceptional completions.
The excluded words `1001` and `0110` are correctly ruled out by degree
incompatibility. The classification and exact hsep formula retain their values
and parameter ranges.

Added 118 regression cases: local degree enumeration checks the recurrence,
odd/even controls verify the diagonal-word exclusion, and a counterexample
guards against inferring fixed rungs from zero rail differences. The independent
standard-library audit checks 100 parameter pairs, including 25 complete
Hamiltonian-cycle universes and matching certificates. The regression scope and
current suite results are recorded in the manuscript's reproducibility section.

The main README now agrees with the manuscript about the proved family formula
and the still-open global extremality claim. The bibliography uses the source
directory's `bibliography.bib`; `latexmkrc` includes a relative lookup for Git
for Windows Perl invoking native MiKTeX BibTeX, so a full rebuild succeeds
without retaining an old `.bbl` file.

Validation: `python -m pytest -q` passed with 365 passed and 5 environment-gated
integration skips in 11.37 seconds, without warnings. A full
`latexmk -gg -pdf main.tex` build with MiKTeX 25.12 and latexmk 4.88 produced
an 18-page PDF with all 15 bibliography entries. The final LaTeX log has no
undefined references or citations and no overfull or underfull boxes. All
18 rendered pages were inspected, with the revised proof on pages 9--10
also inspected separately. The external census packages and established solver
and validation modules were not modified.

## Earlier editorial revision

Date: 2026-08-01

## Scope and result

The main manuscript was reduced from 20 to 17 pages without changing the
proved formula, the finite certified values, or the status of the prospective
examples. The revision removes repeated descriptions and repeated family
plates while keeping the complete proofs and the sole-author framing.

## Sections shortened or reorganized

- The abstract was tightened around the definition, certified census, exact
  double-ladder theorem, and open continuation.
- The introduction no longer repeats an eight-member family display; it points
  to the compact census table and the single complete family gallery.
- The double-ladder section now contains one local TikZ insertion schematic and
  the manuscript's only complete 11-member family gallery.
- The Hamiltonian-cycle section no longer repeats the finite connector and
  family classification after stating the general theorem. The theorem and its
  proof are unchanged in substance.
- The order-36 paragraph no longer prints a long canonical hash in the main
  narrative; the identifier is preserved in the reproducibility supplement.
- The prospective section was reduced to its locked-value table and two short
  interpretive paragraphs. It still distinguishes exact graph-specific hsep
  values from unproved order-level extremality at 40, 44, and 48 vertices.
- The reproducibility section now summarizes the evidence scopes and directs
  detailed hashes, runtimes, layout statistics, and commands to
  `reproducibility_supplement.tex`.
- The conclusion was reduced to three paragraphs: proved results, finite
  evidence, and open problems.

## Mathematical content preserved

- The definition of hsep and its value on graphs without a separating family.
- The signature-antichain equivalence and certificate principle.
- The certified Barnette extremal sequence through order 36, including ties.
- The Barnette and face-structure results for `D(a,b)`.
- The Hamiltonian-cycle classification `|H(D(a,b))|=ab+5`.
- The symbolic packing lower bound, separating-family upper bound, complete
  eight-case antichain argument, and exact formula
  `hsep(D(a,b))=((a+2)(b+2)-1)/2` for odd `a,b >= 3`.
- The six prediction-locked prospective values and their certificate status.
- The explicit caveat that `hsep(D(9,9))=60` does not prove `M_B(40)=60`.

## Wording corrections

- Shared-counter cross-references use the correct object names.
- “Exact family formula equation” was changed to “exact identity.”
- Unsupported Test Cover/Minimum Test Collection terminology was removed from
  the literature discussion rather than left without a direct reference.
- Bibliography capitalization was protected for plantri, Hamiltonian,
  Barnette's Conjecture, and mathematical graph names.
- The acknowledgments and AI-assistance statement remain restrained and do not
  imply review, endorsement, collaboration, or approval.

## Verification

- `pytest -q`: 198 passed, 5 skipped (latest software-validation run; no solver
  or validation code was changed by this editorial pass).
- Final clean command: `latexmk -C main.tex`, followed by
  `latexmk -pdf main.tex` with MiKTeX 25.12.
- Output: `generated/main.pdf`, 17 pages.
- Final source/log audits found no undefined citations or references,
  duplicate labels, overfull or underfull boxes, or absolute result paths.
- The final PDF was rendered and inspected page by page. The local insertion
  schematic, all proof grids, the 11-member gallery, status labels, tables, and
  bibliography are readable and unclipped.

No census, graph search, Hamiltonian enumeration, hsep optimization, or new
mathematical experiment was run. Immutable result packages and Gunnar
Brinkmann's external source were not modified. Nothing was committed, pushed,
emailed, uploaded, submitted, or published.
