# Barnie maximizer gallery

The gallery wrappers visualize the already certified Barnie-sequence
maximizers. They do not run graph generation, Hamiltonian-cycle enumeration,
or hsep optimization.

## External drawing engine

`tools/planar_draw.c` is Gunnar Brinkmann's external drawing program. The
source and compiled executable are intentionally ignored by Git. On Windows,
MinGW-w64 can compile the unmodified source as follows (prepend the compiler's
`bin` directory to `PATH` so that GCC can find its assembler):

```text
gcc -O4 -std=gnu11 -I tools/planar_draw_compat -Wl,--stack,67108864 -o E:\barnette-results\barnie-gallery-toolchain\planar_draw.exe tools\planar_draw.c -lm
```

The compatibility include is intentionally empty: the external source includes
`sys/times.h` but does not use anything declared by that POSIX header, which is
absent from MinGW-w64.

The common drawing options are `T n B`. `T` supplies the certified binary
planar code in the program's equivalent ASCII input form; this avoids Windows
CRT translation of byte `0x1A` at order 26. The remaining options suppress
vertex labels and ask the C program to retain its best-distance planar layout.
The raw TikZ output is saved
alongside a standalone SVG. Before writing the SVG, the wrapper checks that the
vertices and edges parsed from TikZ exactly match the certified graph record.

## Rendering

Render all certified maximizers, including every member of a tie:

```text
python tools/render_all_maximizers.py ^
  --sequence-root E:\barnette-results\barnie-sequence ^
  --gallery-root E:\barnette-results\barnie-sequence\gallery ^
  --engine E:\barnette-results\barnie-gallery-toolchain\planar_draw.exe ^
  --engine-source tools\planar_draw.c ^
  --compiler E:\barnette-results\barnie-gallery-toolchain\w64devkit-2.9.0\w64devkit\bin\gcc.exe ^
  --compat-include tools\planar_draw_compat
```

Pass `--png-renderer` with a Chromium-compatible browser executable to add
900-by-900 PNG previews. SVG and TikZ generation uses only Python's standard
library plus the external C executable.

The run is resumable. Each drawing has a `.render.json` sidecar binding it to
the graph's planar-code hash, the drawing executable hash, the common options,
and output hashes. A failure is recorded and does not prevent later maximizers
from being attempted. The command exits nonzero unless every certified
maximizer is rendered.

Render one maximizer directly with `tools/draw_single_maximizer.py`; its CLI
requires the order and full certified canonical hash.
