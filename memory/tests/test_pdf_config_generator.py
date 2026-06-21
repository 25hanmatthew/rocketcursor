"""Unit tests for memory.llm.pdf_config_generator (mocked Anthropic, no network).

Validation runs through the real root loader (load_network_config), so these
tests require the solver stack (CoolProp etc.) from memory/llm/requirements.txt.
"""

from __future__ import annotations

import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from memory.llm import pdf_config_generator as pcg

REPO_ROOT = Path(__file__).resolve().parents[2]
GOOD_CONFIG_PATH = REPO_ROOT / "network_configs" / "tank_vent_to_atmosphere.json"


def _text_response(payload: str):
    """Fake an Anthropic messages response with a single text block."""
    block = types.SimpleNamespace(type="text", text=payload)
    return types.SimpleNamespace(content=[block])


def _good_config_json() -> str:
    return GOOD_CONFIG_PATH.read_text(encoding="utf-8")


class ExtractJsonTest(unittest.TestCase):
    def test_strips_code_fences(self) -> None:
        self.assertEqual(pcg._extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_pulls_object_out_of_surrounding_prose(self) -> None:
        self.assertEqual(
            pcg._extract_json('here you go: {"a": 1} thanks'), {"a": 1}
        )


class GenerateConfigTest(unittest.TestCase):
    def test_success_on_first_attempt(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_response(_good_config_json())

        with patch.object(pcg, "Anthropic", return_value=mock_client):
            result = pcg.generate_config_from_pdf(pdf_url="https://example.com/x.pdf")

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(mock_client.messages.create.call_count, 1)

    def test_repairs_invalid_then_succeeds(self) -> None:
        mock_client = MagicMock()
        # First reply is valid JSON but an invalid network config (missing
        # nodes/connections); the second reply repairs it.
        mock_client.messages.create.side_effect = [
            _text_response("{}"),
            _text_response(_good_config_json()),
        ]

        with patch.object(pcg, "Anthropic", return_value=mock_client):
            result = pcg.generate_config_from_pdf(
                pdf_url="https://example.com/x.pdf",
                max_repair_attempts=2,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(mock_client.messages.create.call_count, 2)

    def test_gives_up_after_max_attempts(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_response("{}")

        with patch.object(pcg, "Anthropic", return_value=mock_client):
            result = pcg.generate_config_from_pdf(
                pdf_url="https://example.com/x.pdf",
                max_repair_attempts=1,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["validation_errors"])
        self.assertEqual(mock_client.messages.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
