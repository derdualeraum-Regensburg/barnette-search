"""Independent finite audit of the manuscript; Python standard library only.

Run from the repository root:
    python artifacts/proof_audit_20260916/verify_formula.py

This is a finite regression check, not a proof for arbitrary parameters.
The exhaustive check enumerates perfect matchings directly from the graph,
without using the manuscript cycle classification to prune its search.
"""

import hashlib
import json
from pathlib import Path
import platform
import sys
import time


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def build(a, b):
    n = 2 * (a + b) + 4
    edges = []
    ids = {}
    for name, length, offset in (("A", a, 0), ("B", b, 2 * (a + 1))):
        for p in range(length + 1):
            ids[name, "r", p] = len(edges)
            edges.append((offset + 2 * p, offset + 2 * p + 1))
        for i in range(length):
            for side in (0, 1):
                ids[name, "l", i, side] = len(edges)
                edges.append((offset + 2 * i + side, offset + 2 * (i + 1) + side))
    off = 2 * (a + 1)
    for k, edge in enumerate(((0, off), (1, off + 2 * b),
                              (2 * a, off + 1), (2 * a + 1, off + 2 * b + 1))):
        ids["C", k] = len(edges)
        edges.append(edge)
    return n, edges, ids


def connected_cycle(n, edges, mask):
    adj = [[] for _ in range(n)]
    for k, (u, v) in enumerate(edges):
        if mask >> k & 1:
            adj[u].append(v)
            adj[v].append(u)
    if any(len(row) != 2 for row in adj):
        return False
    seen = {0}
    stack = [0]
    while stack:
        for v in adj[stack.pop()]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return len(seen) == n


def predicted_cycles(a, b, ids):
    def mask(keys):
        return sum(1 << ids[key] for key in set(keys))

    connectors = [("C", k) for k in range(4)]
    rails = [(name, "l", i, s) for name, m in (("A", a), ("B", b))
             for i in range(m) for s in (0, 1)]
    out = {("R",): mask(connectors + rails)}
    for i in range(a):
        for j in range(b):
            keys = connectors + [key for key in rails if key[2] != (i if key[0] == "A" else j)]
            keys += [("A", "r", i), ("A", "r", i + 1),
                     ("B", "r", j), ("B", "r", j + 1)]
            out["T", i, j] = mask(keys)
    for word in ("0011", "1100", "0101", "1010"):
        # Derive rails and rungs from endpoint equations for each exception.
        bits = list(map(int, word))
        keys = [("C", k) for k, bit in enumerate(bits) if bit]
        for name, m, left, right in (
            ("A", a, bits[:2], bits[2:]),
            ("B", b, [bits[0], bits[2]], [bits[1], bits[3]]),
        ):
            if left[0] != left[1]:
                d = left[1] - left[0]
                keys += [(name, "r", p) for p in range(m + 1)]
                keys += [(name, "l", i, 0 if d * (-1) ** i == 1 else 1) for i in range(m)]
            else:
                keys += [(name, "l", i, s) for i in range(m) for s in (0, 1)]
                keys += [(name, "r", 0 if left == [0, 0] else m)]
            require(left[0] - left[1] == right[0] - right[1], "endpoint compatibility")
        out["X", word] = mask(keys)
    return out


def exhaustive_cycles(n, edges):
    adj = [[] for _ in range(n)]
    for k, (u, v) in enumerate(edges):
        adj[u].append((v, k))
        adj[v].append((u, k))
    require(all(len(row) == 3 for row in adj), "graph is cubic")
    all_edges = (1 << len(edges)) - 1
    cycles = set()
    matchings = 0

    def visit(unmatched, chosen):
        nonlocal matchings
        if not unmatched:
            matchings += 1
            complement = all_edges ^ chosen
            if connected_cycle(n, edges, complement):
                cycles.add(complement)
            return
        low = unmatched & -unmatched
        u = low.bit_length() - 1
        for v, k in adj[u]:
            if unmatched >> v & 1:
                visit(unmatched ^ low ^ (1 << v), chosen | (1 << k))

    visit((1 << n) - 1, 0)
    return cycles, matchings


def verify(a, b, exhaustive):
    start = time.perf_counter()
    n, edges, ids = build(a, b)
    cycles = predicted_cycles(a, b, ids)
    require(len(set(cycles.values())) == a * b + 5, "distinct cycle classes")
    require(all(connected_cycle(n, edges, c) for c in cycles.values()), "valid predicted cycles")
    universe = None
    count_matchings = None
    if exhaustive:
        universe, count_matchings = exhaustive_cycles(n, edges)
        require(universe == set(cycles.values()), "complete Hamiltonian universe")

    support = lambda e, f: {key for key, c in cycles.items() if c >> ids[e] & 1 and not c >> ids[f] & 1}
    chosen_requirements = []

    def check(e, f, expected, packing=False):
        actual = support(e, f)
        require(actual == expected, f"support mismatch {a,b,e,f,expected,actual}")
        if packing:
            chosen_requirements.append((e, f, actual))

    check(("A", "r", 0), ("A", "r", 1), {("X", "0011")}, True)
    check(("A", "r", a), ("A", "r", a - 1), {("X", "1100")}, True)
    check(("A", "l", 0, 0), ("A", "l", 0, 1), {("X", "0101")}, True)
    check(("A", "l", 0, 1), ("A", "l", 0, 0), {("X", "1010")}, True)
    for j in range(b):
        check(("A", "r", 0), ("B", "l", j, j % 2), {("T", 0, j)}, True)
        check(("A", "r", a), ("B", "l", j, 1 - j % 2), {("T", a - 1, j)}, True)
    for i in range(1, a - 1):
        check(("B", "r", 0), ("A", "l", i, i % 2), {("T", i, 0)}, True)
        check(("B", "r", b), ("A", "l", i, 1 - i % 2), {("T", i, b - 1)}, True)
    for p in range(1, a):
        for j in range(b):
            for s in (0, 1):
                check(("A", "r", p), ("B", "l", j, s), {("T", p - 1, j), ("T", p, j)})
    for q in range(1, b):
        for i in range(a):
            for s in (0, 1):
                check(("B", "r", q), ("A", "l", i, s), {("T", i, q - 1), ("T", i, q)})
    for j in range(1, b - 1):
        for i in range(1, a - 2, 2):
            check(("A", "r", i + 1), ("B", "l", j, 0), {("T", i, j), ("T", i + 1, j)}, True)
    for j in range(1, b - 2, 2):
        check(("B", "r", j + 1), ("A", "l", a - 2, 0), {("T", a - 2, j), ("T", a - 2, j + 1)}, True)
    used = set()
    for _, _, supp in chosen_requirements:
        require(not used & supp, "packing supports disjoint")
        used |= supp
    require(set(cycles) - used == {("R",), ("T", a - 2, b - 2)}, "packing omitted classes")
    primal = [c for key, c in cycles.items() if key[0] == "X" or
              (key[0] == "T" and (key[1] in (0, a - 1) or key[2] in (0, b - 1) or (key[1] + key[2]) % 2))]
    expected_size = ((a + 2) * (b + 2) - 1) // 2
    require(len(primal) == len(chosen_requirements) == expected_size, "matching certificate sizes")
    signatures = [sum(1 << k for k, c in enumerate(primal) if c >> edge & 1) for edge in range(len(edges))]
    require(all(signatures[e] & ~signatures[f] for e in range(len(edges)) for f in range(len(edges)) if e != f), "all directed separations")
    # In exhaustive cases, check the lower certificate directly on the independently enumerated universe.
    if universe is not None:
        for c in universe:
            require(sum(bool(c >> ids[e] & 1 and not c >> ids[f] & 1) for e, f, _ in chosen_requirements) <= 1, "independent packing lower bound")
    return {"a": a, "b": b, "vertices": n, "cycles": len(cycles), "certificate_size": expected_size,
            "exhaustive": exhaustive, "perfect_matchings": count_matchings,
            "seconds": round(time.perf_counter() - start, 6), "status": "pass"}


def main():
    started = time.perf_counter()
    rows = []
    for a in range(3, 22, 2):
        for b in range(3, 22, 2):
            rows.append(verify(a, b, exhaustive=(a <= 11 and b <= 11)))
        print(f"Verified a={a}", flush=True)
    # Negative control: removing a compulsory exceptional cycle must destroy separation.
    _, edges, ids = build(3, 3)
    cycles = predicted_cycles(3, 3, ids)
    remaining = [c for key, c in cycles.items() if key != ("X", "0011")]
    require(not any(c >> ids["A", "r", 0] & 1 and not c >> ids["A", "r", 1] & 1 for c in remaining), "negative control")
    root = Path(__file__).resolve().parents[2]
    sources = [Path(__file__).resolve()] + [root / "paper" / "sections" / name for name in
               ("double_ladders.tex", "hamiltonian_cycles.tex", "exact_hsep.tex")]
    report = {"status": "pass", "python": sys.version, "platform": platform.platform(),
              "command": "python artifacts/proof_audit_20260916/verify_formula.py",
              "seed": None, "solver": "independent deterministic standard-library perfect-matching enumeration",
              "seconds": round(time.perf_counter() - started, 6),
              "source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
              "negative_control": "pass", "cases": rows,
              "scope": "25 exhaustive universes; 75 further construction checks conditional on general cycle classification. Finite evidence does not prove arbitrary parameters."}
    Path(__file__).with_name("results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("cases", "source_sha256")}, indent=2))


if __name__ == "__main__":
    main()
