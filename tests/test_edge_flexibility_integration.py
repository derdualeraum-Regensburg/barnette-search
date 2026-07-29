"""Optional exhaustive cross-check over real plantri graphs through order 24."""

import os

import pytest

from barnette_search.edge_flexibility import analyze_same_face_edge_flexibility
from barnette_search.enumeration import REFERENCE_COUNTS
from barnette_search.plantri import (
    detect_plantri_version,
    locate_plantri,
    stream_barnette_graphs,
)


@pytest.mark.plantri_integration
def test_sat_and_backtracking_agree_through_24_vertices(tmp_path) -> None:
    configured = os.environ.get("PLANTRI_EXECUTABLE")
    if not configured:
        pytest.skip("set PLANTRI_EXECUTABLE to run real plantri integration tests")
    version = detect_plantri_version(locate_plantri(configured))
    for order in range(8, 25, 2):
        count = 0
        with stream_barnette_graphs(version, order) as stream:
            for embedded in stream:
                result = analyze_same_face_edge_flexibility(
                    embedded.graph,
                    embedded,
                    cross_check_backtracking=True,
                    candidate_output_directory=tmp_path / "candidates",
                )
                assert result.complete_property_holds
                assert result.backtracking_queries == (
                    result.total_ordered_same_face_edge_pairs
                )
                assert result.backtracking_agreements == result.backtracking_queries
                count += 1
        assert count == REFERENCE_COUNTS[order]
