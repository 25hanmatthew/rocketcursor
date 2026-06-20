"""Fetch.ai uAgent that exposes the design loop over the Chat Protocol.

This wraps `loop.agent.run_loop` in a uAgent so the design->simulate->evaluate->
revise loop is callable from another agent or from the asi1.ai chat interface
(via Agentverse). The agent's "intelligence" is unchanged — it still calls
Anthropic (Opus 4.8) inside run_loop and the verdict is still pure-Python.

A chat message is interpreted as either:
  - a spec NAME (one of loop/specs/*.json, e.g. "pressure_window_blowdown"), or
  - a full requirements spec as inline JSON (must have "name" and "checks").

Run locally (talks the protocol on a local endpoint; no Agentverse needed):
    .venv/bin/python -m loop.service

Expose on Agentverse / asi1.ai chat (needs the agent registered there):
    AGENT_MAILBOX=1 .venv/bin/python -m loop.service

Offline check (no API calls, no network): .venv/bin/python -m loop.service --selftest

Config via env:
    AGENT_SEED       stable identity seed (default: a dev seed — set your own)
    AGENT_PORT       local port (default 8001)
    AGENT_MAILBOX    "1" to register via Agentverse mailbox (default local endpoint)
    AGENT_COMPRESS   "1" to route Anthropic calls through the-token-company
    AGENT_MAX_ITERS  max design/revise iterations (default 8)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
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

from loop.agent import run_loop
from loop.spec_writer import nl_to_spec

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "loop" / "specs"
INBOUND_DIR = REPO_ROOT / "results" / "loop_runs" / "_inbound"

SEED = os.environ.get("AGENT_SEED", "rocketcursor-feed-designer-dev-seed-change-me")
PORT = int(os.environ.get("AGENT_PORT", "8001"))
MAILBOX = os.environ.get("AGENT_MAILBOX", "0") == "1"
COMPRESS = os.environ.get("AGENT_COMPRESS", "0") == "1"
MAX_ITERS = int(os.environ.get("AGENT_MAX_ITERS", "8"))


# --------------------------------------------------------------------------- #
# Request handling (pure functions — testable without the agent or the API)
# --------------------------------------------------------------------------- #

def available_specs() -> list[str]:
    return sorted(p.stem for p in SPECS_DIR.glob("*.json"))


def resolve_spec(text: str) -> tuple[Path | None, str | None]:
    """Map a chat request to a spec file path. Returns (path, error)."""
    text = (text or "").strip()
    if not text:
        return None, "empty request"

    if text.startswith("{"):
        try:
            spec = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, f"could not parse inline spec JSON: {exc}"
        if not isinstance(spec, dict) or "name" not in spec or "checks" not in spec:
            return None, "inline spec must be a JSON object with 'name' and 'checks'"
        INBOUND_DIR.mkdir(parents=True, exist_ok=True)
        path = INBOUND_DIR / f"{spec['name']}.json"
        path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return path, None

    name = text.split()[0].removesuffix(".json")
    path = SPECS_DIR / f"{name}.json"
    if path.exists():
        return path, None
    return None, f"unknown spec {name!r}; available: {', '.join(available_specs())}"


def _summarize(trace: dict, final_design: dict | None) -> str:
    head = "PASSED" if trace.get("passed") else "DID NOT PASS"
    lines = [f"**{trace.get('spec')}** — {head} after {trace.get('iterations_used', 0)} iteration(s)."]
    iters = trace.get("iterations", [])
    if iters:
        verdict = iters[-1]["verdict"]
        lines.append(f"Final verdict: {verdict['summary']}")
        fails = [c for c in verdict["checks"] if not c["passed"]]
        if fails:
            lines.append("Unmet checks:")
            for c in fails:
                lines.append(f"  - {c['id']}: expected {c['op']} {c['expected']}, actual {c['actual']}")
    if final_design is not None:
        lines.append("\nFinal design:\n```json\n" + json.dumps(final_design, indent=2) + "\n```")
    return "\n".join(lines)


def _help(issue: str) -> str:
    return (
        "I design rocket feed-system networks and iterate until a deterministic "
        "verdict passes. You can:\n"
        f"  - name a built-in spec ({', '.join(available_specs())}),\n"
        "  - paste a full spec JSON (with 'name' and 'checks'), or\n"
        "  - just describe what you want in plain English.\n"
        f"Issue: {issue}"
    )


def _spec_preamble(spec: dict) -> str:
    lines = [
        f"Derived a deterministic spec **{spec.get('name')}** from your request. "
        "Pass/fail criteria (evaluated in Python, not by the model):"
    ]
    for c in spec.get("checks", []):
        target = c.get("component") or c.get("field") or c.get("type")
        stat = f".{c['stat']}" if c.get("stat") else ""
        lines.append(f"  - {c['id']}: {target}{stat} {c['op']} {c['value']}")
    return "\n".join(lines)


def run_and_summarize(text: str) -> str:
    """Resolve the request (spec name / inline JSON / natural language), run the
    loop, and return a human-readable summary."""
    text = (text or "").strip()
    if not text:
        return _help("empty request")

    derived_spec = None
    first_token = text.split()[0].removesuffix(".json")
    if text.startswith("{") or first_token in available_specs():
        spec_path, err = resolve_spec(text)
        if err:
            return _help(err)
    else:
        # Natural-language request -> translate to a structured, checkable spec.
        try:
            derived_spec = nl_to_spec(text)
        except Exception as exc:  # noqa: BLE001
            return _help(f"could not derive a spec from your request: {exc}")
        if "name" not in derived_spec or "checks" not in derived_spec:
            return _help("derived spec is missing 'name' or 'checks'")
        INBOUND_DIR.mkdir(parents=True, exist_ok=True)
        spec_path = INBOUND_DIR / f"{derived_spec['name']}.json"
        spec_path.write_text(json.dumps(derived_spec, indent=2), encoding="utf-8")

    trace = run_loop(spec_path, max_iters=MAX_ITERS, use_compression=COMPRESS)
    final_design = None
    if trace.get("iterations"):
        design_path = trace["iterations"][-1].get("design_path")
        try:
            final_design = json.loads(Path(design_path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            final_design = None

    summary = _summarize(trace, final_design)
    if derived_spec is not None:
        summary = _spec_preamble(derived_spec) + "\n\n" + summary
    return summary


# --------------------------------------------------------------------------- #
# uAgent + Chat Protocol
# --------------------------------------------------------------------------- #

AGENT_DESCRIPTION = (
    "Rocketcursor designs rocket propulsion feed systems from a plain-English "
    "request. It turns your intent into a machine-checkable spec, has an LLM "
    "design a fluid-network (tanks, feeds, orifices, liquid engine), simulates it "
    "with a transient solver, and iterates until a DETERMINISTIC Python verdict "
    "passes. Ask for a tank blowdown to a target pressure, or a LOX/methane engine "
    "hitting a thrust / chamber-pressure / mixture-ratio / Isp target."
)


def _chat_msg(text: str, end: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def build_agent() -> Agent:
    readme = REPO_ROOT / "loop" / "AGENT_README.md"
    kwargs: dict = {
        "name": "rocketcursor-feed-designer",
        "seed": SEED,
        "port": PORT,
        "description": AGENT_DESCRIPTION,
        "publish_agent_details": True,
    }
    if readme.exists():
        kwargs["readme_path"] = str(readme)
    if MAILBOX:
        kwargs["mailbox"] = True
    else:
        kwargs["endpoint"] = [f"http://127.0.0.1:{PORT}/submit"]
    agent = Agent(**kwargs)

    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def _on_chat(ctx: Context, sender: str, msg: ChatMessage):
        # 1. always acknowledge receipt first
        await ctx.send(
            sender,
            ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
        )
        # 2. session-open handshake: ASI1 may send a StartSession with no text
        text = "".join(p.text for p in msg.content if isinstance(p, TextContent)).strip()
        is_start = any(isinstance(p, StartSessionContent) for p in msg.content)
        if not text:
            if is_start:
                await ctx.send(sender, _chat_msg(
                    "Hi — I'm the Rocketcursor feed-system designer. Describe the system "
                    "you want (e.g. \"a LOX/methane engine making ~2 kN thrust at MR 3.2\" "
                    "or \"vent a 6 MPa nitrogen tank to ~2.3 MPa in 12 s\") and I'll design, "
                    "simulate, and verify it."))
            return
        ctx.logger.info(f"design request from {sender}: {text[:80]!r}")
        # 3. let the user know it's working (the loop can take a while), then run it
        await ctx.send(sender, _chat_msg(
            "Got it — deriving a spec, designing a network, and simulating it. "
            "This can take a minute or two while I iterate to a passing design…"))
        try:
            reply = await asyncio.to_thread(run_and_summarize, text)
        except Exception as exc:  # noqa: BLE001 - never leave the chat hanging
            ctx.logger.exception("loop failed")
            reply = f"Sorry — the design run failed: {type(exc).__name__}: {exc}"
        await ctx.send(sender, _chat_msg(reply, end=True))

    @protocol.on_message(ChatAcknowledgement)
    async def _on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(protocol, publish_manifest=True)
    return agent


def _run_selftest() -> None:
    print("available specs:", available_specs())
    p, err = resolve_spec("pressure_window_blowdown")
    print("resolve known  ->", (p.name if p else None), "| err:", err)
    p, err = resolve_spec("does_not_exist")
    print("resolve unknown-> err:", err)
    p, err = resolve_spec('{"name": "inline_demo", "checks": []}')
    print("resolve inline ->", (p.name if p else None), "| err:", err)

    stub = {
        "spec": "demo", "passed": False, "iterations_used": 2,
        "iterations": [{
            "verdict": {"summary": "3/4 checks passed", "checks": [
                {"id": "window_upper", "passed": False, "op": "<=", "expected": 2280000.0, "actual": 2295275.4},
            ]},
            "design_path": "/nonexistent",
        }],
    }
    print("\n--- summary sample ---")
    print(_summarize(stub, {"settings": {"duration": 12.0}}))

    agent = build_agent()
    print("\nagent address:", agent.address)
    print("selftest OK")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the rocketcursor design-loop uAgent.")
    parser.add_argument("--selftest", action="store_true",
                        help="Offline check of request handling + agent construction (no API/network).")
    args = parser.parse_args(argv)

    if args.selftest:
        _run_selftest()
        return 0

    agent = build_agent()
    print(f"agent address: {agent.address}")
    print(f"mailbox={MAILBOX} port={PORT} compress={COMPRESS} max_iters={MAX_ITERS}")
    print(f"send a spec name ({', '.join(available_specs())}) or inline spec JSON via chat.")
    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
