# Figure provenance

The six `d*.png` files are byte-for-byte copies of the corresponding PNG
records in the immutable maximizer gallery:

| local file | certified gallery source | SHA-256 |
|---|---|---|
| `d11.png` | `order_08/n_08_M_6_rank_00001_204b8679.png` | `57a2dc82defd08dd67333658b0a593b610ffcde1902c256fa477eb0b60b6971d` |
| `d53.png` | `order_20/n_20_M_17_rank_00002_bc06aac0.png` | `cdf861854f158aba8d0ed417a40076a3577a4aa9355f38e57d9e7998f3461507` |
| `d55.png` | `order_24/n_24_M_24_rank_00003_5a3354bd.png` | `fd776dfc68949738fe673e36154479348d83c91e2c44bed8b59096db2239de2c` |
| `d75.png` | `order_28/n_28_M_31_rank_00003_4db90650.png` | `fa0eb75d87c7b80c2e868c0d8f1d2c2ecb5a6bfede16eb274f23759ca500cc67` |
| `d77.png` | `order_32/n_32_M_40_rank_00010_d5967330.png` | `8e5239008f0cde687ae872631f7eeeb03003d31b359109d6ce3714400675ec98` |
| `d97.png` | `order_36/n_36_M_49_rank_00011_2f96ada1.png` | `ada24607c3c3d735e17f5d611b025906c2a52d5113128ea0a34169ec8be0a69d` |

The three annotated SVG files are byte-for-byte copies from
`E:\barnette-results\barnie-sequence\ladder-analysis\figures`. Their PNG
counterparts were rasterized at 1200 by 1200 pixels with the already recorded
Microsoft Edge executable, SHA-256
`e95ea3f44d9db3f786bd1fa72c50bc8d173065f629f553a8eb4e502e56e703a8`.
The SVGs remain the presentation masters; the PNGs permit ordinary
`pdflatex` compilation without an SVG conversion dependency.

All layouts ultimately derive from Gunnar Brinkmann's external drawing program
as documented by the immutable gallery. No external C source is copied here.

The packing grid, separating-family grid, and square-insertion lift are drawn
directly in `sections/exact_hsep.tex` with TikZ from the symbolic turn-cell
coordinates. They are mathematical schematics, not graph-layout or generated
illustration assets.
