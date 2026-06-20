"""The Simulator/Evaluator uAgent: deterministic tool execution, no LLM.

This is the worker half of the multi-agent system. It receives a candidate design
plus a requirements spec from the Designer agent, runs the transient fluid-network
simulation, computes the pure-Python verdict, and replies. It never calls an LLM —
its job is to *execute the tool and judge the result*, which is exactly the part of
the loop that must stay deterministic and reproducible.

Run standalone (e.g. to register its own Agentverse profile):
    AGENT_MAILBOX=1 .venv/bin/python -m loop.simulator_agent
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from uagents import Agent, Context

from loop.evaluator import evaluate
from loop.protocol import SimulateRequest, SimulateResult
from loop.simulator_adapter import run_design

SIM_SEED = os.environ.get("SIM_AGENT_SEED", "rocketcursor-simulator-dev-seed-change-me")
SIM_PORT = int(os.environ.get("SIM_AGENT_PORT", "8002"))
SIM_MAILBOX = os.environ.get("AGENT_MAILBOX", "0") == "1"

SIM_DESCRIPTION = (
    "Rocketcursor Simulator/Evaluator: runs a transient fluid-network simulation of a "
    "candidate rocket feed-system design and returns a deterministic pass/fail verdict "
    "against a requirements spec. Pure tool execution, no LLM."
)


def _simulate_and_grade(spec: dict, design: dict, iteration: int) -> SimulateResult:
    """The deterministic core, callable directly (also used by tests)."""
    with tempfile.TemporaryDirectory() as tmp:
        result = run_design(design, Path(tmp) / f"iter_{iteration:02d}")
    verdict = evaluate(spec, result)
    # trimmed result for the Designer to build full UI state (node colors, sidebar)
    result_view = {
        "status": result.get("status"),
        "components": result.get("components", {}),
        "diagnostics": result.get("diagnostics", {}),
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", []),
    }
    return SimulateResult(
        passed=verdict.passed,
        status=result.get("status", "?"),
        summary=verdict.summary,
        feedback=_feedback(verdict, result),
        verdict_json=json.dumps(verdict.to_dict()),
        result_json=json.dumps(result_view),
    )


def _feedback(verdict, result) -> str:
    lines = [f"VERDICT: {verdict.summary}", ""]
    for c in verdict.checks:
        mark = "PASS" if c.passed else "FAIL"
        line = f"[{mark}] {c.id}: {c.description}"
        if not c.passed:
            line += f"\n        expected {c.op} {c.expected!r}; actual={c.actual!r}"
            if c.detail:
                line += f" ({c.detail})"
        lines.append(line)
    if result.get("errors"):
        lines += ["", "SIMULATION ERRORS:"] + [f"  - {e}" for e in result["errors"]]
    if verdict.notes:
        lines += [""] + verdict.notes
    if not verdict.passed:
        lines += ["", "Revise the design to fix the FAILing checks, then submit again."]
    return "\n".join(lines)


def build_simulator_agent() -> Agent:
    kwargs: dict = {
        "name": "rocketcursor-simulator",
        "seed": SIM_SEED,
        "port": SIM_PORT,
        "description": SIM_DESCRIPTION,
        "publish_agent_details": True,
    }
    if SIM_MAILBOX:
        kwargs["mailbox"] = True
    else:
        kwargs["endpoint"] = [f"http://127.0.0.1:{SIM_PORT}/submit"]
    agent = Agent(**kwargs)

    @agent.on_message(SimulateRequest, replies=SimulateResult)
    async def _on_simulate(ctx: Context, sender: str, msg: SimulateRequest):
        ctx.logger.info(f"simulate request (iter {msg.iteration}) from {sender[:16]}…")
        spec = json.loads(msg.spec_json)
        design = json.loads(msg.design_json)
        # run the blocking solver off the event loop
        result = await asyncio.to_thread(_simulate_and_grade, spec, design, msg.iteration)
        ctx.logger.info(f"  -> {result.summary} (status {result.status})")
        await ctx.send(sender, result)

    return agent


def main() -> int:
    agent = build_simulator_agent()
    print(f"simulator agent address: {agent.address}")
    print(f"mailbox={SIM_MAILBOX} port={SIM_PORT}")
    agent.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
