"""Session-state contract + pluggable store for the loop <-> Redis/UI seam.

The loop is the hub of the PRD workflow: the UI (Person 1) polls Redis (Person 3)
every ~2s to render the requirements-review screen, the live design/simulation
view, and the requirements checklist; Person 4 keeps the Redis keys consistent.
This module defines the ONE structured object the loop emits per session/iteration
and a pluggable store so we don't depend on *when* Redis lands:

    get_store()           -> RedisSessionStore if REDIS_URL is set & redis-py is
                             installed, else FileSessionStore (results/loop_runs/...).

The emitted state maps directly to the PRD UI screens:
  - requirements review  <- state["requirements"] (the derived spec + checklist)
  - live design view     <- iterations[-1]["design"] (React Flow nodes/edges) +
                            iterations[-1]["node_status"] (green/red/yellow)
  - sidebar numbers      <- iterations[-1]["components"] (per-component values)
  - requirements checklist <- iterations[-1]["verdict"]["checks"] (pass/fail each)
  - failure report       <- state["report"]

Redis key schema (stable contract for Person 4):
  rocketcursor:session:{id}        -> full state JSON (UI polls this key)
  rocketcursor:sessions            -> set of all session ids
  rocketcursor:session:{id}:events -> pub/sub channel, one message per update
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REDIS_PREFIX = "rocketcursor"


# --------------------------------------------------------------------------- #
# State building
# --------------------------------------------------------------------------- #

def new_state(session_id: str, request: str, provider: str, model: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "request": request,
        "provider": provider,
        "model": model,
        "status": "running",          # running | passed | failed | error
        "stage": "requirements",      # requirements | design | simulate | evaluate | report
        "requirements": None,
        "current_iteration": -1,
        "iterations": [],
        "passed": False,
        "iterations_used": 0,
        "report": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def requirements_view(spec: dict) -> dict[str, Any]:
    """The 'extracted requirements' shown on the review screen + checklist."""
    checks = []
    for c in spec.get("checks", []):
        target = c.get("component") or c.get("field") or c.get("type")
        stat = c.get("stat")
        checks.append({
            "id": c.get("id"),
            "description": c.get("description", ""),
            "target": (f"{target}.{stat}" if stat else target),
            "op": c.get("op"),
            "value": c.get("value"),
        })
    return {
        "name": spec.get("name"),
        "description": spec.get("description", ""),
        "design_guidance": spec.get("design_guidance"),
        "checks": checks,
    }


def node_status_from_verdict(result: dict, verdict_dict: dict) -> dict[str, str]:
    """Per-component status for UI color coding: green (ok), red (failed a check
    that references it), yellow (a solver warning references it)."""
    components = result.get("components", {}) or {}
    status = {name: "green" for name in components}

    for w in result.get("diagnostics", {}).get("warnings", []):
        comp = w.get("component")
        if comp in status:
            status[comp] = "yellow"

    for chk in verdict_dict.get("checks", []):
        if chk.get("passed"):
            continue
        # component checks carry the component name in the detail or we re-derive
        # from the original spec check; here use any component named in the detail.
        comp = chk.get("component")
        if not comp:
            # detail looks like "supply_tank.P.final=..."; take the leading token
            detail = chk.get("detail", "")
            head = detail.split(".", 1)[0] if "." in detail else ""
            comp = head if head in status else None
        if comp in status:
            status[comp] = "red"
    return status


def iteration_view(iteration: int, design: dict, result: dict, verdict_dict: dict) -> dict[str, Any]:
    # Keep this SMALL. The full design JSON and per-component stats are already on
    # disk per iteration (design.json / *_summary.json / report.json) and the UI
    # reads them from there via latest_playable -- duplicating them here bloated
    # session_state.json to thousands of lines. We keep only what the UI reads
    # straight from state: the verdict checklist, the per-node status (for diagram
    # coloring), and the run status.
    return {
        "iteration": iteration,
        "status": result.get("status"),
        "node_status": node_status_from_verdict(result, verdict_dict),  # diagram coloring
        "verdict": verdict_dict,                                        # checklist pass/fail
    }


def report_view(passed: bool, verdict_dict: dict | None, final_design: dict | None,
                iterations_used: int) -> dict[str, Any]:
    unmet = []
    if verdict_dict:
        unmet = [
            {"id": c["id"], "description": c["description"],
             "expected": f"{c['op']} {c['expected']}", "actual": c["actual"]}
            for c in verdict_dict.get("checks", []) if not c.get("passed")
        ]
    headline = (
        f"PASSED in {iterations_used} iteration(s)." if passed
        else f"Did not pass after {iterations_used} iteration(s); {len(unmet)} unmet requirement(s)."
    )
    return {
        "passed": passed,
        "headline": headline,
        "iterations_used": iterations_used,
        "unmet_requirements": unmet,
        "final_design": final_design,
    }


# --------------------------------------------------------------------------- #
# Pluggable store
# --------------------------------------------------------------------------- #

class SessionStore:
    """Write the session state somewhere the UI can read it."""

    def write(self, state: dict[str, Any]) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class FileSessionStore(SessionStore):
    """Default store: results/loop_runs/_sessions/<id>/session_state.json.
    Always-on, no external dependency; useful for local dev and tests."""

    def __init__(self, root: Path | None = None):
        self.root = root or (REPO_ROOT / "results" / "loop_runs" / "_sessions")

    def write(self, state: dict[str, Any]) -> None:
        state["updated_at"] = time.time()
        d = self.root / state["session_id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "session_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


class RedisSessionStore(SessionStore):
    """Writes the full state JSON to rocketcursor:session:{id}, registers the id in
    rocketcursor:sessions, and publishes to rocketcursor:session:{id}:events so the
    UI can poll the key or subscribe to the channel."""

    def __init__(self, url: str | None = None):
        import redis  # lazy: only needed when Redis is actually used

        self.client = redis.Redis.from_url(url or os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

    def write(self, state: dict[str, Any]) -> None:
        state["updated_at"] = time.time()
        sid = state["session_id"]
        payload = json.dumps(state)
        key = f"{REDIS_PREFIX}:session:{sid}"
        pipe = self.client.pipeline()
        pipe.set(key, payload)
        pipe.sadd(f"{REDIS_PREFIX}:sessions", sid)
        pipe.publish(f"{REDIS_PREFIX}:session:{sid}:events", payload)
        pipe.execute()


class _GuardedStore(SessionStore):
    """Wraps a store so a write failure (e.g. Redis server down) logs once and is
    swallowed -- emitting UI state must never crash the design loop."""

    def __init__(self, inner: SessionStore):
        self.inner = inner
        self._warned = False

    def write(self, state: dict[str, Any]) -> None:
        try:
            self.inner.write(state)
        except Exception as exc:  # noqa: BLE001
            if not self._warned:
                print(f"[session_state] {type(self.inner).__name__} write failed "
                      f"({type(exc).__name__}: {exc}); UI state updates disabled this run")
                self._warned = True


def get_store() -> SessionStore:
    """Redis if REDIS_URL is set and redis-py importable; else filesystem. Writes
    are guarded so a store failure never crashes the loop."""
    if os.environ.get("REDIS_URL"):
        try:
            return _GuardedStore(RedisSessionStore())
        except Exception as exc:  # noqa: BLE001 - degrade to filesystem
            print(f"[session_state] Redis unavailable ({exc}); using FileSessionStore")
    return _GuardedStore(FileSessionStore())
