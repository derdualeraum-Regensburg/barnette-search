"""Reconstruction orchestration must not require the lost order-36 package."""
import importlib.util
import json
from pathlib import Path
import pytest


def driver():
    path = Path(__file__).parents[1] / "tools" / "rebuild_lost_certificates.py"
    spec = importlib.util.spec_from_file_location("rebuild_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_order36_is_regenerated_instead_of_imported(tmp_path, monkeypatch):
    from barnette_search import barnie_sequence
    calls = []
    monkeypatch.setattr(barnie_sequence, "process_exact_order", lambda *args: calls.append(args))
    monkeypatch.setattr(barnie_sequence, "import_order36", lambda *args: (_ for _ in ()).throw(AssertionError("lost source imported")))
    plantri = tmp_path / "plantri.exe"
    driver().produce_order(tmp_path, 36, plantri, 2)
    assert calls == [(tmp_path / "barnie-sequence", 36, plantri, 2, True)]


def test_ladder_input_retains_graph_identity_and_is_only_an_upper_bound(tmp_path):
    from io import BytesIO
    from barnette_search.planar_code import iter_planar_code, canonical_graph_hash
    driver().prepare_ladder(tmp_path, 3, 3)
    directory = tmp_path / "ladder-inputs" / "D_3_3"
    record = json.loads((directory / "input.json").read_text())
    [embedded] = iter_planar_code(BytesIO((directory / "graph.planar_code").read_bytes()), require_header=True)
    assert len(embedded.graph) == record["order"] == 16
    assert canonical_graph_hash(embedded) == record["canonical_graph_hash"]
    assert record["greedy_upper_bound"] >= 12
    assert "exact_hsep" not in record


def test_resume_rejects_changed_plan(tmp_path):
    module = driver()
    plan = {"orders": [8, 36], "workers": 2}
    module.check_configuration(tmp_path, plan, False)
    with pytest.raises(FileExistsError):
        module.check_configuration(tmp_path, plan, False)
    module.check_configuration(tmp_path, plan, True)
    with pytest.raises(ValueError):
        module.check_configuration(tmp_path, {**plan, "orders": [8]}, True)
