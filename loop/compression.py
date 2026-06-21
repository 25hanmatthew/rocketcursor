"""Requirement-aware context compression for simulation-driven agents.

The Token Company challenge: reduce the information sent to an LLM while preserving
(or improving) the context needed for high-quality output. This is our own
compression solution — not a call to a hosted model.

The idea: a transient fluid-network simulation emits the full time-series — every
node/connection x every field x every timestep (hundreds of KB of CSV, ~50k+
tokens per run). A naive agent loop feeds that back to the LLM each iteration.
Instead, we compress it using the *downstream task's own requirements*: the spec's
machine-checkable `checks` tell us exactly which quantities matter, so we keep only
those (as a pass/fail verdict with the offending actual values) and drop everything
else. Result: ~99% fewer tokens AND better downstream performance, because the
model revises against a clean, decision-relevant signal instead of raw data it
can't parse.

This is "requirement-aware" compression: unlike generic prose compressors, the
compressor is conditioned on what the consumer will do with the output.

    from loop.compression import compress_simulation_result
    text, stats = compress_simulation_result(spec, simulation_result, raw_sim_text)
    print(stats.reduction_pct, "% smaller")
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from loop.evaluator import evaluate


def estimate_tokens(text: str) -> int:
    """Fast tokenizer-agnostic estimate (~4 chars/token). The compression *ratio*
    is robust to the exact tokenizer; this avoids an API call per measurement."""
    return max(1, len(text) // 4)


@dataclass
class CompressionStats:
    raw_chars: int
    compressed_chars: int
    raw_tokens: int
    compressed_tokens: int
    tokens_saved: int
    kept_fraction: float   # compressed/raw (e.g. 0.004 = we send 0.4% of the input)
    reduction_pct: float   # 1 - kept_fraction, as a percentage

    def to_dict(self) -> dict:
        return asdict(self)


def compression_stats(raw_text: str, compressed_text: str) -> CompressionStats:
    raw_t, comp_t = estimate_tokens(raw_text), estimate_tokens(compressed_text)
    kept = (len(compressed_text) / len(raw_text)) if raw_text else 1.0
    return CompressionStats(
        raw_chars=len(raw_text),
        compressed_chars=len(compressed_text),
        raw_tokens=raw_t,
        compressed_tokens=comp_t,
        tokens_saved=max(0, raw_t - comp_t),
        kept_fraction=round(kept, 5),
        reduction_pct=round((1 - kept) * 100, 2),
    )


def compress_verdict(spec: dict, result: dict) -> str:
    """The compressed context we actually feed the LLM: a requirement-keyed verdict.
    Reuses the loop's canonical formatter so the benchmark measures the real thing."""
    from loop.agent import _verdict_feedback  # lazy: avoids import cycle at module load

    verdict = evaluate(spec, result)
    return _verdict_feedback(verdict, result)


def compress_simulation_result(spec: dict, result: dict, raw_sim_text: str
                               ) -> tuple[str, CompressionStats]:
    """Compress a simulation run into the verdict the LLM revises against, and
    report the stats vs the raw simulator output (`raw_sim_text` = the CSV/time-
    series a naive agent would have sent back)."""
    compressed = compress_verdict(spec, result)
    return compressed, compression_stats(raw_sim_text, compressed)


# --------------------------------------------------------------------------- #
# Domain-agnostic kernel: the same idea, decoupled from rockets.
#
# Most context compressors are task-agnostic — they squeeze prose without knowing
# what the reader needs. The kernel here is the opposite: given a large tabular /
# time-series input AND the requirements the consumer will check it against, keep
# only the requirement-relevant aggregates and drop everything else. Works on any
# list-of-rows (logs, metrics, benchmark output, financial series), not just sims.
# --------------------------------------------------------------------------- #

_OPS = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,  "<":  lambda a, b: a < b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


def _column(records: list[dict], field: str) -> list:
    vals = []
    for row in records:
        v = row.get(field)
        if v is None:
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            vals.append(v)
    return vals


def _aggregate(records: list[dict], field: str, stat: str):
    vals = _column(records, field)
    if not vals:
        return None
    if stat == "final":
        return vals[-1]
    if stat == "first":
        return vals[0]
    if stat == "count":
        return len(vals)
    nums = [v for v in vals if isinstance(v, (int, float))]
    if not nums:
        return None
    if stat == "min":
        return min(nums)
    if stat == "max":
        return max(nums)
    if stat == "mean":
        return sum(nums) / len(nums)
    raise ValueError(f"unknown stat {stat!r}")


def compress_tabular_context(records: list[dict], requirements: list[dict]
                             ) -> tuple[str, CompressionStats]:
    """Compress a large list-of-rows into a requirement-keyed verdict.

    `requirements` is a list of dicts, each:
        {id, description?, field, stat?(final|first|min|max|mean|count),
         op(>=|<=|>|<|==|!=), value}

    Returns (verdict_text, stats), where stats compares the verdict against a
    naive serialization of all the rows (what an agent would otherwise paste in).
    """
    import json as _json

    lines = []
    passed = 0
    for req in requirements:
        rid = req.get("id", "?")
        desc = req.get("description", "")
        field = req["field"]
        stat = req.get("stat", "final")
        op = req.get("op", "==")
        expected = req.get("value")
        actual = _aggregate(records, field, stat)
        fn = _OPS.get(op)
        if actual is None:
            lines.append(f"[FAIL] {rid}: {desc} (no data for {field!r})")
            continue
        if fn is None:
            lines.append(f"[FAIL] {rid}: {desc} (unknown operator {op!r})")
            continue
        ok = bool(fn(actual, expected))
        passed += ok
        tag = "PASS" if ok else "FAIL"
        av = f"{actual:.6g}" if isinstance(actual, (int, float)) else actual
        detail = "" if ok else f"  expected {stat}({field}) {op} {expected}; actual={av}"
        lines.append(f"[{tag}] {rid}: {desc}{detail}")

    verdict = f"VERDICT: {passed}/{len(requirements)} checks passed\n" + "\n".join(lines)
    raw = _json.dumps(records)  # what a naive loop would have sent
    return verdict, compression_stats(raw, verdict)
