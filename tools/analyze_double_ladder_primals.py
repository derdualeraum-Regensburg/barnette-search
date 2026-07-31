#!/usr/bin/env python3
"""Generate the deterministic double-ladder primal-lift analysis package."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any, Sequence

from barnette_search.double_ladder_packing import (
    expansion_map_record,
    sha256_file,
    verify_manifest,
)
from barnette_search.double_ladder_prediction_test import connector_edges
from barnette_search.double_ladder_primal import (
    PrimalDataset,
    antichain_analysis,
    edge_coordinate,
    family_formula,
    injected_cycle_key,
    load_primal_chain,
    normalize_primal,
    primal_alignment,
    signature_records,
    structural_lift,
    symbolic_antichain_check,
    symbolic_family_indices,
    symbolic_family_keys,
)


SCHEMA = "double-ladder-primal-lift-analysis-v1"


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as target:
            target.write(canonical_json_bytes(value))
    os.replace(temporary, path)


def source_inventory(
    datasets: Sequence[PrimalDataset], sequence_root: Path, prediction_root: Path
) -> dict[str, Any]:
    paths: dict[Path, str] = {}
    for dataset in datasets:
        for role, path in dataset.graph.source_files.items():
            paths.setdefault(path.resolve(), role)
        paths.setdefault(dataset.primal_source.resolve(), "primal_certificate")
    global_files = {
        (prediction_root / "SHA256SUMS.txt").resolve(): "prediction_global_manifest",
        (prediction_root / "independent_verification.json").resolve(): (
            "prediction_global_independent_verification"
        ),
    }
    paths.update(global_files)
    artifacts = [
        {
            "role": paths[path],
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(paths, key=str)
    ]
    manifests = [
        sequence_root / "order_36" / "SHA256SUMS.txt",
        sequence_root / "ladder-analysis" / "SHA256SUMS.txt",
        prediction_root / "SHA256SUMS.txt",
        *(dataset.graph.graph_directory / "SHA256SUMS.txt" for dataset in datasets[1:]),
    ]
    return {
        "schema": SCHEMA,
        "artifacts": artifacts,
        "manifest_checks": [verify_manifest(path) for path in manifests],
        "scope": [dataset.graph.label for dataset in datasets],
        "source_packages_are_read_only": True,
    }


def inserted_edges(dataset: PrimalDataset) -> set[tuple[int, int]]:
    directory = dataset.graph.graph_directory
    if directory is None:
        return set()
    certificate = json.loads(
        (directory / "expansion_certificate.json").read_text(encoding="utf-8")
    )
    return {tuple(sorted(map(int, edge))) for edge in certificate["inserted_edges_target_labels"]}


def normalized_output(datasets: Sequence[PrimalDataset]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "symbolic_rule": (
            "select X0011,X1100,X0101,X1010; every boundary T(i,j); and every "
            "interior T(i,j) with i+j odd"
        ),
        "graphs": [normalize_primal(dataset) for dataset in datasets],
    }


def signature_output(datasets: Sequence[PrimalDataset]) -> dict[str, Any]:
    graphs = []
    for dataset in datasets:
        graph = dataset.graph
        selected = symbolic_family_indices(graph)
        analysis = antichain_analysis(graph, selected)
        records = list(signature_records(graph, selected))
        gadget = inserted_edges(dataset)
        for record in records:
            record["is_inserted_gadget_edge"] = tuple(record["edge"]) in gadget
            coordinate = record["coordinate"]
            length = graph.a if coordinate.get("ladder") == "A" else graph.b
            record["is_boundary_or_cap_edge"] = coordinate["kind"] == "connector" or (
                coordinate["kind"] == "rung" and coordinate.get("index") in (0, length)
            )
        graphs.append(
            {
                "label": graph.label,
                "canonical_graph_hash": graph.graph.graph_hash,
                "parameters": {"a": graph.a, "b": graph.b},
                "selected_cycle_classes": [graph.cycle_keys[index] for index in selected],
                "edge_signatures": records,
                "analysis": analysis,
            }
        )
    sanity = [
        symbolic_antichain_check(a, b)
        for a in range(3, 32, 2)
        for b in range(3, 32, 2)
    ]
    return {
        "schema": SCHEMA,
        "graphs": graphs,
        "symbolic_sanity_grid": {
            "parameter_pairs": len(sanity),
            "range": "all odd 3 <= a,b <= 31",
            "all_pass": all(item["antichain"] for item in sanity),
            "results": sanity,
            "status_note": "computational sanity check only; the general claim uses the proof",
        },
    }


def lift_output(datasets: Sequence[PrimalDataset]) -> dict[str, Any]:
    records = []
    for source, target, axis in zip(datasets, datasets[1:], ("B", "A", "B")):
        certificate_path = target.graph.graph_directory / "expansion_certificate.json"  # type: ignore[operator]
        expansion = expansion_map_record(source.graph, target.graph, certificate_path)
        structural = structural_lift(source, target, axis)
        alignment = primal_alignment(source, target, certificate_path)
        direct_source_indices = {
            item["source_cycle_index"] for item in alignment["literal_direct_lifts"]
        }
        repaired = sorted(
            source.graph.cycle_keys[index]
            for index in source.primal_indices
            if index not in direct_source_indices
        )
        repair_map = [
            {"source_cycle_class": key, "target_cycle_class": injected_cycle_key(key, axis)}
            for key in repaired
        ]
        new_records = []
        for key in structural["new_target_cycle_classes"]:
            turn = None if key.startswith("X") else tuple(map(int, key[2:-1].split(",")))
            new_records.append(
                {
                    "cycle_class": key,
                    "turn_coordinates": list(turn) if turn is not None else None,
                    "kind": (
                        "boundary_turn"
                        if turn is not None
                        and (
                            turn[0] in (0, target.graph.a - 1)
                            or turn[1] in (0, target.graph.b - 1)
                        )
                        else "odd_interior_turn"
                    ),
                }
            )
        records.append(
            {
                "source": source.graph.label,
                "target": target.graph.label,
                "axis": axis,
                "expansion_certificate": expansion,
                "source_edge_to_target_paths": expansion["source_edge_to_target_paths"],
                "structural_class_lift": structural,
                "geometric_and_automorphism_alignment": alignment,
                "literal_direct_geometric_lift_count": alignment[
                    "literal_direct_geometric_lift_count"
                ],
                "locally_repaired_source_cycle_count": len(repaired),
                "locally_repaired_source_cycle_classes": repaired,
                "local_repair_map": repair_map,
                "new_target_cycle_count": len(new_records),
                "new_target_cycle_classes": [item["cycle_class"] for item in new_records],
                "new_target_cycles": new_records,
                "new_cycle_kind_distribution": dict(
                    sorted(Counter(item["kind"] for item in new_records).items())
                ),
                "net_family_increment": len(target.primal_indices) - len(source.primal_indices),
            }
        )
    return {"schema": SCHEMA, "lifts": records}


def symbolic_family_markdown() -> str:
    return r"""# Symbolic Hamiltonian separating family

Let `D(a,b)` have odd `a,b >= 3`. Write `T(i,j)` for the Hamiltonian
cycle turning in cell `i` of ladder `A` and cell `j` of ladder `B`.
Let `X0011,X1100,X0101,X1010` be the four two-connector exceptions.

Define


\[
\mathcal C(a,b)=\{X0011,X1100,X0101,X1010\}
 \cup\{T(i,j):i\in\{0,a-1\}\text{ or }j\in\{0,b-1\}\}
 \cup\{T(i,j):0<i<a-1,\ 0<j<b-1,\ i+j\text{ odd}\}.
\]

The boundary contributes `2a+2b-4` cycles. The interior grid has odd
dimensions `(a-2) x (b-2)`; its odd parity class has
`((a-2)(b-2)-1)/2` cells. Hence

\[
 |\mathcal C(a,b)|=4+(2a+2b-4)+\frac{(a-2)(b-2)-1}{2}
 =\frac{(a+2)(b+2)-1}{2}.
\]

This is exactly the unordered structural class set of each of the four stored
optimal primal certificates. No alternative search was needed.

Under a `B`-insertion at cell zero, map `T(i,0)` to `T(i,0)`, map
`T(i,j)` to `T(i,j+2)` for `j>0`, and keep each `X` class. The new
columns 1 and 2 contain four selected boundary turns and one selected parity
cell in each of the `a-2` interior rows, for `a+2` new cycles. The
`A`-insertion rule is symmetric and adds `b+2`.

The class lift is fully nested. A literal graph-edge subdivision preserves all
but `a+2`, respectively `b+2`, old cycles. The remaining old cycles are
replaced locally inside the inserted square gadget; this replacement does not
change the family cardinality.
"""


def proof_markdown() -> str:
    return r"""# Proof draft: symbolic primal upper bound

## Incidence table

By the previously proved Hamiltonian-cycle classification for odd
`a,b >= 3`, every `T(i,j)` and all four `X` cycles used below exist and have
the stated rail/rung/connector incidences.

Let `P` be the selected turn set in `C(a,b)`, and let
`R_i={T(i,j) in P}`, `K_j={T(i,j) in P}`. Every row and column is
nonempty because all boundary turns are selected. Put
`N(p)={p-1,p} intersect {0,...,a-1}`, with the analogous definition on
ladder `B`.

For the turn part of an edge signature:

- every connector occurs in all of `P`;
- rail `ell_A(t,s)` occurs in `P` except row `R_t`, and
  `ell_B(t,s)` occurs in `P` except column `K_t`;
- rung `r_A(p)` occurs in the selected turns whose first coordinate lies in
  `N(p)`; `r_B(q)` is symmetric.

For the four exception coordinates, abbreviate
`B_0=X0011,B_1=X1100,A_0=X0101,A_1=X1010`. Then:

- an `A`-rail has `{B_0,B_1}` plus exactly one of `A_0,A_1`, selected
  by rail side and cell parity; a `B`-rail is symmetric;
- every internal `A`-rung has `{A_0,A_1}`, while endpoint rungs add
  `B_0` or `B_1`; `B`-rungs are symmetric;
- the four connector exception signatures are respectively
  `{B_1,A_1},{B_1,A_0},{B_0,A_1},{B_0,A_0}`.

These formulas include endpoint rungs and every rail/rung introduced by a
square insertion.

## Distinctness

Rail sides in one cell differ on `A_0,A_1` (or `B_0,B_1`). Rails in
different cells differ on a selected turn in either omitted row/column. Rungs
with different nonnested neighborhoods differ on their unique incident
rows/columns; the only nested endpoint-neighbor pairs are distinguished by the
extra endpoint exception. Rungs on different ladders have different exception
cores. Connectors have four distinct two-element exception signatures. The
type comparisons below also give a cycle belonging to one signature and not
the other. Thus all edge signatures are distinct.

## No containment

For every unordered pair of distinct edges, the following catalog supplies a
selected cycle in each signature difference.

1. **Connector--connector.** Their distinct exception sets have equal size
   two, so each has an exception absent from the other.
2. **Connector--rail.** A turn in the rail's omitted row or column belongs to
   the connector only. The rail has three exception cycles, so at least one is
   absent from the connector's two-element exception set.
3. **Connector--rung.** A boundary turn outside the rung's one- or two-cell
   neighborhood belongs only to the connector. The rung contains both
   same-ladder exception cycles, while each connector contains exactly one of
   them, giving the reverse witness.
4. **Rail--rail.** Two sides of one cell use opposite alternating exceptions.
   Different cells of one ladder use turns in the two opposing omitted rows or
   columns. For rails on different ladders, choose a boundary point in the
   omitted column but outside the omitted row, and conversely; both points are
   selected.
5. **Rung--rung on one ladder.** If their neighborhoods are not nested, a
   selected boundary turn in each unique row/column gives both witnesses. For
   `N(0)` contained in `N(1)` and the symmetric far-end pair, the endpoint exception
   gives one direction and a turn in the extra neighboring cell gives the
   other.
6. **Rung--rung on different ladders.** Their two-element exception cores are
   opposite. Endpoint additions never remove the exception unique to either
   core, so exceptions witness both directions.
7. **Rail--rung on the same ladder.** The rail contains both opposite-ladder
   exceptions and only one same-ladder alternating exception; the rung contains
   both same-ladder exceptions and at most one opposite-ladder exception.
   Therefore each has an exception absent from the other.
8. **Rail on one ladder--rung on the other.** For an `A`-rail in row `t`
   and a `B`-rung with neighborhood `N(q)`, choose a boundary row other than
   `t` and a column outside `N(q)`; that selected turn belongs only to the
   rail. Conversely choose `j` in `N(q)` with `T(t,j)` selected. At a
   boundary row any choice works; in an interior row an endpoint neighborhood
   contains a selected boundary column, while an internal two-column
   neighborhood contains exactly one column of the required parity. This turn
   belongs only to the rung. The other orientation is symmetric.

The list exhausts connector, rail and rung types. Hence no edge signature
contains another. Equivalently, for every ordered pair `(e,f)`, some cycle in
`C(a,b)` contains `e` and avoids `f`. Thus

\[
 \operatorname{hsep}(D(a,b))\le\frac{(a+2)(b+2)-1}{2}.
\]

Combining this with the already proved packing lower bound gives, for all odd
`a,b >= 3`,

\[
 \boxed{\operatorname{hsep}(D(a,b))=\frac{(a+2)(b+2)-1}{2}}.
\]

This theorem concerns the defined double-ladder family only. It makes no
claim about order-level Barnette extremality or literature novelty.
"""


def report_markdown(
    normalized: dict[str, Any], signatures: dict[str, Any], lifts: dict[str, Any]
) -> str:
    graph_rows = []
    for graph, signature in zip(normalized["graphs"], signatures["graphs"]):
        analysis = signature["analysis"]
        distribution = graph["selected_cycle_class_distribution"]
        graph_rows.append(
            f"| {graph['label']} | {graph['primal_size']} | "
            f"{distribution['connector_exception']} | {distribution['boundary_turn']} | "
            f"{distribution['odd_interior_turn']} | {analysis['distinct_signature_count']}/"
            f"{analysis['edge_count']} | {analysis['ordered_requirements_covered']} |"
        )
    lift_rows = []
    for lift in lifts["lifts"]:
        alignment = lift["geometric_and_automorphism_alignment"]
        lift_rows.append(
            f"| {lift['source']} -> {lift['target']} | "
            f"{alignment['literal_direct_geometric_lift_count']} | "
            f"{alignment['maximum_automorphism_aligned_direct_lift_count']} | "
            f"{lift['locally_repaired_source_cycle_count']} | "
            f"{lift['new_target_cycle_count']} | {lift['net_family_increment']} |"
        )
    return f"""# Double-ladder primal-lift analysis

## Result

A common recursively liftable primal family **was found and proved**. For odd
`a,b >= 3`, select all four connector exceptions, every boundary turn cycle,
and every interior turn `T(i,j)` with `i+j` odd. Its cardinality is

```text
((a+2)(b+2)-1)/2.
```

The rail/rung/connector incidence formulas prove that all edge signatures are
distinct and form an antichain. Therefore the family separates every ordered
pair of distinct edges. Combined with the existing packing theorem, this gives

```text
hsep(D(a,b)) = ((a+2)(b+2)-1)/2
```

for every odd `a,b >= 3` in the defined double-ladder family.

## Exact finite reconstruction

Each immutable solver primal equals the symbolic family exactly as an
unordered structural class set; only its stored ordering is solver-specific.

| graph | size | exceptions | boundary turns | odd interior turns | distinct signatures | ordered pairs |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(graph_rows)}

Every cycle, edge signature and ordered-pair witness was recomputed from the
existing complete Hamiltonian universe. No replacement search was necessary.

## Square-insertion lift

| transition | direct geometric lifts | best with automorphisms | local repairs | new cycles | net increment |
|---|---:|---:|---:|---:|---:|
{chr(10).join(lift_rows)}

Raw vertex-sequence nesting is impossible because the target has four new
vertices. Directly replacing selected source edges by their certified target
paths preserves all cycles except the turns at the expanded cell and the two
alternating exceptions. Exhausting all graph automorphisms does not improve
the direct counts. Those cycles have a uniform local replacement, while the
new two-column or two-row strip contributes four boundary cycles and one
parity cycle per interior row or column. The net increments are 11, 11, and 13.

## Checkerboard and signatures

The selected interior turns are one checkerboard parity class. Boundary turns
are all selected. `signature_analysis.json` records every edge's complete
incidence signature and two directed witnesses for every unordered edge pair.
It includes explicit boundary and inserted-gadget flags. The symbolic formulas
were additionally sanity-checked for every odd pair `3 <= a,b <= 31`; this
finite grid is corroboration, not the proof.

## Proof status and limits

- The four finite primal facts and all lift counts are independently verified
  computations over immutable complete universes.
- The general upper bound is proved by the eight-case signature catalog in
  `proof_draft.md`; rails, rungs, connectors, endpoint/cap edges and inserted
  gadget edges are all included.
- Together with the previously proved packing lower bound, the double-ladder
  hsep formula is now a theorem for odd `a,b >= 3`.
- No order-level extremal statement, Barnie-sequence continuation, or novelty
  claim follows.
"""


def symbolic_edge_for(dataset: PrimalDataset, edge: tuple[int, int]) -> list[Any]:
    coordinate = edge_coordinate(dataset.graph.graph, edge)
    if coordinate.kind == "connector":
        connectors = connector_edges(dataset.graph.graph)
        return ["C", connectors.index(edge)]
    if coordinate.kind == "rail":
        return [coordinate.ladder, "rail", coordinate.index, coordinate.rail]
    return [coordinate.ladder, "rung", coordinate.index]


def verification_data(
    datasets: Sequence[PrimalDataset], lifts: dict[str, Any]
) -> dict[str, Any]:
    graphs = []
    for dataset in datasets:
        graph = dataset.graph
        graphs.append(
            {
                "label": graph.label,
                "canonical_graph_hash": graph.graph.graph_hash,
                "a": graph.a,
                "b": graph.b,
                "order": len(graph.graph.rotation),
                "edges": [list(edge) for edge in graph.edges],
                "symbolic_edges": [symbolic_edge_for(dataset, edge) for edge in graph.edges],
                "cycles": [list(cycle) for cycle in graph.cycles],
                "cycle_keys": list(graph.cycle_keys),
                "original_primal_indices": list(dataset.primal_indices),
                "symbolic_primal_indices": list(symbolic_family_indices(graph)),
            }
        )
    compact_lifts = []
    for lift in lifts["lifts"]:
        compact_lifts.append(
            {
                "source": lift["source"],
                "target": lift["target"],
                "axis": lift["axis"],
                "source_edge_to_target_paths": lift["source_edge_to_target_paths"],
                "literal_direct_geometric_lift_count": lift[
                    "literal_direct_geometric_lift_count"
                ],
                "locally_repaired_source_cycle_classes": lift[
                    "locally_repaired_source_cycle_classes"
                ],
                "new_target_cycle_classes": lift["new_target_cycle_classes"],
            }
        )
    return {"schema": SCHEMA, "graphs": graphs, "lifts": compact_lifts}


def git_output(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


def write_manifest(root: Path) -> None:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt" and not path.name.endswith(".tmp")
    )
    write_text(
        root / "SHA256SUMS.txt",
        "\n".join(
            f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in files
        )
        + "\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence-root", type=Path, required=True)
    parser.add_argument("--prediction-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    datasets = load_primal_chain(args.sequence_root.resolve(), args.prediction_root.resolve())

    inventory = source_inventory(datasets, args.sequence_root.resolve(), args.prediction_root.resolve())
    normalized = normalized_output(datasets)
    signatures = signature_output(datasets)
    lifts = lift_output(datasets)
    write_json(root / "source_inventory.json", inventory)
    write_json(root / "normalized_primals.json", normalized)
    write_json(root / "signature_analysis.json", signatures)
    write_json(root / "lifting_rules.json", lifts)
    write_text(root / "symbolic_separating_family.md", symbolic_family_markdown())
    write_text(root / "proof_draft.md", proof_markdown())
    write_text(root / "PRIMAL_LIFT_REPORT.md", report_markdown(normalized, signatures, lifts))
    write_text(
        root / "unresolved_cases.md",
        "# Unresolved cases\n\n"
        "There is no unresolved edge-pair class for the defined double-ladder family with "
        "odd `a,b >= 3`. Degenerate parameters with `a=1` or `b=1`, order-level Barnette "
        "extremality, literature priority, and independent expert review of the symbolic proof "
        "remain outside this theorem.\n",
    )
    verifier_source = args.repo / "tools" / "verify_double_ladder_primal_lift.py"
    shutil.copyfile(verifier_source, root / "verify_double_ladder_primal_lift.py")
    write_gzip_json(root / "verification_data.json.gz", verification_data(datasets, lifts))
    write_text(
        root / "commands.log",
        f'python tools/analyze_double_ladder_primals.py --sequence-root "{args.sequence_root}" '
        f'--prediction-root "{args.prediction_root}" --output-root "{args.output_root}" '
        f'--repo "{args.repo}"\n'
        f'python "{root / "verify_double_ladder_primal_lift.py"}" "{root}" --check-manifest\n'
        "python -m pytest tests/test_double_ladder_primal.py -q\n",
    )
    write_json(
        root / "environment.json",
        {
            "schema": SCHEMA,
            "platform": platform.platform(),
            "python": sys.version,
            "python_executable": sys.executable,
            "worker_count": 1,
            "repository": str(args.repo.resolve()),
            "git_commit": git_output(args.repo, "rev-parse", "HEAD"),
            "git_status": git_output(args.repo, "status", "--short"),
        },
    )
    write_gzip_json(root / "verification_data.json.gz", verification_data(datasets, lifts))
    verification = subprocess.run(
        [sys.executable, str(root / "verify_double_ladder_primal_lift.py"), str(root), "--json"],
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(verification.stdout)
    result["manifest_check"] = "performed after final manifest creation"
    write_json(root / "independent_verification.json", result)
    write_manifest(root)
    final = subprocess.run(
        [
            sys.executable,
            str(root / "verify_double_ladder_primal_lift.py"),
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
