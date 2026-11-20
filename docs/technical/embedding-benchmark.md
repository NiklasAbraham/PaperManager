# Embedding benchmark

How the embedding models compared on one real library, and how to run the same comparison on yours.
It backs the advice in [Switching the embedding model](../user-guide/switching-the-embedding-model.md#choosing-an-embedding-model).
The default model is still `BAAI/bge-small-en-v1.5`; nothing here changes it.

**Short version.** On this library, citation-neighbour recall was higher for larger and for scientific-paper
embedders than for the small default, by about 0.03 to 0.09 (standard error about 0.02), and the ranking among the
top models was not stable between two runs. The feed's AUC did not separate the models. Treat the table as a
starting point for your own run, not as a recommendation.

## Run it on your own library

```bash
python backend/scripts/embedder_benchmark.py --data <export dir> --models <id1,id2,...> --out <results dir> --device cuda
```

The script embeds your library and the feed candidates with each model (one process per model, fp16 on a GPU)
and writes the metrics below. Its docstring lists the export format and the model-specific layouts. Keep the
export and the results out of the git repository: they contain your library.

This is an anonymised summary of an offline benchmark of text-embedding models on one personal
PaperManager library. No paper titles, ids, topic names, user names or hosts appear here. The
benchmark script is `backend/scripts/embedder_benchmark.py`; the exact data are private.

## Dataset

| | run 1 | run 2 (this run) |
|---|---|---|
| library papers (real, not reference stubs) | 1,341 | 1,342 |
| of these with an abstract | 604 | 1,181 |
| with an abstract or an AI summary | 612 | 1,184 |
| citation edges between library papers | 345 | 345 |
| library papers with at least one such edge (excluding self-citations) | 192 | 192 |
| of these with an abstract (strict subset) | not measured | 189 |
| library papers with at least one topic | 459 | 468 |
| reference stubs with an abstract (extra neighbour pool) | not used | 5,321 of 9,749 |
| feed candidates (arXiv and bioRxiv preprints) | 2,325 | 2,958 |

Between the runs, abstracts were back-filled for most real papers and for about half of the
reference stubs. The citation graph among real papers did not change. The live system also switched
its embedding model to SciEmbed full between the runs, so run 2 is the first run on the final texts.

## Method

* Text: title, newline, abstract (or AI summary when there is no abstract) cut to 1,500 characters;
  the same text the application embeds. Models whose card asks for it get their own layout
  (title [SEP] abstract for SPECTER2 and SciNCL, a title/abstract pair for MedCPT, a document prefix for
  Nomic). Max length 512 tokens, fp16 on a GPU, unit-normalised vectors, pooling per model card (CLS, mean or
  last token). Each model ran in its own process. The two models with custom code (GTE-large, Nomic) ran
  with remote code allowed, for this benchmark only, on transformers 4.57.
* **M1, citation-neighbour recall:** for every paper with at least one citation edge inside the pool, take its
  10 nearest neighbours by cosine (itself excluded); recall@10 is the share of its cited and citing papers
  found; MRR is the reciprocal rank of the first cited or citing paper in the full ranking.
  Variants: *all* = all 192 real papers with an edge (pool: the 1,342 real papers); *strict* = only the 189
  queries that have a real abstract (pool unchanged); *stubs* = the 281 real papers with at least one edge
  to any pool paper as queries, and a pool of all 6,663 papers (1,342 real + 5,321 reference stubs
  with text; stubs without any text are left out), 7,556 citation edges.
  Random-neighbour baseline recall@10 is 0.008 (all) and 0.002 (stubs pool).
* **M2, topic agreement:** mean Jaccard overlap of the topic sets of a paper and its 10 nearest library
  neighbours, over the 468 papers that have topics. Random-neighbour baseline: 0.010.
* **M3, feed classifier AUC:** the feed's own training and evaluation code is run on each model's vectors
  (positives from the user's ratings, reads and additions; the feed candidates as random negatives).
  "feed" is the number the live feed reports: the 20 % most recently added positives held out
  (23 of 117 positives). "random" holds out a random 20 % of the positives instead (also 23 of 117), repeated for three
  seeds; the table gives mean (standard deviation over seeds).
* **Throughput** is papers per second over all 9,621 texts (library, candidates, stubs) with the model already
  loaded, on a GPU shared with unrelated jobs; peak memory is torch's peak allocated GPU memory.

## Results (run 2)

| model | params (M) | dim | M1 R@10 all | M1 MRR all | M1 R@10 strict | M1 stubs pool R@10 / MRR | M2 Jaccard | M3 AUC feed | M3 AUC random hold-out, 3 seeds | papers/s | peak MB | licence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BAAI/bge-small-en-v1.5 | 33 | 384 | 0.279 | 0.299 | 0.283 | 0.138 / 0.471 | 0.067 | 0.474 | 0.860 (0.051) | 1147 | 214 | MIT |
| BAAI/bge-base-en-v1.5 | 109 | 768 | 0.313 | 0.322 | 0.318 | 0.158 / 0.485 | 0.068 | 0.492 | 0.874 (0.055) | 636 | 502 | MIT |
| BAAI/bge-large-en-v1.5 | 335 | 1024 | 0.320 | 0.310 | 0.326 | 0.153 / 0.478 | 0.069 | 0.574 | 0.879 (0.055) | 227 | 1027 | MIT |
| BAAI/bge-m3 | 568 | 1024 | 0.297 | 0.329 | 0.302 | 0.143 / 0.485 | 0.064 | 0.704 | 0.913 (0.015) | 201 | 1473 | MIT |
| Alibaba-NLP/gte-large-en-v1.5 | 434 | 1024 | 0.332 | 0.334 | 0.338 | 0.153 / 0.470 | 0.071 | 0.564 | 0.879 (0.033) | 159 | 1537 | Apache-2.0 |
| nomic-ai/nomic-embed-text-v1.5 | 137 | 768 | 0.317 | 0.354 | 0.322 | 0.159 / 0.495 | 0.067 | 0.566 | 0.878 (0.051) | 148 | 1525 | Apache-2.0 |
| allenai/specter2_base | 110 | 768 | 0.300 | 0.317 | 0.305 | 0.149 / 0.489 | 0.067 | 0.602 | 0.853 (0.044) | 632 | 478 | Apache-2.0 |
| malteos/scincl | 110 | 768 | 0.289 | 0.327 | 0.293 | 0.138 / 0.468 | 0.066 | 0.548 | 0.847 (0.055) | 649 | 478 | MIT |
| ncbi/MedCPT-Article-Encoder | 109 | 768 | 0.207 | 0.246 | 0.211 | 0.103 / 0.428 | 0.056 | 0.596 | 0.908 (0.024) | 641 | 481 | public domain (NCBI) |
| Qwen/Qwen3-Embedding-0.6B | 596 | 1024 | 0.321 | 0.357 | 0.326 | 0.159 / 0.492 | 0.069 | 0.604 | 0.869 (0.040) | 98 | 3332 | Apache-2.0 |
| Qwen/Qwen3-Embedding-4B | 4022 | 2560 | 0.366 | 0.367 | 0.372 | 0.165 / 0.546 | 0.073 | 0.645 | 0.904 (0.024) | 20 | 9245 | Apache-2.0 |
| J0nasW/sciembed-full | 149 | 768 | 0.334 | 0.347 | 0.339 | 0.170 / 0.514 | 0.071 | 0.582 | 0.898 (0.036) | 335 | 655 | MIT |
| J0nasW/sciembed-ctx-2048 | 149 | 768 | 0.312 | 0.320 | 0.317 | 0.162 / 0.507 | 0.069 | 0.597 | 0.897 (0.045) | 337 | 655 | MIT |
| J0nasW/sciembed-ctx-8192 | 149 | 768 | 0.310 | 0.323 | 0.314 | 0.166 / 0.501 | 0.067 | 0.549 | 0.895 (0.048) | 333 | 655 | MIT |

Notes on the table: Qwen3-Embedding-4B ran at batch size 8 after two out-of-memory halvings under a 10 GB budget (peak 9.2 GB).
Qwen3-Embedding-0.6B and 4B use last-token pooling without an instruction; SPECTER2 is the base model without adapters.
Not run: EmbeddingGemma-300M (gated repository, no access). SciEmbed full is the model the paper calls its headline model;
ctx-2048 and ctx-8192 are its longer-context variants. The model cards name the SciEmbed release (Findings of EMNLP 2026) and an MIT licence.

## Reading the numbers

* **M1 (all and strict):** Qwen3-Embedding-4B has the highest recall (0.372 strict, 0.088 above the
  bge-small baseline with a paired standard error of 0.021). SciEmbed full, GTE-large and Qwen3-Embedding-0.6B follow
  (strict 0.339, 0.338, 0.326; paired gaps to the baseline of 0.056, 0.054, 0.043, standard errors 0.019 to 0.022).
  bge-base is +0.034 (SE 0.015). MedCPT is clearly lowest (0.211), below the baseline (0.283), as expected for a biomedical-only encoder.
* **M1 with the stubs pool:** absolute recall is lower (0.10 to 0.17) because each query now has many more cited papers to find in a pool five
  times larger. SciEmbed full is best (0.170), then ctx-8192 (0.166), Qwen3-4B (0.165), ctx-2048 (0.162); the baseline is 0.138.
  The model ranking is moderately stable across pools (Spearman 0.75 between "all" and "stubs"); the main change is that the three SciEmbed
  models move up and GTE-large and bge-large move down. Qwen3-4B has the best MRR (0.546) in the stubs pool.
* **M2:** every model is far above the random baseline (0.010) but they differ little (0.064 to 0.071), except MedCPT (0.056).
  GTE-large and SciEmbed full are the highest (0.071).
* **M3:** very noisy. With the feed's temporal hold-out (23 positives) the AUCs spread from 0.47 to 0.70 with no consistent order across the two
  runs (Spearman 0.60 between runs). bge-m3 is highest (0.704) and Qwen3-4B next (0.645) there. With random hold-outs the three seeds
  of one model range by up to 0.12 (for example 0.79 to 0.92 for the baseline); means are 0.85 to 0.91, with bge-m3, MedCPT, Qwen3-4B and
  the SciEmbed models at the top. Differences between neighbouring models in M3 are within noise.

## Comparison with run 1

| model | R@10 all (run 1) | M2 (run 1) | M3 feed (run 1) | M3 random (run 1) | R@10 all (run 2) | M2 (run 2) | M3 feed (run 2) | M3 random (run 2) |
|---|---|---|---|---|---|---|---|---|
| BAAI/bge-small-en-v1.5 | 0.292 | 0.068 | 0.576 | 0.847 | 0.279 | 0.067 | 0.474 | 0.860 |
| BAAI/bge-base-en-v1.5 | 0.322 | 0.068 | 0.587 | 0.848 | 0.313 | 0.068 | 0.492 | 0.874 |
| BAAI/bge-large-en-v1.5 | 0.311 | 0.069 | 0.673 | 0.872 | 0.320 | 0.069 | 0.574 | 0.879 |
| BAAI/bge-m3 | 0.311 | 0.065 | 0.739 | 0.890 | 0.297 | 0.064 | 0.704 | 0.913 |
| Alibaba-NLP/gte-large-en-v1.5 | 0.329 | 0.072 | 0.680 | 0.868 | 0.332 | 0.071 | 0.564 | 0.879 |
| nomic-ai/nomic-embed-text-v1.5 | 0.307 | 0.068 | 0.619 | 0.864 | 0.317 | 0.067 | 0.566 | 0.878 |
| allenai/specter2_base | 0.304 | 0.067 | 0.672 | 0.856 | 0.300 | 0.067 | 0.602 | 0.853 |
| malteos/scincl | 0.292 | 0.066 | 0.636 | 0.856 | 0.289 | 0.066 | 0.548 | 0.847 |
| ncbi/MedCPT-Article-Encoder | 0.214 | 0.057 | 0.696 | 0.891 | 0.207 | 0.056 | 0.596 | 0.908 |
| Qwen/Qwen3-Embedding-0.6B | 0.297 | 0.069 | 0.623 | 0.852 | 0.321 | 0.069 | 0.604 | 0.869 |
| Qwen/Qwen3-Embedding-4B | - | - | - | - | 0.366 | 0.073 | 0.645 | 0.904 |
| J0nasW/sciembed-full | 0.360 | 0.071 | 0.660 | 0.877 | 0.334 | 0.071 | 0.582 | 0.898 |
| J0nasW/sciembed-ctx-2048 | 0.330 | 0.070 | 0.660 | 0.865 | 0.312 | 0.069 | 0.597 | 0.897 |
| J0nasW/sciembed-ctx-8192 | 0.317 | 0.067 | 0.645 | 0.869 | 0.310 | 0.067 | 0.549 | 0.895 |

* The text changed a lot (abstracts for 1,181 instead of 604 papers), but M1 and M2 changed little. M1 recall moved by up to about 0.03 per model
  (the baseline fell from 0.292 to 0.279, SciEmbed full from 0.360 to 0.334, Qwen3-0.6B rose from 0.297 to 0.321). The M2 ranking is practically unchanged
  (Spearman 0.98) and the M1 ranking moderately so (0.70). In run 1 SciEmbed full led M1 outright; in run 2 it is
  within noise of Qwen3-4B, GTE-large and Qwen3-0.6B, and Qwen3-4B (not run before) is ahead on the strict subset.
* The feed-style M3 AUC fell for most models, including the baseline (0.576 to 0.474), and its ranking changed (Spearman 0.60). The held-out set is 23 positives in both
  runs and the library, the candidate set (2,958 instead of 2,325 papers) and the training set (117 instead of 113 positives) all changed, so this is
  consistent with noise and a different candidate mix; no cause was tested. The random-hold-out AUC rose slightly for nearly all models and the ordering is stable (Spearman 0.87).
* Throughput roughly doubled for most models (Nomic got slower, 188 to 148 papers/s); the GPU load from other jobs differed between runs, so throughput is not comparable across runs.

## Caveats

* M1 and M2 measure agreement with this one user's own citation graph and topic labels, not usefulness for search or recommendations. The graph is small (345 edges).
* The standard error of an M1 recall mean is about 0.02, so gaps below about 0.04 between models are not distinguishable. Queries in the "stubs" variant differ from the other
  variants, so absolute values are not comparable across variants.
* M3 has 23 held-out positives and the random-hold-out numbers measure mostly whether a model separates the user's papers from recent preprints. It is not a measure of ranking quality inside the feed.
* Only 3 seeds, one library, one run per model; fp16 throughput numbers come from a shared GPU.
