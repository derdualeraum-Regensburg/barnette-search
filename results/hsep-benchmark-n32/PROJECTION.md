# Exact hsep benchmark, order 32

All three graphs completed exact enumeration, optimization, lower-bound certification, and independent verification.

| selection | cycles | exact hsep | stored greedy | universe greedy | enumeration s | optimization s | verifier s | peak MiB | plain/gzip bytes | lower bound |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| niedrig | 60 | 11 | 19 | 13 | 0.026165 | 23.186383 | 2.047512 | 230.8 | 5485/644 | standalone_exhaustive_set_cover |
| median | 138 | 15 | 28 | 19 | 0.042628 | 79.237759 | 63.271555 | 266.6 | 12349/1084 | standalone_exhaustive_set_cover |
| hoch | 54 | 40 | 47 | 41 | 0.027378 | 1.410998 | 0.217346 | 44.4 | 4954/684 | packing |

## Serial projection through order 36

Total reference graph count: 22,263. Scenarios are sorted by observed total runtime, not by the original greedy-selection labels.

| scenario | basis | seconds/graph | serial hours | serial days | projected artifact MiB | peak MiB |
|---|---|---:|---:|---:|---:|---:|
| leicht | hoch | 1.758 | 10.9 | 0.45 | 325.5 | 44.4 |
| mittel | niedrig | 25.349 | 156.8 | 6.53 | 278.3 | 230.8 |
| schwer | median | 142.690 | 882.4 | 36.77 | 441.3 | 266.6 |

This is a coarse three-sample order-32 extrapolation. It excludes census reconstruction and cannot predict rare hard lower-bound tails.
