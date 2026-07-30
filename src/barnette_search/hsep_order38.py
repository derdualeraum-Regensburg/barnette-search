"""Reproducible Phase 1--2 audit and candidate selection for order-38 hsep work.

This module deliberately does not compute ``hsep``.  The strong-flexibility
witness counts consumed here come from a deterministic greedy cover and are
selection heuristics only.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter
from collections.abc import Iterable, Sequence
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from importlib import metadata
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from time import perf_counter
from typing import Any, BinaryIO

import networkx as nx

from .planar_code import (
    EmbeddedPlanarGraph,
    canonical_graph_hash,
    encode_planar_code,
    iter_planar_code,
)
from .plantri import (
    PlantriVersion,
    barnette_plantri_command,
    detect_plantri_version,
    stream_barnette_graphs,
)
from .validation import validate_barnette_graph


EXPECTED_ORDER = 38
EXPECTED_RECORD_COUNT = 50_116
MAX_WORKERS = 4
SCHEMA_VERSION = "hsep-order38-phase12-v1"
SELECTION_ALGORITHM_VERSION = "diverse-candidate-pool-v1"

TOP_LEVEL_FIELDS = frozenset(
    {
        "generation_index",
        "requested_vertex_count",
        "canonical_graph_hash",
        "edge_count",
        "face_size_multiset",
        "plantri_version",
        "plantri_executable_sha256",
        "plantri_command",
        "all_edge_pairs",
        "three_edge_paths",
    }
)

COMMON_ANALYSIS_FIELDS = frozenset(
    {
        "graph_order",
        "edge_count",
        "canonical_graph_hash",
        "face_size_multiset",
        "number_of_constrained_sat_calls",
        "number_of_witness_cycles",
        "witness_cover_ratio",
        "total_sat_wall_time_seconds",
        "median_query_time_seconds",
        "p95_query_time_seconds",
        "p99_query_time_seconds",
        "maximum_query_time_seconds",
        "total_subtour_iterations",
        "total_subtour_constraints",
        "property_satisfied",
        "candidate_requires_review",
        "candidate_report_path",
        "backtracking_queries",
        "backtracking_agreements",
        "backtracking_runtime_seconds",
    }
)

ALL_EDGE_FIELDS = COMMON_ANALYSIS_FIELDS | {
    "total_ordered_edge_pairs",
    "average_pairs_certified_per_witness",
    "maximum_pairs_certified_by_one_witness",
    "hardest_ordered_pair",
}

PATH_FIELDS = COMMON_ANALYSIS_FIELDS | {
    "number_of_distinct_three_edge_paths",
    "average_paths_certified_per_witness",
    "maximum_paths_certified_by_one_witness",
    "hardest_path",
}

CORE_SELECTION_METRICS = (
    "all_edge_pairs.number_of_witness_cycles",
    "all_edge_pairs.total_subtour_constraints",
    "three_edge_paths.number_of_witness_cycles",
    "three_edge_paths.total_subtour_constraints",
)

REASON_PRIORITY = (
    "AE_WITNESS_TOP10",
    "AE_SUBTOUR_TOP5",
    "PATH_WITNESS_TOP5",
    "PATH_SUBTOUR_TOP5",
    "FACE_UNIQUE",
    "MULTIVARIATE_TOP5",
    "RARE_FACE_CONTROL_LOW",
    "RARE_FACE_CONTROL_CENTRAL",
    "RARE_FACE_CONTROL_PATH_HARD",
)

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ROBUST_NORMAL_MAD_FACTOR = 1.4826
_EDGE_IDENTIFIER_SCHEME = (
    "e000.. in insertion-rank-normalized endpoint order for the retained "
    "planar_code labeling"
)
_RECONSTRUCTION_VERIFICATION_SCOPE = (
    "the complete generator stream count and every selected candidate's "
    "generation index plus canonical graph hash"
)


@dataclass(slots=True)
class AuditDataset:
    """Strictly validated source records and immutable file identities."""

    path: Path
    records: list[dict[str, Any]]
    source_size_bytes: int
    source_sha256: str
    decompressed_size_bytes: int
    decompressed_sha256: str
    blank_line_count: int
    plantri_command: tuple[str, ...]
    plantri_version: str
    plantri_executable_sha256: str
    face_pattern_counts: Counter[tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class MetricProfile:
    """Distribution and robust-location information for one scalar metric."""

    count: int
    minimum: float
    p10: float
    q1: float
    median: float
    q3: float
    p90: float
    p95: float
    p99: float
    maximum: float
    mean: float
    mad: float
    robust_scale: float
    robust_scale_method: str
    machine_dependent_timing: bool
    log1p_statistics: dict[str, float] | None

    def robust_z(self, value: float) -> float:
        if self.robust_scale == 0.0:
            return 0.0
        return (value - self.median) / self.robust_scale


@dataclass(slots=True)
class CandidateSelection:
    """Selected hashes, reasons, metrics, and global metric profiles."""

    candidates: list[dict[str, Any]]
    profiles: dict[str, MetricProfile]
    metric_values: dict[str, list[float]]
    multivariate_scores: dict[str, float]
    required_strata_union_size: int
    unique_face_graph_count: int
    full_pool_candidate_count: int = 0
    debug_graph_hash: str | None = None


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text(
        path,
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def _json_scalar(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_integer(value: Any, field: str, line_number: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"record {line_number}: {field} must be an integer")
    return value


def _require_finite_number(value: Any, field: str, line_number: int) -> float:
    if not _json_scalar(value):
        raise ValueError(f"record {line_number}: {field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"record {line_number}: {field} must be finite")
    return result


def _require_nonnegative_number(value: Any, field: str, line_number: int) -> float:
    result = _require_finite_number(value, field, line_number)
    if result < 0:
        raise ValueError(f"record {line_number}: {field} must be nonnegative")
    return result


def _validate_face_multiset(
    value: Any,
    *,
    order: int,
    edge_count: int,
    field: str,
    line_number: int,
) -> tuple[int, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in value
    ):
        raise ValueError(f"record {line_number}: {field} must be a list of integers")
    faces = tuple(value)
    expected_face_count = edge_count - order + 2
    if faces != tuple(sorted(faces)):
        raise ValueError(f"record {line_number}: {field} must be sorted")
    if len(faces) != expected_face_count:
        raise ValueError(
            f"record {line_number}: {field} has {len(faces)} faces, "
            f"expected {expected_face_count}"
        )
    if any(size < 4 or size % 2 for size in faces):
        raise ValueError(
            f"record {line_number}: {field} must contain even sizes at least four"
        )
    if sum(faces) != 2 * edge_count:
        raise ValueError(
            f"record {line_number}: {field} boundary sum is not twice the edge count"
        )
    return faces


def _validate_analysis(
    value: Any,
    *,
    name: str,
    expected_fields: frozenset[str] | set[str],
    record_hash: str,
    order: int,
    edge_count: int,
    faces: tuple[int, ...],
    line_number: int,
) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"record {line_number}: {name} must be an object")
    if set(value) != set(expected_fields):
        missing = sorted(set(expected_fields) - set(value))
        extra = sorted(set(value) - set(expected_fields))
        raise ValueError(
            f"record {line_number}: {name} schema mismatch; "
            f"missing={missing}, extra={extra}"
        )
    if value["canonical_graph_hash"] != record_hash:
        raise ValueError(f"record {line_number}: {name} hash does not match top level")
    if _require_integer(value["graph_order"], f"{name}.graph_order", line_number) != order:
        raise ValueError(f"record {line_number}: {name} order does not match top level")
    if _require_integer(value["edge_count"], f"{name}.edge_count", line_number) != edge_count:
        raise ValueError(f"record {line_number}: {name} edge count does not match top level")
    nested_faces = _validate_face_multiset(
        value["face_size_multiset"],
        order=order,
        edge_count=edge_count,
        field=f"{name}.face_size_multiset",
        line_number=line_number,
    )
    if nested_faces != faces:
        raise ValueError(f"record {line_number}: {name} faces do not match top level")

    count_fields = (
        "number_of_constrained_sat_calls",
        "number_of_witness_cycles",
        "total_subtour_iterations",
        "total_subtour_constraints",
        "backtracking_queries",
        "backtracking_agreements",
    )
    for field in count_fields:
        if _require_integer(value[field], f"{name}.{field}", line_number) < 0:
            raise ValueError(f"record {line_number}: {name}.{field} must be nonnegative")
    for field in (
        "witness_cover_ratio",
        "total_sat_wall_time_seconds",
        "median_query_time_seconds",
        "p95_query_time_seconds",
        "p99_query_time_seconds",
        "maximum_query_time_seconds",
        "backtracking_runtime_seconds",
    ):
        _require_nonnegative_number(value[field], f"{name}.{field}", line_number)

    if value["property_satisfied"] is not True:
        raise ValueError(f"record {line_number}: {name} property is not satisfied")
    if value["candidate_requires_review"] is not False:
        raise ValueError(f"record {line_number}: {name} unexpectedly requires review")
    if value["candidate_report_path"] is not None:
        raise ValueError(f"record {line_number}: {name} has an unexpected report path")

    if name == "all_edge_pairs":
        universe_field = "total_ordered_edge_pairs"
        expected_universe = edge_count * (edge_count - 1)
        average_field = "average_pairs_certified_per_witness"
        maximum_field = "maximum_pairs_certified_by_one_witness"
    else:
        universe_field = "number_of_distinct_three_edge_paths"
        expected_universe = 4 * edge_count
        average_field = "average_paths_certified_per_witness"
        maximum_field = "maximum_paths_certified_by_one_witness"
    universe = _require_integer(value[universe_field], f"{name}.{universe_field}", line_number)
    if universe != expected_universe:
        raise ValueError(
            f"record {line_number}: {name} universe is {universe}, "
            f"expected {expected_universe}"
        )
    witnesses = value["number_of_witness_cycles"]
    if witnesses <= 0:
        raise ValueError(f"record {line_number}: {name} witness count must be positive")
    if value["number_of_constrained_sat_calls"] != witnesses:
        raise ValueError(f"record {line_number}: {name} SAT-call/witness alias mismatch")
    ratio = _require_finite_number(value["witness_cover_ratio"], f"{name}.witness_cover_ratio", line_number)
    average = _require_finite_number(value[average_field], f"{name}.{average_field}", line_number)
    if not math.isclose(ratio, witnesses / universe, rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError(f"record {line_number}: {name} cover ratio is inconsistent")
    if not math.isclose(average, universe / witnesses, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"record {line_number}: {name} average coverage is inconsistent")
    if _require_integer(value[maximum_field], f"{name}.{maximum_field}", line_number) <= 0:
        raise ValueError(f"record {line_number}: {name} maximum coverage must be positive")

    hardest_field = "hardest_ordered_pair" if name == "all_edge_pairs" else "hardest_path"
    hardest = value[hardest_field]
    if name == "all_edge_pairs":
        valid_shape = (
            isinstance(hardest, list)
            and len(hardest) == 2
            and all(isinstance(edge, list) and len(edge) == 2 for edge in hardest)
        )
        vertices = [vertex for edge in hardest for vertex in edge] if valid_shape else []
        valid_structure = (
            valid_shape
            and all(
                isinstance(vertex, int)
                and not isinstance(vertex, bool)
                and 0 <= vertex < order
                for vertex in vertices
            )
            and all(edge[0] != edge[1] for edge in hardest)
            and frozenset(hardest[0]) != frozenset(hardest[1])
        )
    else:
        valid_shape = isinstance(hardest, list) and len(hardest) == 4
        valid_structure = (
            valid_shape
            and all(
                isinstance(vertex, int)
                and not isinstance(vertex, bool)
                and 0 <= vertex < order
                for vertex in hardest
            )
            and len(set(hardest)) == 4
        )
    if not valid_structure:
        raise ValueError(
            f"record {line_number}: {name}.{hardest_field} has invalid shape or labels"
        )


def _open_decompressed_binary(path: Path) -> BinaryIO:
    if ".gz" in path.suffixes:
        return gzip.open(path, "rb")
    return path.open("rb")


def audit_source(
    path: Path,
    *,
    expected_order: int = EXPECTED_ORDER,
    expected_count: int = EXPECTED_RECORD_COUNT,
) -> AuditDataset:
    """Read the complete JSONL stream and reject any schema or identity ambiguity."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    source_size = path.stat().st_size
    source_hash = _sha256_file(path)
    decompressed_digest = sha256()
    decompressed_size = 0
    blank_lines = 0
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    first_command: tuple[str, ...] | None = None
    first_version: str | None = None
    first_executable_hash: str | None = None

    with _open_decompressed_binary(path) as source:
        for line_number, raw_line in enumerate(source, start=1):
            decompressed_digest.update(raw_line)
            decompressed_size += len(raw_line)
            if not raw_line.strip():
                blank_lines += 1
                continue
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"record {line_number}: JSONL is not UTF-8") from error
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"record {line_number}: malformed JSON") from error
            if not isinstance(record, dict):
                raise ValueError(f"record {line_number}: JSON value is not an object")
            if set(record) != set(TOP_LEVEL_FIELDS):
                missing = sorted(TOP_LEVEL_FIELDS - set(record))
                extra = sorted(set(record) - TOP_LEVEL_FIELDS)
                raise ValueError(
                    f"record {line_number}: top-level schema mismatch; "
                    f"missing={missing}, extra={extra}"
                )
            generation_index = _require_integer(
                record["generation_index"], "generation_index", line_number
            )
            if generation_index != len(records):
                raise ValueError(
                    f"record {line_number}: generation index {generation_index} "
                    f"does not equal expected {len(records)}"
                )
            order = _require_integer(
                record["requested_vertex_count"],
                "requested_vertex_count",
                line_number,
            )
            if order != expected_order:
                raise ValueError(
                    f"record {line_number}: order {order} does not equal {expected_order}"
                )
            edge_count = _require_integer(record["edge_count"], "edge_count", line_number)
            if edge_count != 3 * order // 2:
                raise ValueError(f"record {line_number}: edge count is not cubic")
            record_hash = record["canonical_graph_hash"]
            if not isinstance(record_hash, str) or _HASH_PATTERN.fullmatch(record_hash) is None:
                raise ValueError(f"record {line_number}: malformed canonical graph hash")
            if record_hash in seen_hashes:
                raise ValueError(f"record {line_number}: duplicate canonical graph hash")
            seen_hashes.add(record_hash)
            faces = _validate_face_multiset(
                record["face_size_multiset"],
                order=order,
                edge_count=edge_count,
                field="face_size_multiset",
                line_number=line_number,
            )
            command_value = record["plantri_command"]
            if not isinstance(command_value, list) or not command_value or any(
                not isinstance(item, str) for item in command_value
            ):
                raise ValueError(f"record {line_number}: plantri_command must be strings")
            command = tuple(command_value)
            version = record["plantri_version"]
            executable_hash = record["plantri_executable_sha256"]
            if not isinstance(version, str) or not version:
                raise ValueError(f"record {line_number}: plantri_version must be text")
            if not isinstance(executable_hash, str) or _HASH_PATTERN.fullmatch(executable_hash) is None:
                raise ValueError(f"record {line_number}: malformed plantri executable hash")
            if first_command is None:
                first_command = command
                first_version = version
                first_executable_hash = executable_hash
            elif (
                command != first_command
                or version != first_version
                or executable_hash != first_executable_hash
            ):
                raise ValueError(f"record {line_number}: plantri provenance is inconsistent")

            _validate_analysis(
                record["all_edge_pairs"],
                name="all_edge_pairs",
                expected_fields=ALL_EDGE_FIELDS,
                record_hash=record_hash,
                order=order,
                edge_count=edge_count,
                faces=faces,
                line_number=line_number,
            )
            _validate_analysis(
                record["three_edge_paths"],
                name="three_edge_paths",
                expected_fields=PATH_FIELDS,
                record_hash=record_hash,
                order=order,
                edge_count=edge_count,
                faces=faces,
                line_number=line_number,
            )
            records.append(record)

    if blank_lines:
        raise ValueError(f"source contains {blank_lines} blank JSONL lines")
    if len(records) != expected_count:
        raise ValueError(
            f"record count is {len(records)}, expected exactly {expected_count}"
        )
    assert first_command is not None and first_version is not None
    assert first_executable_hash is not None
    return AuditDataset(
        path=path,
        records=records,
        source_size_bytes=source_size,
        source_sha256=source_hash,
        decompressed_size_bytes=decompressed_size,
        decompressed_sha256=decompressed_digest.hexdigest(),
        blank_line_count=blank_lines,
        plantri_command=first_command,
        plantri_version=first_version,
        plantri_executable_sha256=first_executable_hash,
        face_pattern_counts=Counter(
            tuple(record["face_size_multiset"]) for record in records
        ),
    )


def _percentile(ordered: Sequence[float], probability: float) -> float:
    if not ordered:
        raise ValueError("cannot calculate a percentile of no values")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _distribution(values: Sequence[float], *, timing: bool) -> MetricProfile:
    if not values:
        raise ValueError("metric has no values")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("metric contains a non-finite value")
    ordered = sorted(map(float, values))
    median = _percentile(ordered, 0.5)
    deviations = sorted(abs(value - median) for value in ordered)
    mad = _percentile(deviations, 0.5)
    p10 = _percentile(ordered, 0.10)
    q1 = _percentile(ordered, 0.25)
    q3 = _percentile(ordered, 0.75)
    p90 = _percentile(ordered, 0.90)
    if mad > 0:
        robust_scale = _ROBUST_NORMAL_MAD_FACTOR * mad
        scale_method = "1.4826*MAD"
    elif q3 > q1:
        robust_scale = (q3 - q1) / 1.349
        scale_method = "IQR/1.349"
    elif p90 > p10:
        robust_scale = (p90 - p10) / 2.563
        scale_method = "P90-P10/2.563"
    elif ordered[-1] > ordered[0]:
        robust_scale = (ordered[-1] - ordered[0]) / 2
        scale_method = "range/2"
    else:
        robust_scale = 0.0
        scale_method = "constant"
    log_stats: dict[str, float] | None = None
    if timing:
        logged = sorted(math.log1p(value) for value in ordered)
        log_stats = {
            "minimum": logged[0],
            "median": _percentile(logged, 0.5),
            "p95": _percentile(logged, 0.95),
            "p99": _percentile(logged, 0.99),
            "maximum": logged[-1],
        }
    return MetricProfile(
        count=len(ordered),
        minimum=ordered[0],
        p10=p10,
        q1=q1,
        median=median,
        q3=q3,
        p90=p90,
        p95=_percentile(ordered, 0.95),
        p99=_percentile(ordered, 0.99),
        maximum=ordered[-1],
        mean=math.fsum(ordered) / len(ordered),
        mad=mad,
        robust_scale=robust_scale,
        robust_scale_method=scale_method,
        machine_dependent_timing=timing,
        log1p_statistics=log_stats,
    )


def _face_signature(faces: Sequence[int]) -> str:
    counts = Counter(faces)
    return ",".join(
        str(size) if multiplicity == 1 else f"{size}^{multiplicity}"
        for size, multiplicity in sorted(counts.items())
    )


def _record_scalar_metrics(
    record: dict[str, Any], face_counts: Counter[tuple[int, ...]], total: int
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for field, value in record.items():
        if _json_scalar(value):
            metrics[field] = float(value)
    for analysis in ("all_edge_pairs", "three_edge_paths"):
        for field, value in record[analysis].items():
            if _json_scalar(value):
                metrics[f"{analysis}.{field}"] = float(value)
    faces = tuple(record["face_size_multiset"])
    frequency = face_counts[faces]
    nonquadrilateral = tuple(size for size in faces if size != 4)
    metrics.update(
        {
            "derived.face_pattern_frequency": float(frequency),
            "derived.face_pattern_prevalence": frequency / total,
            "derived.face_pattern_surprisal_bits": -math.log2(frequency / total),
            "derived.number_of_faces": float(len(faces)),
            "derived.number_of_quadrilateral_faces": float(faces.count(4)),
            "derived.number_of_nonquadrilateral_faces": float(len(nonquadrilateral)),
            "derived.maximum_face_size": float(max(faces)),
            "derived.number_of_distinct_face_sizes": float(len(set(faces))),
        }
    )
    return metrics


def _competition_rank_and_midpercentile(
    values: Sequence[float], value: float
) -> tuple[int, float]:
    greater = sum(candidate > value for candidate in values)
    less = sum(candidate < value for candidate in values)
    equal = len(values) - greater - less
    return 1 + greater, (less + 0.5 * equal) / len(values)


def _rank_lookup(values: Sequence[float]) -> dict[float, tuple[int, float]]:
    """Precompute tied competition ranks and midpercentiles for all values."""
    counts = Counter(values)
    total = len(values)
    less = 0
    result: dict[float, tuple[int, float]] = {}
    for value in sorted(counts):
        equal = counts[value]
        greater = total - less - equal
        result[value] = (1 + greater, (less + 0.5 * equal) / total)
        less += equal
    return result


def select_candidates(dataset: AuditDataset) -> CandidateSelection:
    """Select a stable, diverse pool and retain every qualifying reason."""
    records = dataset.records
    by_hash = {record["canonical_graph_hash"]: record for record in records}
    scalar_by_hash = {
        graph_hash: _record_scalar_metrics(
            record, dataset.face_pattern_counts, len(records)
        )
        for graph_hash, record in by_hash.items()
    }
    metric_names = sorted(next(iter(scalar_by_hash.values())))
    if any(sorted(metrics) != metric_names for metrics in scalar_by_hash.values()):
        raise ValueError("records do not expose a uniform scalar metric inventory")
    metric_values = {
        name: [scalar_by_hash[record["canonical_graph_hash"]][name] for record in records]
        for name in metric_names
    }
    profiles = {
        name: _distribution(
            values,
            timing=("time" in name or "runtime" in name),
        )
        for name, values in metric_values.items()
    }

    multivariate_scores: dict[str, float] = {}
    for graph_hash, metrics in scalar_by_hash.items():
        multivariate_scores[graph_hash] = math.fsum(
            max(0.0, min(8.0, profiles[name].robust_z(metrics[name])))
            for name in CORE_SELECTION_METRICS
        )
        metrics["derived.multivariate_outlier_score"] = multivariate_scores[graph_hash]
    metric_values["derived.multivariate_outlier_score"] = [
        multivariate_scores[record["canonical_graph_hash"]] for record in records
    ]
    profiles["derived.multivariate_outlier_score"] = _distribution(
        metric_values["derived.multivariate_outlier_score"], timing=False
    )
    rank_lookups = {
        name: _rank_lookup(values) for name, values in metric_values.items()
    }

    reasons: dict[str, list[dict[str, Any]]] = {}

    def add_reason(
        graph_hash: str,
        code: str,
        position: int,
        explanation: str,
    ) -> None:
        entries = reasons.setdefault(graph_hash, [])
        if any(entry["code"] == code for entry in entries):
            return
        entries.append(
            {
                "code": code,
                "priority": REASON_PRIORITY.index(code),
                "position": position,
                "explanation": explanation,
            }
        )

    strata = (
        (
            "AE_WITNESS_TOP10",
            "all_edge_pairs.number_of_witness_cycles",
            10,
            "all-edge greedy witness count",
        ),
        (
            "AE_SUBTOUR_TOP5",
            "all_edge_pairs.total_subtour_constraints",
            5,
            "all-edge subtour-constraint count",
        ),
        (
            "PATH_WITNESS_TOP5",
            "three_edge_paths.number_of_witness_cycles",
            5,
            "three-edge-path greedy witness count",
        ),
        (
            "PATH_SUBTOUR_TOP5",
            "three_edge_paths.total_subtour_constraints",
            5,
            "three-edge-path subtour-constraint count",
        ),
    )
    for code, metric, limit, label in strata:
        ranked = sorted(
            records,
            key=lambda record: (
                -scalar_by_hash[record["canonical_graph_hash"]][metric],
                record["canonical_graph_hash"],
            ),
        )
        for position, record in enumerate(ranked[:limit], start=1):
            graph_hash = record["canonical_graph_hash"]
            value = scalar_by_hash[graph_hash][metric]
            add_reason(
                graph_hash,
                code,
                position,
                f"hash-tiebroken position {position} by {label} (value {value:g})",
            )
    required_union_size = len(reasons)

    unique_face_records = sorted(
        (
            record
            for record in records
            if dataset.face_pattern_counts[tuple(record["face_size_multiset"])] == 1
        ),
        key=lambda record: (
            tuple(record["face_size_multiset"]),
            record["canonical_graph_hash"],
        ),
    )
    for position, record in enumerate(unique_face_records, start=1):
        graph_hash = record["canonical_graph_hash"]
        add_reason(
            graph_hash,
            "FACE_UNIQUE",
            position,
            "the face-size multiset occurs exactly once among all order-38 records",
        )

    outlier_ranked = sorted(
        records,
        key=lambda record: (
            -multivariate_scores[record["canonical_graph_hash"]],
            record["canonical_graph_hash"],
        ),
    )
    for position, record in enumerate(outlier_ranked[:5], start=1):
        graph_hash = record["canonical_graph_hash"]
        add_reason(
            graph_hash,
            "MULTIVARIATE_TOP5",
            position,
            "top-five sum of clipped positive robust z-scores across the four "
            f"independent witness/subtour metrics (score {multivariate_scores[graph_hash]:.6f})",
        )

    # Deliberately label three rare-face graphs as controls.  They are selected
    # for face rarity, not because they occupy the all-edge greedy top ten.
    ae_metric = "all_edge_pairs.number_of_witness_cycles"
    non_top_unique = [
        record
        for record in unique_face_records
        if not any(
            item["code"] == "AE_WITNESS_TOP10"
            for item in reasons[record["canonical_graph_hash"]]
        )
    ]
    if len(non_top_unique) >= 3:
        low = min(
            non_top_unique,
            key=lambda record: (
                scalar_by_hash[record["canonical_graph_hash"]][ae_metric],
                record["canonical_graph_hash"],
            ),
        )
        remaining = [record for record in non_top_unique if record is not low]

        def central_distance(record: dict[str, Any]) -> float:
            graph_hash = record["canonical_graph_hash"]
            return math.fsum(
                profiles[name].robust_z(scalar_by_hash[graph_hash][name]) ** 2
                for name in CORE_SELECTION_METRICS
            )

        central = min(
            remaining,
            key=lambda record: (central_distance(record), record["canonical_graph_hash"]),
        )
        remaining = [record for record in remaining if record is not central]
        path_hard = min(
            remaining,
            key=lambda record: (
                -scalar_by_hash[record["canonical_graph_hash"]][
                    "three_edge_paths.total_subtour_constraints"
                ],
                record["canonical_graph_hash"],
            ),
        )
        controls = (
            (
                low,
                "RARE_FACE_CONTROL_LOW",
                "unique-face control with the lowest all-edge greedy witness count",
            ),
            (
                central,
                "RARE_FACE_CONTROL_CENTRAL",
                "unique-face control closest to the four-metric robust center",
            ),
            (
                path_hard,
                "RARE_FACE_CONTROL_PATH_HARD",
                "unique-face control with the largest path-subtour count among remaining controls",
            ),
        )
        for position, (record, code, explanation) in enumerate(controls, start=1):
            add_reason(record["canonical_graph_hash"], code, position, explanation)

    def reason_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        entries = sorted(
            reasons[item["canonical_graph_hash"]],
            key=lambda reason: (reason["priority"], reason["position"]),
        )
        first = entries[0]
        return first["priority"], first["position"], item["canonical_graph_hash"]

    selected_records = sorted(
        (by_hash[graph_hash] for graph_hash in reasons), key=reason_sort_key
    )
    candidates: list[dict[str, Any]] = []
    for selection_order, record in enumerate(selected_records, start=1):
        graph_hash = record["canonical_graph_hash"]
        metrics = scalar_by_hash[graph_hash]
        evidence: dict[str, dict[str, Any]] = {}
        for name in sorted(metrics):
            value = metrics[name]
            rank, percentile = rank_lookups[name][value]
            evidence[name] = {
                "value": value,
                "descending_competition_rank": rank,
                "tie_aware_midpercentile": percentile,
                "robust_z": profiles[name].robust_z(value),
            }
        face_tuple = tuple(record["face_size_multiset"])
        candidate_reasons = sorted(
            reasons[graph_hash],
            key=lambda reason: (reason["priority"], reason["position"]),
        )
        candidates.append(
            {
                "selection_order": selection_order,
                "canonical_graph_hash": graph_hash,
                "generation_index": record["generation_index"],
                "requested_vertex_count": record["requested_vertex_count"],
                "edge_count": record["edge_count"],
                "face_size_multiset": list(face_tuple),
                "face_signature": _face_signature(face_tuple),
                "face_pattern_frequency": dataset.face_pattern_counts[face_tuple],
                "number_of_nonquadrilateral_faces": sum(
                    size != 4 for size in face_tuple
                ),
                "maximum_face_size": max(face_tuple),
                "multivariate_outlier_score": multivariate_scores[graph_hash],
                "selection_reasons": candidate_reasons,
                "source_metrics": {
                    "all_edge_pairs": record["all_edge_pairs"],
                    "three_edge_paths": record["three_edge_paths"],
                },
                "metric_evidence": evidence,
            }
        )
    return CandidateSelection(
        candidates=candidates,
        profiles=profiles,
        metric_values=metric_values,
        multivariate_scores=multivariate_scores,
        required_strata_union_size=required_union_size,
        unique_face_graph_count=len(unique_face_records),
        full_pool_candidate_count=len(candidates),
    )


def _artifact_paths(output_directory: Path, graph_hash: str) -> dict[str, Path]:
    directory = output_directory / "candidate_graphs"
    return {
        "planar_code": directory / f"{graph_hash}.planar_code",
        "graph6": directory / f"{graph_hash}.g6",
        "embedding": directory / f"{graph_hash}.embedding.json",
    }


def _certificate_edge_identifiers(graph: nx.Graph) -> list[dict[str, Any]]:
    """Return deterministic edge IDs for the retained planar-code labeling."""
    rank = {vertex: index for index, vertex in enumerate(graph.nodes())}
    edges = sorted(
        (
            (left, right) if rank[left] < rank[right] else (right, left)
            for left, right in graph.edges()
        ),
        key=lambda edge: (rank[edge[0]], rank[edge[1]]),
    )
    return [
        {"edge_id": f"e{index:03d}", "endpoints": list(edge)}
        for index, edge in enumerate(edges)
    ]


def _retained_label_graph6_bytes(graph: nx.Graph) -> bytes:
    """Encode graph6 with vertex numbers fixed by the planar-code artifact."""
    vertices = sorted(graph.nodes())
    if vertices != list(range(graph.number_of_nodes())):
        raise ValueError("retained planar-code vertices must be numbered 0..n-1")
    fixed_order = nx.Graph()
    fixed_order.add_nodes_from(vertices)
    fixed_order.add_edges_from(graph.edges())
    return nx.to_graph6_bytes(fixed_order, header=False)


def _write_candidate_graph_artifacts(
    output_directory: Path,
    candidate: dict[str, Any],
    planar_code: bytes,
) -> dict[str, Any]:
    [embedded] = iter_planar_code(BytesIO(planar_code), require_header=True)
    graph_hash = candidate["canonical_graph_hash"]
    recomputed_hash = canonical_graph_hash(embedded)
    if recomputed_hash != graph_hash:
        raise RuntimeError(
            f"reconstructed candidate {graph_hash} instead hashes as {recomputed_hash}"
        )
    validation = validate_barnette_graph(embedded.graph)
    if not validation.valid:
        raise RuntimeError(
            f"reconstructed candidate {graph_hash} is not Barnette: "
            f"{validation.rejection_reasons}"
        )
    if (
        validation.number_of_vertices != candidate["requested_vertex_count"]
        or validation.number_of_edges != candidate["edge_count"]
        or list(embedded.face_size_multiset) != candidate["face_size_multiset"]
    ):
        raise RuntimeError(f"reconstructed candidate {graph_hash} metadata changed")

    paths = _artifact_paths(output_directory, graph_hash)
    graph6 = _retained_label_graph6_bytes(embedded.graph)
    embedding_record = {
        "canonical_graph_hash": graph_hash,
        "generation_index": candidate["generation_index"],
        "requested_vertex_count": candidate["requested_vertex_count"],
        "edge_count": candidate["edge_count"],
        "edge_identifier_scheme": _EDGE_IDENTIFIER_SCHEME,
        "canonical_edge_identifiers": _certificate_edge_identifiers(embedded.graph),
        "rotation_system": embedded.rotation_system,
        "faces": embedded.faces,
        "face_size_multiset": embedded.face_size_multiset,
    }
    _atomic_write_bytes(paths["planar_code"], planar_code)
    _atomic_write_bytes(paths["graph6"], graph6)
    _atomic_write_json(paths["embedding"], embedding_record)
    return {
        "planar_code_path": str(paths["planar_code"].resolve()),
        "planar_code_sha256": sha256(planar_code).hexdigest(),
        "planar_code_base64": base64.b64encode(planar_code).decode("ascii"),
        "graph6_path": str(paths["graph6"].resolve()),
        "graph6_sha256": sha256(graph6).hexdigest(),
        "graph6": graph6.decode("ascii").strip(),
        "embedding_path": str(paths["embedding"].resolve()),
        "embedding_sha256": _sha256_file(paths["embedding"]),
        "recomputed_canonical_graph_hash": recomputed_hash,
        "barnette_validation": asdict(validation),
    }


def _validate_saved_reconstruction(
    reconstruction: dict[str, Any],
    output_directory: Path,
    *,
    expected_hash: str | None = None,
    expected_candidate: dict[str, Any] | None = None,
) -> bool:
    try:
        graph_hash = reconstruction.get("recomputed_canonical_graph_hash")
        if (
            not isinstance(graph_hash, str)
            or (expected_hash is not None and graph_hash != expected_hash)
        ):
            return False
        paths = _artifact_paths(output_directory, graph_hash)
        path_fields = {
            "planar_code": "planar_code_path",
            "graph6": "graph6_path",
            "embedding": "embedding_path",
        }
        digest_fields = {
            "planar_code": "planar_code_sha256",
            "graph6": "graph6_sha256",
            "embedding": "embedding_sha256",
        }
        if not all(
            path.is_file()
            and reconstruction.get(path_fields[name]) == str(path.resolve())
            and _sha256_file(path) == reconstruction.get(digest_fields[name])
            for name, path in paths.items()
        ):
            return False

        planar_code = paths["planar_code"].read_bytes()
        if base64.b64decode(
            reconstruction.get("planar_code_base64", ""), validate=True
        ) != planar_code:
            return False
        [embedded] = iter_planar_code(BytesIO(planar_code), require_header=True)
        if canonical_graph_hash(embedded) != graph_hash:
            return False
        validation = validate_barnette_graph(embedded.graph)
        if not validation.valid or reconstruction.get("barnette_validation") != asdict(
            validation
        ):
            return False

        graph6_bytes = paths["graph6"].read_bytes()
        if reconstruction.get("graph6") != graph6_bytes.decode("ascii").strip():
            return False
        graph6_graph = nx.from_graph6_bytes(graph6_bytes.strip())
        if (
            set(graph6_graph.nodes()) != set(embedded.graph.nodes())
            or {frozenset(edge) for edge in graph6_graph.edges()}
            != {frozenset(edge) for edge in embedded.graph.edges()}
        ):
            return False

        embedding = json.loads(paths["embedding"].read_text(encoding="utf-8"))
        expected_edges = _certificate_edge_identifiers(embedded.graph)
        if (
            embedding.get("canonical_graph_hash") != graph_hash
            or embedding.get("requested_vertex_count")
            != embedded.graph.number_of_nodes()
            or embedding.get("edge_count") != embedded.graph.number_of_edges()
            or embedding.get("edge_identifier_scheme") != _EDGE_IDENTIFIER_SCHEME
            or embedding.get("canonical_edge_identifiers") != expected_edges
            or embedding.get("rotation_system")
            != [list(row) for row in embedded.rotation_system]
            or embedding.get("faces") != [list(face) for face in embedded.faces]
            or embedding.get("face_size_multiset")
            != list(embedded.face_size_multiset)
        ):
            return False
        if expected_candidate is not None and (
            expected_candidate.get("canonical_graph_hash") != graph_hash
            or embedding.get("generation_index")
            != expected_candidate.get("generation_index")
            or embedding.get("requested_vertex_count")
            != expected_candidate.get("requested_vertex_count")
            or embedding.get("edge_count") != expected_candidate.get("edge_count")
            or embedding.get("face_size_multiset")
            != expected_candidate.get("face_size_multiset")
        ):
            return False
    except (
        OSError,
        ValueError,
        TypeError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
        nx.NetworkXException,
    ):
        return False
    return True


def reconstruct_candidates(
    dataset: AuditDataset,
    selection: CandidateSelection,
    *,
    executable: Path,
    output_directory: Path,
    resume: bool,
    overwrite: bool,
) -> dict[str, Any]:
    """Replay plantri and materialize every selected graph after index/hash checks."""
    version = detect_plantri_version(executable)
    if version.version != dataset.plantri_version:
        raise RuntimeError(
            f"plantri reports {version.version}, source records say {dataset.plantri_version}"
        )
    if version.executable_sha256 != dataset.plantri_executable_sha256:
        raise RuntimeError(
            "plantri executable SHA-256 does not match the source records: "
            f"{version.executable_sha256} != {dataset.plantri_executable_sha256}"
        )
    replay_command = barnette_plantri_command(version.executable, EXPECTED_ORDER)
    if tuple(replay_command[1:]) != tuple(dataset.plantri_command[1:]):
        raise RuntimeError(
            f"replay command {replay_command} is incompatible with recorded "
            f"command {dataset.plantri_command}"
        )

    manifest_path = output_directory / "reconstruction_manifest.json"
    checkpoint_path = output_directory / "reconstruction.checkpoint.json"
    target_hashes = [
        candidate["canonical_graph_hash"] for candidate in selection.candidates
    ]
    candidates_by_hash = {
        candidate["canonical_graph_hash"]: candidate
        for candidate in selection.candidates
    }
    configuration = {
        "schema_version": SCHEMA_VERSION,
        "source_sha256": dataset.source_sha256,
        "source_record_count": len(dataset.records),
        "order": EXPECTED_ORDER,
        "plantri_version": version.version,
        "plantri_executable_sha256": version.executable_sha256,
        "plantri_command_suffix": list(replay_command[1:]),
        "target_hashes": target_hashes,
    }
    if overwrite:
        manifest_path.unlink(missing_ok=True)
        checkpoint_path.unlink(missing_ok=True)
    if manifest_path.exists():
        if not resume:
            raise FileExistsError(f"refusing to overwrite {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("completed reconstruction manifest must be an object")
        if manifest.get("configuration") != configuration:
            raise ValueError("completed reconstruction manifest configuration differs")
        reconstructions = manifest.get("candidates", {})
        runtime_seconds = manifest.get("runtime_seconds")
        plantri_stderr = manifest.get("plantri_stderr")
        if (
            set(manifest)
            != {
                "configuration",
                "reconstruction_status",
                "verification_scope",
                "generated_count",
                "selected_candidate_count",
                "plantri_stderr",
                "runtime_seconds",
                "candidates",
                "resume_status",
            }
            or manifest.get("reconstruction_status") != "verified"
            or manifest.get("verification_scope")
            != _RECONSTRUCTION_VERIFICATION_SCOPE
            or manifest.get("generated_count") != len(dataset.records)
            or manifest.get("selected_candidate_count") != len(target_hashes)
            or not isinstance(plantri_stderr, str)
            or not plantri_stderr.splitlines()
            or plantri_stderr.splitlines()[-1]
            != f"{len(dataset.records)} bipartite cubic graphs written to stdout"
            or isinstance(runtime_seconds, bool)
            or not isinstance(runtime_seconds, (int, float))
            or not math.isfinite(runtime_seconds)
            or runtime_seconds < 0
            or manifest.get("resume_status") != "completed_replay"
            or not isinstance(reconstructions, dict)
            or set(reconstructions) != set(target_hashes)
            or not all(
                _validate_saved_reconstruction(
                    value,
                    output_directory,
                    expected_hash=graph_hash,
                    expected_candidate=candidates_by_hash[graph_hash],
                )
                for graph_hash, value in reconstructions.items()
            )
        ):
            raise RuntimeError("completed reconstruction artifacts are missing or changed")
        result = dict(manifest)
        result["resume_status"] = "reused_complete_manifest"
        checkpoint_path.unlink(missing_ok=True)
        return result

    completed: dict[str, dict[str, Any]] = {}
    if checkpoint_path.exists():
        if not resume:
            raise FileExistsError(
                f"unfinished reconstruction exists; pass --resume: {checkpoint_path}"
            )
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(checkpoint, dict):
            raise ValueError("reconstruction checkpoint must be an object")
        if (
            set(checkpoint) != {"configuration", "candidates"}
            or checkpoint.get("configuration") != configuration
        ):
            raise ValueError("reconstruction checkpoint configuration differs")
        completed = checkpoint.get("candidates", {})
        if not isinstance(completed, dict) or not set(completed) <= set(target_hashes):
            raise ValueError("reconstruction checkpoint candidate set is invalid")
        for graph_hash, value in completed.items():
            if not _validate_saved_reconstruction(
                value,
                output_directory,
                expected_hash=graph_hash,
                expected_candidate=candidates_by_hash[graph_hash],
            ):
                raise RuntimeError(
                    f"checkpoint artifact for {graph_hash} is missing or changed"
                )
    else:
        _atomic_write_json(
            checkpoint_path,
            {"configuration": configuration, "candidates": completed},
        )

    by_index = {
        candidate["generation_index"]: candidate
        for candidate in selection.candidates
    }
    started = perf_counter()
    generated_count = 0
    with stream_barnette_graphs(version, EXPECTED_ORDER) as stream:
        for generation_index, embedded in enumerate(stream):
            generated_count = generation_index + 1
            candidate = by_index.get(generation_index)
            if candidate is None:
                continue
            graph_hash = candidate["canonical_graph_hash"]
            if graph_hash in completed:
                continue
            planar_code = encode_planar_code(embedded.rotation_system)
            actual_hash = canonical_graph_hash(embedded)
            if actual_hash != graph_hash:
                raise RuntimeError(
                    f"plantri index {generation_index} hashes as {actual_hash}, "
                    f"but the source record says {graph_hash}"
                )
            completed[graph_hash] = _write_candidate_graph_artifacts(
                output_directory, candidate, planar_code
            )
            _atomic_write_json(
                checkpoint_path,
                {"configuration": configuration, "candidates": completed},
            )
            print(
                f"reconstructed {len(completed)}/{len(target_hashes)}: "
                f"index {generation_index} {graph_hash}",
                flush=True,
            )
        plantri_stderr = stream.stderr_text
    post_replay_executable_hash = _sha256_file(version.executable)
    if post_replay_executable_hash != version.executable_sha256:
        raise RuntimeError(
            "plantri executable changed between provenance check and replay completion"
        )
    if generated_count != len(dataset.records):
        raise RuntimeError(
            f"plantri replay emitted {generated_count} graphs, expected "
            f"{len(dataset.records)}"
        )
    if set(completed) != set(target_hashes):
        missing = sorted(set(target_hashes) - set(completed))
        raise RuntimeError(f"plantri replay did not reconstruct candidates: {missing}")
    elapsed = perf_counter() - started
    manifest = {
        "configuration": configuration,
        "reconstruction_status": "verified",
        "verification_scope": _RECONSTRUCTION_VERIFICATION_SCOPE,
        "generated_count": generated_count,
        "selected_candidate_count": len(completed),
        "plantri_stderr": plantri_stderr.strip(),
        "runtime_seconds": elapsed,
        "candidates": {graph_hash: completed[graph_hash] for graph_hash in sorted(completed)},
        "resume_status": "completed_replay",
    }
    _atomic_write_json(manifest_path, manifest)
    checkpoint_path.unlink(missing_ok=True)
    return manifest


def inventory_associated_artifacts(dataset: AuditDataset) -> dict[str, Any]:
    """Inventory metadata, summaries, top-K files, graph artifacts, and checkpoints."""
    root = dataset.path.parent
    summary_name = dataset.path.name
    if summary_name.endswith(".jsonl.gz"):
        summary_name = summary_name.removesuffix(".jsonl.gz") + ".summary.csv"
    else:
        summary_name = summary_name.removesuffix(".jsonl") + ".summary.csv"
    summary_path = root / summary_name
    metadata_path = root / "strong_flexibility_run_metadata.json"
    result: dict[str, Any] = {
        "root": str(root),
        "summary": {"path": str(summary_path), "exists": summary_path.is_file()},
        "metadata": {"path": str(metadata_path), "exists": metadata_path.is_file()},
    }
    summary_row: dict[str, str] | None = None
    if summary_path.is_file():
        with summary_path.open("r", encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        if len(rows) != 1:
            raise ValueError(f"expected one summary row in {summary_path}")
        summary_row = rows[0]
        result["summary"].update(
            {
                "size_bytes": summary_path.stat().st_size,
                "sha256": _sha256_file(summary_path),
                "row": summary_row,
            }
        )
    metadata_record: dict[str, Any] | None = None
    if metadata_path.is_file():
        metadata_record = json.loads(metadata_path.read_text(encoding="utf-8"))
        result["metadata"].update(
            {
                "size_bytes": metadata_path.stat().st_size,
                "sha256": _sha256_file(metadata_path),
                "requested_vertex_counts": metadata_record.get(
                    "requested_vertex_counts"
                ),
                "options": metadata_record.get("options"),
                "dependency_versions": metadata_record.get("dependency_versions"),
                "machine": metadata_record.get("machine"),
            }
        )

    leaderboard_inventory: dict[str, Any] = {}
    current_unions: dict[str, set[str]] = {}
    extremal_root = root / "extremal"
    for analysis in ("all_edge_pairs", "three_edge_paths"):
        directory = extremal_root / analysis
        files = sorted(directory.glob("leaderboard_*.csv"))
        union: set[str] = set()
        row_count = 0
        per_file: dict[str, int] = {}
        leaderboard_files: list[dict[str, Any]] = []
        for path in files:
            with path.open("r", encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
            current_rows = [
                row for row in rows if int(row.get("vertex_count", 0)) == EXPECTED_ORDER
            ]
            row_count += len(current_rows)
            per_file[path.name] = len(current_rows)
            union.update(row["canonical_graph_hash"] for row in current_rows)
            leaderboard_files.append(
                {
                    "path": str(path.resolve()),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                    "total_row_count": len(rows),
                    "order38_row_count": len(current_rows),
                }
            )
        current_unions[analysis] = union
        graph_directory = directory / "graphs"
        order_counts: Counter[int] = Counter()
        invalid_artifacts: list[str] = []
        for path in sorted(graph_directory.glob("*.planar_code")):
            try:
                [embedded] = iter_planar_code(
                    BytesIO(path.read_bytes()), require_header=True
                )
                actual_hash = canonical_graph_hash(embedded)
                if actual_hash != path.stem:
                    invalid_artifacts.append(str(path))
                order_counts[embedded.graph.number_of_nodes()] += 1
            except Exception:
                invalid_artifacts.append(str(path))
        order_comparison_path = directory / "order_comparison.csv"
        order_comparison: dict[str, Any] = {
            "path": str(order_comparison_path.resolve()),
            "exists": order_comparison_path.is_file(),
        }
        if order_comparison_path.is_file():
            with order_comparison_path.open(
                "r", encoding="utf-8", newline=""
            ) as source:
                comparison_rows = list(csv.DictReader(source))
            order_comparison.update(
                {
                    "size_bytes": order_comparison_path.stat().st_size,
                    "sha256": _sha256_file(order_comparison_path),
                    "row_count": len(comparison_rows),
                    "orders": sorted(
                        {int(row["vertex_count"]) for row in comparison_rows}
                    ),
                }
            )
        missing_current = sorted(
            graph_hash
            for graph_hash in union
            if not all(
                (graph_directory / f"{graph_hash}.{suffix}").is_file()
                for suffix in ("planar_code", "embedding.json", "txt")
            )
        )
        current_artifacts: list[dict[str, Any]] = []
        invalid_current_companions: list[str] = []
        for graph_hash in sorted(union):
            planar_path = graph_directory / f"{graph_hash}.planar_code"
            embedding_path = graph_directory / f"{graph_hash}.embedding.json"
            text_path = graph_directory / f"{graph_hash}.txt"
            if not all(path.is_file() for path in (planar_path, embedding_path, text_path)):
                continue
            [embedded] = iter_planar_code(
                BytesIO(planar_path.read_bytes()), require_header=True
            )
            embedding = json.loads(embedding_path.read_text(encoding="utf-8"))
            text_report = text_path.read_text(encoding="utf-8")
            companion_valid = (
                embedding.get("canonical_graph_hash") == graph_hash
                and embedding.get("rotation_system")
                == [list(row) for row in embedded.rotation_system]
                and embedding.get("faces") == [list(face) for face in embedded.faces]
                and embedding.get("face_size_multiset")
                == list(embedded.face_size_multiset)
                and graph_hash in text_report
                and f"Graph order: {EXPECTED_ORDER}" in text_report
            )
            if not companion_valid:
                invalid_current_companions.append(graph_hash)
            current_artifacts.append(
                {
                    "canonical_graph_hash": graph_hash,
                    "order": embedded.graph.number_of_nodes(),
                    "planar_code": {
                        "path": str(planar_path.resolve()),
                        "size_bytes": planar_path.stat().st_size,
                        "sha256": _sha256_file(planar_path),
                        "recomputed_hash_matches": (
                            canonical_graph_hash(embedded) == graph_hash
                        ),
                    },
                    "embedding": {
                        "path": str(embedding_path.resolve()),
                        "size_bytes": embedding_path.stat().st_size,
                        "sha256": _sha256_file(embedding_path),
                    },
                    "text_report": {
                        "path": str(text_path.resolve()),
                        "size_bytes": text_path.stat().st_size,
                        "sha256": _sha256_file(text_path),
                    },
                    "companions_match_planar_code": companion_valid,
                }
            )
        leaderboard_inventory[analysis] = {
            "leaderboard_file_count": len(files),
            "leaderboard_rows": row_count,
            "rows_per_file": per_file,
            "leaderboard_files": leaderboard_files,
            "order_comparison": order_comparison,
            "current_unique_hash_count": len(union),
            "planar_code_artifact_counts_by_order": {
                str(order): count for order, count in sorted(order_counts.items())
            },
            "missing_current_artifacts": missing_current,
            "invalid_or_hash_mismatched_planar_code_artifacts": invalid_artifacts,
            "invalid_current_embedding_or_text_companions": invalid_current_companions,
            "current_retained_artifacts": current_artifacts,
        }
    result["extremal"] = leaderboard_inventory
    result["extremal"]["cross_analysis_unique_hash_count"] = len(
        set().union(*current_unions.values())
    )
    if metadata_record is not None:
        selected = metadata_record.get("extremal_selected_hashes", {})
        result["extremal"]["metadata_selected_sets_match_leaderboards"] = all(
            set(selected.get(analysis, ())) == current_unions[analysis]
            for analysis in current_unions
        )

    checkpoints = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and any(
            marker in path.name
            for marker in ("checkpoint", ".partial", "progress", "manifest")
        )
    )
    result["checkpoints_or_partial_files"] = checkpoints
    result["detailed_candidate_jsonl_present"] = any(
        root.glob("strong_flexibility.candidates.jsonl*")
    )

    aggregates = {
        "generated_count": len(dataset.records),
        "all_edge_witnesses": sum(
            record["all_edge_pairs"]["number_of_witness_cycles"]
            for record in dataset.records
        ),
        "all_edge_subtour_constraints": sum(
            record["all_edge_pairs"]["total_subtour_constraints"]
            for record in dataset.records
        ),
        "all_edge_subtour_iterations": sum(
            record["all_edge_pairs"]["total_subtour_iterations"]
            for record in dataset.records
        ),
        "all_edge_sat_time_seconds": math.fsum(
            record["all_edge_pairs"]["total_sat_wall_time_seconds"]
            for record in dataset.records
        ),
        "path_witnesses": sum(
            record["three_edge_paths"]["number_of_witness_cycles"]
            for record in dataset.records
        ),
        "path_subtour_constraints": sum(
            record["three_edge_paths"]["total_subtour_constraints"]
            for record in dataset.records
        ),
        "path_subtour_iterations": sum(
            record["three_edge_paths"]["total_subtour_iterations"]
            for record in dataset.records
        ),
        "path_sat_time_seconds": math.fsum(
            record["three_edge_paths"]["total_sat_wall_time_seconds"]
            for record in dataset.records
        ),
    }
    result["recomputed_aggregates"] = aggregates
    if summary_row is not None:
        comparisons = {
            "generated_count": int(summary_row["generated_count"]) == aggregates["generated_count"],
            "all_edge_witnesses": int(summary_row["all_edge_witness_cycles"]) == aggregates["all_edge_witnesses"],
            "all_edge_subtour_constraints": int(summary_row["all_edge_subtour_constraints"]) == aggregates["all_edge_subtour_constraints"],
            "all_edge_subtour_iterations": int(summary_row["all_edge_subtour_iterations"]) == aggregates["all_edge_subtour_iterations"],
            "path_witnesses": int(summary_row["three_edge_path_witness_cycles"]) == aggregates["path_witnesses"],
            "path_subtour_constraints": int(summary_row["three_edge_path_subtour_constraints"]) == aggregates["path_subtour_constraints"],
            "path_subtour_iterations": int(summary_row["three_edge_path_subtour_iterations"]) == aggregates["path_subtour_iterations"],
        }
        result["summary_aggregate_checks"] = comparisons
        if not all(comparisons.values()):
            raise ValueError("source summary disagrees with recomputed record aggregates")
    return result


def _profile_record(profile: MetricProfile) -> dict[str, Any]:
    return asdict(profile)


def _markdown_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    materialized = [[cell(value) for value in row] for row in rows]
    lines = [
        "| " + " | ".join(map(cell, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in materialized)
    return "\n".join(lines)


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.9g}"


def _schema_inventory_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    top_types = {
        "generation_index": "integer",
        "requested_vertex_count": "integer",
        "canonical_graph_hash": "64-character lowercase hexadecimal string",
        "edge_count": "integer",
        "face_size_multiset": "sorted integer array",
        "plantri_version": "string",
        "plantri_executable_sha256": "64-character lowercase hexadecimal string",
        "plantri_command": "string array",
        "all_edge_pairs": "object",
        "three_edge_paths": "object",
    }
    for field in sorted(TOP_LEVEL_FIELDS):
        rows.append((field, top_types[field], "required in every record"))
    for analysis, fields in (
        ("all_edge_pairs", ALL_EDGE_FIELDS),
        ("three_edge_paths", PATH_FIELDS),
    ):
        for field in sorted(fields):
            if field in {"candidate_report_path"}:
                value_type = "null"
            elif field in {
                "property_satisfied",
                "candidate_requires_review",
            }:
                value_type = "boolean"
            elif field in {
                "canonical_graph_hash",
            }:
                value_type = "string"
            elif field in {"face_size_multiset", "hardest_ordered_pair", "hardest_path"}:
                value_type = "array"
            elif (
                field.endswith("_seconds")
                or field == "witness_cover_ratio"
                or field.startswith("average_")
            ):
                value_type = "number"
            else:
                value_type = "integer"
            rows.append((f"{analysis}.{field}", value_type, "required in summary detail"))
    return rows


def _data_audit_markdown(
    dataset: AuditDataset,
    selection: CandidateSelection,
    associated: dict[str, Any],
    reconstruction: dict[str, Any],
) -> str:
    records = dataset.records
    face_counts = dataset.face_pattern_counts
    unique_faces = sorted(pattern for pattern, count in face_counts.items() if count == 1)
    all_edge = records[0]["all_edge_pairs"]
    paths = records[0]["three_edge_paths"]
    metric_rows = []
    for name, profile in sorted(selection.profiles.items()):
        metric_rows.append(
            (
                name,
                _format_number(profile.minimum),
                _format_number(profile.median),
                _format_number(profile.mean),
                _format_number(profile.p95),
                _format_number(profile.p99),
                _format_number(profile.maximum),
                profile.robust_scale_method,
                "yes" if profile.machine_dependent_timing else "no",
            )
        )
    extremal = associated["extremal"]
    all_edge_artifacts = extremal["all_edge_pairs"]
    path_artifacts = extremal["three_edge_paths"]
    source_reconstruction_fields = (
        "generation_index, canonical_graph_hash, plantri_version, "
        "plantri_executable_sha256, and plantri_command"
    )
    lines = [
        "# Order-38 strong-flexibility data audit",
        "",
        "## Verdict",
        "",
        "**PASS.** The gzip JSONL is fully readable and satisfies the strict "
        f"order-38 audit: exactly **{len(records):,}** records, contiguous generation "
        "indices, unique canonical hashes, a uniform exact schema, consistent nested "
        "identities, and valid cubic-plane face arithmetic.",
        "",
        "The main JSONL is **not self-contained graph data**. It has no graph6, "
        "planar_code, edge list, adjacency list, rotation system, or faces list. Its "
        f"reconstruction fields are {source_reconstruction_fields}. The recorded "
        "plantri executable is still present and hash-matched. A full plantri stream "
        f"of {reconstruction['generated_count']:,} graphs was replayed; every one of "
        f"the {reconstruction['selected_candidate_count']} selected generation indices "
        "recomputed to its stored canonical hash. Those candidates now have independent "
        "planar_code, graph6, and embedding artifacts outside OneDrive. Reconstruction "
        "is therefore operationally unambiguous for the selected pool, but the source "
        "JSONL alone is not a portable graph certificate.",
        "",
        "> The stored `number_of_witness_cycles` is a deterministic greedy "
        "strong-flexibility cover count. It is not exact hsep, and its stored "
        "`witness_cover_ratio` is witnesses divided by requirements, not hsep "
        "divided by the number of Hamiltonian cycles.",
        "",
        "## Source identity and integrity",
        "",
        _markdown_table(
            ("Item", "Value"),
            (
                ("Path", dataset.path),
                ("Compressed size", f"{dataset.source_size_bytes:,} bytes"),
                ("Compressed SHA-256", dataset.source_sha256),
                ("Decompressed size", f"{dataset.decompressed_size_bytes:,} bytes"),
                ("Decompressed SHA-256", dataset.decompressed_sha256),
                ("JSON records", f"{len(records):,}"),
                ("Blank lines", dataset.blank_line_count),
                ("Generation indices", f"0..{len(records) - 1}, ordered and gap-free"),
                ("Unique graph hashes", f"{len({r['canonical_graph_hash'] for r in records}):,}"),
                ("Order / edges", f"{EXPECTED_ORDER} / {records[0]['edge_count']}"),
                ("Plantri version", dataset.plantri_version),
                ("Plantri executable SHA-256", dataset.plantri_executable_sha256),
                ("Plantri command", " ".join(dataset.plantri_command)),
            ),
        ),
        "",
        "The user-supplied expected count is 50,116 and matches exactly. The original "
        "pipeline's `reference_count` field is null because its built-in count table "
        "ends at order 32; this audit performs the missing explicit comparison.",
        "",
        "## Structural and status invariants",
        "",
        f"- All {len(records):,} rows have order 38 and 57 edges.",
        f"- Every face multiset has {len(records[0]['face_size_multiset'])} sorted even "
        "entries, minimum size four, and boundary sum 114.",
        f"- There are {len(face_counts)} face-size multisets; {len(unique_faces)} occur once.",
        "- Nested hashes, graph orders, edge counts, and face multisets agree with the "
        "top-level fields in every row.",
        "- Both strong-flexibility properties are satisfied in every row; no row is "
        "flagged for candidate review.",
        "- All backtracking counts and times are zero because the original pipeline "
        "cross-checked automatically only through order 24.",
        f"- All-edge requirements are constant at {all_edge['total_ordered_edge_pairs']}; "
        f"path requirements are constant at {paths['number_of_distinct_three_edge_paths']}.",
        "",
        "## Exact record schema",
        "",
        _markdown_table(("Field", "Observed type", "Requirement"), _schema_inventory_rows()),
        "",
        "No schema-version field or external JSON Schema was stored. This audit therefore "
        "checks the exact observed summary schema and rejects missing, extra, wrong-type, "
        "non-finite, or inconsistent fields.",
        "",
        "## Numerical and derived metric inventory",
        "",
        "Ranks are descending competition ranks (`1 + number strictly greater`). "
        "Percentiles are tie-aware mid-percentiles. Robust z-scores use the median and "
        "the first nonzero scale in this order: 1.4826×MAD, IQR/1.349, "
        "(P90−P10)/2.563, range/2; constant metrics receive z=0. Timing metrics are "
        "machine-dependent and also have log1p summaries in `candidate_pool.json`.",
        "",
        _markdown_table(
            (
                "Metric",
                "Min",
                "Median",
                "Mean",
                "P95",
                "P99",
                "Max",
                "Robust scale",
                "Timing",
            ),
            metric_rows,
        ),
        "",
        "Available SAT-difficulty proxies are SAT-call/witness counts, subtour "
        "iterations and constraints, total/query timing summaries, and timing-defined "
        "hardest queries. Automorphism order, symmetry, perfect-matching counts, complete "
        "Hamiltonian-cycle counts, exact hsep, and memory per graph are absent.",
        "",
        "## Associated outputs",
        "",
        _markdown_table(
            ("Artifact", "Audit result"),
            (
                (
                    "Summary CSV",
                    f"present={associated['summary']['exists']}; "
                    f"SHA-256={associated['summary'].get('sha256', 'n/a')}",
                ),
                (
                    "Run metadata",
                    f"present={associated['metadata']['exists']}; "
                    f"SHA-256={associated['metadata'].get('sha256', 'n/a')}",
                ),
                (
                    "All-edge leaderboards",
                    f"{all_edge_artifacts['leaderboard_file_count']} files, "
                    f"{all_edge_artifacts['leaderboard_rows']} rows, "
                    f"{all_edge_artifacts['current_unique_hash_count']} current unique graphs",
                ),
                (
                    "Path leaderboards",
                    f"{path_artifacts['leaderboard_file_count']} files, "
                    f"{path_artifacts['leaderboard_rows']} rows, "
                    f"{path_artifacts['current_unique_hash_count']} current unique graphs",
                ),
                (
                    "Cross-analysis retained union",
                    f"{extremal['cross_analysis_unique_hash_count']} order-38 graphs",
                ),
                (
                    "Metadata/leaderboard identity",
                    extremal.get("metadata_selected_sets_match_leaderboards"),
                ),
                (
                    "Checkpoints/partials",
                    associated["checkpoints_or_partial_files"] or "none",
                ),
                (
                    "Detailed candidate JSONL",
                    associated["detailed_candidate_jsonl_present"],
                ),
            ),
        ),
        "",
        "The extremal graph directories retain older order-34/order-36 files. Current "
        "order-38 artifacts were identified from the current leaderboards/metadata; the "
        "directory contents as a whole must not be interpreted as the current top-K set.",
        "",
        "## Missing source artifacts and consequence",
        "",
        "The summary-detail run did not retain witness cycles or per-constraint assignments. "
        "Accordingly, neither its greedy count nor any later exact-hsep claim can be "
        "independently certified from this JSONL. Later phases must enumerate the complete "
        "Hamiltonian-cycle set and create separate primal and lower-bound certificates.",
        "",
    ]
    return "\n".join(lines)


def _candidate_report_markdown(
    dataset: AuditDataset,
    selection: CandidateSelection,
) -> str:
    core_rows = []
    for name in CORE_SELECTION_METRICS:
        profile = selection.profiles[name]
        core_rows.append(
            (
                name,
                _format_number(profile.minimum),
                _format_number(profile.median),
                _format_number(profile.p95),
                _format_number(profile.p99),
                _format_number(profile.maximum),
                profile.robust_scale_method,
            )
        )
    candidate_rows = []
    for candidate in selection.candidates:
        ae = candidate["source_metrics"]["all_edge_pairs"]
        path = candidate["source_metrics"]["three_edge_paths"]
        reasons = "; ".join(
            reason["code"] for reason in candidate["selection_reasons"]
        )
        candidate_rows.append(
            (
                candidate["selection_order"],
                candidate["canonical_graph_hash"],
                candidate["generation_index"],
                ae["number_of_witness_cycles"],
                ae["total_subtour_constraints"],
                path["number_of_witness_cycles"],
                path["total_subtour_constraints"],
                candidate["face_signature"],
                candidate["face_pattern_frequency"],
                f"{candidate['multivariate_outlier_score']:.3f}",
                reasons,
            )
        )
    unique_rows = []
    by_hash = {
        candidate["canonical_graph_hash"]: candidate
        for candidate in selection.candidates
    }
    for pattern, frequency in sorted(
        dataset.face_pattern_counts.items(), key=lambda item: (item[1], item[0])
    ):
        if frequency != 1:
            continue
        record = next(
            record
            for record in dataset.records
            if tuple(record["face_size_multiset"]) == pattern
        )
        candidate = by_hash.get(record["canonical_graph_hash"])
        if candidate is None:
            continue
        unique_rows.append(
            (
                candidate["canonical_graph_hash"],
                candidate["generation_index"],
                candidate["face_signature"],
                record["all_edge_pairs"]["number_of_witness_cycles"],
                record["three_edge_paths"]["number_of_witness_cycles"],
            )
        )
    full_pool_count = selection.full_pool_candidate_count or len(selection.candidates)
    phase3_pool_worker_hours = 0.5 * full_pool_count
    if selection.debug_graph_hash is None:
        result_paragraph = (
            f"The deterministic candidate pool contains **{len(selection.candidates)}** "
            "distinct canonical graph hashes. The four required top-N strata contribute "
            f"{selection.required_strata_union_size}; all "
            f"{selection.unique_face_graph_count} unique face-multiset graphs are included; "
            "and the top-five joint robust-outlier stratum contributes additional graphs "
            "where it is not already represented."
        )
    else:
        result_paragraph = (
            f"**Debug-filtered output:** this artifact contains only "
            f"`{selection.debug_graph_hash}` from the full deterministic pool. The full "
            f"selection contained {full_pool_count} candidates, had a required-strata "
            f"union of {selection.required_strata_union_size} "
            f"and {selection.unique_face_graph_count} globally unique face-multiset graphs. "
            "This one-graph output must not be presented as the complete candidate pool."
        )
    lines = [
        "# Order-38 diverse candidate selection",
        "",
        "## Result",
        "",
        result_paragraph,
        "",
        "> These rankings screen graphs for further work. The all-edge witness count is "
        "a deterministic greedy feasible-cover count and only a heuristic upper bound "
        "on hsep. The path witness count is a structural heuristic, not an hsep bound.",
        "",
        "## Method",
        "",
        "1. Strictly validate the complete source before ranking anything.",
        "2. Rank top-N strata independently by descending raw value and break ties by "
        "canonical hash.",
        "3. Include top 10 all-edge greedy witnesses, top 5 all-edge subtour counts, "
        "top 5 path greedy witnesses, and top 5 path subtour counts.",
        "4. Include every graph whose exact face-size multiset occurs once.",
        "5. Compute robust z-scores for the four non-alias core metrics. Sum clipped "
        "positive z-scores (0 to 8 per metric) and include the top five joint outliers. "
        "Witness/SAT-call aliases and cover-ratio/average aliases are not double-weighted; "
        "timing is excluded from this invariant score.",
        "6. Among unique-face graphs outside the all-edge top ten, label three deliberate "
        "controls: lowest all-edge greedy count, nearest robust center, and largest "
        "remaining path-subtour count.",
        "7. Deduplicate by canonical hash, aggregate every reason in fixed priority order, "
        "and preserve generation index plus independently replayed graph certificates.",
        "",
        "## Core order-38 distributions",
        "",
        _markdown_table(
            ("Metric", "Min", "Median", "P95", "P99", "Max", "Robust scale"),
            core_rows,
        ),
        "",
        "## Candidate pool",
        "",
        _markdown_table(
            (
                "#",
                "Canonical hash",
                "Index",
                "AE witnesses",
                "AE subtours",
                "Path witnesses",
                "Path subtours",
                "Faces",
                "Face freq.",
                "Joint z+",
                "Selection reasons",
            ),
            candidate_rows,
        ),
        "",
        "Every listed candidate has a matching `.planar_code`, `.g6`, and "
        "`.embedding.json` under `candidate_graphs/`. The JSON pool also embeds base64 "
        "planar_code so later work is not dependent on another generator replay.",
        "",
        "## Unique face-multiset representatives",
        "",
        _markdown_table(
            ("Canonical hash", "Index", "Face multiset", "AE witnesses", "Path witnesses"),
            unique_rows,
        ),
        "",
        "## Estimated next-phase computational cost",
        "",
        "The repository currently has no perfect-matching enumerator, complete "
        "Hamiltonian-cycle enumerator, exact set-cover implementation, or hsep verifier. "
        "Consequently an exact wall-clock estimate would be fabricated. The completed "
        "strong-flexibility timings do not measure either complete cycle enumeration or "
        "set-cover proof search.",
        "",
        "A defensible launch budget is staged as follows:",
        "",
        _markdown_table(
            ("Stage", "Inputs", "Initial budget", "Safeguard / interpretation"),
            (
                (
                    "Phase 3 pilot",
                    "3 diverse candidates",
                    "10 minutes per graph",
                    "Calibrate matching/cycle enumeration; timeout means incomplete only",
                ),
                (
                    "Phase 3 pool",
                    f"full deterministic pool ({full_pool_count} candidates)",
                    f"30 minutes per graph = {phase3_pool_worker_hours:g} "
                    "worker-hours ceiling",
                    "At most 4 workers; checkpoint after every graph and cycle batch",
                ),
                (
                    "Phase 4 pilot",
                    "at least 10 finalists",
                    "2 solver-hours per graph initially",
                    "Retain rigorous L..U intervals; no timeout becomes a lower bound",
                ),
                (
                    "Barnie 49 regression",
                    "1 order-36 benchmark",
                    "mandatory before finalist claims",
                    "Must recover 68 cycles and matching 49/49 certificates",
                ),
            ),
        ),
        "",
        f"Thus the proposed pre-authorized ceiling would be roughly "
        f"{phase3_pool_worker_hours:g} worker-hours for "
        "screening plus 20 solver-hours for a ten-finalist exact pilot, with elapsed time "
        "reduced by at most four workers. These are safety budgets, not predictions. "
        "Actual estimates should be replaced after the three-graph pilot.",
        "",
        "No Phase 3 or Phase 4 computation was launched by this run.",
        "",
    ]
    return "\n".join(lines)


def _candidate_csv(selection: CandidateSelection) -> str:
    core_aliases = {
        "ae_witness": "all_edge_pairs.number_of_witness_cycles",
        "ae_subtour": "all_edge_pairs.total_subtour_constraints",
        "path_witness": "three_edge_paths.number_of_witness_cycles",
        "path_subtour": "three_edge_paths.total_subtour_constraints",
    }
    fields = [
        "selection_order",
        "canonical_graph_hash",
        "generation_index",
        "vertex_count",
        "edge_count",
        "face_signature",
        "face_size_multiset_json",
        "face_pattern_frequency",
        "number_of_nonquadrilateral_faces",
        "maximum_face_size",
        "multivariate_outlier_score",
        "selection_reasons",
    ]
    for alias in core_aliases:
        fields.extend(
            (
                alias,
                f"{alias}_rank",
                f"{alias}_percentile",
                f"{alias}_robust_z",
            )
        )
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for candidate in selection.candidates:
        row: dict[str, Any] = {
            "selection_order": candidate["selection_order"],
            "canonical_graph_hash": candidate["canonical_graph_hash"],
            "generation_index": candidate["generation_index"],
            "vertex_count": candidate["requested_vertex_count"],
            "edge_count": candidate["edge_count"],
            "face_signature": candidate["face_signature"],
            "face_size_multiset_json": json.dumps(
                candidate["face_size_multiset"], separators=(",", ":")
            ),
            "face_pattern_frequency": candidate["face_pattern_frequency"],
            "number_of_nonquadrilateral_faces": candidate[
                "number_of_nonquadrilateral_faces"
            ],
            "maximum_face_size": candidate["maximum_face_size"],
            "multivariate_outlier_score": candidate["multivariate_outlier_score"],
            "selection_reasons": ";".join(
                reason["code"] for reason in candidate["selection_reasons"]
            ),
        }
        for alias, metric in core_aliases.items():
            evidence = candidate["metric_evidence"][metric]
            row[alias] = evidence["value"]
            row[f"{alias}_rank"] = evidence["descending_competition_rank"]
            row[f"{alias}_percentile"] = evidence["tie_aware_midpercentile"]
            row[f"{alias}_robust_z"] = evidence["robust_z"]
        writer.writerow(row)
    return output.getvalue()


def _environment_record(workers: int) -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for package in ("barnette-search", "networkx", "python-sat", "psutil"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    external = {
        command: shutil.which(command)
        for command in ("highs", "cbc", "glpsol", "scip", "gurobi_cl")
    }
    pysat_capabilities: dict[str, bool] = {}
    for name, module, symbol in (
        ("RC2", "pysat.examples.rc2", "RC2"),
        ("Hitman", "pysat.examples.hitman", "Hitman"),
        ("FM", "pysat.examples.fm", "FM"),
    ):
        try:
            imported = __import__(module, fromlist=[symbol])
            getattr(imported, symbol)
        except (ImportError, AttributeError):
            pysat_capabilities[name] = False
        else:
            pysat_capabilities[name] = True
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        commit = None
        status = []
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "dependency_versions": versions,
        "external_optimizers_on_path": external,
        "pysat_exact_cover_capabilities": pysat_capabilities,
        "machine": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "requested_worker_limit": workers,
            "worker_cap": MAX_WORKERS,
            "phase12_worker_processes_used": 0,
            "phase12_execution_note": (
                "audit, selection, artifact inventory, and generator replay are "
                "streaming serial operations; the option records/enforces the cap "
                "for later screening extensions"
            ),
        },
        "git_commit": commit,
        "git_status_short": status,
    }


class _PeakMemoryMonitor:
    def __init__(self) -> None:
        self.peak_bytes: int | None = None
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import psutil
        except ImportError:
            return

        def sample() -> None:
            root = psutil.Process(os.getpid())
            peak = 0
            while not self._stop.wait(0.05):
                total = 0
                try:
                    processes = [root, *root.children(recursive=True)]
                except psutil.Error:
                    processes = []
                for process in processes:
                    try:
                        total += process.memory_info().rss
                    except psutil.Error:
                        pass
                peak = max(peak, total)
                self.samples += 1
            self.peak_bytes = peak

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


class _OutputLock:
    """OS-backed exclusive lock; process exit releases it without stale recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._descriptor: int | None = None

    @staticmethod
    def _acquire_system_lock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release_system_lock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)

    def __enter__(self) -> "_OutputLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        ).encode("utf-8")
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR)
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            try:
                self._acquire_system_lock(descriptor)
            except OSError as error:
                raise RuntimeError(
                    f"another Phase 1--2 run owns the output lock: {self.path}"
                ) from error
            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except BaseException:
            try:
                self._release_system_lock(descriptor)
            except OSError:
                pass
            os.close(descriptor)
            raise
        self._descriptor = descriptor
        return self

    def __exit__(self, *args: object) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            self._release_system_lock(descriptor)
        finally:
            os.close(descriptor)


def _phase12_lock_path(output_directory: Path) -> Path:
    normalized = os.path.normcase(str(output_directory.resolve()))
    identity = sha256(normalized.encode("utf-8")).hexdigest()
    return (
        Path(tempfile.gettempdir())
        / "barnette-search-phase12-locks"
        / f"{identity}.lock"
    )


def _write_phase12_outputs(
    output_directory: Path,
    dataset: AuditDataset,
    selection: CandidateSelection,
    associated: dict[str, Any],
    reconstruction: dict[str, Any],
) -> None:
    for candidate in selection.candidates:
        graph_hash = candidate["canonical_graph_hash"]
        candidate["reconstruction"] = reconstruction["candidates"][graph_hash]
    candidate_json = {
        "schema_version": SCHEMA_VERSION,
        "selection_algorithm_version": SELECTION_ALGORITHM_VERSION,
        "source": {
            "path": str(dataset.path),
            "compressed_size_bytes": dataset.source_size_bytes,
            "compressed_sha256": dataset.source_sha256,
            "decompressed_size_bytes": dataset.decompressed_size_bytes,
            "decompressed_sha256": dataset.decompressed_sha256,
            "record_count": len(dataset.records),
            "expected_record_count": EXPECTED_RECORD_COUNT,
            "order": EXPECTED_ORDER,
            "plantri_version": dataset.plantri_version,
            "plantri_executable_sha256": dataset.plantri_executable_sha256,
            "plantri_command": dataset.plantri_command,
        },
        "selection": {
            "candidate_count": len(selection.candidates),
            "full_pool_candidate_count": selection.full_pool_candidate_count,
            "debug_graph_hash": selection.debug_graph_hash,
            "full_pool_required_strata_union_size": selection.required_strata_union_size,
            "global_unique_face_graph_count": selection.unique_face_graph_count,
            "reason_priority": REASON_PRIORITY,
            "core_multivariate_metrics": CORE_SELECTION_METRICS,
            "multivariate_score": (
                "sum of max(0, min(8, robust_z)) over the four core metrics"
            ),
            "greedy_value_warning": (
                "all-edge and path witness counts are deterministic greedy "
                "selection heuristics, not exact hsep"
            ),
        },
        "metric_profiles": {
            name: _profile_record(profile)
            for name, profile in sorted(selection.profiles.items())
        },
        "candidates": selection.candidates,
    }
    _atomic_write_json(output_directory / "candidate_pool.json", candidate_json)
    _atomic_write_text(
        output_directory / "candidate_pool.csv", _candidate_csv(selection)
    )
    _atomic_write_text(
        output_directory / "data_audit.md",
        _data_audit_markdown(dataset, selection, associated, reconstruction),
    )
    _atomic_write_text(
        output_directory / "candidate_selection_report.md",
        _candidate_report_markdown(dataset, selection),
    )
    _atomic_write_json(output_directory / "associated_artifact_inventory.json", associated)
    _atomic_write_text(
        output_directory / "phase12_implementation_plan.md",
        """# Phase 1--2 implementation plan

1. Strictly audit the complete order-38 result and associated provenance.
2. Profile all available scalar metrics and derive face-structure metrics.
3. Select a deterministic diverse pool with explicit, aggregated reasons.
4. Replay the pinned plantri binary and preserve graph certificates for every candidate.
5. Stop before Hamiltonian screening and exact hsep; present a staged cost budget.

Established validation, SAT, planar-code, enumeration, and flexibility modules remain unchanged.
""",
    )


def _clear_phase12_outputs(output_directory: Path) -> None:
    """Remove only files owned by this workflow, preserving unrelated user data."""
    owned_names = {
        "data_audit.md",
        "candidate_pool.csv",
        "candidate_pool.json",
        "candidate_selection_report.md",
        "associated_artifact_inventory.json",
        "phase12_implementation_plan.md",
        "phase12_run_metadata.json",
        "phase12_failure.json",
        "reconstruction_manifest.json",
        "reconstruction.checkpoint.json",
        "SHA256SUMS.txt",
    }
    for name in owned_names:
        (output_directory / name).unlink(missing_ok=True)
    graph_directory = output_directory / "candidate_graphs"
    if graph_directory.is_dir():
        for pattern in ("*.planar_code", "*.g6", "*.embedding.json"):
            for path in graph_directory.glob(pattern):
                if path.is_file() and path.parent.resolve() == graph_directory.resolve():
                    path.unlink()


def _owned_phase12_files(output_directory: Path) -> list[Path]:
    """Return successful workflow files, excluding notes and crash temporaries."""
    top_level_names = (
        "data_audit.md",
        "candidate_pool.csv",
        "candidate_pool.json",
        "candidate_selection_report.md",
        "associated_artifact_inventory.json",
        "phase12_implementation_plan.md",
        "phase12_run_metadata.json",
        "reconstruction_manifest.json",
    )
    paths = [
        output_directory / name
        for name in top_level_names
        if (output_directory / name).is_file()
    ]
    graph_directory = output_directory / "candidate_graphs"
    if graph_directory.is_dir():
        for pattern in ("*.planar_code", "*.g6", "*.embedding.json"):
            paths.extend(path for path in graph_directory.glob(pattern) if path.is_file())
    return sorted(set(paths))


def _has_completed_phase12_output(output_directory: Path) -> bool:
    metadata_path = output_directory / "phase12_run_metadata.json"
    checksum_path = output_directory / "SHA256SUMS.txt"
    if not metadata_path.is_file() or not checksum_path.is_file():
        return False
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected: dict[str, str] = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            if not _HASH_PATTERN.fullmatch(digest) or relative in expected:
                return False
            expected[relative] = digest
        owned = {
            path.relative_to(output_directory).as_posix(): _sha256_file(path)
            for path in _owned_phase12_files(output_directory)
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("status") == "complete"
        and expected == owned
    )


def _run_phase12_locked(
    source_path: Path,
    *,
    output_directory: Path,
    plantri_executable: Path | None = None,
    expected_count: int = EXPECTED_RECORD_COUNT,
    workers: int = 1,
    graph_hash: str | None = None,
    resume: bool = False,
    overwrite: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Run the complete Phase 1--2 audit, selection, and reconstruction workflow."""
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if resume and overwrite:
        raise ValueError("--resume and --overwrite are mutually exclusive")
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    if overwrite:
        _clear_phase12_outputs(output_directory)
    final_paths = (
        output_directory / "data_audit.md",
        output_directory / "candidate_pool.csv",
        output_directory / "candidate_pool.json",
        output_directory / "candidate_selection_report.md",
        output_directory / "phase12_run_metadata.json",
    )
    if not (resume or overwrite):
        existing = [path for path in final_paths if path.exists()]
        if existing:
            raise FileExistsError(f"refusing to overwrite existing outputs: {existing}")

    started_at = datetime.now(timezone.utc)
    started = perf_counter()
    monitor = _PeakMemoryMonitor()
    monitor.start()
    try:
        print("auditing complete order-38 JSONL...", flush=True)
        dataset = audit_source(
            source_path,
            expected_order=EXPECTED_ORDER,
            expected_count=expected_count,
        )
        print("calculating metric distributions and candidate strata...", flush=True)
        selection = select_candidates(dataset)
        if graph_hash is not None:
            if _HASH_PATTERN.fullmatch(graph_hash) is None:
                raise ValueError("--graph-hash must be 64 lowercase hexadecimal characters")
            matching = [
                candidate
                for candidate in selection.candidates
                if candidate["canonical_graph_hash"] == graph_hash
            ]
            if not matching:
                raise ValueError(
                    "--graph-hash debugging currently accepts a hash in the selected pool"
                )
            selection.candidates = matching
            selection.debug_graph_hash = graph_hash
        print("inventorying associated metadata and retained artifacts...", flush=True)
        associated = inventory_associated_artifacts(dataset)
        executable = (
            plantri_executable.resolve()
            if plantri_executable is not None
            else Path(dataset.plantri_command[0]).resolve()
        )
        print("replaying pinned plantri stream for candidate reconstruction...", flush=True)
        reconstruction = reconstruct_candidates(
            dataset,
            selection,
            executable=executable,
            output_directory=output_directory,
            resume=resume,
            overwrite=overwrite,
        )
        _write_phase12_outputs(
            output_directory, dataset, selection, associated, reconstruction
        )
    finally:
        monitor.stop()
    elapsed = perf_counter() - started
    environment = _environment_record(workers)
    environment["machine"]["aggregate_peak_rss_bytes"] = monitor.peak_bytes
    environment["machine"]["memory_samples"] = monitor.samples
    (output_directory / "phase12_failure.json").unlink(missing_ok=True)
    output_hashes = {
        path.relative_to(output_directory).as_posix(): _sha256_file(path)
        for path in _owned_phase12_files(output_directory)
        if path.name != "phase12_run_metadata.json"
    }
    metadata_record = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": elapsed,
        "command": [sys.executable, "-m", "barnette_search.hsep_order38", *sys.argv[1:]],
        "source_path": str(source_path.resolve()),
        "source_sha256": dataset.source_sha256,
        "output_directory": str(output_directory),
        "candidate_count": len(selection.candidates),
        "requested_worker_limit": workers,
        "phase12_worker_processes_used": 0,
        "random_seed": None,
        "ordering": (
            "source generation index; hash tie-breaks; fixed reason priority"
        ),
        "reconstruction": {
            key: value
            for key, value in reconstruction.items()
            if key != "candidates"
        },
        "environment": environment,
        "output_sha256_excluding_metadata_and_checksum_file": output_hashes,
        "next_phase_status": "not_started",
    }
    _atomic_write_json(output_directory / "phase12_run_metadata.json", metadata_record)
    checksum_paths = _owned_phase12_files(output_directory)
    checksum_text = "".join(
        f"{_sha256_file(path)}  {path.relative_to(output_directory).as_posix()}\n"
        for path in checksum_paths
    )
    _atomic_write_text(output_directory / "SHA256SUMS.txt", checksum_text)
    print(
        f"Phase 1--2 complete: {len(selection.candidates)} candidates in "
        f"{elapsed:.3f}s; Phase 3/4 not started",
        flush=True,
    )
    return tuple(selection.candidates)


def run_phase12(
    source_path: Path,
    *,
    output_directory: Path,
    plantri_executable: Path | None = None,
    expected_count: int = EXPECTED_RECORD_COUNT,
    workers: int = 1,
    graph_hash: str | None = None,
    resume: bool = False,
    overwrite: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Run Phase 1--2 under an exclusive output lock and record failures."""
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if resume and overwrite:
        raise ValueError("--resume and --overwrite are mutually exclusive")
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    with _OutputLock(_phase12_lock_path(output_directory)):
        try:
            return _run_phase12_locked(
                source_path,
                output_directory=output_directory,
                plantri_executable=plantri_executable,
                expected_count=expected_count,
                workers=workers,
                graph_hash=graph_hash,
                resume=resume,
                overwrite=overwrite,
            )
        except BaseException as error:
            if not _has_completed_phase12_output(output_directory):
                failure = {
                    "schema_version": SCHEMA_VERSION,
                    "status": "failed",
                    "failed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source_path": str(source_path.resolve()),
                    "output_directory": str(output_directory),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "phase3_or_phase4_started": False,
                }
                _atomic_write_json(
                    output_directory / "phase12_failure.json", failure
                )
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="completed order-38 strong-flexibility JSONL or JSONL.gz",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--plantri",
        type=Path,
        help="pinned plantri executable; defaults to the path stored in the records",
    )
    parser.add_argument("--expected-count", type=int, default=EXPECTED_RECORD_COUNT)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--graph-hash",
        help="debug one hash already present in the deterministic selected pool",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    run_phase12(
        arguments.input,
        output_directory=arguments.output_dir,
        plantri_executable=arguments.plantri,
        expected_count=arguments.expected_count,
        workers=arguments.workers,
        graph_hash=arguments.graph_hash,
        resume=arguments.resume,
        overwrite=arguments.overwrite,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
