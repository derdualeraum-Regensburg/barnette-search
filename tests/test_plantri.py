"""Unit tests for plantri command construction and process metadata."""

from pathlib import Path
import subprocess
import sys

import pytest

from barnette_search.plantri import (
    PlantriGraphStream,
    PlantriProcessError,
    PlantriVersionError,
    barnette_plantri_command,
    detect_plantri_version,
    dual_triangulation_order,
)


def test_barnette_dual_order_and_exact_command(tmp_path: Path) -> None:
    executable = tmp_path / "plantri"
    assert dual_triangulation_order(24) == 14
    assert barnette_plantri_command(executable, 24) == (
        str(executable),
        "-b",
        "-c3",
        "-d",
        "14",
        "-",
    )


@pytest.mark.parametrize("order", [-2, 0, 7, 9])
def test_invalid_barnette_orders_are_rejected(order: int) -> None:
    with pytest.raises(ValueError):
        dual_triangulation_order(order)


def test_detect_version_reads_stderr_and_hashes_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "plantri"
    executable.write_bytes(b"fixed executable contents")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[str(executable), "--help"],
            returncode=0,
            stdout=b"",
            stderr=b"Plantri version 5.8 - March 4, 2026\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = detect_plantri_version(executable)
    assert result.version == "5.8"
    assert len(result.executable_sha256) == 64


def test_other_version_requires_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "plantri"
    executable.write_bytes(b"x")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"Plantri version 5.7\n", stderr=b""
        ),
    )
    with pytest.raises(PlantriVersionError, match="5.8 is required"):
        detect_plantri_version(executable)
    assert detect_plantri_version(executable, allow_other_version=True).version == "5.7"


def test_generation_error_reports_separately_captured_stderr() -> None:
    script = (
        "import sys; "
        "sys.stdout.buffer.write(b'>>planar_code<<'); "
        "sys.stdout.buffer.flush(); "
        "sys.stderr.write('generation failed\\n'); "
        "raise SystemExit(3)"
    )
    with pytest.raises(PlantriProcessError, match="generation failed"):
        with PlantriGraphStream((sys.executable, "-c", script)) as stream:
            list(stream)
