<div align="center">

<img src="rocketcursor_logo.png" alt="RocketCursor" width="96" />

# RocketCursor

**From a one-line prompt to a 6-DOF flight.**

Design a pressure-fed liquid-rocket propulsion system in natural language, prove it out in a transient thermofluid simulation, physicalize it into a complete flight vehicle, and fly it — all in the browser.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/UI-React%20+%20R3F-61DAFB?logo=react&logoColor=white)
![Three.js](https://img.shields.io/badge/3D-three.js-000000?logo=threedotjs&logoColor=white)
![RocketPy](https://img.shields.io/badge/Flight-RocketPy-FF6B00)

</div>

---

## Overview

RocketCursor turns a natural-language propulsion request into a fully simulated rocket. A deterministic **design loop** proposes a piping-and-instrumentation diagram (P&ID); a **transient solver** proves out the fluid system; and a **physics pipeline** sizes the hardware, synthesizes a vehicle, and flies it in six degrees of freedom. Everything is surfaced through three interactive 3-D twins, a one-click design-rationale report, and automated supplier quoting.

A guiding principle runs through the stack: **the LLM proposes, deterministic code decides.** Every engineering number is computed by a solver or a documented model, validated against a versioned JSON-Schema contract, and carries provenance — nothing is silently invented.

## The pipeline

```text
  Prompt
    │  natural-language request
    ▼
  Requirements  ─────────────────────────────► deterministic checks
    │
    ▼
  P&ID design ◄──────────────┐  LLM proposes, evaluator decides
    │                        │
    ▼                        │ revise
  Thermofluid simulation ────┘  tanks · valves · regulators · lines · engine (CEA)
    │
    ▼
  Propulsion package  ⇄  packaging convergence   sizes tanks/engine/lines, re-routes,
    │                                            re-solves until consistent
    ▼
  Vehicle synthesis        airframe · nose · auto-sized fins · Barrowman stability
    │
    ▼
  6-DOF flight (RocketPy)   ignition → rail → max-Q → burnout → apogee → landing
    │
    ▼
  Validation               design rules + Monte-Carlo dispersion
    │
    ├──────────────► Systems Twin   (internal plumbing + live telemetry)
    ├──────────────► Vehicle Studio (the generated rocket, CG/CP/stability)
    ├──────────────► Flight Twin    (the 6-DOF trajectory)
    ├──────────────► Design report  (PDF: every choice + its rationale)
    └──────────────► Procurement    (automated supplier RFQs)
```

## Highlights

- **Prompt → P&ID design loop** — an LLM drafts the fluid system; a deterministic evaluator runs requirement checks and drives revisions until the design passes.
- **Transient thermofluid solver** — two-phase tanks with ullage, orifices, valves, regulators, bang-bang controllers, pipe lines, and CEA-coupled engine performance, on a CoolProp/REFPROP property backend.
- **Propulsion physicalization + convergence** — turns logical components into sized hardware (tank walls from hoop stress, engine envelope from throat/exit geometry, routed feed lines) and re-solves until plumbing and performance agree.
- **Vehicle synthesis** — generates the full airframe around the propulsion package; body diameter is driven by the package envelope, and fins are auto-sized to a target static margin via the Barrowman method.
- **6-DOF flight** — a RocketPy trajectory with time-varying mass, CG and inertia from the propellant burn.
- **Independent validation** — engineering design rules (stability, thrust-to-weight, rail-exit velocity, constraint fits) plus a Monte-Carlo wind/mass dispersion.
- **Three 3-D twins** — Systems, Vehicle and Flight views built with React Three Fiber, sharing one timeline.
- **Design-rationale PDF** — a one-click report embedding the P&ID schematic and explaining every propellant, pressure and sizing choice, with the assumption ledger behind each.
- **Automated procurement** — derives a bill of materials and stages supplier RFQs (McMaster-Carr) via a Browserbase/Stagehand agent.

## Architecture

| Layer | Path | Responsibility |
|---|---|---|
| Thermofluid solver | `simulator/` | Transient fluid-network simulation, JSON I/O, CLI, and an MCP server. The source of truth for thermofluids. |
| Design loop | `loop/` | The propose→simulate→evaluate→revise loop, spec writer, and deterministic evaluator. |
| Flight pipeline | `backend/` | `propulsion_package/` → `vehicle_synthesis/` → `flight/` → `validation/`, chained by `pipeline.py`. |
| Contracts | `shared/schemas/` | Versioned JSON Schemas: `mission_spec`, `propulsion_package`, `vehicle_model`, `flight_result`, plus `provenance` / `assumption`. |
| Web API | `ui/backend/` | FastAPI app: design runs, the Build-&-Fly endpoint, procurement, and the report PDF. |
| Web app | `ui/frontend/` | React + React Three Fiber UI: the P&ID canvas and the three twins. |
| Procurement | `tools/procurement/` | Browserbase/Stagehand supplier-quote automation. |
| Tests | `tests/`, `backend/tests/` | Unit and end-to-end pipeline tests. |

Coordinate frame across the pipeline: origin at the nozzle exit, **+Z toward the nose**, SI units throughout.

## Quick start

### Prerequisites

- Python **3.10+** and Node **18+**
- The solver stack (`numpy`, `scipy`, `CoolProp`, `matplotlib`); `rocketpy` for flight; `rocketcea` only for the real CEA engine path. REFPROP is optional and falls back to CoolProp.

### Install

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt

cd ui/frontend && npm install && cd ../..
```

### Run

```bash
# 1) backend (from the repo root)
python -m uvicorn ui.backend.app:app --reload --host 127.0.0.1 --port 8000

# 2) frontend (second terminal)
cd ui/frontend && npm run dev
```

Open the printed Vite URL — usually **http://localhost:5173**.

### Try it without an API key

The UI has three input modes: **Chat** (natural-language design — needs an LLM key), **JSON** (paste a `NetworkConfig` to visualize it instantly), and **Voice**.

A pre-baked design is served from cache for one exact prompt, so you can drive the whole pipeline offline:

> Design a simple pressure fed fluid system with a rocket engine block that uses kerosene and lox as the propellants and nitrogen as the pressurant gas.

Submit it → **Build & Fly** runs physicalization → vehicle → 6-DOF flight → validation, then jumps to the Flight Twin. To make the procurement button work offline too, start the backend with `RC_PROCUREMENT_DEMO=1` (it replays a cached supplier RFQ instead of driving Browserbase).

For full chat-driven design, copy `.env.example` to `.env` and set your LLM provider key.

## Configuration

Create `.env` at the repository root from `.env.example`. The frontend reads the same file, but only `VITE_`-prefixed variables are exposed to browser code. Manual JSON visualization needs no keys.

## Beyond the UI

<details>
<summary><b>Simulator CLI</b> — run a P&ID without the browser</summary>

```bash
# validate only
python -m simulator.run_network simulator/network_configs/tank_vent_to_atmosphere.json --validate-only

# run and export CSV/JSON (+ PNG plots with --plots)
python -m simulator.run_network simulator/network_configs/tank_vent_to_atmosphere.json --plots --out results/tank_vent

# override runtime settings
python -m simulator.run_network <config> --duration 5 --dt 0.1 --out results/short
```

Each run writes `report.json` (the canonical one-file summary), plus `nodes.csv`, `connections.csv`, `summary.json`, `diagnostics.json`, and optional plots. `report.json` carries `status`, component roles, `key_stats` (with units), `derived_stats`, a deterministic `interpretation`, and artifact paths.
</details>

<details>
<summary><b>Agent / MCP access</b></summary>

```bash
python -m simulator.fluid_network_mcp
```

Exposes `get_network_schema()`, `validate_network(...)`, `run_network(...)`, and `read_result(...)`. Recommended flow: read the schema → validate → run into an explicit output dir → inspect `report.json` first, lower-level artifacts only if needed. The format is documented in `simulator/network_schema.json`.
</details>

<details>
<summary><b>Build a network in Python</b></summary>

```python
from simulator.general_fluid_network import Node, Ambient, Connection, Network, PropsSI_auto

rho = PropsSI_auto("D", "P", 5_000_000.0, "T", 293.15, "Nitrogen")
tank = Node("Nitrogen", m=rho * (10.0 / 1000.0), V=10.0, T=293.15, name="tank")
ambient = Ambient(fluid="Air", P=101325, T=293.15, name="ambient")
orifice = Connection(CdA=1e-6, name="vent")

network = Network({orifice: (tank, ambient)})
network.sim(t=10.0, dt=0.01)                       # actions={1.0: [(orifice, 0.0)]} to schedule a close
network.plot_nodes_overlay([tank], units="SI")
```
</details>

<details>
<summary><b>Run the pipeline programmatically</b></summary>

```python
import json
from backend.pipeline import run_pipeline

design = json.load(open("simulator/network_configs/pressure_fed_kero_lox.json"))
manifest = run_pipeline(design, "shared/examples/mission_spec.pressure_fed_kero_lox.json", "results/my_run")
print(manifest["stages"]["flight"]["report"]["apogee_m"])
```
</details>

## Tests

```bash
python -m unittest discover -s tests           # solver, loop, UI backend, pipeline suites
python -m pytest backend/tests/test_pipeline.py   # end-to-end P&ID → flight regression
```

## Units

SI throughout, unless a value is explicitly converted for display.

| Quantity | Unit | | Quantity | Unit |
|---|---|---|---|---|
| Pressure | Pa | | `Node.V`, `Tank.V_total_L` | liters |
| Temperature | K | | `CdA` | m² |
| Mass / mass flow | kg / kg·s⁻¹ | | `Line` ID, length, roughness | m |
| Enthalpy flow | J·s⁻¹ | | Coordinate frame | nozzle-exit origin, +Z to nose |

## Notes

- **REFPROP** is optional; without it the solver uses CoolProp.
- **`rocketcea`** is required only to instantiate `Engine` nodes. Where the CEA extension can't load, the propulsion package falls back to an analytic engine estimate (tagged in the assumption ledger) and prefers real solver history wherever CEA is available.
- Generated run artifacts live under `results/` and are git-ignored; cached demo fixtures are kept in-tree so the offline demo works on a fresh clone.
