"""Throwaway chat-protocol client: message a registered agent and print replies.

    .venv/bin/python -m loop.chat_client <agent_address> "<message>" [collect_secs]

Sends one ChatMessage to <agent_address> (resolved via Almanac -> Agentverse),
then prints every ChatMessage it receives back for collect_secs seconds.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec,
)

TARGET = sys.argv[1]
MESSAGE = sys.argv[2]
COLLECT = int(sys.argv[3]) if len(sys.argv) > 3 else 40

client = Agent(name="rc-chat-client", seed="rc-chat-client-throwaway-seed",
               port=8020, endpoint=["http://127.0.0.1:8020/submit"])
proto = Protocol(spec=chat_protocol_spec)
_state = {"sent_at": None, "replies": 0}


@client.on_event("startup")
async def _send(ctx: Context):
    ctx.logger.info(f"sending to {TARGET[:18]}…: {MESSAGE!r}")
    await ctx.send(TARGET, ChatMessage(
        timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
        content=[TextContent(type="text", text=MESSAGE)]))
    print(f"\n>>> SENT to {TARGET}\n>>> {MESSAGE}\n", flush=True)


@proto.on_message(ChatMessage)
async def _on_msg(ctx: Context, sender: str, msg: ChatMessage):
    text = "".join(p.text for p in msg.content if isinstance(p, TextContent))
    _state["replies"] += 1
    print(f"\n<<< REPLY #{_state['replies']} from {sender[:18]}…:\n{text}\n", flush=True)
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))


@proto.on_message(ChatAcknowledgement)
async def _on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@client.on_interval(period=float(COLLECT))
async def _stop(ctx: Context):
    print(f"\n=== collected {_state['replies']} reply message(s) in {COLLECT}s; exiting ===", flush=True)
    import os
    os._exit(0)


client.include(proto)

if __name__ == "__main__":
    client.run()
