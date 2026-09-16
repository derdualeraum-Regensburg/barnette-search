# Data availability and reconstruction status

This is a public research draft, not peer-reviewed. An accidental deletion of
drive E: destroyed the original external certificate packages. The current
release distinguishes the reconstructed files from historical claims based on
the original computation. Original hashes in historical reports are retained;
they do not imply that the corresponding lost files can currently be downloaded.

## Available reconstructed certificates

| Scope | Graphs provided | What this supports |
|---|---:|---|
| Nonempty orders 8 through 24 | 55 | Complete small censuses against the recorded plantri reference counts |
| Order 26 | 39 of 57 | Individual exact values for the supplied graphs; incomplete census |
| Order 32 | 3 of 1,543 | Individual exact values only; no maximum or uniqueness claim |

Each graph package retains its graph6/planar_code representation, complete
Hamiltonian universe, upper and lower certificates, original manifests, and
recorded solver metadata. A release-level verifier checks all hashes,
re-enumerates Hamiltonian cycles independently, verifies both bounds, rejects
duplicate graph identities, and checks the stated inventory. Completeness of
the small graph censuses rests on the reference class counts; the verifier
does not independently prove plantri's enumeration theorem.

The public release assets are at
<https://github.com/derdualeraum-Regensburg/barnette-search/releases/tag/v0.8.0>:

- `barnette-reconstructed-certificates-v0.8.0.zip`
- `barnette-manuscript-v0.8.0.pdf`
- `SHA256SUMS.txt`

Download the certificate archive and checksum file, check the archive's SHA-256,
extract it, and run from the extracted directory:

```console
python verify_reconstructed_release.py . --workers 4
```

The verifier and adjacent `verify_barnie_sequence.py` use only the Python 3.10+
standard library. The release records the verification runtime and file hashes.
All 97 supplied graphs passed this independent check on 2026-09-16 in 527.83
seconds with four workers on Windows and Python 3.12.10. The
[verification report](releases/v0.8.0-verification.json) records each exact value,
the command, environment, and verifier hashes. The archive also includes this
report as `release_verification.json`.
Verification reads the package without overwriting its original records.
Use `--workers 1` for a serial check. The allowed range is one to four workers;
result order remains deterministic. Exhaustive lower proofs for a few graphs
take several minutes, so full verification can take substantially longer than
the software regression suite.

## Unavailable original packages

The original `barnie-sequence` package through order 36, its gallery and
ladder-analysis packages, and the double-ladder prediction, packing-lift, and
primal-lift packages are not part of the recovered data. Their historical
summaries remain in the manuscript and audit reports, explicitly subject to
this limitation. In particular, the public reconstruction does not currently
re-establish the claimed order-36 global maximum and uniqueness.

The general theorem for D(a,b) is proved symbolically in the manuscript. The
independent finite checker in `artifacts/proof_audit_20260916/verify_formula.py`
rebuilds its test graphs directly and does not require the lost datasets.

## Configuration and test reporting

Use `BARNETTE_RESULTS_ROOT` for external artifacts. For example, in PowerShell:

```powershell
$env:BARNETTE_RESULTS_ROOT = 'C:/research/barnette-results'
python -m pytest -q
```

Tests requiring lost packages use explicit skips. The legacy single-graph
benchmark uses Windows-specific peak-memory telemetry and is skipped on other
platforms; the underlying mathematical verifiers and this release verifier are
portable. A passing software test count is not a substitute for corpus
verification. New reconstruction runs must be versioned separately and must
not silently replace original historical certificates or hashes.
