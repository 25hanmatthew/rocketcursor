# Requirement-Aware Context Compression

**The Token Company Challenge — "build your own compression solution that reduces
tokens while preserving context for high-quality outputs."**

This is our own compression system. It is not a call to a hosted compressor — it is
a compression *strategy* we built into the agent loop, with measured results below.

## The problem

rocketcursor designs rocket feed systems with an LLM-in-the-loop:

```
spec → LLM designs → fluid-network simulation → verdict → LLM revises → repeat
```

Each simulation emits the **full transient time-series**: every node and every
connection, every field, at every timestep — hundreds of KB of CSV. A naive agent
loop feeds that raw output back to the model each iteration. That is the dominant
token cost of the loop, and it *recurs every iteration*.

## The idea: compress against the downstream task's requirements

Generic compressors (prose summarizers, byte-level models) are task-agnostic — they
don't know what the reader will do with the text. Our insight: **the consumer's own
pass/fail criteria tell us exactly which numbers matter.** Every spec carries
machine-checkable `checks` (e.g. "end-of-burn thrust ≥ 1500 N"). So we:

1. Run the simulation in full (no fidelity lost in the physics).
2. Evaluate it deterministically in Python against the spec's checks (`evaluator.py`).
3. Emit only a **requirement-keyed verdict** — pass/fail per check, plus the
   offending *actual* value for any failure — and send that to the LLM.

Everything not bearing on a requirement is dropped. What survives is exactly the
signal the model needs to revise. Example of the compressed context (~200 tokens):

```
VERDICT: 5/8 checks passed
[PASS] flow_happens: Propellant actually flows.
[FAIL] thrust_min: End-of-burn thrust is at least 1500 N.
        expected >= 1500.0; actual=1136.79 (engine.thrust.final=1136.79)
...
```

This is "requirement-aware" compression: the compressor is **conditioned on what the
consumer will do with the output**, which is why it can be this aggressive without
losing decision-relevant context.

## Measured results

Across 3 real multi-iteration design runs (14 iterations), measured by
`python -m loop.compression_benchmark`:

| spec | iters | raw tokens | sent tokens | reduction |
|---|---:|---:|---:|---:|
| lox_methane_engine | 6 | 334,882 | 1,232 | 99.63% |
| nitrogen_blowdown_vent | 2 | 1,286,112 | 226 | 99.98% |
| pressure_window_blowdown | 6 | 758,135 | 1,348 | 99.82% |
| **TOTAL** | **14** | **2,379,129** | **2,806** | **99.88%** |

**~2.38M tokens of raw simulator output compressed to ~2,806 — a 99.88% reduction**,
averaging ~170k raw → ~200 sent per iteration. (Token counts estimated at 4
chars/token; the *ratio* is tokenizer-robust.)

## It improves downstream performance — not just shrinks input

The challenge asks for compression that **preserves or improves** output quality. Ours
improves it:

- The loop **converges to passing designs** using only the ~200-token verdict
  (lox_methane_engine reaches 8/8 checks; tank/blowdown specs pass cleanly).
- A model revises *better* from a clean, decision-relevant verdict with exact failing
  metrics than from 170k tokens of CSV time-series it cannot reliably parse. The
  compression removes noise, not signal.

So the compressed representation is not a lossy degradation we tolerate — it is a
*better* input for the task than the raw data.

## It's not rocket-specific — a domain-agnostic kernel

The same principle works on any large list-of-rows checked against requirements —
service logs vs SLOs, metrics vs thresholds, benchmark output vs targets.
`compress_tabular_context(records, requirements)` takes generic rows plus a
requirement set (`field`, `stat`, `op`, `value`) and emits the same requirement-keyed
verdict. Example — a 5,000-row request-latency log compressed against an SLO:

```python
reqs = [{"id": "p99_latency", "description": "Max latency under 500ms.",
         "field": "latency_ms", "stat": "max", "op": "<", "value": 500}]
text, stats = compress_tabular_context(rows, reqs)
# -> "VERDICT: 0/1 checks passed
#     [FAIL] p99_latency: Max latency under 500ms.  expected max(latency_ms) < 500; actual=900"
# >95% reduction vs serializing the raw log.
```

So the technique generalizes; the rocket loop is just where we measured it at scale.

## Where it lives

- `loop/compression.py` — the compression module: `compress_simulation_result`,
  `compress_verdict`, `compression_stats` (rocket loop) and the domain-agnostic
  `compress_tabular_context` kernel.
- `loop/evaluator.py` — the deterministic, requirement-keyed evaluation that defines
  what survives compression in the rocket loop.
- `loop/compression_benchmark.py` — reproduces the table above
  (`python -m loop.compression_benchmark --json`).
- `tests/test_compression.py` — proves hard reduction *and* signal preservation, for
  both the rocket path and the generic kernel.

## Honest scope

- This is a **system/application-level** compressor for requirement-bearing
  structured/tabular inputs — not a general prose compressor. The challenge explicitly
  invites solutions "at the model, application, or system level."
- We *also* integrate The Token Company's hosted product (`with_compression`) for the
  static system-prompt prefix (~44% on that slice). That is a product integration, and
  is secondary to — and separate from — the compression solution described here, which
  is our own.
