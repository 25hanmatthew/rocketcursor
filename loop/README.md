# Design Loop (P2)

The design → simulate → evaluate → revise loop. Claude designs a fluid-network
JSON for a requirements spec; the simulator runs it; a **pure-Python evaluator**
produces a pass/fail verdict; the verdict is fed back to Claude to revise.

> Design principle: **Python produces the verdict, not Claude.** Claude designs
> and revises; deterministic code decides pass/fail. The solver's diagnostics
> only say the sim *ran cleanly* — the evaluator is what says the design *meets
> requirements*.

```
requirements (specs/*.json)
      |
      v
Claude designs design.json            agent.py
      |
      v
simulator_adapter.run_design(design)  simulator_adapter.py  (validate/run/export/classify)
      |
      v
simulation_result.json
      |
      v
evaluator.evaluate(spec, result)      evaluator.py          (PURE PYTHON)
      |
      v
verdict  --> Claude revises --> repeat
```

## Files

| File | Role |
|---|---|
| `specs/*.json` | Requirements specs: machine-checkable `checks` + design guidance for the agent |
| `simulator_adapter.py` | Wraps `network_io`; returns one structured result, classifying `invalid_config` / `crashed` / `ok` |
| `evaluator.py` | Deterministic requirements → verdict. **No LLM.** The heart of P2 |
| `agent.py` | Orchestrates the loop: Claude (design) → adapter → evaluator → revise |
| `selftest.py` | Offline check of adapter + evaluator (no API key) |

## Run the deterministic half (no API key)

```bash
.venv/bin/python -m loop.selftest
```

Shows the evaluator discriminating under-vent (fail) / good (pass) / over-vent (fail).

## Run the full loop (needs an API key)

Keys are read from a gitignored `.env` at the repo root (see `.env.example`):
`ANTHROPIC_API_KEY`, optional `TTC_API_KEY` (the-token-company compression),
optional `ASI1_API_KEY` (Fetch.ai). `agent.py` auto-loads `.env`.

```bash
.venv/bin/python -m loop.agent loop/specs/tank_blowdown.json --max-iters 4
# route Anthropic calls through the-token-company prompt compression:
.venv/bin/python -m loop.agent loop/specs/tank_blowdown.json --compress
```

Per-iteration outputs land in `results/loop_runs/<spec-name>/iter_NN/`
(`design.json`, `simulation_result.json`, plus the solver's CSV/summary files);
a `loop_trace.json` summarizing every iteration is written at the run root.

## LLM provider (ASI1 by default)

The loop's reasoning runs on **ASI1** (Fetch.ai's agentic LLM, OpenAI-compatible)
by default, or Anthropic. Select via env: `LLM_PROVIDER=asi1` (default, uses
`ASI1_API_KEY`, model `asi1`) or `LLM_PROVIDER=anthropic` (uses `ANTHROPIC_API_KEY`,
model `claude-opus-4-8`); `LLM_MODEL` overrides the model. See `loop/llm.py`. The
deterministic verdict (`loop/evaluator.py`) never depends on the provider.

## Run as Fetch.ai agents

### Multi-agent system (`system.py`) — recommended

A **Designer** agent (LLM reasoning + Chat Protocol, user-facing) and a
**Simulator** agent (deterministic `run_design` + `evaluate`, no LLM) collaborate
over uAgents messaging: the Designer designs on ASI1, sends each candidate to the
Simulator via `SimulateRequest`, gets back a deterministic `SimulateResult`, and
revises until it passes — genuine agent-to-agent orchestration.

```bash
# one process, Bureau hosts both agents (simplest local demo / test):
.venv/bin/python -m loop.system                  # (== --role both)
AGENT_MAILBOX=1 .venv/bin/python -m loop.system  # each registers its own Agentverse profile
.venv/bin/python -m loop.system_roundtrip_test   # local end-to-end A2A test (single process)

# TRUE distributed: each agent its own process. The Designer finds the Simulator by
# its seed-derived address (or set SIM_AGENT_ADDRESS). Start them in two terminals:
.venv/bin/python -m loop.system --role simulator     # process 1
.venv/bin/python -m loop.system --role designer      # process 2 (targets process 1)
# verify cross-process messaging without a Designer:
.venv/bin/python -m loop.simulator_agent &           # then:
.venv/bin/python -m loop.distributed_probe           # sends one SimulateRequest across processes
```

### Single agent (`service.py`) — simpler fallback

```bash
.venv/bin/python -m loop.service --selftest          # offline check, no API/network
.venv/bin/python -m loop.service                      # local
AGENT_MAILBOX=1 .venv/bin/python -m loop.service      # expose on Agentverse
.venv/bin/python -m loop.chat_roundtrip_test --ping   # protocol-only round-trip, no API
```

A chat message is a **spec name** (e.g. `lox_methane_engine`), a full **inline spec
JSON**, or **plain English** (translated via `spec_writer.py`).

Env knobs: `AGENT_SEED` / `SIM_AGENT_SEED` (set your own stable identities),
`AGENT_PORT` / `SIM_AGENT_PORT`, `AGENT_MAILBOX`, `AGENT_MAX_ITERS` (8),
`SIM_TIMEOUT` (180 s). To connect a local agent's mailbox: run it, open the printed
inspector link, then **Connect → Mailbox → Finish** on agentverse.ai. On-chain
Almanac registration is optional (needs testnet funds); the Almanac **API**
registration that powers Agentverse discovery is automatic.

## Failure classifier (revise vs scrap-and-restart)

On each failed iteration the loop runs a **deterministic** classifier
(`loop/classifier.py`) that decides whether to **revise** the current design or
**scrap** it and start a fresh design line (with a note telling the model which
approaches already failed, so it explores elsewhere):

- repeated solver crashes → **scrap**; a single crash → **revise**
- invalid config → **revise** (structural fix from the error)
- ran but **stalled** (no improvement in passing-check count for 2 iterations) → **scrap**
- ran and **making progress** → **revise**

Scrap only fires while restarts remain (`max_restarts`, default 2), else it falls
back to revise so the iteration budget is still spent. The decision (action +
reason) is recorded per iteration in the trace and the session state, so the UI can
show "revised" vs "started over". Wired into both `run_loop` (single-agent) and the
distributed loop (`system.py`).

## Session state — the Redis / UI integration surface

Every run emits a structured **session state** that maps directly onto the PRD's UI
screens. It's written through a pluggable store (`loop/session_state.py`):

- **Default (no setup):** `FileSessionStore` →
  `results/loop_runs/_sessions/<session_id>/session_state.json`.
- **Redis (set `REDIS_URL`):** `RedisSessionStore`. Writes are best-effort — a
  Redis outage logs once and never crashes the loop.

Both the single-agent (`service.py` → `run_loop`) and multi-agent (`system.py`)
paths emit the same shape, so the UI reads one contract regardless of topology.

### Redis key schema (stable contract for orchestration / Person 4)

| Key | Value |
|---|---|
| `rocketcursor:session:{id}` | full state JSON — **the UI polls this every ~2s** |
| `rocketcursor:sessions` | set of all session ids |
| `rocketcursor:session:{id}:events` | pub/sub channel, one message per update |

### State shape (maps to UI screens)

```jsonc
{
  "session_id", "request", "provider", "model",
  "status": "running|passed|failed|error",
  "stage":  "requirements|design|simulate|evaluate|report",
  "requirements": {            // -> requirements-review screen + checklist
    "name", "description", "design_guidance",
    "checks": [{"id","description","target","op","value"}]
  },
  "current_iteration": 1,
  "iterations": [{             // -> live design view, updated each iteration
    "iteration", "status",
    "design":      {...},      //    React Flow nodes/edges source
    "node_status": {"supply_tank":"green","vent":"red"},  // color coding
    "components":  {...},      //    sidebar per-component values
    "verdict": {"passed","summary","checks":[{"id","passed","op","expected","actual"}]}
  }],
  "passed", "iterations_used",
  "report": {"passed","headline","unmet_requirements":[...],"final_design":{...}}
}
```

`node_status`: `green` ok · `red` a failed check references it · `yellow` a solver
warning references it.

## Requirements spec format

```jsonc
{
  "name": "...",
  "description": "...",            // context shown to the designer agent
  "design_guidance": { ... },      // optional hints (required component names, etc.)
  "checks": [
    {"id": "ran",   "type": "status", "op": "==", "value": "ok"},
    {"id": "flow",  "type": "sim",    "field": "has_nonzero_flow", "op": "==", "value": true},
    {"id": "drop",  "type": "component", "component": "supply_tank",
                    "field": "P", "stat": "delta", "op": "<", "value": -500000.0},
    {"id": "clean", "type": "no_warnings", "op": "==", "value": true}
  ]
}
```

`stat` (component checks) is one of the per-field statistics the solver records:
`first, final, min, max, delta, range, nonzero_count, sample_count`.
Operators: `>`, `>=`, `<`, `<=`, `==`, `!=`.
