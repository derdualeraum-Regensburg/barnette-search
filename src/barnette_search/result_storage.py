"""Deterministic JSONL, gzip, and resumable-checkpoint utilities."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
import gzip
import json
import os
from pathlib import Path
from typing import Any, TextIO


def _open_text(path: Path, mode: str) -> TextIO:
    if ".gz" in path.suffixes:
        return gzip.open(path, mode + "t", encoding="utf-8", newline="\n")
    return path.open(mode, encoding="utf-8", newline="\n")


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Read plain or gzip JSONL transparently."""
    with _open_text(path, "r") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"malformed JSONL at {path}:{line_number}"
                ) from error
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record at {path}:{line_number} is not an object")
            yield value


def write_jsonl_atomic(
    path: Path, records: Iterable[dict[str, Any]]
) -> None:
    """Write deterministic JSONL and atomically publish the completed file."""
    temporary = path.with_name(path.name + ".tmp")
    with _open_text(temporary, "w") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True, default=repr) + "\n")
        output.flush()
        if ".gz" not in path.suffixes:
            os.fsync(output.fileno())
    os.replace(temporary, path)


def append_checkpoint(path: Path, record: dict[str, Any]) -> None:
    """Append one newline-terminated completed record and force it to disk."""
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(record, sort_keys=True, default=repr) + "\n")
        output.flush()
        os.fsync(output.fileno())


def read_checkpoint(path: Path) -> tuple[dict[str, Any], ...]:
    """Read complete checkpoint lines, ignoring only a truncated final line."""
    if not path.exists():
        return ()
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1 and not line.endswith(("\n", "\r")):
                break
            raise ValueError(f"malformed checkpoint record {index + 1} in {path}")
        if not isinstance(value, dict):
            raise ValueError(f"checkpoint record {index + 1} is not an object")
        records.append(value)
    return tuple(records)
