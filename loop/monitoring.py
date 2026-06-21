"""Sentry error monitoring — one init for the whole stack.

The orchestration layer: every entry point (the CLI loop, the uAgents, and the
FastAPI UI backend) calls init_sentry() once at startup so any crash anywhere —
a solver blow-up, an LLM/tool failure, a bad request, a background design-run
thread dying — surfaces immediately in Sentry with a full traceback.

Guarded + idempotent, same pattern as Arize tracing (loop/tracing.py): if
SENTRY_DSN isn't set it's a clean no-op, so it never blocks a run. DSN comes from
the env (gitignored .env), never hardcoded in the repo.

    pip install "sentry-sdk[fastapi]"

Docs: https://docs.sentry.io/platforms/python/
"""

from __future__ import annotations

import os

_INITIALIZED = False


def init_sentry(component: str = "loop") -> bool:
    """Initialize Sentry if SENTRY_DSN is set. `component` tags every event so we
    can tell which part of the stack (loop / ui-backend / designer-agent /
    simulator-agent) raised it. Returns True if enabled. Never raises."""
    global _INITIALIZED
    if _INITIALIZED:
        return True
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("SENTRY_ENV", "hackathon"),
            send_default_pii=True,
            # capture a sample of traces for performance/latency visibility too
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "1.0")),
        )
        sentry_sdk.set_tag("component", component)
        sentry_sdk.set_tag("project", "rocketcursor")
        _INITIALIZED = True
        print(f"[monitoring] Sentry ENABLED (component={component})")
        return True
    except Exception as exc:  # noqa: BLE001 - monitoring must never break the app
        print(f"[monitoring] Sentry unavailable ({type(exc).__name__}: {exc}); continuing unmonitored")
        return False


def capture(exc: BaseException, **context) -> None:
    """Best-effort report of a handled exception with extra context. No-op if
    Sentry isn't initialized."""
    if not _INITIALIZED:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        pass
