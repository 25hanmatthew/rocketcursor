"""Offline check of the deterministic half of the loop (no API key needed).

Runs two hand-written designs through simulator_adapter + evaluator and prints
the verdicts, proving that:
  - the adapter classifies runs and surfaces per-component statistics, and
  - the evaluator discriminates a passing design from a failing one,
entirely in Python.

    python -m loop.selftest
"""

from __future__ import annotations

import json
from pathlib import Path

from loop.evaluator import evaluate
from loop.simulator_adapter import run_design

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((REPO_ROOT / "loop" / "specs" / "tank_blowdown.json").read_text())


def _design(cda: float, duration: float = 20.0, dt: float = 0.05) -> dict:
    return {
        "settings": {"duration": duration, "dt": dt},
        "nodes": [
            {"id": 0, "type": "Node", "params": {
                "fluid": "Nitrogen", "P": 9.5e6, "V": 7.0, "T": 293.15, "name": "supply_tank"}},
            {"id": 1, "type": "Ambient", "params": {
                "fluid": "Air", "P": 101325.0, "T": 293.15, "name": "atmosphere"}},
        ],
        "connections": [
            {"type": "Connection", "start_id": 0, "end_id": 1, "params": {
                "CdA": cda, "qdot": 0.0, "location": 0.0,
                "normal_state": 1, "checking": 1, "name": "vent"}},
        ],
        "actions": [],
    }


def _show(label: str, design: dict) -> None:
    out = REPO_ROOT / "results" / "loop_runs" / "_selftest" / label
    result = run_design(design, out)
    verdict = evaluate(SPEC, result)
    print(f"\n--- {label} (sim status: {result['status']}) -> {verdict.summary} ---")
    for c in verdict.checks:
        mark = "PASS" if c.passed else "FAIL"
        extra = "" if c.passed else f"  (actual={c.actual!r} {c.detail})"
        print(f"  [{mark}] {c.id}{extra}")


def main() -> None:
    # Under-vent: orifice too small / window too short -> tank drops <5 bar -> FAIL.
    _show("under_vent", _design(1e-7, duration=2.0))
    # Good blowdown: drops ~7 bar, stays above atmospheric -> PASS.
    _show("good_blowdown", _design(1e-6, duration=2.0))
    # Over-vent: orifice too large -> tank empties below atmospheric -> FAIL.
    _show("over_vent", _design(1e-4, duration=20.0, dt=0.005))


if __name__ == "__main__":
    main()
