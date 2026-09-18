# Data availability and reconstruction status

This is a public research draft, not peer-reviewed. An accidental deletion of
drive E: destroyed the original external certificate packages. Release v0.9.0
contains newly calculated replacement certificates with new hashes and runtime
metadata. It does not claim to recover the deleted files byte for byte.

## Available recalculated certificates

| Scope | Graphs provided | What this supports |
|---|---:|---|
| Nonempty even orders 8 through 36 | 22,263 | Complete censuses and certified extremal values against the recorded Plantri 5.8 reference counts |
| D(9,9), D(11,9), D(11,11) | 3 | Exact graph-specific hsep values 60, 71, and 84 |

The census package retains canonical graph certificates and separating covers
for every graph. At orders through 24 every hsep value is exact. At larger
orders, exact lower certificates are included for every potential maximizer;
the remaining graphs have independently checked covers strictly below the
certified maximum. A release-level verifier checks the complete file inventory,
nested hashes, graph identities, covers, lower certificates, and stated maxima.
Census completeness rests on the recorded Plantri 5.8 reference class counts;
the verifier does not independently prove Plantri's enumeration theorem.

The public release assets are at
<https://github.com/derdualeraum-Regensburg/barnette-search/releases/tag/v0.9.0>:

- `barnette-recalculated-certificates-v0.9.0.zip`
- `barnette-manuscript-v0.9.0.pdf`
- `SHA256SUMS.txt`

Download the certificate archive and checksum file, check the archive's SHA-256,
extract it, and run from the extracted directory:

```console
python verify_recalculated_release.py . --report verification.json
```

The verifier and adjacent `verify_barnie_sequence.py` use only the Python 3.10+
standard library. Verification reads the package without modifying its records.
The [verification report](releases/v0.9.0-verification.json) records the checked
orders, exact extrema, graph-specific double-ladder values, environment, hashes,
and runtime. The release package passed this independent check on 2026-09-18 in
560.39 seconds with Python 3.12.10 on Windows 11.

## Historical and non-recalculated files

The deleted historical files remain unavailable, and their old hashes and
timestamps cannot be recreated. The v0.9.0 package is a separate recalculation
that re-establishes the complete extremal sequence through order 36, including
the unique order-36 maximizer with value 49. The old galleries and separate
prediction, packing-lift, and primal-lift computational packages were not part
of this recalculation. Symbolic proof-audit artifacts developed after the loss
remain versioned directly in the repository.

The general theorem for D(a,b) is proved symbolically in the manuscript. The
independent finite checker in `artifacts/proof_audit_20260916/verify_formula.py`
rebuilds its test graphs directly and does not require the lost datasets.

## Configuration and test reporting

Use `BARNETTE_RESULTS_ROOT` for external artifacts. For example, in PowerShell:

```powershell
$env:BARNETTE_RESULTS_ROOT = 'C:/research/barnette-results'
python -m pytest -q
```

The legacy single-graph benchmark uses Windows-specific peak-memory telemetry
and is skipped on other platforms; the mathematical release verifiers are
portable. A passing software test count is not a substitute for corpus
verification. New reconstruction runs must be versioned separately and must
not silently replace historical certificates or hashes.
