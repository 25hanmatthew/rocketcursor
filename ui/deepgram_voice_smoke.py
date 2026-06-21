"""Real smoke test of the Deepgram Voice Agent integration behind the copilot.

No mic/browser needed. Connects with the project's key and sends the SAME Settings
the frontend sends (Flux STT + gpt-4o-mini think + client functions + Aura-2 TTS),
then verifies the full path:

    Welcome -> SettingsApplied -> greeting TTS audio
            -> InjectAgentMessage (the design-narration path) -> spoken audio

A silent linear16 stream stands in for the mic so the server doesn't close early;
the "waited too long for user speech" close is treated as benign.

    pip install websockets            # already in the repo .venv
    python ui/deepgram_voice_smoke.py # run from the repo root (reads ui/frontend/.env)

Exit code 0 = PASS.
"""
import asyncio
import json
import re
import sys

import websockets

AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"


def load_key() -> str:
    for line in open("ui/frontend/.env"):
        m = re.match(r"\s*VITE_DEEPGRAM_API_KEY\s*=\s*(\S+)", line)
        if m:
            return m.group(1)
    raise SystemExit("no VITE_DEEPGRAM_API_KEY in ui/frontend/.env")


SETTINGS = {
    "type": "Settings",
    "audio": {
        "input": {"encoding": "linear16", "sample_rate": 16000},
        "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
    },
    "agent": {
        "language": "en",
        "listen": {"provider": {"type": "deepgram", "model": "flux-general-en", "version": "v2",
                                "keyterms": ["LOX", "methane", "chamber pressure", "mixture ratio"],
                                "eot_threshold": 0.8, "eot_timeout_ms": 8000}},
        "think": {"provider": {"type": "open_ai", "model": "gpt-4o-mini", "temperature": 0.5},
                  "prompt": "You are Nova, a terse rocket propulsion intake assistant.",
                  "functions": [
                      {"name": "start_design_run", "description": "Launch the design loop.",
                       "parameters": {"type": "object",
                                      "properties": {"requirements_summary": {"type": "string"}},
                                      "required": ["requirements_summary"]}},
                      {"name": "check_design_status", "description": "Report run status.",
                       "parameters": {"type": "object", "properties": {}, "required": []}},
                  ]},
        "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
        "greeting": "Smoke test online.",
    },
}


async def main() -> None:
    key = load_key()
    seen = {"Welcome": False, "SettingsApplied": False, "audio_bytes": 0, "audio_frames": 0,
            "injected": False, "post_inject_audio": 0, "error": None}
    try:
        async with websockets.connect(AGENT_URL, additional_headers={"Authorization": f"Token {key}"},
                                      max_size=None) as ws:
            injected = False
            silence = bytes(3200)  # 100ms of linear16 @ 16kHz — stands in for a silent mic

            async def feed_silence():
                try:
                    while True:
                        await ws.send(silence)
                        await asyncio.sleep(0.1)
                except Exception:
                    pass

            async def stopper():
                await asyncio.sleep(20)
                await ws.close()

            asyncio.create_task(stopper())
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    seen["audio_frames"] += 1
                    seen["audio_bytes"] += len(msg)
                    if injected:
                        seen["post_inject_audio"] += len(msg)
                    continue
                data = json.loads(msg)
                t = data.get("type")
                if t == "Welcome":
                    seen["Welcome"] = True
                    await ws.send(json.dumps(SETTINGS))
                elif t == "SettingsApplied":
                    seen["SettingsApplied"] = True
                    asyncio.create_task(feed_silence())
                elif t == "AgentAudioDone" and not injected:
                    injected = True
                    seen["injected"] = True
                    await ws.send(json.dumps({"type": "InjectAgentMessage",
                                              "message": "Iteration one: nine of ten checks passed. Revising thrust.",
                                              "behavior": "queue"}))
                elif t == "Error":
                    seen["error"] = data.get("description") or data.get("message") or str(data)
                    break
    except Exception as e:  # noqa: BLE001
        seen["error"] = seen["error"] or f"{type(e).__name__}: {e}"

    benign = bool(seen["error"]) and "waited too long" in seen["error"]
    print(json.dumps(seen, indent=2))
    ok = (seen["Welcome"] and seen["SettingsApplied"] and seen["audio_bytes"] > 0
          and seen["post_inject_audio"] > 0 and (not seen["error"] or benign))
    print("\nSMOKE:", "PASS" if ok else "FAIL", "(benign no-mic close ignored)" if benign else "")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
