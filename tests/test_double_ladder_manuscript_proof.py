"""Independent finite checks for the revised manuscript classification proof."""

from itertools import product
from pathlib import Path
import runpy

import pytest


AUDIT = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "artifacts" / "proof_audit_20260916" / "verify_formula.py")
)


def ladder_degree_solutions(length, left, right):
    """Enumerate local degree-two assignments without using the difference rule."""
    solutions = []

    def extend(rails, rungs):
        if len(rails) == length:
            end = tuple(2 - rails[-1][s] - right[s] for s in (0, 1))
            if end[0] == end[1] and end[0] in (0, 1):
                solutions.append((tuple(rails), tuple(rungs) + (end[0],)))
            return
        for rung in (0, 1):
            following = tuple(2 - rails[-1][s] - rung for s in (0, 1))
            if all(x in (0, 1) for x in following):
                extend(rails + [following], rungs + [rung])

    for rung in (0, 1):
        first = tuple(2 - left[s] - rung for s in (0, 1))
        if all(x in (0, 1) for x in first):
            extend([first], [rung])
    return solutions


@pytest.mark.parametrize("length", range(1, 9))
def test_endpoint_recurrence_against_local_degree_enumeration(length):
    for bits in product((0, 1), repeat=4):
        left, right = bits[:2], bits[2:]
        for rails, _ in ladder_degree_solutions(length, left, right):
            differences = [x - y for x, y in rails]
            assert differences[0] == left[1] - left[0]
            assert differences[-1] == right[1] - right[0]
            assert all(differences[t] == (-1) ** t * differences[0] for t in range(length))


@pytest.mark.parametrize("length", (3, 5, 7, 9))
@pytest.mark.parametrize("bits", ((1, 0, 0, 1), (0, 1, 1, 0)))
def test_diagonal_connector_words_are_degree_infeasible_for_odd_ladders(length, bits):
    assert not ladder_degree_solutions(length, bits[:2], bits[2:])
    # Even lengths provide a positive control for the role of parity.
    assert ladder_degree_solutions(length - 1, bits[:2], bits[2:])


def test_zero_differences_do_not_fix_the_rungs():
    solutions = ladder_degree_solutions(3, (1, 1), (1, 1))
    assert len({rungs for _, rungs in solutions}) > 1
    assert all(x == y for rails, _ in solutions for x, y in rails)


@pytest.mark.parametrize("a,b", list(product(range(3, 22, 2), repeat=2)))
def test_classification_and_matching_certificates(a, b):
    # For 25 pairs this enumerates every perfect matching, retaining exactly
    # the connected complements, and verifies both optimality certificates.
    # The other 75 pairs check constructions without claiming completeness.
    result = AUDIT["verify"](a, b, exhaustive=(a <= 11 and b <= 11))
    assert result["status"] == "pass"


def test_removing_a_forced_exception_breaks_separation():
    _, _, ids = AUDIT["build"](3, 3)
    cycles = AUDIT["predicted_cycles"](3, 3, ids)
    e, f = ids["A", "r", 0], ids["A", "r", 1]
    witnesses = {key for key, cycle in cycles.items() if cycle >> e & 1 and not cycle >> f & 1}
    assert witnesses == {("X", "0011")}
