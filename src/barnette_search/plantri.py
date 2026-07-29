"""Safe subprocess integration for the external plantri generator."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Iterator, Sequence

from .planar_code import EmbeddedPlanarGraph, iter_planar_code


REQUIRED_PLANTRI_VERSION = "5.8"
_VERSION_PATTERN = re.compile(r"Plantri version\s+(\d+(?:\.\d+)*)", re.IGNORECASE)


class PlantriError(RuntimeError):
    """Base class for plantri integration errors."""


class PlantriNotFoundError(PlantriError):
    """Raised when no external executable can be located."""


class PlantriVersionError(PlantriError):
    """Raised when plantri does not report the required version."""


class PlantriProcessError(PlantriError):
    """Raised when a generation subprocess exits unsuccessfully."""


@dataclass(frozen=True, slots=True)
class PlantriVersion:
    """Identity information captured from an external plantri executable."""

    executable: Path
    version: str
    executable_sha256: str
    version_output: str


def locate_plantri(executable: str | os.PathLike[str] | None = None) -> Path:
    """Locate plantri without downloading, building, or executing anything."""
    candidate = executable or os.environ.get("PLANTRI_EXECUTABLE")
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()
        resolved = shutil.which(str(candidate))
        if resolved:
            return Path(resolved).resolve()
        raise PlantriNotFoundError(f"plantri executable does not exist: {candidate}")
    resolved = shutil.which("plantri") or shutil.which("plantri.exe")
    if resolved:
        return Path(resolved).resolve()
    raise PlantriNotFoundError(
        "plantri was not found; pass --plantri or set PLANTRI_EXECUTABLE"
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_plantri_version(
    executable: str | os.PathLike[str], *, allow_other_version: bool = False
) -> PlantriVersion:
    """Execute ``plantri --help`` and require version 5.8 by default."""
    path = locate_plantri(executable)
    completed = subprocess.run(
        [str(path), "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=15,
    )
    output = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    match = _VERSION_PATTERN.search(output)
    if match is None:
        raise PlantriVersionError(
            f"could not detect plantri version from {path}: {output.strip()}"
        )
    version = match.group(1)
    if version != REQUIRED_PLANTRI_VERSION and not allow_other_version:
        raise PlantriVersionError(
            f"plantri {REQUIRED_PLANTRI_VERSION} is required; {path} reports {version}"
        )
    return PlantriVersion(
        executable=path,
        version=version,
        executable_sha256=_file_sha256(path),
        version_output=output.strip(),
    )


def dual_triangulation_order(barnette_vertices: int) -> int:
    """Return triangulation order ``T`` from dual cubic order ``N=2T-4``."""
    if barnette_vertices <= 0:
        raise ValueError("Barnette vertex count must be positive")
    if barnette_vertices % 2:
        raise ValueError("Barnette vertex count must be even")
    return barnette_vertices // 2 + 2


def barnette_plantri_command(
    executable: str | os.PathLike[str], barnette_vertices: int
) -> tuple[str, ...]:
    """Construct the guide-verified Eulerian-triangulation dual command."""
    triangulation_vertices = dual_triangulation_order(barnette_vertices)
    return (
        str(Path(executable)),
        "-b",
        "-c3",
        "-d",
        str(triangulation_vertices),
        "-",
    )


class PlantriGraphStream:
    """Context-managed, one-record-at-a-time plantri output stream."""

    def __init__(self, command: Sequence[str]) -> None:
        self.command = tuple(map(str, command))
        self.stderr_text = ""
        self.returncode: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._finished = False

    def __enter__(self) -> "PlantriGraphStream":
        if self._process is not None:
            raise RuntimeError("plantri stream cannot be entered twice")
        self._process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert self._process.stderr is not None

        def drain_stderr() -> None:
            for chunk in iter(lambda: self._process.stderr.read(8192), b""):
                self._stderr.extend(chunk)

        self._stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        self._stderr_thread.start()
        return self

    def __iter__(self) -> Iterator[EmbeddedPlanarGraph]:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("use PlantriGraphStream as a context manager")
        try:
            yield from iter_planar_code(self._process.stdout, require_header=True)
            self._finish()
        except BaseException:
            self.close()
            raise

    def _finish(self) -> None:
        if self._finished:
            return
        assert self._process is not None
        self.returncode = self._process.wait()
        if self._stderr_thread is not None:
            self._stderr_thread.join()
        self.stderr_text = self._stderr.decode("utf-8", "replace")
        self._finished = True
        if self.returncode != 0:
            raise PlantriProcessError(
                f"plantri exited with status {self.returncode}: "
                f"{self.stderr_text.strip()}"
            )

    def close(self) -> None:
        """Terminate an unfinished child and reap it without masking errors."""
        if self._finished or self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self.returncode = self._process.returncode
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=5)
        self.stderr_text = self._stderr.decode("utf-8", "replace")
        self._finished = True

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        # Exhausting the iterator already called _finish(). If a caller stops
        # early, terminate instead of waiting on a child blocked by a full
        # stdout pipe.
        self.close()


def stream_barnette_graphs(
    version: PlantriVersion, barnette_vertices: int
) -> PlantriGraphStream:
    """Create a stream for simple cubic bipartite 3-connected plane graphs."""
    return PlantriGraphStream(
        barnette_plantri_command(version.executable, barnette_vertices)
    )
