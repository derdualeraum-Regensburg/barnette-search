# Hamiltonian edge-separation number

Let H(G) denote the set of all undirected Hamiltonian cycles of a
Hamiltonian graph G.

For distinct edges e and f, a Hamiltonian cycle C covers the ordered
edge-pair requirement (e,f) when:

    e is in C and f is not in C.

A family S contained in H(G) is Hamiltonian edge-separating when every
ordered pair of distinct edges is covered.

Define provisionally:

    hsep(G) = minimum |S|

over all Hamiltonian edge-separating families S.

## Certificates

An upper-bound certificate of value k consists of k Hamiltonian cycles
covering all ordered edge-pair requirements.

A packing lower-bound certificate of value k consists of k requirements
such that every Hamiltonian cycle covers at most one of them.

Matching certificates prove hsep(G) = k exactly.
