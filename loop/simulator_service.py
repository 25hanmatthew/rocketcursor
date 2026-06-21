"""Fetch.ai uAgent that exposes the fluid-network SIMULATOR over the Chat Protocol.

The companion to loop.service (the designer): this agent takes a *design* and runs
the transient fluid-network simulation, returning the measured behaviour — and, if
you include requirements, a DETERMINISTIC pass/fail verdict (pure Python, no LLM).
It never calls an LLM; it executes the tool and reports/judges the result.

A chat message is interpreted as either:
  - a built-in network-config NAME (one of simulator/network_configs/*.json,
    e.g. "vehicle_sim", "tank_vent_to_atmosphere"), or
  - an inline design as JSON (a network config with "nodes"/"connections"), or
  - a wrapper {"design": {...}, "spec": {...}} to also grade against requirements.

Run locally (local endpoint; no Agentverse needed):
    .venv/bin/python -m loop.simulator_service

Expose on Agentverse / asi1.ai chat:
    AGENT_MAILBOX=1 .venv/bin/python -m loop.simulator_service           # mailbox transport
    SIM_AGENT_ENDPOINT=https://<tunnel>/submit .venv/bin/python -m loop.simulator_service  # public endpoint

Offline check (no network): .venv/bin/python -m loop.simulator_service --selftest

Config via env:
    SIM_AGENT_SEED      stable identity seed (default: a dev seed — set your own)
    SIM_AGENT_PORT      local port (default 8002)
    AGENT_MAILBOX       "1" to register via Agentverse mailbox
    SIM_AGENT_ENDPOINT  public endpoint URL to advertise (e.g. an ngrok /submit URL)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from loop.evaluator import evaluate
from loop.simulator_adapter import run_design

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "simulator" / "network_configs"

SEED = os.environ.get("SIM_AGENT_SEED", "rocketcursor-simulator-dev-seed-change-me")
PORT = int(os.environ.get("SIM_AGENT_PORT", "8002"))
MAILBOX = os.environ.get("AGENT_MAILBOX", "0") == "1"
ENDPOINT = os.environ.get("SIM_AGENT_ENDPOINT")  # public URL (must end in /submit)

AGENT_DESCRIPTION = (
    "Rocketcursor Simulator/Evaluator: give it a rocket fluid-network design (a "
    "built-in config name or inline JSON) and it runs a transient physics simulation "
    "and reports the measured behaviour — pressures, flows, thrust, durations, "
    "warnings. Include requirements and it returns a DETERMINISTIC pass/fail verdict. "
    "Pure tool execution, no LLM."
)


# --------------------------------------------------------------------------- #
# Request handling (pure functions — testable without the agent or the network)
# --------------------------------------------------------------------------- #

def available_configs() -> list[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.json"))


def resolve_design(text: str) -> tuple[dict | None, dict | None, str, str]:
    """Map a chat message to (design, spec_or_None, label, error).

    Accepts a built-in config name, an inline design JSON, or a
    {"design":..., "spec":...} wrapper.
    """
    text = text.strip()
    if not text:
        return None, None, "", "empty request"

    # 1. built-in config name
    if not text.lstrip().startswith("{"):
        name = text.split()[0]
        path = CONFIGS_DIR / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text()), None, name, ""
        return None, None, name, (
            f"unknown config {name!r}. Available: {', '.join(available_configs())}. "
            "Or paste a design as JSON.")

    # 2. inline JSON
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, None, "", f"could not parse JSON: {exc}"

    if isinstance(obj, dict) and "design" in obj:  # wrapper with optional spec
        spec = obj.get("spec") if isinstance(obj.get("spec"), dict) else None
        return obj["design"], spec, obj.get("name", "inline-design"), ""
    if isinstance(obj, dict) and ("nodes" in obj or "connections" in obj):
        return obj, None, obj.get("name", "inline-design"), ""
    return None, None, "", "JSON has no 'nodes'/'connections' (or 'design' wrapper)."


def simulate(design: dict, label: str, spec: dict | None = None) -> dict:
    """Run the solver on a design (in a temp dir) and optionally grade it."""
    with TemporaryDirectory() as tmp:
        result = run_design(design, Path(tmp) / "run")
    verdict = evaluate(spec, result) if spec else None
    return {"label": label, "result": result, "verdict": verdict}


def _summarize(outcome: dict) -> str:
    label, result, verdict = outcome["label"], outcome["result"], outcome["verdict"]
    status = result.get("status", "?")
    diag = result.get("diagnostics", {})
    lines = [f"Simulation of '{label}': status = {status.upper()}"]

    if result.get("errors"):
        lines.append("\nERRORS:")
        lines += [f"  - {e}" for e in result["errors"][:6]]

    if status == "ok":
        lines.append(
            f"\nRan {diag.get('step_count', '?')} steps over "
            f"{diag.get('duration', '?')} s (dt={diag.get('dt', '?')}); "
            f"{diag.get('node_count', '?')} nodes, "
            f"{diag.get('connection_count', '?')} connections, "
            f"{diag.get('action_count', 0)} timed actions.")

        final = result.get("final_nodes", {})
        if final:
            lines.append("\nFinal node state:")
            for name, st in list(final.items())[:8]:
                if isinstance(st, dict):
                    bits = []
                    for k in ("P", "T", "m"):
                        if k in st and isinstance(st[k], (int, float)):
                            bits.append(f"{k}={st[k]:.4g}")
                    lines.append(f"  {name}: {', '.join(bits) if bits else st}")

        warns = result.get("warnings", []) or diag.get("warnings", [])
        if warns:
            lines.append(f"\n{len(warns)} warning(s):")
            for w in warns[:5]:
                lines.append(f"  - {w.get('message', w) if isinstance(w, dict) else w}")

    if verdict is not None:
        lines.append("")
        lines.append(f"VERDICT: {verdict.summary}")
        for c in verdict.checks:
            mark = "PASS" if c.passed else "FAIL"
            line = f"[{mark}] {c.id}: {c.description}"
            if not c.passed:
                line += f"  (expected {c.op} {c.expected!r}; actual={c.actual!r})"
            lines.append(line)

    return "\n".join(lines)


def run_and_summarize(text: str) -> str:
    design, spec, label, err = resolve_design(text)
    if err:
        return f"Couldn't simulate that: {err}"
    return _summarize(simulate(design, label, spec))


# --------------------------------------------------------------------------- #
# uAgent wrapper
# --------------------------------------------------------------------------- #

def _chat_msg(text: str, end: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def build_agent() -> Agent:
    readme = REPO_ROOT / "loop" / "SIMULATOR_README.md"
    kwargs: dict = {
        "name": "rocketcursor-simulator",
        "seed": SEED,
        "port": PORT,
        "description": AGENT_DESCRIPTION,
        "publish_agent_details": True,
    }
    if readme.exists():
        kwargs["readme_path"] = str(readme)
    if MAILBOX:
        kwargs["mailbox"] = True
    elif ENDPOINT:
        kwargs["endpoint"] = [ENDPOINT]
    else:
        kwargs["endpoint"] = [f"http://127.0.0.1:{PORT}/submit"]
    agent = Agent(**kwargs)

    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def _on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(
            sender,
            ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
        )
        text = "".join(p.text for p in msg.content if isinstance(p, TextContent)).strip()
        is_start = any(isinstance(p, StartSessionContent) for p in msg.content)
        if not text:
            if is_start:
                await ctx.send(sender, _chat_msg(
                    "Hi — I'm the Rocketcursor simulator. Send me a design to simulate: "
                    f"a built-in config name ({', '.join(available_configs())}), inline "
                    "design JSON, or a {\"design\":…, \"spec\":…} wrapper to also grade it."))
            return
        ctx.logger.info(f"simulate request from {sender[:16]}…: {text[:80]!r}")
        await ctx.send(sender, _chat_msg("Running the transient simulation…"))
        try:
            reply = await asyncio.to_thread(run_and_summarize, text)
        except Exception as exc:  # noqa: BLE001 - never leave the chat hanging
            ctx.logger.exception("simulation failed")
            reply = f"Sorry — the simulation failed: {type(exc).__name__}: {exc}"
        await ctx.send(sender, _chat_msg(reply, end=True))

    @protocol.on_message(ChatAcknowledgement)
    async def _on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(protocol, publish_manifest=True)
    return agent


def _run_selftest() -> None:
    print("available configs:", available_configs())
    # a fast, non-engine config exercises the full path without CEA
    demo = "tank_vent_to_atmosphere" if "tank_vent_to_atmosphere" in available_configs() else available_configs()[0]
    print(f"\n--- simulating {demo!r} ---")
    print(run_and_summarize(demo))
    print("\n--- unknown name ---")
    print(run_and_summarize("does_not_exist"))
    agent = build_agent()
    print("\nagent address:", agent.address)
    print("selftest OK")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the rocketcursor simulator uAgent.")
    parser.add_argument("--selftest", action="store_true",
                        help="Offline check of request handling + agent construction (no network).")
    args = parser.parse_args(argv)

    if args.selftest:
        _run_selftest()
        return 0

    from loop.agent import _load_dotenv
    from loop.monitoring import init_sentry
    from loop.tracing import enable_tracing
    _load_dotenv()
    enable_tracing(project_name="rocketcursor-simulator")
    init_sentry(component="simulator-agent")
    agent = build_agent()
    print(f"agent address: {agent.address}")
    print(f"mailbox={MAILBOX} port={PORT} endpoint={ENDPOINT or f'http://127.0.0.1:{PORT}/submit'}")
    print(f"send a config name ({', '.join(available_configs())}) or inline design JSON via chat.")
    agent.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
