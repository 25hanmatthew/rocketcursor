"""Unit tests for the context compressor (no network, no CoolProp).

Voyage embedding is forced to fail so the lexical fallback is exercised, and the
Anthropic client is stubbed, so these run without external services.
"""

from __future__ import annotations

import json
import types
import unittest
from unittest.mock import patch

from memory.llm import compress, prefilter
from memory.llm.tokens import count_tokens


def _text_response(payload: str):
    block = types.SimpleNamespace(type="text", text=payload)
    return types.SimpleNamespace(content=[block])


class TokensTest(unittest.TestCase):
    def test_positive_and_monotonic(self) -> None:
        self.assertGreater(count_tokens("hello world"), 0)
        self.assertGreaterEqual(
            count_tokens("a b c d e f g h"), count_tokens("a b")
        )

    def test_empty_is_zero(self) -> None:
        self.assertEqual(count_tokens(""), 0)


class ChunkTest(unittest.TestCase):
    def test_chunks_cover_paragraphs(self) -> None:
        text = "\n\n".join(f"paragraph number {i} with some words" for i in range(10))
        chunks = prefilter.chunk_text(text, target_tokens=20)
        self.assertGreater(len(chunks), 1)
        self.assertIn("paragraph number 0", chunks[0])


class SelectRelevantTest(unittest.TestCase):
    def test_lexical_fallback_picks_relevant_under_budget(self) -> None:
        chunks = [
            "the valve controls tank pressure during the burn",
            "a recipe for chocolate cake with flour and sugar",
            "weather today is sunny with a light breeze",
        ]
        # Force the embedding path to fail so the lexical fallback runs.
        with patch.object(prefilter, "_embed", side_effect=RuntimeError("no key")):
            sel = prefilter.select_relevant(
                chunks, "valve tank pressure", token_budget=count_tokens(chunks[0])
            )
        self.assertEqual(sel["method"], "lexical")
        self.assertIn("valve controls tank pressure", sel["text"])
        self.assertGreaterEqual(sel["chunks_kept"], 1)


class CompressContextTest(unittest.TestCase):
    def test_metrics_and_compression(self) -> None:
        good = json.dumps({"nodes": [{"id": 0}], "connections": []})
        mock_client = types.SimpleNamespace()
        mock_client.messages = types.SimpleNamespace(
            create=lambda **kw: _text_response(good)
        )

        long_doc = "\n\n".join(
            [
                "valve tank pressure feed line oxidizer fuel engine nozzle",
                *[f"irrelevant filler paragraph {i} about nothing" for i in range(40)],
            ]
        )

        with patch.object(prefilter, "_embed", side_effect=RuntimeError("no key")), patch.object(
            compress, "Anthropic", return_value=mock_client
        ):
            result = compress.compress_context(
                text=long_doc,
                objective_prompt="extract valve tank pressure feed engine config",
                token_budget=30,
                chunk_tokens=8,
            )

        self.assertTrue(result["ok"])
        self.assertIn("compressed", result)
        m = result["metrics"]
        for key in (
            "tokens_in_full_document",
            "tokens_to_frontier",
            "baseline_tokens_to_frontier",
            "frontier_reduction_pct",
        ):
            self.assertIn(key, m)
        # Pre-filtering must reduce tokens sent to the frontier vs the full doc.
        self.assertLess(m["tokens_to_frontier"], m["baseline_tokens_to_frontier"])
        self.assertGreater(m["frontier_reduction_pct"], 0)
        self.assertEqual(result["manifest"]["selection_method"], "lexical")


if __name__ == "__main__":
    unittest.main()
