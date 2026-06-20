"""LLM provider abstraction for the design loop.

The loop's reasoning (design + revise, and NL->spec translation) can run on either:
  - ASI1  (Fetch.ai's agentic LLM, OpenAI-compatible at https://api.asi1.ai/v1) -- DEFAULT
  - Anthropic (Claude)

ASI1 is the default because this is a Fetch.ai project: using ASI1 as the actual
reasoning engine (not just the discovery layer) is the point. Select via the
LLM_PROVIDER env var ("asi1" | "anthropic"); the model can be overridden with
LLM_MODEL.

Tool schemas are written ONCE in Anthropic-native form ({name, description,
input_schema}) and converted to OpenAI function form when needed. A
`ToolLoopSession` hides the per-provider multi-turn tool-call threading so the
design/revise loop stays provider-agnostic. The deterministic verdict is computed
elsewhere (loop.evaluator) and is unaffected by which LLM is used.
"""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "asi1").lower()
ASI1_BASE_URL = "https://api.asi1.ai/v1"
ASI1_DEFAULT_MODEL = "asi1"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"


def active_provider() -> str:
    return os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).lower()


def active_model() -> str:
    override = os.environ.get("LLM_MODEL")
    if override:
        return override
    return ASI1_DEFAULT_MODEL if active_provider() == "asi1" else ANTHROPIC_DEFAULT_MODEL


def _to_openai_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


class ToolLoopSession:
    """A multi-turn conversation that repeatedly elicits ONE tool call.

    Usage:
        s = ToolLoopSession(system, tool, tool_name="submit_design")
        design = s.first(user_text)          # -> dict (tool input) or None
        design = s.tool_result(feedback, is_error)   # next iteration
    """

    def __init__(self, system: str, tool: dict, tool_name: str,
                 model: str | None = None, max_tokens: int = 16000):
        self.system = system
        self.tool = tool
        self.tool_name = tool_name
        self.max_tokens = max_tokens
        self.provider = active_provider()
        self.model = model or active_model()
        self._last_tool_id: str | None = None
        if self.provider == "asi1":
            from openai import OpenAI

            self._client = OpenAI(base_url=ASI1_BASE_URL, api_key=os.environ["ASI1_API_KEY"])
            self._oai_tools = [_to_openai_tool(tool)]
            self.messages: list[dict] = [{"role": "system", "content": system}]
        else:
            import anthropic

            self._client = anthropic.Anthropic()
            self.messages = []

    # -- public turns ------------------------------------------------------- #

    def first(self, user_text: str) -> dict | None:
        if self.provider == "asi1":
            self.messages.append({"role": "user", "content": user_text})
        else:
            self.messages.append({"role": "user", "content": user_text})
        return self._step()

    def tool_result(self, text: str, is_error: bool = False) -> dict | None:
        if self.provider == "asi1":
            self.messages.append({
                "role": "tool",
                "tool_call_id": self._last_tool_id or "tool_0",
                "content": text,
            })
        else:
            self.messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": self._last_tool_id,
                    "content": text,
                    "is_error": is_error,
                }],
            })
        return self._step()

    def nudge(self, text: str) -> dict | None:
        self.messages.append({"role": "user", "content": text})
        return self._step()

    # -- provider step ------------------------------------------------------ #

    def _step(self) -> dict | None:
        if self.provider == "asi1":
            return self._step_openai()
        return self._step_anthropic()

    def _step_openai(self) -> dict | None:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=self._oai_tools,
            tool_choice="auto",
            max_tokens=self.max_tokens,
        )
        msg = resp.choices[0].message
        # record the assistant turn verbatim (tool_calls must be echoed back)
        self.messages.append(msg.model_dump(exclude_none=True))
        for call in (msg.tool_calls or []):
            if call.function.name == self.tool_name:
                self._last_tool_id = call.id
                try:
                    return json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    return None
        return None

    def _step_anthropic(self) -> dict | None:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            system=self.system,
            tools=[self.tool],
            messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": resp.content})
        for block in resp.content:
            if block.type == "tool_use" and block.name == self.tool_name:
                self._last_tool_id = block.id
                return dict(block.input)
        return None


def one_tool_call(system: str, user_text: str, tool: dict, tool_name: str,
                  model: str | None = None, max_tokens: int = 8000) -> dict:
    """Single forced tool call (used by the NL->spec translator)."""
    session = ToolLoopSession(system, tool, tool_name, model=model, max_tokens=max_tokens)
    result = session.first(user_text)
    if result is None:
        result = session.nudge(f"You did not call {tool_name}. Call it now.")
    if result is None:
        raise RuntimeError(f"{tool_name}: model did not emit a tool call")
    return result
