"""Downstream-quality evals for the compressor.

Two complementary fidelity signals:
- evaluate_config_runnable: objective, domain-specific. Does the compressed
  artifact actually drive the root simulator to completion?
- qa_roundtrip: generic, transferable. Do answers grounded in the compressed
  context agree with answers grounded in the full document?
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def evaluate_config_runnable(
    config: dict[str, Any],
    duration: float | None = None,
    dt: float | None = None,
) -> dict[str, Any]:
    """Load and run a generated config through the root solver.

    Returns {"runnable": bool, "errors": [...], "steps": int|None}. Imports the
    root solver lazily so this module loads without CoolProp installed.
    """
    try:
        from network_io import (
            NetworkConfigError,
            load_network_config,
            run_loaded_network,
        )
    except Exception as exc:  # solver stack unavailable
        return {"runnable": False, "errors": [f"solver import failed: {exc}"]}

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "config.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        try:
            loaded = load_network_config(path)
            run_loaded_network(
                loaded,
                duration=duration if duration is not None else loaded.duration,
                dt=dt if dt is not None else loaded.dt,
                verbose_steps=0,
            )
            return {"runnable": True, "errors": [], "warnings": list(loaded.warnings)}
        except NetworkConfigError as e:
            return {"runnable": False, "errors": list(e.errors)}
        except Exception as e:
            return {"runnable": False, "errors": [f"{type(e).__name__}: {e}"]}


def _ask_text(client: Any, model: str, system: str, user: str, max_tokens: int = 800) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": [{"type": "text", "text": user}]}],
    )
    chunks = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(chunks).strip()


def _generate_questions(client: Any, model: str, full_text: str, n: int) -> list[str]:
    prompt = (
        f"Read the document below and write {n} short, specific factual questions "
        "whose answers are stated in the document. Return one question per line, "
        "no numbering.\n\nDOCUMENT:\n" + full_text[:40000]
    )
    raw = _ask_text(client, model, "You write precise factual questions.", prompt)
    questions = [q.strip("-* \t") for q in raw.splitlines() if q.strip()]
    return questions[:n]


def _judge_agreement(client: Any, model: str, question: str, a: str, b: str) -> bool:
    prompt = (
        f"Question: {question}\n\nAnswer A: {a}\n\nAnswer B: {b}\n\n"
        "Do Answer A and Answer B agree on the key facts? Reply with only YES or NO."
    )
    verdict = _ask_text(
        client, model, "You judge whether two answers agree.", prompt, max_tokens=10
    )
    return verdict.strip().upper().startswith("YES")


def qa_roundtrip(
    full_text: str,
    compressed_context: str,
    questions: list[str] | None = None,
    n: int = 3,
    model: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Compare answers grounded in the full document vs the compressed context.

    Costs roughly 1 + 3*len(questions) model calls, so keep n small. Returns an
    agreement_score in [0, 1] and per-question detail.
    """
    model = model or DEFAULT_MODEL
    if client is None:
        from anthropic import Anthropic

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if not questions:
        questions = _generate_questions(client, model, full_text, n)
    if not questions:
        return {"agreement_score": None, "per_question": [], "questions": []}

    answer_system = (
        "Answer the question using only the provided context. "
        "If the answer is not present, say 'not stated'."
    )
    per_question = []
    agreements = 0
    for q in questions:
        ans_full = _ask_text(
            client, model, answer_system, f"CONTEXT:\n{full_text[:60000]}\n\nQUESTION: {q}"
        )
        ans_comp = _ask_text(
            client, model, answer_system, f"CONTEXT:\n{compressed_context}\n\nQUESTION: {q}"
        )
        agree = _judge_agreement(client, model, q, ans_full, ans_comp)
        agreements += int(agree)
        per_question.append(
            {
                "question": q,
                "answer_full": ans_full,
                "answer_compressed": ans_comp,
                "agree": agree,
            }
        )

    return {
        "agreement_score": round(agreements / len(questions), 3),
        "questions_evaluated": len(questions),
        "per_question": per_question,
    }
