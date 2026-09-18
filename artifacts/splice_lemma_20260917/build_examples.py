"""Build small, explicitly bounded examples for the splice lemma (at most 30 vertices)."""
from datetime import datetime, timezone
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

import networkx as nx

from construct import compose, cycles_by_paths, prism, separating
from verify import check


def irredundant_family(edges):
    """Delete redundant cycles deterministically; this is not an exact solver."""
    family = list(cycles_by_paths(edges))
    for c in tuple(family):
        candidate = [d for d in family if d != c]
        if separating(edges, candidate):
            family = candidate
    return tuple(family)


def main():
    start = perf_counter()
    root = Path(__file__).resolve().parent
    examples = root / "examples"
    examples.mkdir(exist_ok=True)
    rows = []
    nested = compose(prism(4), prism(4), 0, 0)["output_edges"]
    specifications = [("cube_cube", prism(4), prism(4)),
                      ("cube_prism6", prism(4), prism(6)),
                      ("prism6_prism6", prism(6), prism(6)),
                      ("prism8_prism8", prism(8), prism(8)),
                      ("nested_cube_cube", nested, prism(4))]
    for name, left, right in specifications:
        neighbours = sorted(v for e in right if 0 in e for v in e if v != 0)
        for index, ports in enumerate(permutations(neighbours)):
            modes = ("complete", "irredundant") if name == "nested_cube_cube" else ("complete",)
            for mode in modes:
                family = [irredundant_family(left), irredundant_family(right)] if mode == "irredundant" else None
                certificate = compose(left, right, 0, 0, ports, family)
                graph = nx.Graph()
                graph.add_nodes_from(sorted({v for e in certificate["output_edges"] for v in e}))
                graph.add_edges_from(certificate["output_edges"])
                if not (nx.is_bipartite(graph) and nx.check_planarity(graph)[0] and nx.node_connectivity(graph) == 3):
                    raise ValueError("example is not a Barnette graph")
                certificate["labelled_graph6"] = nx.to_graph6_bytes(graph, header=False).decode().strip()
                restored = nx.from_graph6_bytes(certificate["labelled_graph6"].encode())
                if {tuple(sorted(e)) for e in restored.edges()} != set(certificate["output_edges"]):
                    raise ValueError("graph6 round-trip changed labelled edges")
                certificate["graph6_scope"] = "labelled representation; no new isomorphism-class claim"
                filename = f"{name}_{index}_{mode}.json"
                payload = (json.dumps(certificate, indent=2) + "\n").encode()
                (examples / filename).write_bytes(payload)
                row = check(json.loads(payload))
                row.update(example=filename, certificate_sha256=sha256(payload).hexdigest())
                rows.append(row)
    report = {"verified": True, "scope": "bounded examples, not a census or proof of the general theorem",
              "command": "python artifacts/splice_lemma_20260917/build_examples.py",
              "python": sys.version, "platform": platform.platform(), "networkx": nx.__version__,
              "solver": "none; path DFS and independent exhaustive perfect matchings", "seed": None,
              "finished_utc": datetime.now(timezone.utc).isoformat(), "seconds": perf_counter() - start,
              "source_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))},
              "examples": rows}
    (root / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    files = sorted([*examples.glob("*.json"), root / "results.json", *root.glob("*.py")])
    (root / "SHA256SUMS.txt").write_text("".join(f"{sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\n" for p in files))
    print(json.dumps({"examples_verified": len(rows), "seconds": report["seconds"],
                      "strict_refinements": sum(r["reduced_upper_bound"] < r["product_upper_bound"] for r in rows)}, indent=2))


if __name__ == "__main__":
    main()
