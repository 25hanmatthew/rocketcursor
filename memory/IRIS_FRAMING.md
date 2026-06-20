# IRIS Memory Layer Briefing

The memory layer isn't a lookup table — it's a retrieval system that tells the agent where knowledge came from and whether it applies.

## Agent memory

Agents read and write shared state through the `memory` package (`memory.core`) on Redis Stack (RedisJSON + RediSearch). Failure records and design-iteration snapshots persist across sessions. External prior art (NASA LLIS/NTRS via `memory.ingest_failures`, hand-seeded cases via `memory.seed_failures`) and runtime internal writeback share the same storage contract.

- `write_failure()` and `write_design()` in `memory.core`

## Vector search

All failures live in one RediSearch index (`idx:failures`) with 1024-dimensional Voyage `voyage-3.5-lite` embeddings (`VECTOR_DIM = 1024`). Each record carries two HNSW vector fields: `embedding` (combined text from failure_mode, root_cause, and the other three fields) and `rc_embedding` (root cause only). `search_failures()` runs cosine k-NN over the selected vector. The `field` parameter switches the query target — `combined` (all five fields, including `failure_mode`) or `root_cause` alone — changing which records surface, not just their rank.

- `idx:failures` with `VECTOR_DIM = 1024` in `memory.core`

## Context retrieval

Retrieval returns structured context — `failure_mode`, `root_cause`, `corrective_action`, cosine distance score — plus provenance on every hit. The `source` tag filters internal vs external corpus; `source_type` (TAG field on the index) marks whether a case is project-native or imported. Before listing retrieved cases in the orchestrator prompt, the hour-20 transferability fragment instructs the agent: internal cases transfer as direct constraints; external cases require an explicit structural analogy or the lesson is not applied.

- Transferability prompt fragment (hour 20): internal `source_type` → direct constraint; external → require structural analogy
