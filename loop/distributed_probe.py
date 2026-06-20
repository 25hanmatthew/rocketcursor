"""Probe: send ONE SimulateRequest to a separately-running Simulator agent and
print the SimulateResult. Proves cross-process agent-to-agent resolution works.

Usage (Simulator must already be running in another process):
    .venv/bin/python -m loop.simulator_agent &           # process 1
    .venv/bin/python -m loop.distributed_probe           # process 2 (this)
"""

from __future__ import annotations

import json
import os
import sys

from uagents import Agent, Context

from loop.agent import _load_dotenv
from loop.protocol import SimulateRequest, SimulateResult
from loop.system import simulator_address

_DESIGN = {
    "settings": {"duration": 2.0, "dt": 0.05},
    "nodes": [
        {"id": 0, "type": "Node", "params": {"fluid": "Nitrogen", "P": 9.5e6, "V": 7.0, "T": 293.15, "name": "supply_tank"}},
        {"id": 1, "type": "Ambient", "params": {"fluid": "Air", "P": 101325.0, "T": 293.15, "name": "atmosphere"}},
    ],
    "connections": [
        {"type": "Connection", "start_id": 0, "end_id": 1,
         "params": {"CdA": 1e-6, "location": 0.0, "normal_state": 1, "checking": 1, "name": "vent"}},
    ],
    "actions": [],
}


def main() -> int:
    _load_dotenv()
    spec = json.load(open("loop/specs/tank_blowdown.json"))
    sim_addr = simulator_address()
    print(f"probe targeting Simulator: {sim_addr}")

    probe = Agent(name="dist-probe", seed="dist-probe-seed", port=8014,
                  endpoint=["http://127.0.0.1:8014/submit"])

    @probe.on_event("startup")
    async def _go(ctx: Context):
        req = SimulateRequest(spec_json=json.dumps(spec), design_json=json.dumps(_DESIGN), iteration=0)
        reply, status = await ctx.send_and_receive(
            sim_addr, req, response_type=SimulateResult, timeout=60)
        print("\n=========== DISTRIBUTED PROBE RESULT ===========")
        if isinstance(reply, SimulateResult):
            print("OK cross-process A2A: ", reply.summary, "| status:", reply.status, "| passed:", reply.passed)
        else:
            print("FAILED to reach Simulator across processes. status:", status)
        print("================================================")
        os._exit(0 if isinstance(reply, SimulateResult) else 1)

    probe.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
