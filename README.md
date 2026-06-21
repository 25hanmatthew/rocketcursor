# General Fluid Network

Transient fluid-network simulation tools for feed systems, tanks, pressurization systems, valves, regulators, pipes, and simple rocket-engine performance coupling.

The core solver lives in `simulator/general_fluid_network.py`. Networks can be built directly in Python or run from JSON configs with `python -m simulator.run_network`.

## What This Code Does

- Models fluid nodes, ambient boundaries, two-phase tanks with ullage, and simple engine nodes.
- Models connections such as orifices, valves, throttle valves, bang-bang regulators, pipe lines, and series-connected components.
- Uses CoolProp for thermodynamic properties, with optional REFPROP support when installed.
- Runs time-marching simulations with scheduled valve/controller actions.
- Plots node and connection histories with Matplotlib.
- Provides a local web UI for chat-driven design runs and manual JSON uploads.
- Provides a command-line JSON runner for automated validation, simulation, and result export.

## Repository Layout

```text
simulator/general_fluid_network.py        Core node, connection, tank, engine, network, and plotting classes
simulator/network_io.py                   JSON loader, validator, runner, and result exporter
simulator/run_network.py                  Command-line JSON simulation runner
simulator/fluid_network_mcp.py            MCP server exposing the solver as structured agent tools
simulator/network_schema.json             JSON format reference for agents and tools
simulator/network_configs/                JSON network configurations
tests/                          Loader, validator, CLI, and export tests
requirements.txt                Python package pins for the solver stack
```

## Requirements

- Python 3.10+ recommended.
- CoolProp is the default property backend.
- REFPROP is optional. If installed, the code looks for it at `C:\Program Files\REFPROP` or the `RPPREFIX` environment variable.

## Setup

From this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `rocketcea` or `ctREFPROP` installation fails, install the solver dependencies you need for the configs you plan to run. Non-engine simulations require `numpy`, `scipy`, `matplotlib`, and `CoolProp`; engine configs require `rocketcea`.

## Quick Start

The main way to run this project is the local UI: start the FastAPI backend, start the Vite frontend, then open the frontend URL in your browser.

Start the backend API from the repository root:

```powershell
python -m uvicorn ui.backend.app:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, start the frontend:

```powershell
cd ui\frontend
npm install
npm run dev
```

Open the Vite URL printed by `npm run dev`, usually:

```powershell
http://localhost:5173
```

Use the UI in either mode:

- `Chat`: type a plain-English design request. Real chat runs require the LLM keys from `.env`.
- `JSON`: upload a simulator JSON file, such as `simulator\network_configs\tank_vent_to_atmosphere.json`.

## Local P&ID Run Viewer

The UI lives under `ui/` and keeps the simulator pipeline unchanged. The backend shells out to `python -m simulator.run_network`, writes manual JSON runs under `results/ui_runs/<run_id>/`, writes chat design runs under `results/ui_design_runs/<session_id>/`, and the frontend renders the latest simulated design as a generated 2D P&ID with animated flow from `nodes.csv` and `connections.csv`.

For chat-driven design, create `.env` from `.env.example` and set the required LLM API key for your selected provider. Manual JSON upload does not need an LLM key.

## Simulator CLI

Use the CLI for debugging configs or running simulations without the UI.

Validate the tank vent example:

```powershell
python -m simulator.run_network simulator\network_configs\tank_vent_to_atmosphere.json --validate-only
```

Run it and export CSV, JSON, and PNG plots:

```powershell
python -m simulator.run_network simulator\network_configs\tank_vent_to_atmosphere.json --plots --out results\tank_vent_to_atmosphere
```

Open the plots on Windows:

```powershell
start results\tank_vent_to_atmosphere\nodes.png
start results\tank_vent_to_atmosphere\connections.png
```

Verify the project after copying or changing support files:

```powershell
python -m unittest tests.test_network_io tests.test_fluid_network_mcp
python -m simulator.run_network simulator\network_configs\tank_vent_to_atmosphere.json --validate-only
```

## Agent Usage

Agents should prefer JSON configs plus machine-readable outputs. Use `report.json` as the one-file run summary before reading lower-level artifacts. Do not scrape plots or console text when the same data is available in `report.json`, `summary.json`, `diagnostics.json`, `nodes.csv`, or `connections.csv`.

For formal agent access, run the MCP server from the repository root:

```powershell
python -m simulator.fluid_network_mcp
```

It exposes these tools:

- `get_network_schema()`: return the supported JSON schema.
- `validate_network(config_path=None, config_json=None)`: validate a file config or inline JSON config.
- `run_network(config_path=None, config_json=None, output_dir=None, duration=None, dt=None, plots=False)`: run and export results.
- `read_result(output_dir, result_name)`: read known result files such as `report.json`, `report.md`, `summary.json`, `diagnostics.json`, `nodes_summary.json`, `connections_summary.json`, `nodes.csv`, or `connections.csv`.

Recommended agent workflow:

1. Read `simulator/network_schema.json` or call `get_network_schema()` before generating a new config.
2. Validate before running: `validate_network(...)` or `python -m simulator.run_network <config> --validate-only`.
3. Run into an explicit output directory so later steps have stable paths.
4. Inspect `report.json` first for status, failures, warnings, component roles, key stats, derived stats, interpretation, and artifact paths.
5. Read `diagnostics.json`, `summary.json`, or CSV files only when detailed follow-up is needed.
6. Set `plots=True` or pass `--plots` only when image artifacts are needed for a human review.

For shell-based agents and debugging, use the JSON runner.

Validate a config:

```powershell
python -m simulator.run_network simulator\network_configs\tank_vent_to_atmosphere.json --validate-only
```

Run a config and export machine-readable results:

```powershell
python -m simulator.run_network simulator\network_configs\tank_vent_to_atmosphere.json --out results\tank_vent_to_atmosphere
```

Run a config and also save plots:

```powershell
python -m simulator.run_network simulator\network_configs\tank_vent_to_atmosphere.json --plots --out results\tank_vent_to_atmosphere
```

Override the JSON runtime settings:

```powershell
python -m simulator.run_network simulator\network_configs\tank_vent_to_atmosphere.json --duration 5 --dt 0.1 --out results\tank_vent_short
```

The runner writes:

- `nodes.csv`: node and engine histories.
- `connections.csv`: connection histories, including `Series` subcomponents as `series_name/component_name`.
- `nodes_summary.json`: per-node min/max/final/delta summaries for numeric fields.
- `connections_summary.json`: per-connection min/max/final/delta summaries, including `Series` subcomponents.
- `diagnostics.json`: agent-oriented checks such as step count, action window, all-zero flow, and unchanged non-ambient node states.
- `summary.json`: run metadata, component counts, final node states, diagnostics, warnings, and output paths.
- `report.json`: canonical one-file agent report with `status`, `status_policy`, `components`, `key_stats`, `derived_stats`, `interpretation`, and `artifacts`.
- `report.md`: human-readable companion generated from the same report data, including interpretation, recommendations, status checks, and key node/connection tables with units.
- `nodes.png` and `connections.png`: generated only when `--plots` or `plots=True` is used.

`report.json` is the best starting point for agents:

- `status`: pass/fail result, hard failures, warnings, and required check results.
- `status_policy`: explains which checks determine pass/fail; warnings are reported but do not fail a run.
- `components`: node/connection inventory with kind, sample count, and heuristic roles such as `tank`, `boundary`, or `vent`.
- `key_stats`: min/max/final/delta summaries with field labels and units.
- `derived_stats`: agent-ready facts such as pressure drop, mass change, max/final flow, and whether flow stayed nonzero.
- `interpretation`: deterministic summary, outcome, important observations, and recommended next actions.
- `artifacts`: paths to the lower-level CSV, JSON, plot, and report files.

The JSON format is documented in `simulator/network_schema.json`. Existing GUI-style JSON files remain supported by the loader.

For JSON `Node` configs, prefer pressure/volume/temperature:

```json
{
  "type": "Node",
  "params": {
    "fluid": "Nitrogen",
    "P": 5000000,
    "V": 10.0,
    "T": 293.15,
    "name": "tank"
  }
}
```

The loader converts `P`, `V`, and `T` to the internal node mass using the EOS. Legacy `m`, `V`, `T` nodes are still supported.

Run the loader and CLI tests:

```powershell
python -m unittest tests.test_network_io tests.test_fluid_network_mcp
```

## Build A Network In Python

Minimal Python example:

```python
from simulator.general_fluid_network import Node, Ambient, Connection, Network, PropsSI_auto

V_liters = 10.0
rho = PropsSI_auto("D", "P", 5000000.0, "T", 293.15, "Nitrogen")
tank = Node("Nitrogen", m=rho * (V_liters / 1000.0), V=V_liters, T=293.15, name="tank")
ambient = Ambient(fluid="Air", P=101325, T=293.15, name="ambient")
orifice = Connection(CdA=1e-6, name="vent")

network = Network({
    orifice: (tank, ambient),
})

network.sim(t=10.0, dt=0.01)
network.plot_nodes_overlay([tank], units="SI")
network.plot_connections_overlay([orifice], units="SI")
```

Scheduled actions are passed as a dictionary keyed by simulation time:

```python
actions = {
    1.0: [(orifice, 0.0)],  # close at 1.0 s
    2.0: [(orifice, 1.0)],  # reopen at 2.0 s
}

network.sim(t=5.0, dt=0.01, actions=actions)
```

## Units

Use SI units unless a script explicitly converts for plotting or convenience.

- Pressure: Pa
- Temperature: K
- Mass: kg
- Mass flow: kg/s
- Energy/enthalpy flow: J/s
- `Node` volume argument `V`: liters
- `Tank` total volume argument `V_total_L`: liters
- `CdA`: m^2
- `Line` inner diameter, length, and roughness: meters

## Notes

- REFPROP is optional. If REFPROP or `ctREFPROP` is unavailable, the solver falls back to CoolProp.
- `rocketcea` is required only when instantiating `Engine` nodes.
- For formal agent workflows, use `python -m simulator.fluid_network_mcp`; for shell workflows, use JSON configs plus `python -m simulator.run_network`.
