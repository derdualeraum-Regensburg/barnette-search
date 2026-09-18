# Four-port composition and conditional induction

The full proof draft is [`paper/four_port_induction.tex`](../../paper/four_port_induction.tex).
It is a separate research note; Conjecture 11.2 in the main manuscript remains open.

## Results and assumptions

- A fragment has four distinct degree-two terminals; all other vertices have degree three.
- Six spanning-path states and three two-path pairing states give nine formal states.
  There are twelve compatible ordered state pairs. Equal four-terminal pairings
  produce two cycles and must be excluded.
- For state families of sizes `a,b` and edge-union subfamilies of sizes `p,q`,
  the compatible product can be reduced from `ab` to `pb+aq-pq` cycles per block.
  The reduced family preserves **exactly** the ordered edge requirements covered
  by the full family, even if that family does not separate all edges.
- Nonempty states have edge-union covers of size at most `n/2` for two used
  terminals and `n/2+1` for four. Greedy covers are feasible upper bounds only.
- A separate local-and-cross-edge criterion states precisely when the product
  separates all edges. This is a hypothesis to prove for a graph class, not a
  consequence of having nine states.
- Fragment replacement gives a conditional lift-and-repair lemma. If an old
  certificate has `k` cycles and `r` repair witnesses suffice after lifting,
  the new upper bound is at most `k+r`. With certified slack `s=B(m)-k`, the
  induction budget is `r <= B(n)-B(m)+s`.
- The induction criterion requires base certificates, reductions staying in
  the graph class, and lift/repair bounds for every allowed input certificate
  (or a stronger preserved invariant). These structural obligations remain open.

There is no exact hsep claim, proof of global extremality, or priority claim.
Matching-connectivity boundary states are established prior work; see
Curticapean, Lindzey and Nederlof, <https://arxiv.org/abs/1709.02311>.
The degree assumptions restrict this note to matching four-edge cuts, not all
cuts of size four with repeated endpoints.

## Bounded reproducible audit

```console
python artifacts/four_port_20260917/build_examples.py
python -I artifacts/four_port_20260917/verify.py artifacts/four_port_20260917/examples/ladder4_ladder4_02.json
python -m pytest -q tests/test_four_port_lemma.py
```

`construct.py` enumerates local edge subsets and groups admissible spanning
path covers by state. `verify.py` imports only the Python standard library,
checks every path and pairing, tests connectivity of the actual glued edges,
and independently enumerates global Hamiltonian cycles using perfect matchings.
It verifies the two counts and equality of full/reduced covered requirements.
The local separation criterion is checked against direct global separation.
The `complete_universe_claimed` flag certifies the global product universe;
the verifier does not claim to enumerate unused, incompatible local covers.

The 120 labelled examples use all 24 terminal bijections on four pairs of
fragments and another 24 cases with proper local subfamilies. They are not
asserted to be distinct isomorphism classes. Resulting orders are at most 16.
NetworkX records graph6 and checks Barnette properties separately: 16 cases
are Barnette graphs, all separating. Sixteen cases have strict count reductions.
In four Barnette cases the count improves from 14 to 13, still above B(16)=12.

`lift_repair.py` gives a deterministic conditional lift and greedy repair
constructor. Tests independently check its output cycles, preserved exterior
incidences, full separation, and rejection of missing lifts/nonseparating
source families. It does not claim a minimum repair cost.

The suite has 132 tests. `results.json` and `SHA256SUMS.txt` record example
hashes, source hashes, versions, commands and runtime. `review.json` records
proof/PDF hashes and the combined regression run. No random choices or
optimization solvers are used. Established solver/validation modules are
unchanged. No large census reconstruction is started by these commands.

## Subsequent 16-vertex diagnosis

The [step-1 audit](../four_port_step1_20260917/README.md) proves exact hsep 12
for the four labelled Barnette cases whose original bound was 13. Explicit
isomorphism certificates identify them as one class, D(3,3). The minimum
within the original full-state union-cover rectangle construction is 13;
reaching 12 requires dropping a whole redundant singleton state block.
That audit supplies independent upper/lower certificates and does not change
the original examples or the historical 14-to-13 construction above.
