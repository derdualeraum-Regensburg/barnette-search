# AGENTS.md

## Project overview

This repository performs computational research on Barnette graphs:
simple, cubic, bipartite, planar, 3-connected graphs.

Correctness, reproducibility, deterministic output, and independently
verifiable certificates take priority over runtime.

## Hamiltonian edge separation

Before implementing or analysing hsep, read `docs/hsep.md`.

Never equate a greedy witness-cover count with the exact value of hsep.
A greedy result is only an upper bound.

An exact claim hsep(G) = k requires:

1. A primal certificate containing k Hamiltonian cycles that cover every
   ordered pair of distinct edges (e,f), where the cycle contains e and
   avoids f.

2. A lower-bound certificate proving that fewer than k cycles cannot
   cover all requirements.

3. A self-contained independent verification script.

The name and notation hsep are provisional. Do not claim novelty without
a literature review and expert confirmation.

## Research rules

- Do not claim that a generated graph is new merely because its hash is new.
- Distinguish graph isomorphism classes from labelled representations.
- Preserve canonical graph certificates such as graph6 and planar_code.
- Do not modify established solver or validation modules unless explicitly requested.
- Add tests for every mathematical or parsing change.
- Record solver versions, seeds, command lines, hashes, and runtimes.
- Report uncertainty and incomplete optimality proofs clearly.
