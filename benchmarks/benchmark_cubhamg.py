"""Optional documented cubhamg-versus-reference benchmark; not a proof tool."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
from time import perf_counter

from barnette_search.cubhamg import (
    CubhamgCommandSpec,
    benchmark_cubhamg,
    inspect_cubhamg,
)
from barnette_search.graph_io import graph_from_graph6_file
from barnette_search.hamiltonian_sat import solve_hamiltonian_cycle_sat


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--documentation-reference", required=True)
    parser.add_argument("--version-arg", action="append", default=[])
    parser.add_argument("--graph-arg", action="append", required=True)
    parser.add_argument("--hamiltonian-pattern", required=True)
    parser.add_argument("--non-hamiltonian-pattern", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("graphs", nargs="+", type=Path)
    arguments = parser.parse_args()
    specification = CubhamgCommandSpec(
        documentation_reference=arguments.documentation_reference,
        graph_arguments=tuple(arguments.graph_arg),
        version_arguments=tuple(arguments.version_arg or ("--help",)),
        hamiltonian_pattern=arguments.hamiltonian_pattern,
        non_hamiltonian_pattern=arguments.non_hamiltonian_pattern,
    )
    executable = inspect_cubhamg(arguments.executable, specification)
    records = []
    for path in arguments.graphs:
        graph = graph_from_graph6_file(path)
        reference_started = perf_counter()
        reference = solve_hamiltonian_cycle_sat(graph)
        reference_time = perf_counter() - reference_started
        external = benchmark_cubhamg(
            graph,
            executable,
            specification,
            timeout_seconds=arguments.timeout,
        )
        records.append(
            {
                "graph_file": str(path),
                "vertices": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
                "reference_sat_hamiltonian": reference.satisfiable,
                "reference_sat_wall_time_seconds": reference_time,
                "cubhamg": asdict(external),
                "binary_results_agree": (
                    external.hamiltonian == reference.satisfiable
                    if external.hamiltonian is not None
                    else None
                ),
            }
        )
    report = {
        "warning": (
            "single-machine benchmark only; timings do not establish "
            "algorithmic superiority and external output is not treated as proof"
        ),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "executable": asdict(executable),
        "specification": asdict(specification),
        "records": records,
    }
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
