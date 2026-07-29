"""Compare reference backtracking and SAT runtimes without asserting timing."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Hashable
from statistics import median
from time import perf_counter

import networkx as nx

from barnette_search import (
    find_hamiltonian_cycle,
    find_hamiltonian_cycle_sat,
    solve_hamiltonian_cycle_sat,
    verify_hamiltonian_cycle,
)

CycleFinder = Callable[[nx.Graph], tuple[Hashable, ...] | None]


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _measure(finder: CycleFinder, graph: nx.Graph, repeats: int) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        cycle = finder(graph)
        samples.append(perf_counter() - started)
        if cycle is not None and not verify_hamiltonian_cycle(graph, cycle):
            raise RuntimeError("benchmark solver returned an invalid certificate")
    return median(samples)


def _benchmark_graphs() -> list[tuple[str, nx.Graph]]:
    graphs = [
        ("cube", nx.cubical_graph()),
        ("k33", nx.complete_bipartite_graph(3, 3)),
        ("petersen", nx.petersen_graph()),
        ("bridge", nx.barbell_graph(3, 0)),
    ]
    random_cases = ((8, 7), (9, 1), (10, 7), (11, 7), (12, 1))
    graphs.extend(
        (
            f"gnp-n{number_of_vertices}-s{seed}",
            nx.gnp_random_graph(number_of_vertices, 0.32, seed=seed),
        )
        for number_of_vertices, seed in random_cases
    )
    return graphs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=_positive_integer, default=3)
    arguments = parser.parse_args()

    print(
        "graph vertices edges hamiltonian backtracking_ms sat_ms "
        "sat_iterations sat_constraints"
    )
    for name, graph in _benchmark_graphs():
        backtracking_cycle = find_hamiltonian_cycle(graph)
        sat_result = solve_hamiltonian_cycle_sat(graph)
        if (backtracking_cycle is not None) != sat_result.satisfiable:
            raise RuntimeError(f"solver disagreement for {name}")

        backtracking_seconds = _measure(
            find_hamiltonian_cycle, graph, arguments.repeats
        )
        sat_seconds = _measure(
            find_hamiltonian_cycle_sat, graph, arguments.repeats
        )
        print(
            name,
            graph.number_of_nodes(),
            graph.number_of_edges(),
            sat_result.satisfiable,
            f"{1000 * backtracking_seconds:.3f}",
            f"{1000 * sat_seconds:.3f}",
            sat_result.number_of_subtour_iterations,
            sat_result.number_of_subtour_constraints,
        )


if __name__ == "__main__":
    main()

