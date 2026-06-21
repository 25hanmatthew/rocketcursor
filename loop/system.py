"""Multi-agent system: Designer + Simulator, orchestrated over uAgents messaging.

This is the agent-to-agent version of the loop. Two agents, each with its own
identity/address, collaborate to fulfil a user's request:

    user --(chat protocol / ASI1)--> Designer agent
                                       | derive spec (ASI1)
                                       | design network (ASI1 tool call)
                                       v
                          SimulateRequest  --(uAgents msg)-->  Simulator agent
                                                                  | run_design (solver)
                                                                  | evaluate (pure Python)
                          SimulateResult  <--(uAgents msg)--      v
                                       | verdict failed? revise (ASI1) and resend
                                       | verdict passed? reply to user
                                       v
    user <--(chat protocol)-- Designer agent

The Designer does all the LLM reasoning and talks to the user; the Simulator does
the deterministic tool execution + verdict. The simulate+evaluate step of the loop
is a network round-trip between two distinct agents -- genuine agent-to-agent
orchestration. The verdict remains pure Python, computed on the Simulator.

Run the whole system locally (one process, both agents in a Bureau):
    .venv/bin/python -m loop.system

Expose on Agentverse (each agent registers its own profile):
    AGENT_MAILBOX=1 .venv/bin/python -m loop.system
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Bureau, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from loop.agent import SUBMIT_DESIGN_TOOL, SYSTEM_PROMPT, _first_user_message, _load_dotenv
from loop.classifier import IterationOutcome, classify
from loop.llm import ToolLoopSession, active_model, active_provider
from loop.protocol import SimulateRequest, SimulateResult
from loop.session_state import (
    get_store,
    iteration_view,
    new_state,
    report_view,
    requirements_view,
)
from loop.service import (
    AGENT_DESCRIPTION,
    _chat_msg,
    _help,
    _spec_preamble,
    _summarize,
    available_specs,
    nl_to_spec,
    resolve_spec,
)
from loop.simulator_agent import SIM_SEED, build_simulator_agent

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGNER_SEED = os.environ.get("AGENT_SEED", "rocketcursor-designer-dev-seed-change-me")
DESIGNER_PORT = int(os.environ.get("AGENT_PORT", "8001"))
MAILBOX = os.environ.get("AGENT_MAILBOX", "0") == "1"
MAX_ITERS = int(os.environ.get("AGENT_MAX_ITERS", "8"))
SIM_TIMEOUT = int(os.environ.get("SIM_TIMEOUT", "180"))


def simulator_address() -> str:
    """The Simulator agent's address. Set SIM_AGENT_ADDRESS to target a specific
    deployed Simulator; otherwise it is derived deterministically from SIM_AGENT_SEED
    (so the Designer can reach a separately-running Simulator without a shared Bureau)."""
    explicit = os.environ.get("SIM_AGENT_ADDRESS")
    if explicit:
        return explicit
    from uagents.crypto import Identity

    return Identity.from_seed(SIM_SEED, 0).address


def _resolve_request_to_spec(text: str) -> tuple[dict | None, str | None, bool]:
    """Return (spec_dict, error, was_derived). Mirrors service.run_and_summarize's
    front-end (spec name / inline JSON / natural language)."""
    text = (text or "").strip()
    if not text:
        return None, "empty request", False
    first = text.split()[0].removesuffix(".json")
    if text.startswith("{") or first in available_specs():
        path, err = resolve_spec(text)
        if err:
            return None, err, False
        return json.loads(Path(path).read_text(encoding="utf-8")), None, False
    try:
        spec = nl_to_spec(text)
    except Exception as exc:  # noqa: BLE001
        return None, f"could not derive a spec from your request: {exc}", False
    if "name" not in spec or "checks" not in spec:
        return None, "derived spec is missing 'name' or 'checks'", False
    return spec, None, True


async def _run_distributed_loop(ctx: Context, sim_address: str, spec: dict,
                                request: str | None = None) -> tuple[dict, dict | None]:
    """The design/revise loop with simulate+evaluate delegated to the Simulator agent.
    Also emits per-iteration session state (Redis/UI seam) — the Designer is the
    single writer of session state for the multi-agent system."""
    session = ToolLoopSession(SYSTEM_PROMPT, SUBMIT_DESIGN_TOOL, tool_name="submit_design")
    trace = {"spec": spec["name"], "provider": session.provider, "model": session.model,
             "multiagent": True, "restarts": 0, "iterations": []}
    spec_json = json.dumps(spec)

    store = get_store()
    state = new_state(spec["name"], request or spec["name"], session.provider, session.model)
    state["requirements"] = requirements_view(spec)
    state["stage"] = "design"
    store.write(state)

    first_msg = _first_user_message(spec)
    design = await asyncio.to_thread(session.first, first_msg)
    final_design = None
    final_verdict = None
    line: list[IterationOutcome] = []
    restarts_used = 0
    dead_ends: list[str] = []
    for i in range(MAX_ITERS):
        if design is None:
            design = await asyncio.to_thread(
                session.nudge, "You did not call submit_design. Call it now with a full design.")
            if design is None:
                break
            continue
        final_design = design

        state["stage"] = "simulate"; state["current_iteration"] = i; store.write(state)
        req = SimulateRequest(spec_json=spec_json, design_json=json.dumps(design), iteration=i)
        reply, status = await ctx.send_and_receive(
            sim_address, req, response_type=SimulateResult, timeout=SIM_TIMEOUT)
        if not isinstance(reply, SimulateResult):
            trace["error"] = f"simulator did not respond ({status})"
            state["status"] = "error"; state["error"] = trace["error"]; store.write(state)
            break

        ctx.logger.info(f"iter {i}: {reply.summary} (status {reply.status})")
        verdict_dict = json.loads(reply.verdict_json)
        final_verdict = verdict_dict
        checks = verdict_dict.get("checks", [])
        n_passed = sum(1 for c in checks if c.get("passed"))

        # classify: revise this line, or scrap and start a fresh design line
        line.append(IterationOutcome(reply.status, reply.passed, n_passed, len(checks)))
        decision = classify(line, restarts_used, max_restarts=2)
        if not reply.passed:
            ctx.logger.info(f"  classifier -> {decision.action}: {decision.reason}")

        trace["iterations"].append({
            "iteration": i, "status": reply.status, "verdict": verdict_dict,
            "decision": {"action": decision.action, "reason": decision.reason},
        })
        result_view = json.loads(reply.result_json) if reply.result_json else {}
        state["stage"] = "evaluate"
        iv = iteration_view(i, design, result_view, verdict_dict)
        iv["decision"] = {"action": decision.action, "reason": decision.reason}
        state["iterations"].append(iv)
        store.write(state)

        if reply.passed:
            break

        if decision.action == "scrap":
            dead_ends.append(f"Attempt {restarts_used + 1}: {reply.summary}; "
                             f"unmet checks: {sorted(c['id'] for c in checks if not c.get('passed'))}")
            restarts_used += 1
            trace["restarts"] = restarts_used
            line = []
            state["stage"] = "design"; store.write(state)
            session = ToolLoopSession(SYSTEM_PROMPT, SUBMIT_DESIGN_TOOL, tool_name="submit_design")
            restart_msg = first_msg + "\n\nYour earlier design approaches FAILED — do NOT repeat " \
                "them; try a materially different design:\n" + "\n".join(dead_ends)
            design = await asyncio.to_thread(session.first, restart_msg)
        else:
            design = await asyncio.to_thread(session.tool_result, reply.feedback, True)

    trace["passed"] = bool(trace["iterations"]) and trace["iterations"][-1]["verdict"]["passed"]
    trace["iterations_used"] = len(trace["iterations"])

    state["stage"] = "report"
    state["passed"] = trace["passed"]
    state["status"] = state.get("status") if state.get("status") == "error" else (
        "passed" if trace["passed"] else "failed")
    state["iterations_used"] = trace["iterations_used"]
    state["report"] = report_view(trace["passed"], final_verdict, final_design, trace["iterations_used"])
    store.write(state)
    return trace, final_design


def build_designer_agent(sim_address: str) -> Agent:
    readme = REPO_ROOT / "loop" / "AGENT_README.md"
    kwargs: dict = {
        "name": "rocketcursor-feed-designer",
        "seed": DESIGNER_SEED,
        "port": DESIGNER_PORT,
        "description": AGENT_DESCRIPTION,
        "publish_agent_details": True,
    }
    if readme.exists():
        kwargs["readme_path"] = str(readme)
    if MAILBOX:
        kwargs["mailbox"] = True
    else:
        kwargs["endpoint"] = [f"http://127.0.0.1:{DESIGNER_PORT}/submit"]
    agent = Agent(**kwargs)

    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def _on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        text = "".join(p.text for p in msg.content if isinstance(p, TextContent)).strip()
        is_start = any(isinstance(p, StartSessionContent) for p in msg.content)
        if not text:
            if is_start:
                await ctx.send(sender, _chat_msg(
                    "Hi — I'm the Rocketcursor feed-system designer (multi-agent). Describe a "
                    "system (e.g. \"a LOX/methane engine making ~2 kN thrust at MR 3.2\") and I'll "
                    "design it, hand it to my Simulator agent to run and grade, and iterate to a "
                    "passing design."))
            return

        ctx.logger.info(f"design request from {sender[:16]}…: {text[:80]!r}")
        await ctx.send(sender, _chat_msg(
            "Got it — deriving a spec and designing a network, then handing each candidate to my "
            "Simulator agent to run and grade. This can take a minute or two while I iterate…"))

        spec, err, derived = await asyncio.to_thread(_resolve_request_to_spec, text)
        if err:
            await ctx.send(sender, _chat_msg(_help(err), end=True))
            return
        try:
            trace, final_design = await _run_distributed_loop(ctx, sim_address, spec, request=text)
        except Exception as exc:  # noqa: BLE001
            ctx.logger.exception("distributed loop failed")
            await ctx.send(sender, _chat_msg(
                f"Sorry — the design run failed: {type(exc).__name__}: {exc}", end=True))
            return

        summary = _summarize(trace, final_design)
        if derived:
            summary = _spec_preamble(spec) + "\n\n" + summary
        summary += f"\n\n_(designed by ASI1 on the Designer agent; simulated + graded on the Simulator agent)_"
        await ctx.send(sender, _chat_msg(summary, end=True))

    @protocol.on_message(ChatAcknowledgement)
    async def _on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(protocol, publish_manifest=True)
    return agent


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Designer+Simulator multi-agent system.")
    parser.add_argument("--role", choices=["both", "designer", "simulator"], default="both",
                        help="both = one process, Bureau hosts both agents (local demo). "
                             "designer / simulator = run that agent as its OWN process "
                             "(true distributed; the Designer targets the Simulator by its "
                             "seed-derived address or SIM_AGENT_ADDRESS).")
    args = parser.parse_args(argv)
    _load_dotenv()
    from loop.monitoring import init_sentry
    from loop.tracing import enable_tracing
    enable_tracing(project_name="rocketcursor-multiagent")
    init_sentry(component="multiagent")
    print(f"LLM provider: {active_provider()} | model: {active_model()}")

    if args.role == "simulator":
        agent = build_simulator_agent()
        print(f"Simulator agent address: {agent.address}  (role=simulator, own process)")
        print(f"mailbox={MAILBOX}")
        agent.run()
        return 0

    if args.role == "designer":
        sim_addr = simulator_address()
        designer = build_designer_agent(sim_addr)
        print(f"Designer  agent address: {designer.address}  (role=designer, own process)")
        print(f"-> targeting Simulator at: {sim_addr}")
        print(f"mailbox={MAILBOX}  max_iters={MAX_ITERS}")
        print(f"specs: {', '.join(available_specs())} (or natural language, or inline spec JSON)")
        designer.run()
        return 0

    # role == both: single process, Bureau hosts both (local demo / test)
    simulator = build_simulator_agent()
    designer = build_designer_agent(simulator.address)
    print(f"Designer  agent address: {designer.address}")
    print(f"Simulator agent address: {simulator.address}")
    print(f"mailbox={MAILBOX}  max_iters={MAX_ITERS}")
    print(f"specs: {', '.join(available_specs())} (or natural language, or inline spec JSON)")
    bureau = Bureau(port=8000, endpoint=["http://127.0.0.1:8000/submit"])
    bureau.add(simulator)
    bureau.add(designer)
    bureau.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
