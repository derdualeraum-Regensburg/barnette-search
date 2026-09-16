# Third-party notices

## plantri

`tools/plantri/plantri-guide-5.8.txt` is the upstream plantri guide. Its Appendix G
states the copyright of Gunnar Brinkmann and Brendan McKay and the Apache
License, Version 2.0. The license text is preserved in
`tools/plantri/LICENSE-2.0.txt`; source identifiers and hashes are in
`tools/plantri/SOURCE.json`. The local Windows patch is identified separately
and changes platform handling, not graph generation. No plantri executable or
upstream C source is distributed here.

## External drawing program

Gunnar Brinkmann's `planar_draw` source and executable are not licensed by this
repository and are not distributed in the public source history. Historical
research logs preserve the commands and hashes used to produce the figures.
Those records do not grant permission to redistribute the program. The
locally authored compatibility include and wrappers are project software.
Previously committed executable, debug, object, and compiler-cache files were
removed during preparation of the public repository.

## Dependencies and references

NetworkX, python-sat, Matplotlib, pytest, psutil, and the build tools are separate
packages under their respective licenses; installing this project does not
relicense them. Bibliographic citations do not grant rights to the cited papers.
MIT and CC BY grants cover only the project's own contributions as described
in `LICENSES/README.md`.
