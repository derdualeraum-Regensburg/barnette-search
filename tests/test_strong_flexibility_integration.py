"""Optional real-plantri cross-validation for both stronger properties."""

import os
from pathlib import Path

import pytest

from barnette_search.all_edge_flexibility import analyze_all_edge_pair_flexibility
from barnette_search.flexibility_enumeration import (
    REFERENCE_COUNTS,
    run_strong_flexibility_enumeration,
)
from barnette_search.plantri import (
    detect_plantri_version,
    locate_plantri,
    stream_barnette_graphs,
)
from barnette_search.result_storage import read_jsonl
from barnette_search.three_edge_path_flexibility import (
    analyze_three_edge_path_flexibility,
)


@pytest.mark.plantri_integration
def test_both_strong_properties_cross_validate_through_24(tmp_path: Path) -> None:
    configured = os.environ.get("PLANTRI_EXECUTABLE")
    if not configured:
        pytest.skip("set PLANTRI_EXECUTABLE to run real plantri integration tests")
    version = detect_plantri_version(locate_plantri(configured))
    for order in range(8, 25, 2):
        count = 0
        with stream_barnette_graphs(version, order) as stream:
            for embedded in stream:
                for result in (
                    analyze_all_edge_pair_flexibility(
                        embedded.graph,
                        cross_check_backtracking=True,
                        candidate_output_directory=tmp_path / "candidates",
                    ),
                    analyze_three_edge_path_flexibility(
                        embedded.graph,
                        cross_check_backtracking=True,
                        candidate_output_directory=tmp_path / "candidates",
                    ),
                ):
                    assert result.property_satisfied
                    assert result.backtracking_queries == result.backtracking_agreements
                count += 1
        assert count == REFERENCE_COUNTS[order]


@pytest.mark.plantri_integration
def test_one_and_two_workers_preserve_output_order(tmp_path: Path) -> None:
    configured = os.environ.get("PLANTRI_EXECUTABLE")
    if not configured:
        pytest.skip("set PLANTRI_EXECUTABLE to run real plantri integration tests")
    outputs = []
    for workers in (1, 2):
        directory = tmp_path / f"workers-{workers}"
        run_strong_flexibility_enumeration(
            [16],
            executable=configured,
            output_directory=directory,
            test_all_edge_pairs=True,
            test_three_edge_paths=True,
            output_detail="summary",
            retain_top_k=1,
            compress_results=True,
            resume=False,
            workers=workers,
            overwrite=True,
        )
        records = list(
            read_jsonl(
                directory / "barnette_16.strong_flexibility.jsonl.gz"
            )
        )
        outputs.append(
            [
                (record["generation_index"], record["canonical_graph_hash"])
                for record in records
            ]
        )
    assert outputs[0] == outputs[1]
