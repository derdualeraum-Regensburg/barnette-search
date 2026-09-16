# Contributing

Read `AGENTS.md` and `docs/hsep.md` before changing mathematical code. Report
mathematical concerns with a graph6/planar_code example and an independently
checkable certificate where possible. Distinguish labelled graphs from
isomorphism classes, upper bounds from exact values, and finite evidence from
general proofs. Preserve original data and provenance.

Install with `python -m pip install -e ".[test]"`, then run
`python -m pytest -q`. Tests requiring unavailable external programs or original
data packages are explicitly skipped. See `docs/data_availability.md` for what
can currently be reproduced. Add tests for mathematical and parsing changes.

Use an issue or pull request for proposed changes. Include the reason for the
change, verification performed, dependency versions, and any remaining proof
limitations. Do not commit credentials, compiler caches, external drawing
programs, or private result directories. Contributions must be compatible with
the applicable licenses in `LICENSES/README.md`.
