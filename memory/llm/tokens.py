"""Token counting and cost estimation for the context compressor.

Counts are a proxy for the frontier model's tokenizer: tiktoken's cl100k_base
when available, otherwise a conservative chars/4 heuristic. Prices are estimates
and overridable via env so the benchmark numbers stay honest.
"""

from __future__ import annotations

import os

# Claude Sonnet-class list prices (USD per million tokens), overridable.
INPUT_USD_PER_MTOK = float(os.getenv("LLM_INPUT_USD_PER_MTOK", "3.0"))
OUTPUT_USD_PER_MTOK = float(os.getenv("LLM_OUTPUT_USD_PER_MTOK", "15.0"))

_ENCODER = None
_ENCODER_TRIED = False


def _encoder():
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENCODER = None
    return _ENCODER


def count_tokens(text: str) -> int:
    """Best-effort token count. Falls back to chars/4 if tiktoken is absent."""
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def estimate_input_cost(tokens: int) -> float:
    return (tokens / 1_000_000) * INPUT_USD_PER_MTOK


def estimate_output_cost(tokens: int) -> float:
    return (tokens / 1_000_000) * OUTPUT_USD_PER_MTOK


def estimate_cost(input_tokens: int, output_tokens: int = 0) -> float:
    """Estimated USD for a single call. Reported as an estimate, not a bill."""
    return round(
        estimate_input_cost(input_tokens) + estimate_output_cost(output_tokens), 6
    )
