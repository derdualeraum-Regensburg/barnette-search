"""Tests for the single-graph exact hsep benchmark wrapper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools" / "benchmark_hsep_single.py"
SPEC = importlib.util.spec_from_file_location("benchmark_hsep_single", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.mark.skipif(sys.platform != "win32", reason="legacy benchmark telemetry uses Windows peak_wset; core verifiers run on all platforms")
def test_exact_cube_bundle_round_trips_through_independent_verifier(tmp_path: Path) -> None:
    planar_code = ROOT / "tests" / "fixtures" / "cube.planar_code"
    output = tmp_path / "cube"
    status = benchmark.main(
        [
            "--planar-code",
            str(planar_code),
            "--expected-hash",
            "204b8679f3d0425a4964c1b6574ada41a4aecc186316477cf33fa20be1b301ee",
            "--generation-index",
            "0",
            "--existing-greedy-upper-bound",
            "6",
            "--expected-order",
            "8",
            "--output",
            str(output),
        ]
    )
    assert status == 0
    result = json.loads((output / "benchmark_result.json").read_text(encoding="utf-8"))
    verification = json.loads(
        (output / "independent_verification.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "EXACT_VERIFIED"
    assert result["exact_hsep"] == 6
    assert result["hsep_minus_one_result"] in {
        "UNSAT",
        "EXCLUDED_BY_MATCHING_PACKING",
    }
    assert verification["verified"] is True
    assert (output / "SHA256SUMS.txt").is_file()
