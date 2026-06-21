"""Memory hook: ground the design loop in the NASA/historical failure corpus.

Before designing, the loop pulls the most relevant prior failures from P3's memory
layer (memory.Memory.search_failures) and injects them into the prompt, so the
agent designs aware of how similar systems have failed. After a run that does NOT
pass, it writes the failure back (write_failure "internal") so the system learns
across sessions -- the PRD's "memory retrieval" + "write failures back" stages.

LAZY + GUARDED, like tracing/monitoring. The memory layer imports `voyageai` and
needs Redis + VOYAGE_API_KEY; none of that is required to run the loop. Every
function here no-ops (and says why) if memory is unavailable, and never raises.
"""

from __future__ import annotations

import os
from typing import Any

_last_reason: str | None = None


def memory_status() -> str | None:
    """Why memory last no-op'd (None = it was available)."""
    return _last_reason


def get_memory():
    """A memory.Memory instance, or None if unavailable. No-ops when voyageai
    isn't installed, VOYAGE_API_KEY is unset, or Redis can't be reached."""
    global _last_reason
    if not os.environ.get("VOYAGE_API_KEY"):
        _last_reason = "VOYAGE_API_KEY not set"
        return None
    try:
        from memory import Memory  # lazy: imports voyageai/redis

        memory = Memory()  # connects to Redis (REDIS_URL or localhost), ensures index
        _last_reason = None
        return memory
    except Exception as exc:  # noqa: BLE001 - memory is optional; never break the loop
        _last_reason = f"{type(exc).__name__}: {exc}"
        return None


def retrieve_failure_context(query_text: str, k: int = 5) -> tuple[str, list[dict[str, Any]]]:
    """Return (prompt_block, compact_results). Empty when memory is unavailable or
    finds nothing. `prompt_block` is prose to prepend to the design prompt;
    `compact_results` is a small list for session_state / the UI."""
    memory = get_memory()
    if memory is None:
        return "", []
    try:
        results = memory.search_failures(query_text, k=k)
    except Exception as exc:  # noqa: BLE001
        global _last_reason
        _last_reason = f"search failed: {type(exc).__name__}: {exc}"
        return "", []
    if not results:
        return "", []

    lines = [
        "RELEVANT PRIOR FAILURES — real propulsion failures from a NASA/historical "
        "corpus, retrieved for this design. Treat them as hazards to engineer "
        "against; do not repeat these failure modes:"
    ]
    compact = []
    for r in results:
        fm = str(r.get("failure_mode", "")).strip()
        rc = str(r.get("root_cause", "")).strip()
        ca = str(r.get("corrective_action", "")).strip()
        if not fm and not rc:
            continue
        line = f"- {fm}" if fm else "-"
        if rc:
            line += f"  (root cause: {rc})"
        if ca:
            line += f"  [mitigation: {ca}]"
        lines.append(line)
        compact.append({"failure_mode": fm[:200], "score": r.get("score")})
    return "\n".join(lines), compact


def record_failure(record_id: str, fields: dict[str, Any]) -> bool:
    """Write an internal failure record so the system learns from this run.
    No-op (returns False) if memory is unavailable."""
    memory = get_memory()
    if memory is None:
        return False
    try:
        memory.write_failure("internal", record_id, fields)
        return True
    except Exception:  # noqa: BLE001
        return False
