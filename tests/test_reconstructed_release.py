from hashlib import sha256
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


SPEC = importlib.util.spec_from_file_location(
    "release_verifier", Path(__file__).parents[1] / "tools" / "verify_reconstructed_release.py"
)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def test_manifest_verification_detects_modified_data(tmp_path):
    (tmp_path / "data.txt").write_bytes(b"certificate")
    (tmp_path / "SHA256SUMS.txt").write_text(sha256(b"certificate").hexdigest() + "  data.txt\n")
    assert VERIFIER.verify_hashes(tmp_path) == 1
    (tmp_path / "data.txt").write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        VERIFIER.verify_hashes(tmp_path)


def test_manifest_rejects_parent_path(tmp_path):
    (tmp_path / "SHA256SUMS.txt").write_text("0" * 64 + "  ../outside.txt\n")
    with pytest.raises(ValueError, match="escapes"):
        VERIFIER.verify_hashes(tmp_path)


def test_manifest_rejects_duplicate_entries(tmp_path):
    (tmp_path / "data.txt").write_bytes(b"ok")
    entry = sha256(b"ok").hexdigest() + "  data.txt\n"
    (tmp_path / "SHA256SUMS.txt").write_text(entry * 2)
    with pytest.raises(ValueError, match="repeated"):
        VERIFIER.verify_hashes(tmp_path)


def test_manifest_rejects_empty_inventory(tmp_path):
    (tmp_path / "SHA256SUMS.txt").write_text("")
    with pytest.raises(ValueError, match="empty"):
        VERIFIER.verify_hashes(tmp_path)


def test_worker_limit_is_enforced_by_cli(tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(VERIFIER.__file__)), str(tmp_path), "--workers", "5"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
