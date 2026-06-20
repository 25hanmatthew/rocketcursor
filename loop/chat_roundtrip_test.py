"""Local end-to-end chat-protocol round-trip test (no Agentverse, no asi1.ai).

Spins up the real service agent plus a tiny client agent on a local Bureau, sends
a ChatMessage to the service, and asserts a ChatMessage reply comes back over the
standard chat protocol. This proves the protocol wiring works before doing the
Agentverse mailbox / asi1.ai steps in the web UI.

To keep it fast and offline, it sends a request that resolves WITHOUT an LLM call:
the built-in spec name "tank_blowdown" (which the designer also one-shots, but the
loop still calls Anthropic to design). So this test DOES need ANTHROPIC_API_KEY.
For a pure-protocol check with zero API calls, pass --ping (sends an empty
StartSession-style greeting and expects the greeting reply).

    .venv/bin/python -m loop.chat_roundtrip_test --ping        # protocol only, no API
    .venv/bin/python -m loop.chat_roundtrip_test               # full loop round-trip
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Bureau, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from loop.agent import _load_dotenv
from loop.service import build_agent

PING = "--ping" in sys.argv[1:]
REQUEST = "tank_blowdown"

_state = {"replies": 0, "last": None, "done": False}


def _client_agent(service_address: str) -> Agent:
    client = Agent(name="roundtrip-client", seed="roundtrip-client-seed", port=8011,
                   endpoint=["http://127.0.0.1:8011/submit"])
    proto = Protocol(spec=chat_protocol_spec)

    @client.on_event("startup")
    async def _kick(ctx: Context):
        if PING:
            content = [StartSessionContent(type="start-session")]
        else:
            content = [TextContent(type="text", text=REQUEST)]
        await ctx.send(service_address, ChatMessage(
            timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content))
        ctx.logger.info("client sent request")

    @proto.on_message(ChatMessage)
    async def _on_reply(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        text = "".join(p.text for p in msg.content if isinstance(p, TextContent))
        ended = any(getattr(p, "type", "") == "end-session" for p in msg.content)
        _state["replies"] += 1
        _state["last"] = text
        ctx.logger.info(f"client got reply #{_state['replies']} (end={ended}): {text[:120]!r}")
        # In ping mode the first reply is terminal; in full mode wait for end-session.
        if PING or ended:
            _state["done"] = True

    @proto.on_message(ChatAcknowledgement)
    async def _on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    client.include(proto)
    return client


def main() -> int:
    _load_dotenv()
    service = build_agent()  # local endpoint (MAILBOX off by default)
    client = _client_agent(service.address)

    bureau = Bureau(port=8010, endpoint=["http://127.0.0.1:8010/submit"])
    bureau.add(service)
    bureau.add(client)

    # Stop the bureau shortly after we get a terminal reply (or on timeout).
    import asyncio

    async def _watchdog():
        for _ in range(120):  # up to ~120s for the full loop
            await asyncio.sleep(1)
            if _state["done"]:
                break
        print("\n================ ROUND-TRIP RESULT ================")
        print("mode:", "ping (protocol only)" if PING else "full loop")
        print("replies received:", _state["replies"])
        print("terminal reply received:", _state["done"])
        print("last reply (truncated):\n", (_state["last"] or "")[:600])
        print("===================================================")
        # Hard-exit so the bureau servers don't keep the process alive.
        import os
        os._exit(0 if _state["done"] else 1)

    loop = asyncio.get_event_loop()
    loop.create_task(_watchdog())
    bureau.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
