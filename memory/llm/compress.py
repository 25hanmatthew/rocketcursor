"""Generic, measured context compressor.

compress_context() distills a large source document into a compact, optionally
schema-validated structured artifact, while measuring how many tokens are saved
at the frontier model. The fluid-network config generator is one caller of this
engine; the same engine works for any objective + optional validator.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

try:
    from anthropic import Anthropic
except Exception:  # SDK optional at import time; required only when calling the model
    Anthropic = None

from memory.llm import prefilter
from memory.llm.tokens import count_tokens, estimate_cost

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_OUTPUT_TOKENS = 12000

Validator = Callable[[dict[str, Any]], tuple[bool, list[str]]]


def _new_client() -> Any:
    if Anthropic is None:
        raise RuntimeError(
            "The 'anthropic' package is required. Install memory/llm/requirements.txt."
        )
    return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _response_text(response: Any) -> str:
    chunks = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            chunks.append(block.text)
    return "\n".join(chunks).strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating accidental code fences or wrapping prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def build_prompt(user_prompt: str, schema_text: str, validation_feedback: str) -> str:
    schema_block = f"\nCONFIG SCHEMA:\n{schema_text}\n" if schema_text else ""
    return f"""
USER TASK:
{user_prompt}
{schema_block}
{validation_feedback}

Return only the final JSON object.
""".strip()


def _repair_feedback(errors: list[str]) -> str:
    return f"""
The previous JSON failed validation.

Validation errors:
{json.dumps(errors, indent=2)}

Repair the JSON. Keep the same extracted numbers where possible.
Return only valid JSON.
""".strip()


def _noop_validate(_config: dict[str, Any]) -> tuple[bool, list[str]]:
    return True, []


def run_generation_loop(
    client: Any,
    *,
    leading_blocks: list[dict[str, Any]],
    user_prompt: str,
    schema_text: str,
    system_prompt: str,
    model: str,
    max_repair_attempts: int,
    validate: Validator | None = None,
    max_tokens: int = MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    """Run the generate -> validate -> repair loop with a provided client.

    leading_blocks are the content blocks placed before the instruction text
    (e.g. a PDF document block or a compressed-text block). The client is passed
    in so callers control construction (and tests can patch it).
    """
    validate = validate or _noop_validate
    validation_feedback = ""
    result: dict[str, Any] = {}
    errors: list[str] = []

    for attempt in range(max_repair_attempts + 1):
        prompt = build_prompt(user_prompt, schema_text, validation_feedback)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [*leading_blocks, {"type": "text", "text": prompt}],
                }
            ],
            system=system_prompt,
        )
        result = _extract_json(_response_text(response))
        ok, errors = validate(result)
        if ok:
            return {
                "ok": True,
                "result": result,
                "attempts": attempt + 1,
                "validation_errors": [],
            }
        validation_feedback = _repair_feedback(errors)

    return {
        "ok": False,
        "result": result,
        "attempts": max_repair_attempts + 1,
        "validation_errors": errors,
    }


def _download_pdf(pdf_url: str) -> str:
    import httpx

    resp = httpx.get(pdf_url, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as fh:
        fh.write(resp.content)
    return tmp


def _resolve_source_text(
    text: str | None,
    pdf_path: str | None,
    pdf_url: str | None,
) -> str:
    if text is not None:
        return text
    if pdf_path:
        return prefilter.extract_pdf_text(pdf_path)
    if pdf_url:
        tmp = _download_pdf(pdf_url)
        try:
            return prefilter.extract_pdf_text(tmp)
        finally:
            try:
                Path(tmp).unlink()
            except OSError:
                pass
    raise ValueError("Provide one of text, pdf_path, or pdf_url.")


def compress_context(
    *,
    text: str | None = None,
    pdf_path: str | None = None,
    pdf_url: str | None = None,
    objective_prompt: str,
    system_prompt: str = "",
    schema_text: str = "",
    token_budget: int | None = None,
    chunk_tokens: int = 512,
    model: str | None = None,
    max_repair_attempts: int = 2,
    validate: Validator | None = None,
    client: Any | None = None,
    result_key: str = "compressed",
) -> dict[str, Any]:
    """Compress a document toward an objective and finalize with the frontier model.

    When token_budget is set, only the most relevant chunks are sent to the
    model. Returns the structured result plus token/cost metrics and a manifest.
    """
    model = model or DEFAULT_MODEL
    client = client or _new_client()

    full_text = _resolve_source_text(text, pdf_path, pdf_url)

    if token_budget is not None:
        chunks = prefilter.chunk_text(full_text, target_tokens=chunk_tokens)
        selection = prefilter.select_relevant(chunks, objective_prompt, token_budget)
        selected_text = selection["text"]
    else:
        selection = {
            "text": full_text,
            "kept_indices": [],
            "method": "none",
            "chunks_total": 0,
            "chunks_kept": 0,
        }
        selected_text = full_text

    leading_blocks = [
        {
            "type": "text",
            "text": f"SOURCE DOCUMENT (compressed excerpt):\n{selected_text}",
        }
    ]

    res = run_generation_loop(
        client,
        leading_blocks=leading_blocks,
        user_prompt=objective_prompt,
        schema_text=schema_text,
        system_prompt=system_prompt,
        model=model,
        max_repair_attempts=max_repair_attempts,
        validate=validate,
    )

    overhead_text = build_prompt(objective_prompt, schema_text, "") + system_prompt
    overhead_tokens = count_tokens(overhead_text)
    tokens_in_full = count_tokens(full_text)
    baseline_frontier = tokens_in_full + overhead_tokens
    compressed_frontier = count_tokens(selected_text) + overhead_tokens
    tokens_out = count_tokens(json.dumps(res["result"]))

    frontier_reduction_pct = (
        round(100 * (1 - compressed_frontier / baseline_frontier), 2)
        if baseline_frontier
        else 0.0
    )
    compression_ratio = round(tokens_in_full / max(1, tokens_out), 2)
    cost_saved = round(
        estimate_cost(baseline_frontier) - estimate_cost(compressed_frontier), 6
    )

    metrics = {
        "tokens_in_full_document": tokens_in_full,
        "tokens_to_frontier": compressed_frontier,
        "baseline_tokens_to_frontier": baseline_frontier,
        "tokens_out": tokens_out,
        "prompt_overhead_tokens": overhead_tokens,
        "frontier_reduction_pct": frontier_reduction_pct,
        "compression_ratio_doc_to_artifact": compression_ratio,
        "estimated_input_cost_saved_usd": cost_saved,
    }
    manifest = {
        "token_budget": token_budget,
        "chunk_tokens": chunk_tokens,
        "selection_method": selection["method"],
        "chunks_total": selection["chunks_total"],
        "chunks_kept": selection["chunks_kept"],
        "model": model,
    }

    return {
        "ok": res["ok"],
        result_key: res["result"],
        "attempts": res["attempts"],
        "validation_errors": res["validation_errors"],
        "metrics": metrics,
        "manifest": manifest,
    }
