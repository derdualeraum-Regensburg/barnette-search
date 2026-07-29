"""Conservative optional wrapper for a user-documented cubhamg executable.

No command syntax is assumed here because the repository contains no verified
official cubhamg guide. Callers must provide a command specification tied to
documentation they have reviewed; ambiguous output remains ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
import tempfile
from time import perf_counter

import networkx as nx


@dataclass(frozen=True, slots=True)
class CubhamgCommandSpec:
    """User-supplied syntax verified against identified documentation."""

    documentation_reference: str
    graph_arguments: tuple[str, ...]
    version_arguments: tuple[str, ...] = ("--help",)
    hamiltonian_pattern: str = ""
    non_hamiltonian_pattern: str = ""


@dataclass(frozen=True, slots=True)
class CubhamgExecutable:
    """Executable identity and captured version/help output."""

    path: Path
    sha256: str
    version_stdout: str
    version_stderr: str
    documentation_reference: str


@dataclass(frozen=True, slots=True)
class CubhamgResult:
    """One optional benchmark result; ``hamiltonian=None`` is inconclusive."""

    hamiltonian: bool | None
    returncode: int
    timed_out: bool
    wall_time_seconds: float
    command: tuple[str, ...]
    stdout: str
    stderr: str
    executable_sha256: str
    interpretation: str


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_cubhamg(
    executable: str | os.PathLike[str],
    specification: CubhamgCommandSpec,
    *,
    timeout_seconds: float = 10.0,
) -> CubhamgExecutable:
    """Hash an explicit executable and capture its documented help/version call."""
    if not specification.documentation_reference.strip():
        raise ValueError("a verified documentation reference is required")
    path = Path(executable).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"cubhamg executable does not exist: {path}")
    completed = subprocess.run(
        (str(path), *specification.version_arguments),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    return CubhamgExecutable(
        path=path,
        sha256=_hash_file(path),
        version_stdout=completed.stdout.decode("utf-8", "replace"),
        version_stderr=completed.stderr.decode("utf-8", "replace"),
        documentation_reference=specification.documentation_reference,
    )


def benchmark_cubhamg(
    graph: nx.Graph,
    executable: CubhamgExecutable,
    specification: CubhamgCommandSpec,
    *,
    timeout_seconds: float = 60.0,
) -> CubhamgResult:
    """Run a documented command on one graph without treating ambiguity as proof."""
    if graph.is_directed() or graph.is_multigraph() or nx.number_of_selfloops(graph):
        raise ValueError("cubhamg benchmark input must be an undirected simple graph")
    if not any("{input}" in argument for argument in specification.graph_arguments):
        raise ValueError("graph_arguments must contain an {input} placeholder")
    with tempfile.TemporaryDirectory(prefix="barnette-cubhamg-") as temporary:
        input_path = Path(temporary) / "graph.g6"
        input_path.write_bytes(nx.to_graph6_bytes(graph, header=False))
        arguments = tuple(
            argument.replace("{input}", str(input_path))
            for argument in specification.graph_arguments
        )
        command = (str(executable.path), *arguments)
        started = perf_counter()
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return CubhamgResult(
                hamiltonian=None,
                returncode=-1,
                timed_out=True,
                wall_time_seconds=perf_counter() - started,
                command=command,
                stdout=(error.stdout or b"").decode("utf-8", "replace"),
                stderr=(error.stderr or b"").decode("utf-8", "replace"),
                executable_sha256=executable.sha256,
                interpretation="timeout; no mathematical conclusion",
            )
        elapsed = perf_counter() - started
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
        combined = stdout + "\n" + stderr
        positive = bool(
            specification.hamiltonian_pattern
            and re.search(specification.hamiltonian_pattern, combined)
        )
        negative = bool(
            specification.non_hamiltonian_pattern
            and re.search(specification.non_hamiltonian_pattern, combined)
        )
        if positive == negative:
            verdict = None
            interpretation = "ambiguous output; no mathematical conclusion"
        else:
            verdict = positive
            interpretation = (
                "binary benchmark classification under caller-supplied syntax; "
                "not independently treated as a proof"
            )
        return CubhamgResult(
            hamiltonian=verdict,
            returncode=completed.returncode,
            timed_out=False,
            wall_time_seconds=elapsed,
            command=command,
            stdout=stdout,
            stderr=stderr,
            executable_sha256=executable.sha256,
            interpretation=interpretation,
        )
