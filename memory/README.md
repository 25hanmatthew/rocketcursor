# Memory Layer

Retrieval contract for propulsion/orchestrator agents: read and write shared state through
the `memory` package (`memory.core`). Redis Stack (RedisJSON + RediSearch) holds failure
records and design history; agents never touch Redis keys directly.

## 0. Install (from repo root)

```bash
pip install -r memory/requirements.txt
cp .env.example .env   # fill in repo-root keys
export $(grep -v '^#' .env | xargs)   # or use direnv / your shell loader
```

Run scripts as modules so imports resolve:

```bash
python -m memory.ingest_failures --load --dry-run
python -m memory.seed_failures
python -m memory.verify_voyage
python -m unittest memory.tests.test_ntrs_helpers
```

Cache JSON files and downloaded PDFs live under `memory/` (see `memory.paths`).

## 1. What this is

Shared memory is Redis Stack on localhost with one RediSearch vector index, `idx:failures`,
over the `failure:` JSON key prefix. Embeddings use Voyage `voyage-3.5-lite` at 1024
dimensions (`VECTOR_DIM=1024`, frozen — do not change without re-indexing). Requires
`VOYAGE_API_KEY` in the environment. Internal failures (written by agents at runtime) and
external failures (scraped or hand-seeded prior art) share the **same** index; a `source`
tag distinguishes `"internal"` from `"external"`.

**Full documents** fetched from the web are stored separately from the extracted failure
records. Each lives at `doc:{source}:{doc_id}` (full text + provenance: `url`,
`canonical_url`, `title`, `sha256`, `fetched_at`, `content_type`). A dedup hash
`doc:url_index` maps `sha256(canonical_url)` to the stored key so a source is never fetched
twice (`has_document_by_url`). Document text is chunked and embedded into a second
RediSearch index, `idx:docs`, over the `docchunk:{doc_id}:{n}` prefix (same frozen
`VECTOR_DIM=1024` model), searchable via `search_documents`. This is what powers
passage-level retrieval in `memory.research`.

## 2. Setup / connection

**Redis Stack (Docker, one line):**

```bash
docker run -d --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
```

**Environment variables (from code):**

| Variable | Required | Purpose |
|----------|----------|---------|
| `VOYAGE_API_KEY` | Yes | Voyage client for `embed_documents` / `embed_query` |
| `REDIS_URL` | No | Used when `Memory(redis_url=...)` is omitted; overrides host/port |

**Instantiation:**

```python
from memory import Memory

m = Memory()                          # default: localhost:6379
m = Memory(redis_url="redis://...")   # explicit URL wins
m = Memory(host="127.0.0.1", port=6380)  # only if no redis_url and no REDIS_URL
```

Constructor: `Memory(redis_url=None, host="localhost", port=6379)`.

Connection resolution (`_redis_client`): if `redis_url` is passed, it is used; otherwise
`REDIS_URL` from the environment; otherwise `redis.Redis(host="localhost", port=6379)`.
So `redis_url` (or `REDIS_URL`) overrides `host`/`port`. Default no-arg `Memory()` connects
to **localhost:6379**. On first use, `Memory` creates index `idx:failures` if missing.

## 3. API reference

Instantiate first: `m = Memory()`. All methods below are on the `Memory` class.

### `search_failures(query_text: str, k=5, source=None, field="combined")`

Semantic k-NN search over indexed failures.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `query_text` | `str` | Plain-text query; embedded internally (`input_type="query"`) |
| `k` | `int` | Max neighbors requested (default `5`) |
| `source` | `str \| None` | `None` = all sources; `"internal"` or `"external"` to filter |
| `field` | `str` | `"combined"` (default) or `"root_cause"` — which vector field to search |

**Parameter order is `query_text, k, source, field`.** Pass `source` and `field` by keyword
to avoid positional mistakes.

- **`field`:** selects the indexed vector compared to the query.
  - `"combined"` → `embedding` (built from all five text fields)
  - `"root_cause"` → `rc_embedding` (root-cause text only)
  - This changes **what surfaces**, not just ranking — `root_cause` can return records that
    do not appear under `combined` for the same query.
- **`source`:** RediSearch tag filter `@source:{internal}` or `@source:{external}`.

**Returns:** `list[dict]`, each with keys `id`, `score`, `source`, `failure_mode`,
`root_cause`, `corrective_action`.

**Score direction:** COSINE **distance** (index metric `DISTANCE_METRIC: COSINE`). Results
are sorted ascending by `score`; **lower = closer / more relevant** (0 = identical direction).

```python
m.search_failures("cryogenic tank rupture during pressurization", k=5)
m.search_failures("O-ring seal failure", k=3, source="external", field="root_cause")
```

### `write_failure(source, id_, fields: dict)`

Write or overwrite one failure record. Key: `failure:{source}:{id_}` (e.g.
`failure:external:llis_485`, `failure:internal:iter3_valve_margin`).

| Parameter | Type | Meaning |
|-----------|------|---------|
| `source` | `str` | `"internal"` or `"external"` |
| `id_` | `str` | Stable slug within that source |
| `fields` | `dict` | Failure text fields (see below) |

**`fields` keys read by the code:**

| Key | Used for |
|-----|----------|
| `failure_mode` | Stored + combined embedding |
| `system_config` | Stored + combined embedding |
| `operating_conditions` | Stored + combined embedding |
| `root_cause` | Stored + combined embedding + separate `rc_embedding` |
| `corrective_action` | Stored + combined embedding |

Missing keys are treated as empty strings. The method also writes `id`, `source`,
`embedding`, and `rc_embedding` into the JSON document.

**Returns:** Redis key string (e.g. `"failure:external:apollo13_o2_tank"`).

**Idempotent:** re-writing the same `failure:{source}:{id_}` overwrites in place — no dupes.

```python
m.write_failure("internal", "iter2_feed_line", {
    "failure_mode": "Propellant feed line leak at manifold",
    "system_config": "Staged-combustion engine with dual redundant feed paths",
    "operating_conditions": "Hot-fire test, 80% rated thrust",
    "root_cause": "Improper torque on flange bolts",
    "corrective_action": "Re-torque procedure and flange redesign",
})
```

### `write_design(session_id, iteration, payload: dict)`

Append one design-iteration snapshot. Key: `design:{session_id}:{iteration}`.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `session_id` | `str` | Session identifier |
| `iteration` | `int` | Iteration number (part of key) |
| `payload` | `dict` | Free-form design state (merged into stored JSON) |

Stored document is `{**payload, "session_id", "iteration", "timestamp"}` where
`timestamp` is `int(time.time())`.

**Returns:** Redis key string (e.g. `"design:run-abc:3"`).

```python
m.write_design("run-abc", 3, {"topology": "dual-pump", "bottleneck": "valve_margin"})
```

### `get_design_history(session_id)`

| Parameter | Type | Meaning |
|-----------|------|---------|
| `session_id` | `str` | Session whose `design:{session_id}:*` keys to load |

**Returns:** `list[dict]` — full JSON documents, **ordered by ascending `iteration`**
(keys sorted by the numeric suffix after the last `:`).

```python
history = m.get_design_history("run-abc")
```

## 4. The two ingestion paths (internals)

**External prior art**

- `ingest_failures.py` — scrapes NASA sources via Stagehand/Browserbase, three cached phases:
  - **LLIS** (default `--source llis`): direct site search at llis.nasa.gov
    - `--discover` → `memory/lesson_urls.json`
    - `--extract` → `memory/lesson_fields.json`
  - **NTRS** (`--source ntrs`): Google site search `site:ntrs.nasa.gov {query} filetype:pdf`,
    PDF download, text extraction, structured field extraction
    - `--discover` → `memory/ntrs_sources.json`
    - `--extract` → `memory/ntrs_fields.json` (PDFs cached under `memory/pdfs/ntrs/`)
  - `--load` → Redis (applies relevance gate; no browser)
  - `--source all` runs both LLIS and NTRS in each phase
  - `--query "rocket propulsion"` overrides `SEARCH_QUERIES` (repeatable)
  - No phase flags = all three in order
  - `--limit N` caps reports per source per run (default **3** — pass `--limit 50` for fuller loads)
  - `--load --dry-run` previews records that pass the relevance gate without writing
- `seed_failures.py` — hand-entered historical cases (Apollo 13, Challenger, Falcon 9 COPV,
  etc.)

Both paths call `write_failure("external", ...)`. Everything lands as `source="external"`.

During `--extract`, `ingest_failures.py` also captures the **full document text** into
Redis (best-effort) via `write_document`: NTRS PDF text under `doc:ntrs:{citation_id}` and
LLIS page text under `doc:llis:{lesson_id}`. This is skipped silently if Redis is
unavailable, and the `doc:url_index` dedup hash prevents re-storing an already-captured URL.

**Self-contained research (`research.py`)**

`memory.research.research_failure_mode(query, *, mem, ...)` is a reusable, retrieval-first
research function (it does **not** import or touch the `loop` package):

1. Queries existing memory first — `search_failures` + `search_documents`.
2. Only if local coverage is weak (too few hits, or the closest hit is beyond
   `max_local_distance`) and Browserbase env vars are set, it searches the web (reusing the
   NTRS Google-search + extraction primitives from `ingest_failures.py`), deduping via
   `has_document_by_url`.
3. Writes any newly fetched source back to Redis (`write_document` + `write_failure`).
4. Returns a ranked, provenance-tagged list of cases with an IRIS transferability note per
   case (internal → direct constraint; external → requires an explicit structural analogy),
   ready for a future caller to inject into an agent prompt.

Web access is best-effort: missing env, CAPTCHA, or network failures degrade to local-only
results and never raise. A wall-clock `budget_sec` and `max_web_sources` bound the work.

**Internal (runtime)**

Agents call `write_failure("internal", id_, fields)` during the session. Until they do,
search results are all external. Internal records appear in the same index once written.

## 5. Current corpus state

**32 records total, all `source="external"`**, searchable now:

- ~18 LLIS scraped (`failure:external:llis_*`)
- ~14 hand-seeded historical cases from `seed_failures.py`

No `failure:internal:*` keys until orchestrator agents write them back.

## 6. Gotchas / contract guarantees

- **`VECTOR_DIM=1024` is frozen.** Changing the embedding model or dimension requires
  dropping and rebuilding `idx:failures` and re-ingesting all failures.
- **`k` is a ceiling, not fetch-all.** A vague query may return fewer than `k` results even
  when the corpus is larger (e.g. `k=50` with 32 indexed records can still return `<50`).
  This is expected RediSearch k-NN behavior, not data loss.
- **One index for both sources.** Use `source="internal"` or `source="external"` in
  `search_failures` to scope; omit `source` to search everything.
- **Prefer keyword args** for `source` and `field` in `search_failures` — parameter order is
  `source` before `field`.
