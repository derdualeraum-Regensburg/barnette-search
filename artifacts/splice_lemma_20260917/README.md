# Quantitative three-edge gluing lemma

Proof: [`paper/quantitative_splice.tex`](../../paper/quantitative_splice.tex).
This is an unreviewed derivation, not a claim of literature priority.
It quantifies the gluing argument behind Gorsky, Steiner and Wiederrecht's
known qualitative H+- decomposition theorem (Lemma 4.5(iv), 2023 article;
<https://arxiv.org/html/2202.11641>).

For two separating families partitioned by the omitted splice edge, let their
three state sizes be `a_i`, `b_i`. Choose subfamilies of sizes `p_i`, `q_i`
covering all internal edges in their respective states. The constructed
separating family in the splice has size

    sum_i (p_i*b_i + a_i*q_i - p_i*q_i) <= sum_i a_i*b_i.

The universal consequence for finite factor values `h1`, `h2` is

    max(h1,h2) <= hsep(splice) <= (h1-4)*(h2-4)+8.

The proof requires no planarity or bipartiteness. Splicing Barnette graphs
preserves their defining properties. The hypotheses do assume that the factors
have separating families; the lemma does not settle Barnette's conjecture or
the double-ladder extremal conjecture.

## Independent checks

From the repository root:

```console
python artifacts/splice_lemma_20260917/build_examples.py
python artifacts/splice_lemma_20260917/verify.py artifacts/splice_lemma_20260917/examples/prism8_prism8_0_complete.json
python -m pytest -q tests/test_splice_lemma.py
```

`construct.py` uses anchored Hamiltonian-path DFS. `verify.py` uses independent
perfect-matching enumeration and explicit ordered-pair coverage, with standard
Python only. The example builder additionally uses NetworkX to check the
Barnette properties and preserve a labelled graph6 representation.

All 36 labelled examples passed. The original audit had 29 regression tests; manuscript integration adds
a thirtieth test of the cube cycles actually printed in Section 10. Every one of
the six terminal bijections is checked. The tests include proper subfamilies
of the Hamiltonian universe and deliberately damaged certificates. The
30-vertex prism splice has a 40-cycle upper certificate, compared with the
44-cycle full product. Neither number is asserted to be its exact hsep value.

These are bounded checks of the new lemma, not the paused reconstruction run.
No solver or established validation module was modified. Input/output graph6
strings identify labelled representations, not previously unknown graphs.
`results.json` records versions, command, runtime, and SHA-256 hashes;
`SHA256SUMS.txt` covers the verifier, constructor, builder, report and examples.

The underlying qualitative theorem is established prior work. A targeted
literature search found no directly matching quantitative statement, but that
does not establish novelty. Independent mathematical review is still needed.

The lemma is now integrated into `paper/sections/quantitative_splice.tex`.
`manuscript_integration_review.json` records the resulting 21-page PDF,
current source hashes, 148 targeted proof checks, and visual inspection.
The earlier `review.json` records the separate four-page research note.
