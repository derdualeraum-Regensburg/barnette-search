"""Optional integration test requiring user-verified cubhamg syntax."""

import json
import os

import networkx as nx
import pytest

from barnette_search.cubhamg import (
    CubhamgCommandSpec,
    benchmark_cubhamg,
    inspect_cubhamg,
)


@pytest.mark.cubhamg_integration
def test_documented_real_cubhamg_invocation() -> None:
    executable = os.environ.get("CUBHAMG_EXECUTABLE")
    documentation = os.environ.get("CUBHAMG_DOCUMENTATION_REFERENCE")
    arguments_json = os.environ.get("CUBHAMG_GRAPH_ARGUMENTS_JSON")
    if not executable or not documentation or not arguments_json:
        pytest.skip(
            "set CUBHAMG_EXECUTABLE, CUBHAMG_DOCUMENTATION_REFERENCE, and "
            "CUBHAMG_GRAPH_ARGUMENTS_JSON after verifying official syntax"
        )
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise ValueError("CUBHAMG_GRAPH_ARGUMENTS_JSON must be a JSON string list")
    specification = CubhamgCommandSpec(
        documentation_reference=documentation,
        graph_arguments=tuple(arguments),
        version_arguments=tuple(
            json.loads(os.environ.get("CUBHAMG_VERSION_ARGUMENTS_JSON", '["--help"]'))
        ),
        hamiltonian_pattern=os.environ.get("CUBHAMG_HAMILTONIAN_PATTERN", ""),
        non_hamiltonian_pattern=os.environ.get(
            "CUBHAMG_NON_HAMILTONIAN_PATTERN", ""
        ),
    )
    identity = inspect_cubhamg(executable, specification)
    result = benchmark_cubhamg(nx.cubical_graph(), identity, specification)
    assert len(identity.sha256) == 64
    assert result.executable_sha256 == identity.sha256
