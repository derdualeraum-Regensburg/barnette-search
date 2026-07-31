#!/usr/bin/env python3
"""Create the deterministic double-ladder packing-lift analysis package."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any, Iterable, Sequence

from barnette_search.double_ladder_packing import (
    PackingDataset,
    block_alignment,
    canonical_json_bytes,
    canonical_structural_packing,
    candidate_conflict_summary,
    expansion_map_record,
    load_chain,
    packing_formula,
    packing_summary,
    requirement_alignment,
    requirement_record,
    sha256_file,
    verify_manifest,
)


SCHEMA = "double-ladder-packing-lift-analysis-v1"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, canonical_json_bytes(value))


def write_text(path: Path, value: str) -> None:
    atomic_write(path, value.replace("\r\n", "\n").encode("utf-8"))


def write_gzip_json(path: Path, value: Any) -> None:
    data = canonical_json_bytes(value)
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as target:
            target.write(data)
    os.replace(temporary, path)


def git_output(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repo, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def artifact_entry(role: str, path: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def inventory(
    datasets: Sequence[PackingDataset], sequence_root: Path, prediction_root: Path
) -> dict[str, Any]:
    manifests = [
        sequence_root / "order_36" / "SHA256SUMS.txt",
        sequence_root / "ladder-analysis" / "SHA256SUMS.txt",
        prediction_root / "SHA256SUMS.txt",
        *(dataset.graph_directory / "SHA256SUMS.txt" for dataset in datasets[1:]),
    ]
    graph_records = []
    for dataset in datasets:
        seen: set[Path] = set()
        artifacts = []
        for role, path in dataset.source_files.items():
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            artifacts.append(artifact_entry(role, path))
        graph_records.append(
            {
                "label": dataset.label,
                "parameters": {"a": dataset.a, "b": dataset.b},
                "canonical_graph_hash": dataset.graph.graph_hash,
                "order": len(dataset.graph.rotation),
                "edge_count": len(dataset.edges),
                "complete_hamiltonian_cycle_count": len(dataset.cycles),
                "optimal_packing_size": len(dataset.requirements),
                "formula_value": packing_formula(dataset.a, dataset.b),
                "artifacts": artifacts,
            }
        )
    return {
        "schema": SCHEMA,
        "scope": [dataset.label for dataset in datasets],
        "graphs": graph_records,
        "verified_manifests": [verify_manifest(path) for path in manifests],
        "existing_independent_verification": {
            "order_36": json.loads(
                (sequence_root / "order_36" / "independent_verification.json").read_text(
                    encoding="utf-8"
                )
            ),
            "prediction_package": json.loads(
                (prediction_root / "independent_verification.json").read_text(encoding="utf-8")
            ),
        },
        "integrity_scope_note": (
            "D(9,7) is extracted from immutable order-36 JSONL collections and relabelled "
            "with the certified original_to_canonical map. The three prospective graphs "
            "are read directly from their immutable per-graph directories."
        ),
    }


def inventory_markdown(value: dict[str, Any]) -> str:
    lines = [
        "# Artifact inventory",
        "",
        "All paths below were read-only inputs. SHA-256 values bind this analysis to the existing artifacts.",
        "",
        "| graph | hash | order | cycles | packing | formula |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for graph in value["graphs"]:
        lines.append(
            f"| {graph['label']} | `{graph['canonical_graph_hash']}` | {graph['order']} | "
            f"{graph['complete_hamiltonian_cycle_count']} | {graph['optimal_packing_size']} | "
            f"{graph['formula_value']} |"
        )
    lines += ["", "## Manifest checks", ""]
    for item in value["verified_manifests"]:
        lines.append(
            f"- `{item['path']}`: **{item['status']}**, {item['entries_checked']} entries, "
            f"SHA-256 `{item['sha256']}`."
        )
    lines += ["", "## Bound artifacts", ""]
    for graph in value["graphs"]:
        lines.append(f"### {graph['label']}")
        lines.append("")
        for artifact in graph["artifacts"]:
            lines.append(
                f"- {artifact['role']}: `{artifact['path']}` ({artifact['size_bytes']} bytes; "
                f"`{artifact['sha256']}`)."
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def inserted_edges_for(dataset: PackingDataset) -> set[tuple[int, int]]:
    if dataset.graph_directory is None:
        return set()
    certificate = json.loads(
        (dataset.graph_directory / "expansion_certificate.json").read_text(encoding="utf-8")
    )
    return {tuple(sorted(map(int, edge))) for edge in certificate["inserted_edges_target_labels"]}


def normalized_packings(datasets: Sequence[PackingDataset]) -> dict[str, Any]:
    graphs = []
    for dataset in datasets:
        inserted = inserted_edges_for(dataset)
        original_records = [
            requirement_record(
                dataset, requirement, ordinal=index, inserted_edges=inserted
            )
            for index, requirement in enumerate(dataset.requirements)
        ]
        structural = canonical_structural_packing(dataset, anchor="A")
        structural_records = [
            requirement_record(
                dataset, requirement, ordinal=index, inserted_edges=inserted
            )
            for index, requirement in enumerate(structural)
        ]
        graphs.append(
            {
                "label": dataset.label,
                "canonical_graph_hash": dataset.graph.graph_hash,
                "parameters": {"a": dataset.a, "b": dataset.b},
                "original_immutable_packing": {
                    "requirements": original_records,
                    "summary": packing_summary(dataset, dataset.requirements),
                },
                "structural_packing_anchor_A": {
                    "requirements": structural_records,
                    "summary": packing_summary(dataset, structural),
                },
            }
        )
    return {"schema": SCHEMA, "graphs": graphs}


def write_normalized_csv(path: Path, normalized: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as target:
        fields = [
            "graph",
            "packing",
            "ordinal",
            "included_edge_index",
            "excluded_edge_index",
            "included_coordinate",
            "excluded_coordinate",
            "included_edge_class",
            "excluded_edge_class",
            "included_is_boundary",
            "excluded_is_boundary",
            "touches_inserted_gadget",
            "coverage_size",
            "coverage_shape",
            "coverage_cycle_classes",
        ]
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for graph in normalized["graphs"]:
            for packing_key in ("original_immutable_packing", "structural_packing_anchor_A"):
                for record in graph[packing_key]["requirements"]:
                    writer.writerow(
                        {
                            "graph": graph["label"],
                            "packing": packing_key,
                            "ordinal": record["ordinal"],
                            "included_edge_index": record["included_edge_index"],
                            "excluded_edge_index": record["excluded_edge_index"],
                            "included_coordinate": json.dumps(
                                record["included_coordinate"], sort_keys=True, separators=(",", ":")
                            ),
                            "excluded_coordinate": json.dumps(
                                record["excluded_coordinate"], sort_keys=True, separators=(",", ":")
                            ),
                            "included_edge_class": record["included_edge_details"]["edge_class"],
                            "excluded_edge_class": record["excluded_edge_details"]["edge_class"],
                            "included_is_boundary": record["included_edge_details"][
                                "is_cap_or_boundary_edge"
                            ],
                            "excluded_is_boundary": record["excluded_edge_details"][
                                "is_cap_or_boundary_edge"
                            ],
                            "touches_inserted_gadget": record["touches_inserted_gadget"],
                            "coverage_size": record["coverage_size"],
                            "coverage_shape": record["coverage_shape"],
                            "coverage_cycle_classes": ";".join(record["coverage_cycle_classes"]),
                        }
                    )
    os.replace(temporary, path)


def expansion_and_alignment(
    datasets: Sequence[PackingDataset], normalized: dict[str, Any], sequence_root: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    expansion_records = []
    alignments = []
    increments = []
    for index, (source, target) in enumerate(zip(datasets, datasets[1:])):
        certificate = target.graph_directory / "expansion_certificate.json"  # type: ignore[operator]
        expansion_records.append(expansion_map_record(source, target, certificate))
        original_alignment = requirement_alignment(source, target, certificate)
        source_original = normalized["graphs"][index]["original_immutable_packing"]["requirements"]
        target_original = normalized["graphs"][index + 1]["original_immutable_packing"]["requirements"]
        axis = expansion_records[-1]["selected_ladder"]
        coverage_alignment = block_alignment(source_original, target_original, axis)
        anchor = "A" if axis == "B" else "B"
        source_structural = canonical_structural_packing(source, anchor=anchor)
        target_structural = canonical_structural_packing(target, anchor=anchor)
        structural_alignment = requirement_alignment(
            source,
            target,
            certificate,
            source_requirements=source_structural,
            target_requirements=target_structural,
        )
        alignments.append(
            {
                "transition": f"{source.label} -> {target.label}",
                "selected_ladder": axis,
                "original_certificates": original_alignment,
                "direct_structural_coverage_block_alignment": coverage_alignment,
                "constructed_structural_certificates": structural_alignment,
                "constructed_exception_anchor": anchor,
            }
        )
        new_ordinals = structural_alignment["literal_new_target_requirement_ordinals"]
        target_inserted = inserted_edges_for(target)
        new_records = [
            requirement_record(
                target,
                target_structural[ordinal],
                ordinal=ordinal,
                inserted_edges=target_inserted,
            )
            for ordinal in new_ordinals
        ]
        increments.append(
            {
                "transition": f"{source.label} -> {target.label}",
                "expanded_ladder": axis,
                "source_parameters": {"a": source.a, "b": source.b},
                "target_parameters": {"a": target.a, "b": target.b},
                "source_size": len(source_structural),
                "target_size": len(target_structural),
                "increment": len(target_structural) - len(source_structural),
                "expected_increment": source.a + 2 if axis == "B" else source.b + 2,
                "path_aware_inherited_requirement_count": structural_alignment[
                    "literal_path_aware_ordered_requirement_overlap"
                ],
                "new_requirement_count": len(new_records),
                "new_requirements": new_records,
                "new_support_size_distribution": dict(
                    sorted(
                        {
                            size: sum(record["coverage_size"] == size for record in new_records)
                            for size in {record["coverage_size"] for record in new_records}
                        }.items()
                    )
                ),
                "disjointness_reason": (
                    "The standalone verifier recomputes all target coverage sets. The new "
                    "sets and the chosen images of inherited requirements are members of one "
                    "verified pairwise-disjoint structural packing."
                ),
            }
        )
    ladder_family = json.loads(
        (sequence_root / "ladder-analysis" / "ladder_family.json").read_text(encoding="utf-8")
    )
    barnie_record = next(
        record
        for record in ladder_family["graphs"]
        if record["canonical_graph_hash"] == datasets[0].graph.graph_hash
    )
    label_maps = [
        {
            "label": dataset.label,
            "canonical_graph_hash": dataset.graph.graph_hash,
            "canonical_vertex_to_model": [
                [vertex, list(dataset.graph.model_by_vertex[vertex])]
                for vertex in sorted(dataset.graph.model_by_vertex)
            ],
            "artifact_original_to_canonical": (
                barnie_record["canonical_embedding"]["original_to_canonical"]
                if index == 0
                else list(range(len(dataset.graph.rotation)))
            ),
            "label_note": (
                "D(9,7) exact-cycle and packing labels require the emitted nonidentity map; "
                "the prediction-test per-graph artifacts are already in their canonical labels."
                if index == 0
                else "artifact labels are canonical"
            ),
        }
        for index, dataset in enumerate(datasets)
    ]
    return (
        {"schema": SCHEMA, "graph_label_maps": label_maps, "expansions": expansion_records},
        {"schema": SCHEMA, "alignments": alignments},
        {"schema": SCHEMA, "increments": increments},
    )


def alignment_report(value: dict[str, Any]) -> str:
    lines = [
        "# Packing alignment report",
        "",
        "The ordered-requirement comparison is path-aware: a deleted rail edge may be represented by any one edge of its certified three-edge replacement path. The automorphism maximum exhausts all graph automorphisms returned by exact graph isomorphism.",
        "",
        "| transition | raw endpoint coincidence | unshifted structural | certified path-aware | coverage blocks | automorphism maximum | structural construction |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in value["alignments"]:
        original = item["original_certificates"]
        structural = item["constructed_structural_certificates"]
        lines.append(
            f"| {item['transition']} | {original['raw_canonical_endpoint_pair_coincidence']} | "
            f"{original['unshifted_structural_coordinate_pair_overlap']} | "
            f"{original['literal_path_aware_ordered_requirement_overlap']}/"
            f"{original['source_requirement_count']} | "
            f"{item['direct_structural_coverage_block_alignment']['exact_target_coverage_block_overlap']}/"
            f"{original['source_requirement_count']} | "
            f"{original['maximum_automorphism_aligned_ordered_requirement_overlap']}/"
            f"{original['source_requirement_count']} | "
            f"{structural['literal_path_aware_ordered_requirement_overlap']}/"
            f"{structural['source_requirement_count']} (anchor {item['constructed_exception_anchor']}) |"
        )
    lines += [
        "",
        "The first two immutable greedy packings are therefore not nested, even after all graph automorphisms. The third happens to be literally nested. In every transition a different, explicitly emitted optimal structural packing is fully nested under the path-aware convention.",
    ]
    return "\n".join(lines) + "\n"


def coverage_output(normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "definition": "Cov(e,f) = Hamiltonian cycles containing e and avoiding f",
        "graphs": [
            {
                "label": graph["label"],
                "original": [
                    {
                        "ordinal": record["ordinal"],
                        "coverage": record["coverage_cycle_classes"],
                    }
                    for record in graph["original_immutable_packing"]["requirements"]
                ],
                "structural": [
                    {
                        "ordinal": record["ordinal"],
                        "coverage": record["coverage_cycle_classes"],
                    }
                    for record in graph["structural_packing_anchor_A"]["requirements"]
                ],
            }
            for graph in normalized["graphs"]
        ],
    }


def checkerboard_output(datasets: Sequence[PackingDataset], normalized: dict[str, Any]) -> dict[str, Any]:
    graphs = []
    for dataset, graph in zip(datasets, normalized["graphs"]):
        summary = graph["original_immutable_packing"]["summary"]
        hole = next(key for key in summary["uncovered_cycle_classes"] if key.startswith("T"))
        graphs.append(
            {
                "label": dataset.label,
                "extended_grid_dimensions": [dataset.a + 2, dataset.b + 2],
                "smaller_checkerboard_color_size": packing_formula(dataset.a, dataset.b),
                "actual_model": {
                    "four_exception_singletons": 4,
                    "boundary_turn_singletons": 2 * dataset.a + 2 * dataset.b - 4,
                    "interior_dominoes": ((dataset.a - 2) * (dataset.b - 2) - 1) // 2,
                    "uncovered_turn_hole": hole,
                },
                "hole_has_majority_interior_parity": (
                    sum(map(int, hole[2:-1].split(","))) % 2 == 0
                ),
            }
        )
    return {
        "schema": SCHEMA,
        "conclusion": (
            "The checkerboard hypothesis is correct as a parity/cardinality model, but the "
            "certificates do not canonically attach one raw requirement to each cell of the "
            "extended grid. Their intrinsic description is four exception monomers, all "
            "boundary turn monomers, and a domino tiling of the odd-by-odd interior turn grid "
            "after deleting one majority-color cell."
        ),
        "graphs": graphs,
    }


def svg_grid(dataset: PackingDataset, records: Sequence[dict[str, Any]]) -> str:
    cell = 34
    margin = 70
    width = margin * 2 + dataset.b * cell
    height = margin * 2 + dataset.a * cell
    support_blocks = [record["coverage_cycle_classes"] for record in records]
    hole = set(dataset.cycle_keys) - {key for block in support_blocks for key in block}
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="25" text-anchor="middle" font-family="sans-serif" font-size="18">{dataset.label}: certified turn-grid packing</text>',
    ]
    for i in range(dataset.a):
        for j in range(dataset.b):
            x = margin + j * cell
            y = margin + i * cell
            key = f"T({i},{j})"
            boundary = i in (0, dataset.a - 1) or j in (0, dataset.b - 1)
            fill = "#dbeafe" if boundary else "#f8fafc"
            if key in hole:
                fill = "#fecaca"
            lines.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" stroke="#64748b"/>'
            )
            lines.append(
                f'<text x="{x+cell/2}" y="{y+cell/2+4}" text-anchor="middle" font-family="monospace" font-size="9">{i},{j}</text>'
            )
    for block in support_blocks:
        if len(block) != 2 or not all(key.startswith("T") for key in block):
            continue
        coords = [tuple(map(int, key[2:-1].split(","))) for key in block]
        centers = [
            (margin + j * cell + cell / 2, margin + i * cell + cell / 2) for i, j in coords
        ]
        lines.append(
            f'<line x1="{centers[0][0]}" y1="{centers[0][1]}" x2="{centers[1][0]}" y2="{centers[1][1]}" stroke="#7c3aed" stroke-width="7" stroke-linecap="round" opacity="0.65"/>'
        )
    lines += [
        f'<text x="{margin}" y="{height-20}" font-family="sans-serif" font-size="12">blue: boundary singleton; purple: interior domino; red: uncovered turn cell; four exception singletons are off-grid</text>',
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def svg_increment(item: dict[str, Any], number: int) -> str:
    axis = item["expanded_ladder"]
    count = item["increment"]
    singles = item["new_support_size_distribution"].get(1, item["new_support_size_distribution"].get("1", 0))
    doubles = item["new_support_size_distribution"].get(2, item["new_support_size_distribution"].get("2", 0))
    a = item["target_parameters"]["a"]
    b = item["target_parameters"]["b"]
    cell = 27
    margin_x = 70
    margin_y = 58
    width = margin_x * 2 + b * cell
    height = margin_y + a * cell + 55
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">{item["transition"]}: new {axis}-strip</text>',
    ]
    for i in range(a):
        for j in range(b):
            is_new = i in (1, 2) if axis == "A" else j in (1, 2)
            is_boundary = i in (0, a - 1) or j in (0, b - 1)
            fill = "#bfdbfe" if is_new else "#e2e8f0"
            if is_new and is_boundary:
                fill = "#60a5fa"
            x = margin_x + j * cell
            y = margin_y + i * cell
            lines.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" stroke="#64748b"/>'
            )
            if is_new:
                lines.append(
                    f'<text x="{x+cell/2}" y="{y+cell/2+3}" text-anchor="middle" font-family="monospace" font-size="8">{i},{j}</text>'
                )
    if axis == "B":
        for i in range(1, a - 1):
            y = margin_y + i * cell + cell / 2
            lines.append(
                f'<line x1="{margin_x+1*cell+cell/2}" y1="{y}" x2="{margin_x+2*cell+cell/2}" y2="{y}" stroke="#7c3aed" stroke-width="6" stroke-linecap="round"/>'
            )
    else:
        for j in range(1, b - 1):
            x = margin_x + j * cell + cell / 2
            lines.append(
                f'<line x1="{x}" y1="{margin_y+1*cell+cell/2}" x2="{x}" y2="{margin_y+2*cell+cell/2}" stroke="#7c3aed" stroke-width="6" stroke-linecap="round"/>'
            )
    lines += [
        f'<text x="{width/2}" y="{height-20}" text-anchor="middle" font-family="sans-serif" font-size="12">gray inherited; blue new coordinates; dark blue 4 boundary singletons; purple {doubles} dominoes; net +{count}</text>',
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def svg_checkerboard(a: int, b: int) -> str:
    rows, columns = a + 2, b + 2
    cell = 28
    margin = 55
    width = columns * cell + 2 * margin
    height = rows * cell + 2 * margin
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="17">D({a},{b}): auxiliary ({a+2}) x ({b+2}) checkerboard</text>',
    ]
    selected = 0
    for i in range(rows):
        for j in range(columns):
            odd = (i + j) % 2 == 1
            selected += odd
            lines.append(
                f'<rect x="{margin+j*cell}" y="{margin+i*cell}" width="{cell}" height="{cell}" fill="{"#334155" if odd else "#f8fafc"}" stroke="#94a3b8"/>'
            )
    lines += [
        f'<text x="{width/2}" y="{height-18}" text-anchor="middle" font-family="sans-serif" font-size="13">smaller parity class: {selected}; equal to packing size (cardinality model, not a canonical raw-edge labeling)</text>',
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def symbolic_definition() -> str:
    return r"""# Symbolic packing definition

## Graph coordinates

For ladder `L` in `{A,B}`, let `r_L(t)` be its rung at boundary `t`, and let
`ell_L(t,s)` be rail `s` in cell `t`.  The four connector edges are ordered as
in the certified model.  Write `T(i,j)` for the Hamiltonian cycle turning in
cell `i` of `A` and cell `j` of `B`; write `R` for the all-rails cycle and
`X0011`, `X0101`, `X1010`, `X1100` for the four connector exceptions.

## Packing P(a,b)

Assume odd `a,b >= 3`.

1. Isolate the four exceptions. Anchored on ladder `A`, use
   `(r_A(0),r_A(1))`, `(r_A(a),r_A(a-1))`,
   `(ell_A(0,0),ell_A(0,1))`, and `(ell_A(0,1),ell_A(0,0))`.
   The symmetric four requirements on `B` are interchangeable.
2. Isolate every boundary turn. For every `0 <= j < b`, use
   `(r_A(0),ell_B(j,j mod 2))` and
   `(r_A(a),ell_B(j,1-j mod 2))`. For `1 <= i <= a-2`, use
   `(r_B(0),ell_A(i,i mod 2))` and
   `(r_B(b),ell_A(i,1-i mod 2))`.
3. Tile the interior turn grid `1 <= i <= a-2`, `1 <= j <= b-2` by
   dominoes after deleting one majority-parity cell. A horizontal-in-`A`
   domino `{T(p-1,j),T(p,j)}` is represented by
   `(r_A(p),ell_B(j,0))`; a horizontal-in-`B` domino
   `{T(i,q-1),T(i,q)}` is represented by `(r_B(q),ell_A(i,0))`.

The emitted canonical choice deletes `T(a-2,b-2)`, pairs `A`-rows
`1-2,3-4,...,a-4-(a-3)` in every interior `B` column, and pairs the remaining
last `A` row along `B`, leaving its far corner.

## Status

This definition is label-independent. It was independently evaluated against
all complete Hamiltonian universes for the four in-scope graphs. Its general
packing property follows from the cycle-class incidence table proved in
`proof_draft.md`. It is a lower-bound construction only; it does not supply a
general separating family of the same cardinality.
"""


def proof_draft() -> str:
    return r"""# Proof draft: the double-ladder lower packing

## Classification lemma

Let `a,b` be odd and at least three. Every Hamiltonian cycle of `D(a,b)` is
exactly one of:

- `R`, using all four connectors, every rail, and no rung;
- `T(i,j)`, for `0 <= i < a`, `0 <= j < b`, using all four connectors,
  omitting the two rails in cell `i` of `A` and cell `j` of `B`, and using the
  two rungs bounding each omitted rail pair;
- the four cycles `X0011`, `X0101`, `X1010`, `X1100`.

For completeness, this is not merely inferred from the four computations.
Put binary variables `x_(t,s)` on rail `s` of cell `t`, `y_t` on rung `t`,
and `c_(0,s),c_(m,s)` on the endpoint connectors of a ladder of length `m`.
At an internal vertex the Hamiltonian degree equation is

`x_(t-1,s) + x_(t,s) + y_t = 2`,

and the endpoint equations are `x_(0,s)+y_0+c_(0,s)=2` and
`x_(m-1,s)+y_m+c_(m,s)=2`. Subtracting the two rail equations gives
`d_t=-d_(t-1)` for `d_t=x_(t,0)-x_(t,1)`. Thus the endpoint bits determine
the alternating rail difference, and then each rung bit is forced. This is a
two-state induction along the ladder.

If all four connector bits are one, `d_0=0`, so both rails agree in every
cell. A zero rail pair forces the two adjacent rungs. Two zero pairs enclose a
separate cycle, hence a connected spanning solution has either no zero pair or
one. The two ladders must make the same choice type: mixed all-rail/turn
solutions are two disjoint cycles. This gives `R` and the `ab` independent
turn pairs. If exactly two connector bits are one, applying `d_t=(-1)^t d_0`
at the far endpoint (using odd `m`) gives the following four connected
solutions; the other two choices of a two-element connector set close a
component before all vertices are reached (rail strings are shown from cell
zero):

| class | A rungs | A rails `(0,1)` | B rungs | B rails `(0,1)` |
|---|---|---|---|---|
| `X0011` | only `r_A(0)` | all/all | all | `1010...1` / `0101...0` |
| `X1100` | only `r_A(a)` | all/all | all | `0101...0` / `1010...1` |
| `X0101` | all | `1010...1` / `0101...0` | only `r_B(0)` | all/all |
| `X1010` | all | `0101...0` / `1010...1` | only `r_B(b)` | all/all |

Zero connectors cannot give a spanning connected cycle, and the cut between
the ladders rules out one or three connectors. This exhausts the recurrence.

## Coverage lemma

The incidence table immediately gives:

- the four exception requirements in the definition cover their named `X`
  cycle and no other cycle;
- each boundary requirement covers exactly its named boundary `T(i,j)`;
- `(r_A(p),ell_B(j,s))`, with `0<p<a`, covers exactly
  `{T(p-1,j),T(p,j)}` for either rail `s`;
- `(r_B(q),ell_A(i,s))`, with `0<q<b`, covers exactly
  `{T(i,q-1),T(i,q)}` for either rail `s`;
- `R` covers none of these requirements because every one has a rung as its
  included edge, except the four exception isolators, whose two rail/rung
  incidences agree on `R`.

The parity choices on boundary excluded rails are exactly the rail occupied by
the possible exception containing the included endpoint rung, so that the
exception is excluded from that boundary requirement's coverage.

## Packing theorem

The four exception supports, all boundary-turn singleton supports, and all
interior-domino supports are disjoint. They partition all Hamiltonian cycles
except `R` and the deleted interior turn cell. Therefore every Hamiltonian
cycle covers at most one chosen requirement.

There are four exception requirements, `2a+2b-4` boundary requirements, and

`((a-2)(b-2)-1)/2`

interior dominoes. Their sum is

`(ab+2a+2b+3)/2 = ((a+2)(b+2)-1)/2`.

Consequently, for every odd `a,b >= 3`,

`hsep(D(a,b)) >= ((a+2)(b+2)-1)/2`.

## Square-insertion lift

Use exception isolators on the ladder not being expanded. Under insertion in
cell zero, each unaffected source edge retains its certified image; either
edge on the deleted rail pair may be represented by the corresponding member
of its three-edge target path. With this path-aware convention, all old
requirements in the emitted far-corner construction occur in the target
construction.

For `b -> b+2`, four new boundary singletons cover the two new columns at the
top and bottom, and `a-2` new domino requirements cover those columns in the
interior: the net increment is `4+(a-2)=a+2`. Symmetrically, `a -> a+2` adds
four boundary singletons and `b-2` interior dominoes, hence `b+2`.

This proves existence of a path-aware nested structural certificate family.
It does not say that an arbitrary optimal packing, or the particular greedy
packing stored by a solver, is nested.

## What is not proved

No general upper construction is supplied. Equality would additionally
require a separating family of the same size for every odd `a,b >= 3`.
Nothing here establishes novelty or resolves terminology in the literature.
"""


def main_report(
    datasets: Sequence[PackingDataset],
    normalized: dict[str, Any],
    alignments: dict[str, Any],
    increments: dict[str, Any],
) -> str:
    rows = []
    for graph in normalized["graphs"]:
        summary = graph["original_immutable_packing"]["summary"]
        rows.append(
            f"| {graph['label']} | {summary['packing_size']} | "
            f"{summary['support_size_distribution'].get(1)} | "
            f"{summary['support_size_distribution'].get(2)} | "
            f"{', '.join(summary['uncovered_cycle_classes'])} |"
        )
    alignment_rows = []
    for item in alignments["alignments"]:
        old = item["original_certificates"]
        new = item["constructed_structural_certificates"]
        alignment_rows.append(
            f"| {item['transition']} | {old['raw_canonical_endpoint_pair_coincidence']} | "
            f"{old['unshifted_structural_coordinate_pair_overlap']} | "
            f"{old['literal_path_aware_ordered_requirement_overlap']}/"
            f"{old['source_requirement_count']} | "
            f"{item['direct_structural_coverage_block_alignment']['exact_target_coverage_block_overlap']}/"
            f"{old['source_requirement_count']} | "
            f"{old['maximum_automorphism_aligned_ordered_requirement_overlap']}/"
            f"{old['source_requirement_count']} | {new['literal_path_aware_ordered_requirement_overlap']}/"
            f"{new['source_requirement_count']} |"
        )
    increment_rows = [
        f"| {item['transition']} | {item['increment']} | "
        f"{item['new_support_size_distribution'].get(1, 0)} | "
        f"{item['new_support_size_distribution'].get(2, 0)} |"
        for item in increments["increments"]
    ]
    return f"""# Double-ladder packing-lift analysis

## Result

A common structural description **was found**. Every immutable optimal
packing is four connector-exception singletons, every boundary turn singleton,
and a domino tiling of the odd-by-odd interior turn grid with one majority-
parity cell removed. This is an exact certificate fact for all four graphs.

The immutable solver-selected packings are not uniformly nested. Exhaustive
graph-automorphism alignment still fails for the first two transitions; the
third is literally nested. A different deterministic structural certificate
is path-aware nested in all three transitions. Thus square insertion has a
proved certificate-lifting rule, but the rule is existential/constructive and
does not lift every arbitrary optimum unchanged.

| graph | packing | singleton supports | doubleton supports | uncovered cycles |
|---|---:|---:|---:|---|
{chr(10).join(rows)}

All support sets were recomputed from the complete immutable Hamiltonian
universes. In each graph they are pairwise disjoint and cover every cycle
except the all-rails cycle and one interior turn cycle.

## Alignment

| transition | raw endpoints | unshifted coordinates | certified path-aware | coverage blocks | best automorphism | structural construction |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(alignment_rows)}

The comparison is stronger than raw canonical-label comparison: it uses the
certified source-to-target graph map, permits all three representatives of a
subdivided rail edge, and exhausts all graph automorphisms (including the
available reversals, rail swaps, and ladder exchanges).

## Checkerboard test

The numerical checkerboard observation is correct:
`((a+2)(b+2)-1)/2` is the smaller color class of the odd `(a+2) x (b+2)`
grid. The certificates reveal a more intrinsic model: boundary and exception
monomers plus a domino tiling of the interior `(a-2) x (b-2)` turn grid after
removing one majority-color cell. A unique raw requirement-to-extended-cell
bijection is not canonical and is not asserted.

## Exact lifting increments

| transition | increment | new singleton supports | new domino supports |
|---|---:|---:|---:|
{chr(10).join(increment_rows)}

For expansion of `B`, four new boundary singletons plus `a-2` interior
dominoes give `a+2`. For expansion of `A`, four plus `b-2` give `b+2`.
`lifting_increments.json` records every new ordered requirement and its exact
cycle support.

## Proof status

- **Exact certificate facts:** source hashes, cycle counts, original packing
  sizes, every coverage set, disjointness, and the three finite increments.
- **Computational structural discovery:** all four greedy certificates have
  the same monomer/domino form; automorphism maxima are exhaustive for these
  four labelled graphs.
- **Proved general lemma:** using the explicit Hamiltonian-cycle incidence
  classification, the emitted symbolic requirements form a packing of size
  `((a+2)(b+2)-1)/2` for every odd `a,b >= 3`; the path-aware local lift has
  increments `a+2` and `b+2`.
- **Not proved:** a general separating cover of the same size. Therefore the
  result proves only the lower bound, not the general equality formula.
- **No novelty claim:** literature priority and the provisional `hsep` name
  remain outside this computation.

## Answers to the requested questions

1. The four immutable packings are not all literally nested.
2. Automorphisms do not repair the first two; a different optimal structural
   certificate choice is fully path-aware nested in all three.
3. A checkerboard parity model exists, most naturally as an interior domino
   model rather than a canonical extended-grid cell label.
4. Boundary coordinates isolate boundary turns; interior domino coordinates
   are rung/rail requirements covering two adjacent turn cycles; four special
   requirements isolate connector exceptions.
5. The count is `4+(2a+2b-4)+((a-2)(b-2)-1)/2`.
6. The finite increments are 11, 11, and 13, explicitly listed in JSON.
7. Square insertion admits the local path-aware lift described above.
8. The packing property and lifting count are proved from the full cycle-class
   incidence table and computationally checked on all four universes.
9. `R`, all `ab` turn cycles, and all four exception cycles are handled.
10. No packing boundary case remains for odd `a,b >= 3` in the defined model.
11. Yes, the lower bound follows for all such odd parameters.
12. Equality still needs a general separating family of the same cardinality.

## Reproducibility

The standalone verifier uses only Python's standard library. It rechecks every
emitted Hamiltonian cycle, both packing families, all coverage sets, every
disjointness assertion, the expansion paths, immutable source hashes, and the
output manifest. Completeness of the cycle universes is inherited by SHA-256
from the already independently verified immutable packages; it is not
re-enumerated here.
"""


def verification_data(
    datasets: Sequence[PackingDataset], expansions: dict[str, Any]
) -> dict[str, Any]:
    graphs = []
    for dataset in datasets:
        graphs.append(
            {
                "label": dataset.label,
                "canonical_graph_hash": dataset.graph.graph_hash,
                "a": dataset.a,
                "b": dataset.b,
                "order": len(dataset.graph.rotation),
                "edges": [list(edge) for edge in dataset.edges],
                "cycles": [list(cycle) for cycle in dataset.cycles],
                "cycle_keys": list(dataset.cycle_keys),
                "original_requirements": [list(item) for item in dataset.requirements],
                "structural_requirements": [
                    list(item) for item in canonical_structural_packing(dataset, anchor="A")
                ],
            }
        )
    return {"schema": SCHEMA, "graphs": graphs, "expansions": expansions["expansions"]}


def write_manifest(root: Path) -> None:
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt" and not path.name.endswith(".tmp")
    )
    lines = [f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in paths]
    write_text(root / "SHA256SUMS.txt", "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence-root", type=Path, required=True)
    parser.add_argument("--prediction-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "figures").mkdir(exist_ok=True)

    datasets = load_chain(args.sequence_root.resolve(), args.prediction_root.resolve())
    artifact_inventory = inventory(datasets, args.sequence_root, args.prediction_root)
    normalized = normalized_packings(datasets)
    expansions, alignments, increments = expansion_and_alignment(
        datasets, normalized, args.sequence_root.resolve()
    )

    write_json(root / "artifact_inventory.json", artifact_inventory)
    write_text(root / "artifact_inventory.md", inventory_markdown(artifact_inventory))
    write_json(root / "normalized_packings.json", normalized)
    write_normalized_csv(root / "normalized_packings.csv", normalized)
    write_json(root / "expansion_maps.json", expansions)
    write_json(root / "packing_alignment.json", alignments)
    write_text(root / "packing_alignment_report.md", alignment_report(alignments))
    write_json(root / "coverage_sets.json", coverage_output(normalized))
    conflict = {
        "schema": SCHEMA,
        "graphs": [
            {
                "label": dataset.label,
                "canonical_graph_hash": dataset.graph.graph_hash,
                **candidate_conflict_summary(dataset),
            }
            for dataset in datasets
        ],
    }
    write_json(root / "conflict_graph_summary.json", conflict)
    write_json(root / "checkerboard_model.json", checkerboard_output(datasets, normalized))
    write_json(root / "lifting_increments.json", increments)
    write_text(root / "symbolic_packing_definition.md", symbolic_definition())
    write_text(root / "proof_draft.md", proof_draft())
    write_text(
        root / "unresolved_cases.md",
        "# Unresolved cases\n\n"
        "No packing boundary case remains for the defined double-ladder model with odd "
        "`a,b >= 3`. A matching general upper bound remains unresolved: one must construct "
        "a Hamiltonian edge-separating family of the same size for every parameter pair. "
        "Literature novelty and nomenclature are also explicitly unresolved.\n",
    )
    write_text(root / "PACKING_LIFT_REPORT.md", main_report(datasets, normalized, alignments, increments))
    original_d97 = normalized["graphs"][0]["original_immutable_packing"]["requirements"]
    write_text(root / "figures" / "D_9_7_packing.svg", svg_grid(datasets[0], original_d97))
    write_text(root / "figures" / "D_9_7_checkerboard.svg", svg_checkerboard(9, 7))
    for number, item in enumerate(increments["increments"], start=1):
        name = item["transition"].replace("(", "_").replace(")", "").replace(",", "_").replace(" -> ", "_to_")
        write_text(root / "figures" / f"{number}_{name}.svg", svg_increment(item, number))

    verifier_source = args.repo / "tools" / "verify_double_ladder_packing_lift.py"
    shutil.copyfile(verifier_source, root / "verify_double_ladder_packing_lift.py")
    write_gzip_json(root / "verification_data.json.gz", verification_data(datasets, expansions))

    command = (
        f'python tools/analyze_double_ladder_packings.py --sequence-root "{args.sequence_root}" '
        f'--prediction-root "{args.prediction_root}" --output-root "{args.output_root}" '
        f'--repo "{args.repo}"'
    )
    verify_command = f'python "{root / "verify_double_ladder_packing_lift.py"}" "{root}" --check-manifest'
    write_text(
        root / "commands.log",
        "\n".join(
            [
                command,
                f'python "{args.prediction_root / "verify_double_ladder_predictions.py"}" "{args.prediction_root}" --check-manifest',
                verify_command,
            ]
        )
        + "\n",
    )
    environment = {
        "schema": SCHEMA,
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "worker_count": 1,
        "repository": str(args.repo.resolve()),
        "git_commit": git_output(args.repo, "rev-parse", "HEAD"),
        "git_status_before_manifest": git_output(args.repo, "status", "--short"),
        "networkx_version": __import__("networkx").__version__,
    }
    write_json(root / "environment.json", environment)

    # First run establishes the independently recomputed mathematical facts.
    verification = subprocess.run(
        [sys.executable, str(root / "verify_double_ladder_packing_lift.py"), str(root), "--json"],
        text=True,
        capture_output=True,
        check=True,
    )
    independent = json.loads(verification.stdout)
    independent["manifest_check"] = "performed in the final verification command after manifest creation"
    write_json(root / "independent_verification.json", independent)
    write_manifest(root)
    final = subprocess.run(
        [
            sys.executable,
            str(root / "verify_double_ladder_packing_lift.py"),
            str(root),
            "--check-manifest",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    print(final.stdout.strip())
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
