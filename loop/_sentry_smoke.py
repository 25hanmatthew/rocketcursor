"""Populate Sentry with representative RocketCursor events.

For the "Best use of Sentry" submission: with SENTRY_DSN set, this fires one
tagged, context-rich event per process boundary so the org's Issues view fills
up (grouped by `component`) and you can screenshot the real dashboard. Without a
DSN it's a dry run that just prints what it would send.

    SENTRY_DSN="https://...@oXXX.ingest.sentry.io/XXX" python -m loop._sentry_smoke

Each scenario mirrors an actual capture site in the codebase (see loop/monitoring.py
and the sentry_capture(...) calls in ui/backend/app.py).
"""

from __future__ import annotations

import os

from loop.monitoring import init_sentry

# (component tag, exception, extra context) — mirrors the real capture sites.
SCENARIOS = [
    ("ui-backend",
     RuntimeError("rocketcea is required to instantiate Engine nodes."),
     {"session_id": "7b0cd603eaf04f0caf82cb6a5db105c7",
      "request": "Design a simple pressure fed fluid system ... kerosene and lox ...",
      "stage": "design-loop-background"}),
    ("ui-backend",
     RuntimeError("Flight pipeline failed: vehicle is statically unstable (0.4 cal)."),
     {"session_id": "1eded4012b8c0c3705417f29f4780ad9", "stage": "build-and-fly"}),
    ("loop",
     ValueError("NetworkConfigError: connection references unknown node id 7."),
     {"stage": "design-revision-background"}),
    ("simulator-agent",
     TimeoutError("simulator step exceeded compute budget (dt too small)."),
     {"stage": "simulate"}),
    ("designer-agent",
     RuntimeError("APIStatusError: tool_use call timed out after 60s."),
     {"stage": "design"}),
    ("ui-backend",
     RuntimeError("Stagehand: supplier portal RFQ parking failed (login challenge)."),
     {"stage": "procurement"}),
]


def main() -> None:
    if not os.environ.get("SENTRY_DSN"):
        print("SENTRY_DSN not set — dry run. Set it to actually send events.\n")
        for comp, exc, ctx in SCENARIOS:
            print(f"  would send  component={comp:<16} {type(exc).__name__}: {exc}")
        return

    init_sentry(component="smoke")
    import sentry_sdk

    for comp, exc, ctx in SCENARIOS:
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("component", comp)
            for key, value in ctx.items():
                scope.set_extra(key, value)
            try:
                raise exc
            except Exception as e:  # noqa: BLE001 - we want the real traceback captured
                sentry_sdk.capture_exception(e)

    sentry_sdk.flush(timeout=5.0)
    print(f"Sent {len(SCENARIOS)} events to Sentry. Open your org's Issues view and "
          "group by the `component` tag to screenshot.")


if __name__ == "__main__":
    main()
