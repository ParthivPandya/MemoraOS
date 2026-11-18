# Scaling the vector index

`python -m benchmarks.scaling` measures two things; the raw tables are in [SCALING.md](../benchmarks/reports/SCALING.md).

## 1. Exact search is fast enough far beyond the old 10^5 note

Brute-force cosine over a float32 matrix (random unit vectors, latency only, one query, median):

| vectors | latency | matrix size |
|---:|---:|---:|
| 20,000 | 3.5 ms | 41 MB |
| 100,000 | 25 ms | 205 MB |
| 500,000 | 139 ms | 1 GB |

Memory, not latency, is the first limit. Latency was not measured with neural-embedding dimensions beyond the 512 used here, so scale the matrix size by `dim / 512`.

## 2. The opt-in IVF index trades recall for little speed

`Settings(vector_index="ivf")` builds a numpy inverted-file index once a scope holds at least `ann_min_vectors` vectors (default 20,000). Measured against exact search on 6,248 real sentences (this repo's docs plus Python's pydoc topics), recall@10 was 0.52-0.93 depending on `ann_nprobe`; for example 0.70 at `nprobe=8` while scoring 5.7% of vectors, and 0.84 at `nprobe=32` while scoring 22%. Latency gains were small or negative at this size.

Why the default stays `exact`: the hashing embedder clusters poorly, so IVF loses neighbours, and exact search is cheap well past 10^5 vectors. IVF is shipped for users with very large scopes and a neural embedder, but it has **not** been measured with a neural embedder, and no claim is made that it helps. Check `benchmarks.scaling` (`measure_recall`) on your own data before enabling it.
