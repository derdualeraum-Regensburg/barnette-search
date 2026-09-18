from hashlib import sha256
import importlib.util
from pathlib import Path

import pytest


def load_verifier():
    path = Path(__file__).parents[1] / "tools" / "verify_recalculated_release.py"
    spec = importlib.util.spec_from_file_location("recalculated_release_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_manifest_requires_exact_inventory(tmp_path):
    verifier = load_verifier()
    data = tmp_path / "certificate.txt"
    data.write_bytes(b"certificate")
    (tmp_path / "SHA256SUMS.txt").write_text(
        sha256(data.read_bytes()).hexdigest() + "  certificate.txt\n", encoding="ascii"
    )
    assert verifier.verify_release_manifest(tmp_path) == 1
    (tmp_path / "unlisted.txt").write_text("extra")
    with pytest.raises(ValueError, match="inventory mismatch"):
        verifier.verify_release_manifest(tmp_path)


def test_release_manifest_rejects_escape(tmp_path):
    verifier = load_verifier()
    (tmp_path / "SHA256SUMS.txt").write_text("0" * 64 + "  ../outside\n", encoding="ascii")
    with pytest.raises(ValueError, match="escapes"):
        verifier.verify_release_manifest(tmp_path)
