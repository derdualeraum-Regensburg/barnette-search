"""Tests for the documentation-gated optional cubhamg wrapper."""

from pathlib import Path
import sys

import networkx as nx
import pytest

from barnette_search.cubhamg import (
    CubhamgCommandSpec,
    benchmark_cubhamg,
    inspect_cubhamg,
)


def test_documentation_reference_and_input_placeholder_are_required() -> None:
    with pytest.raises(ValueError, match="documentation"):
        inspect_cubhamg(sys.executable, CubhamgCommandSpec("", ("{input}",)))
    executable = inspect_cubhamg(
        sys.executable,
        CubhamgCommandSpec("controlled test fixture", ("{input}",), ("--version",)),
    )
    with pytest.raises(ValueError, match="placeholder"):
        benchmark_cubhamg(
            nx.cycle_graph(4),
            executable,
            CubhamgCommandSpec("controlled test fixture", ("no-input",)),
        )


def test_stdout_and_stderr_are_separate_and_ambiguity_is_not_proof() -> None:
    specification = CubhamgCommandSpec(
        documentation_reference="controlled test fixture",
        version_arguments=("--version",),
        graph_arguments=(
            "-c",
            "import sys; print('unknown'); print('diagnostic', file=sys.stderr)",
            "{input}",
        ),
        hamiltonian_pattern="Hamiltonian: yes",
        non_hamiltonian_pattern="Hamiltonian: no",
    )
    executable = inspect_cubhamg(sys.executable, specification)
    result = benchmark_cubhamg(nx.cycle_graph(4), executable, specification)
    assert result.hamiltonian is None
    assert "unknown" in result.stdout
    assert "diagnostic" in result.stderr
    assert "no mathematical conclusion" in result.interpretation
