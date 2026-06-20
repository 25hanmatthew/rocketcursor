"""End-to-end test of the multi-agent system (Designer + Simulator) over a Bureau.

A client agent sends a ChatMessage to the Designer; the Designer derives a spec,
designs on ASI1, delegates simulate+evaluate to the Simulator agent via uAgents
messaging, and replies. Asserts a terminal chat reply comes back. This exercises
the real agent-to-agent path locally (no Agentverse).

    .venv/bin/python -m loop.system_roundtrip_test            # default: tank_blowdown
    .venv/bin/python -m loop.system_roundtrip_test "vent a 5 MPa nitrogen tank ..."
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Bureau, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

from loop.agent import _load_dotenv
from loop.simulator_agent import build_simulator_agent
from loop.system import build_designer_agent

REQUEST = " ".join(sys.argv[1:]).strip() or "tank_blowdown"
_state = {"replies": 0, "last": None, "done": False}


def _client(designer_address: str) -> Agent:
    client = Agent(name="system-roundtrip-client", seed="system-roundtrip-client-seed",
                   port=8013, endpoint=["http://127.0.0.1:8013/submit"])
    proto = Protocol(spec=chat_protocol_spec)

    @client.on_event("startup")
    async def _kick(ctx: Context):
        await ctx.send(designer_address, ChatMessage(
            timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
            content=[TextContent(type="text", text=REQUEST)]))
        ctx.logger.info(f"client sent request: {REQUEST!r}")

    @proto.on_message(ChatMessage)
    async def _reply(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        text = "".join(p.text for p in msg.content if isinstance(p, TextContent))
        ended = any(getattr(p, "type", "") == "end-session" for p in msg.content)
        _state["replies"] += 1
        _state["last"] = text
        ctx.logger.info(f"client reply #{_state['replies']} (end={ended}): {text[:100]!r}")
        if ended:
            _state["done"] = True

    @proto.on_message(ChatAcknowledgement)
    async def _ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    client.include(proto)
    return client


def main() -> int:
    _load_dotenv()
    simulator = build_simulator_agent()
    designer = build_designer_agent(simulator.address)
    client = _client(designer.address)

    bureau = Bureau(port=8012, endpoint=["http://127.0.0.1:8012/submit"])
    for a in (simulator, designer, client):
        bureau.add(a)

    import asyncio

    async def _watchdog():
        for _ in range(240):
            await asyncio.sleep(1)
            if _state["done"]:
                break
        print("\n============ SYSTEM ROUND-TRIP RESULT ============")
        print("request:", REQUEST)
        print("designer:", designer.address)
        print("simulator:", simulator.address)
        print("replies:", _state["replies"], "| terminal reply:", _state["done"])
        print("last reply (truncated):\n", (_state["last"] or "")[:800])
        print("==================================================")
        os._exit(0 if _state["done"] else 1)

    asyncio.get_event_loop().create_task(_watchdog())
    bureau.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
