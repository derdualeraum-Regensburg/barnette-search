from pathlib import Path

from barnette_search.paths import results_root


def test_default_results_root_is_relative(monkeypatch):
    monkeypatch.delenv("BARNETTE_RESULTS_ROOT", raising=False)
    assert results_root() == Path("results")


def test_explicit_results_root_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv("BARNETTE_RESULTS_ROOT", str(tmp_path))
    assert results_root() == tmp_path


def test_empty_results_root_uses_default(monkeypatch):
    monkeypatch.setenv("BARNETTE_RESULTS_ROOT", "")
    assert results_root() == Path("results")
