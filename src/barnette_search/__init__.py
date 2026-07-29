"""Reference tools for working with Barnette graphs."""

from .graph_io import graph_from_graph6_file, graph_from_graph6_string, load_graph
from .validation import ValidationResult, validate_barnette_graph
from .hamiltonian import find_hamiltonian_cycle, verify_hamiltonian_cycle
from .hamiltonian_sat import (
    HamiltonianSatResult,
    find_hamiltonian_cycle_sat,
    solve_hamiltonian_cycle_sat,
)
from .planar_code import (
    EmbeddedPlanarGraph,
    PlanarCodeError,
    canonical_graph_hash,
    iter_planar_code,
)
from .plantri import (
    PlantriError,
    PlantriVersion,
    detect_plantri_version,
    locate_plantri,
    stream_barnette_graphs,
)
from .constrained_hamiltonian import find_constrained_hamiltonian_cycle
from .constrained_hamiltonian_sat import (
    ConstrainedHamiltonianSatResult,
    ConstrainedHamiltonianSatSession,
    solve_constrained_hamiltonian_cycle_sat,
)
from .edge_flexibility import (
    EdgeFlexibilityResult,
    analyze_same_face_edge_flexibility,
)
from .all_edge_flexibility import (
    AllEdgePairFlexibilityResult,
    analyze_all_edge_pair_flexibility,
)
from .three_edge_path_flexibility import (
    ThreeEdgePathFlexibilityResult,
    analyze_three_edge_path_flexibility,
    enumerate_three_edge_paths,
)
from .cubhamg import (
    CubhamgCommandSpec,
    CubhamgExecutable,
    CubhamgResult,
    benchmark_cubhamg,
    inspect_cubhamg,
)
from .result_storage import read_jsonl

__all__ = [
    "ValidationResult",
    "HamiltonianSatResult",
    "EmbeddedPlanarGraph",
    "PlanarCodeError",
    "PlantriError",
    "PlantriVersion",
    "ConstrainedHamiltonianSatResult",
    "ConstrainedHamiltonianSatSession",
    "EdgeFlexibilityResult",
    "AllEdgePairFlexibilityResult",
    "ThreeEdgePathFlexibilityResult",
    "CubhamgCommandSpec",
    "CubhamgExecutable",
    "CubhamgResult",
    "analyze_all_edge_pair_flexibility",
    "analyze_same_face_edge_flexibility",
    "analyze_three_edge_path_flexibility",
    "benchmark_cubhamg",
    "canonical_graph_hash",
    "detect_plantri_version",
    "find_hamiltonian_cycle",
    "find_hamiltonian_cycle_sat",
    "enumerate_three_edge_paths",
    "find_constrained_hamiltonian_cycle",
    "graph_from_graph6_file",
    "graph_from_graph6_string",
    "load_graph",
    "iter_planar_code",
    "inspect_cubhamg",
    "locate_plantri",
    "read_jsonl",
    "solve_hamiltonian_cycle_sat",
    "solve_constrained_hamiltonian_cycle_sat",
    "stream_barnette_graphs",
    "validate_barnette_graph",
    "verify_hamiltonian_cycle",
]
