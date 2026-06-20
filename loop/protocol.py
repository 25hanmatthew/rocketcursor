"""Shared uAgent message models for Designer <-> Simulator agent-to-agent calls.

The design loop is split across two agents:
  - the Designer (LLM reasoning + chat protocol, user-facing) sends a SimulateRequest,
  - the Simulator/Evaluator (pure deterministic tool execution, no LLM) replies with
    a SimulateResult.

Design and spec are passed as JSON strings (not nested dicts) so the message schema
stays simple and validates cleanly regardless of how deep the network JSON nests.
"""

from __future__ import annotations

from uagents import Model


class SimulateRequest(Model):
    """Designer -> Simulator: please run and grade this design."""
    spec_json: str            # the full requirements spec (JSON)
    design_json: str          # the candidate fluid-network design (JSON)
    iteration: int = 0        # which design/revise iteration this is (for labelling)


class SimulateResult(Model):
    """Simulator -> Designer: deterministic verdict for one design."""
    passed: bool              # did every check pass?
    status: str               # sim status: ok | invalid_config | crashed
    summary: str              # e.g. "6/8 checks passed"
    feedback: str             # full verdict text the Designer revises against
    verdict_json: str         # the structured Verdict (JSON) for the trace
    result_json: str = "{}"   # trimmed sim result (components/diagnostics/warnings/
                              # status/errors) so the Designer can emit full UI state
