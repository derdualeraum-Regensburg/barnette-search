"""Optional smoke test against an explicitly configured real plantri."""

import os

import pytest

from barnette_search.plantri import (
    detect_plantri_version,
    locate_plantri,
    stream_barnette_graphs,
)
from barnette_search.validation import validate_barnette_graph


@pytest.mark.plantri_integration
def test_real_plantri_generates_the_unique_eight_vertex_graph() -> None:
    configured = os.environ.get("PLANTRI_EXECUTABLE")
    if not configured:
        pytest.skip("set PLANTRI_EXECUTABLE to run real plantri integration tests")
    version = detect_plantri_version(locate_plantri(configured))
    with stream_barnette_graphs(version, 8) as stream:
        graphs = list(stream)
    assert len(graphs) == 1
    assert validate_barnette_graph(graphs[0].graph).valid
