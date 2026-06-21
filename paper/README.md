# Requirement-Aware Context Compression — paper

Self-contained two-column arXiv-style preprint.

## Build

```bash
tectonic main.tex      # -> main.pdf (6 pages)
```

No external class files needed; `tectonic` pulls every package on first run.

## Where the numbers come from (all live-measured, not estimated by hand)

| Claim in paper | Source |
|---|---|
| 2,379,129 → 3,065 tokens, 99.87% (Table 1, Fig 1) | `python -m loop.compression_benchmark` → `results/compression/benchmark.json` |
| Head-to-head 198,358 → 433 / bear-2 0.45% / verdict→315 (Table 2) | `python -m loop.compression_benchmark --ttc` (needs `TTC_API_KEY`) |
| LLM summary 198,358 → 1,948, drops failing actual (Table 2) | `python -m loop._paper_summarization_baseline` (needs `ANTHROPIC_API_KEY` + `TTC_API_KEY`) → `results/compression/summarization_baseline.json` |
| Verdict example (Listing 1) | `loop.compression.compress_verdict` on `results/loop_runs/lox_methane_engine/iter_00` |

## Scope notes (kept honest)

- The paper claims fidelity + cost of the feedback channel; it does **not** claim the
  loop reaches all-pass on every spec within the recorded budget (the saved runs peak
  at 6/8 and 8/9). The quality claim is the model's targeted revision behavior acting
  only on the ~220-token verdict, plus the measured summarization comparison.
- Two tokenizer regimes are reported distinctly: a 4-char/token estimate for the
  aggregate sweep, and the byte-level compressor's own tokenizer for the head-to-head.
