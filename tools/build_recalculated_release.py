#!/usr/bin/env python3
"""Build a compact, deterministic release archive from a completed reconstruction."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import stat
import zipfile


LADDERS = ("D_9_9", "D_11_9", "D_11_11")


def copy_tree_without_work(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if ".work" in relative.parts or not path.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def write_manifest(root: Path) -> None:
    entries = []
    manifest = root / "SHA256SUMS.txt"
    for path in sorted(root.rglob("*")):
        if path.is_file() and path != manifest:
            entries.append(f"{sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
    manifest.write_text("\n".join(entries) + "\n", encoding="ascii", newline="\n")


def deterministic_zip(source: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            output.writestr(info, path.read_bytes(), compresslevel=9)


def build(repository: Path, run_root: Path, output: Path, version: str) -> tuple[Path, Path]:
    status = json.loads((run_root / "work" / "status.json").read_text(encoding="utf-8"))
    if status.get("status") != "completed":
        raise ValueError("reconstruction is not complete")
    package = output / f"barnette-recalculated-certificates-{version}"
    archive = output / f"barnette-recalculated-certificates-{version}.zip"
    if package.exists() or archive.exists():
        raise FileExistsError("release output already exists")
    package.mkdir(parents=True)
    copy_tree_without_work(run_root / "work" / "barnie-sequence", package / "barnie-sequence")
    for name in LADDERS:
        shutil.copytree(
            run_root / "work" / "double-ladders" / name / "attempt-1",
            package / "double-ladders" / name / "attempt-1",
        )
    shutil.copytree(run_root / "work" / "verification", package / "run-verification")
    for name in ("configuration.json", "status.json"):
        shutil.copyfile(run_root / "work" / name, package / name)
    shutil.copyfile(run_root / "RUN_PLAN.json", package / "RUN_PLAN.json")
    shutil.copyfile(repository / "LICENSE", package / "LICENSE")
    shutil.copyfile(repository / "LICENSES" / "CC-BY-4.0.txt", package / "CC-BY-4.0.txt")
    shutil.copyfile(repository / "tools" / "verify_barnie_sequence.py", package / "verify_barnie_sequence.py")
    shutil.copyfile(repository / "tools" / "verify_recalculated_release.py", package / "verify_recalculated_release.py")
    readme = f"""# Recalculated Barnette certificates {version}

This package contains a newly calculated complete Barnette-graph census for
orders 8 through 36 and exact graph-specific hsep certificates for D(9,9),
D(11,9), and D(11,11). The package has its own hashes and runtime metadata.

Verify after extraction with Python 3.10 or newer:

    python verify_recalculated_release.py . --report verification.json

The verifier uses only the Python standard library, checks the complete release
inventory and nested manifests, validates every census graph and separating
cover, checks the exact lower certificates needed for each census maximum, and
independently verifies the three double-ladder certificates. Census completeness
uses the recorded Plantri 5.8 reference counts.
"""
    (package / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    write_manifest(package)
    output.mkdir(parents=True, exist_ok=True)
    deterministic_zip(package, archive)
    return package, archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", default="v0.9.0")
    args = parser.parse_args()
    package, archive = build(args.repository.resolve(), args.run_root.resolve(), args.output.resolve(), args.version)
    print(json.dumps({
        "package": str(package),
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive.read_bytes()).hexdigest(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
