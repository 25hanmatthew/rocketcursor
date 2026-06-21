# memory.llm — PDF to fluid-network config

Converts a technical PDF into a validated, runnable fluid-network simulator config
(the JSON consumed by the repo's `run_network.py`) using Claude. This is the
"better output" stage of ingestion: a frontier model reads the whole PDF natively
and emits one complete config that passes the repository validator.

This subpackage reuses the root solver at runtime (`network_io`,
`general_fluid_network`, `network_schema.json`); it does not carry its own copy.
Run everything as a module from the repository root so those imports resolve.

## What it produces

A single JSON object matching `network_schema.json` (`nodes` / `connections`,
optionally `Tank` / `Engine` / `actions`), validated via the root
`load_network_config`. The generator self-repairs up to two times by feeding
validation errors back to the model. It also adds top-level
`source_extracted_numbers` and `assumptions` for human inspection.

This is distinct from the Redis failure-memory records produced by
`memory.ingest_failures` (`--discover/--extract/--load`); the two pipelines are
independent.

## Requirements

```bash
pip install -r memory/llm/requirements.txt   # anthropic + the solver stack
export ANTHROPIC_API_KEY=...                  # see repo .env.example
# optional: export ANTHROPIC_MODEL=claude-sonnet-4-6
```

## CLI

```bash
# From a local PDF:
python -m memory.llm.generate_config --pdf path/to/report.pdf --out generated_config.json

# From a direct PDF URL:
python -m memory.llm.generate_config --pdf-url https://example.com/report.pdf
```

## MCP server

```bash
python -m memory.llm.fluid_network_mcp
```

Exposes the root solver tools (`get_network_schema`, `validate_network`,
`run_network`, `read_result`) plus `generate_network_config_from_pdf`.

## NTRS handoff from the scraper

`memory.ingest_failures` can hand its downloaded NTRS PDFs directly to this
generator. The `--emit-config` phase needs no browser; it consumes the already
discovered `ntrs_sources.json`, downloads each PDF over HTTP, and writes configs
to `memory/llm/configs/{citation_id}.json` (cached in `memory/ntrs_configs.json`).

```bash
# 1. Discover NTRS PDF sources (browser; one-time / refreshable):
python -m memory.ingest_failures --discover --source ntrs

# 2. Generate configs from those PDFs (no browser):
python -m memory.ingest_failures --emit-config --source ntrs --limit 3
```

LLIS is intentionally excluded because it produces no PDF.

## Context compression (challenge mode)

The generator is one instantiation of a general, measured context compressor in
`compress.py`. The goal: send fewer tokens to the frontier model while preserving
the context needed for high-quality downstream outputs.

Two stages:

1. Stage 1 - cheap pre-filter (`prefilter.py`): extract text with `pypdf`, chunk
   it, and keep only the chunks most relevant to the task objective under a token
   budget. Relevance uses Voyage embeddings (`VOYAGE_API_KEY`) with a
   dependency-free lexical fallback. This is what actually reduces tokens sent to
   the LLM.
2. Stage 2 - frontier finalize (`compress.run_generation_loop`): the existing
   generate -> validate -> repair loop produces the compact, schema-valid JSON.

### Opt-in from the config generator

```python
from memory.llm.pdf_config_generator import generate_config_from_pdf

# Default: whole PDF sent natively (unchanged behavior).
generate_config_from_pdf(pdf_path="report.pdf")

# Compression mode: pre-filter to <= 4000 source tokens; adds "metrics"/"manifest".
generate_config_from_pdf(pdf_path="report.pdf", token_budget=4000)
```

`metrics` reports `tokens_in_full_document`, `tokens_to_frontier`,
`baseline_tokens_to_frontier`, `tokens_out`, `frontier_reduction_pct`,
`compression_ratio_doc_to_artifact`, and `estimated_input_cost_saved_usd`
(prices are estimates, overridable via `LLM_INPUT_USD_PER_MTOK` /
`LLM_OUTPUT_USD_PER_MTOK`; token counts use `tiktoken` as a proxy).

### Benchmark + evidence

```bash
python -m memory.llm.benchmark --pdf report.pdf --token-budget 4000 --qa 3
```

Writes `memory/llm/results/compression_report.json` with the token metrics plus
downstream-quality evidence:

- `downstream_runnable`: the generated config is loaded and run through the root
  simulator (`evaluate.evaluate_config_runnable`) - objective proof the compressed
  artifact still works.
- `qa_roundtrip` (when `--qa N > 0`): asks N factual questions and checks that
  answers grounded in the compressed context agree with answers grounded in the
  full document (`evaluate.qa_roundtrip`) - a general fidelity signal.

