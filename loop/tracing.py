"""Arize AX tracing — observability for the loop's LLM reasoning.

The loop reasons via the OpenAI SDK (ASI1 is OpenAI-compatible), so OpenInference's
OpenAI instrumentor auto-captures every design / spec / revise call — prompt,
response, tokens, latency, tool calls — with no change to the call sites. It wraps
the SDK, so the ASI1 base_url is irrelevant.

Enable by setting ARIZE_SPACE_ID + ARIZE_API_KEY (see .env.example). Without them
this is a no-op, so it never blocks a run. Call enable_tracing() once at startup.

    pip install arize-otel openinference-instrumentation-openai

Docs: https://arize.com/docs/ax
"""

from __future__ import annotations

import os

_ENABLED = False


def enable_tracing(project_name: str | None = None) -> bool:
    """Turn on Arize tracing if creds are present. Returns True if enabled.
    Idempotent and best-effort — any failure degrades to no-op (never crashes)."""
    global _ENABLED
    if _ENABLED:
        return True
    space_id = os.environ.get("ARIZE_SPACE_ID")
    api_key = os.environ.get("ARIZE_API_KEY")
    if not (space_id and api_key):
        return False
    try:
        from arize.otel import register
        from openinference.instrumentation.openai import OpenAIInstrumentor

        tracer_provider = register(
            space_id=space_id,
            api_key=api_key,
            project_name=project_name or os.environ.get("ARIZE_PROJECT_NAME", "rocketcursor-loop"),
        )
        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        _ENABLED = True
        print(f"[tracing] Arize AX tracing ENABLED (project="
              f"{project_name or os.environ.get('ARIZE_PROJECT_NAME', 'rocketcursor-loop')})")
        return True
    except Exception as exc:  # noqa: BLE001 - observability must never break the app
        print(f"[tracing] Arize tracing unavailable ({type(exc).__name__}: {exc}); continuing untraced")
        return False
