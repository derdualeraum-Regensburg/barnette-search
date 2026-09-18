# Public history preparation

The first public release is v0.8.0. Before publication, the full original Git
history and the current working tree were backed up privately. Public branches
and tags were rewritten to remove the accidentally committed external
`planar_draw` executable, debug/object files, and compiler caches. The author's
commit email was normalized to the account's GitHub noreply address; author
names and research source contents were preserved except for the documented
publication-preparation changes.

Consequently historical commit identifiers may differ from those in old run
metadata. Original graph identities, data manifests, and executable hashes
inside research records were not rewritten to pretend that the original runs
used a different environment. These records document past runs, not permission
to redistribute external programs or a promise that lost data remains available.

Existing local clones should be backed up and freshly cloned after this rewrite;
merging the old branches would reintroduce removed files. Private backup bundles
must never be pushed to a public remote.

Release v0.9.0 publishes a newly calculated replacement for the lost census
evidence. It does not reuse the historical hashes or present the new files as a
recovery of the deleted bytes. Resumable working checkpoints remain outside Git;
only the compact immutable certificate package is distributed as a release
asset.
