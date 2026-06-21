import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from anthropic import Anthropic
except Exception:  # SDK optional at import time; required only when calling the model
    Anthropic = None

from network_io import NetworkConfigError, load_network_config
from memory.llm.compress import (
    DEFAULT_MODEL,
    _extract_json,
    compress_context,
    run_generation_loop,
)

__all__ = [
    "DEFAULT_USER_PROMPT",
    "SYSTEM_PROMPT",
    "generate_config_from_pdf",
    "_extract_json",
]


DEFAULT_USER_PROMPT = """pull only the relevant numbers from the attached document

i have a valid config rulebook here. Output the config.

Use SI units unless the schema explicitly says otherwise.
Node V and Tank V_total_L are liters.
Pressure must be Pa.
Temperature must be K.
CdA must be m^2.
Line ID, length, and roughness must be meters.

Return only valid JSON.
"""


SYSTEM_PROMPT = """You convert technical documents into valid JSON configs for a general fluid-network simulator.

You must:
1. Read the attached document.
2. Extract only numbers relevant to a runnable fluid-network configuration.
3. Convert units to the schema units.
4. Produce one complete JSON object matching the provided schema.
5. Prefer simple, runnable configs over over-complicated guesses.
6. Include top-level "source_extracted_numbers" and "assumptions" fields so humans can inspect what you used.
7. Never include markdown, comments, prose, or code fences.
8. If a number is unavailable, make the smallest physically reasonable assumption and record it in "assumptions".
9. Do not invent extra components unless needed for a valid network.
10. The JSON must pass the repository's validator.

Important simulator conventions:
- A basic gas tank / node should usually be a Node with params fluid, P, V, T, name.
- Ambient boundaries should use type Ambient.
- A simple restriction / valve should usually be Connection with CdA.
- Engine nodes require exactly one oxidizer feed and one fuel feed ending at the Engine.
- If you do not have enough information to make an Engine node valid, build a simpler pressure / flow network instead.
"""


def _read_schema_text() -> str:
    schema_path = Path(__file__).resolve().parents[2] / "network_schema.json"
    return schema_path.read_text(encoding="utf-8")


def _validate_config_object(config: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Uses the repo's existing validator/loader rather than duplicating validation logic.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "generated_config.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        try:
            load_network_config(path)
            return True, []
        except NetworkConfigError as e:
            return False, list(e.errors)
        except Exception as e:
            return False, [str(e)]


def _make_pdf_document_block(pdf_path: str | None = None, pdf_url: str | None = None) -> dict[str, Any]:
    if pdf_url:
        return {
            "type": "document",
            "source": {
                "type": "url",
                "url": pdf_url,
            },
        }

    if not pdf_path:
        raise ValueError("Provide either pdf_path or pdf_url.")

    pdf_bytes = Path(pdf_path).read_bytes()
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": pdf_b64,
        },
    }


def generate_config_from_pdf(
    *,
    pdf_path: str | None = None,
    pdf_url: str | None = None,
    user_prompt: str = DEFAULT_USER_PROMPT,
    model: str = DEFAULT_MODEL,
    max_repair_attempts: int = 2,
    token_budget: int | None = None,
) -> dict[str, Any]:
    """
    Generate a validated fluid-network config from a PDF.

    Default (token_budget=None): the whole PDF is sent to the model natively
    (unchanged behavior). When token_budget is set, the document is text-extracted
    and pre-filtered to the most relevant chunks under the budget before the model
    call, and the returned dict additionally includes "metrics" and "manifest".

    The upstream web-search agent should either save the PDF locally and pass
    pdf_path, or return a direct PDF URL and pass pdf_url.
    """
    if Anthropic is None:
        raise RuntimeError(
            "The 'anthropic' package is required. Install memory/llm/requirements.txt."
        )
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model = model or DEFAULT_MODEL
    schema_text = _read_schema_text()

    if token_budget is None:
        res = run_generation_loop(
            client,
            leading_blocks=[_make_pdf_document_block(pdf_path=pdf_path, pdf_url=pdf_url)],
            user_prompt=user_prompt,
            schema_text=schema_text,
            system_prompt=SYSTEM_PROMPT,
            model=model,
            max_repair_attempts=max_repair_attempts,
            validate=_validate_config_object,
        )
        return {
            "ok": res["ok"],
            "config": res["result"],
            "attempts": res["attempts"],
            "validation_errors": res["validation_errors"],
        }

    return compress_context(
        pdf_path=pdf_path,
        pdf_url=pdf_url,
        objective_prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        schema_text=schema_text,
        token_budget=token_budget,
        model=model,
        max_repair_attempts=max_repair_attempts,
        validate=_validate_config_object,
        client=client,
        result_key="config",
    )
