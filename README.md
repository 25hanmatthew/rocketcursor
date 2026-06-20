# General Fluid Network

Transient fluid-network simulation tools for feed systems, tanks, pressurization systems, valves, regulators, pipes, and simple rocket-engine performance coupling.

The core solver lives in `general_fluid_network.py`. Networks can be built directly in Python or run from JSON configs with `run_network.py`.

## What This Code Does

- Models fluid nodes, ambient boundaries, two-phase tanks with ullage, and simple engine nodes.
- Models connections such as orifices, valves, throttle valves, bang-bang regulators, pipe lines, and series-connected components.
- Uses CoolProp for thermodynamic properties, with optional REFPROP support when installed.
- Runs time-marching simulations with scheduled valve/controller actions.
- Plots node and connection histories with Matplotlib.
- Provides a command-line JSON runner for automated validation, simulation, and result export.

## Repository Layout

```text
general_fluid_network.py        Core node, connection, tank, engine, network, and plotting classes
network_io.py                   JSON loader, validator, runner, and result exporter
run_network.py                  Command-line JSON simulation runner
fluid_network_mcp.py            MCP server exposing the solver as structured agent tools
network_schema.json             JSON format reference for agents and tools
network_configs/                JSON network configurations
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

Validate the tank vent example:

```powershell
python run_network.py network_configs\tank_vent_to_atmosphere.json --validate-only
```

Run it and export CSV, JSON, and PNG plots:

```powershell
python run_network.py network_configs\tank_vent_to_atmosphere.json --plots --out results\tank_vent_to_atmosphere
```

Open the plots on Windows:

```powershell
start results\tank_vent_to_atmosphere\nodes.png
start results\tank_vent_to_atmosphere\connections.png
```

Verify the project after copying or changing support files:

```powershell
python -m unittest tests.test_network_io tests.test_fluid_network_mcp
python run_network.py network_configs\tank_vent_to_atmosphere.json --validate-only
```

## Agent Usage

Agents should prefer JSON configs plus machine-readable outputs. Do not scrape plots or console text when the same data is available in `summary.json`, `diagnostics.json`, `nodes.csv`, or `connections.csv`.

For formal agent access, run the MCP server from the repository root:

```powershell
python fluid_network_mcp.py
```

It exposes these tools:

- `get_network_schema()`: return the supported JSON schema.
- `validate_network(config_path=None, config_json=None)`: validate a file config or inline JSON config.
- `run_network(config_path=None, config_json=None, output_dir=None, duration=None, dt=None, plots=False)`: run and export results.
- `read_result(output_dir, result_name)`: read known result files such as `summary.json`, `diagnostics.json`, `nodes_summary.json`, `connections_summary.json`, `nodes.csv`, or `connections.csv`.

Recommended agent workflow:

1. Read `network_schema.json` or call `get_network_schema()` before generating a new config.
2. Validate before running: `validate_network(...)` or `python run_network.py <config> --validate-only`.
3. Run into an explicit output directory so later steps have stable paths.
4. Inspect `diagnostics.json` first, then `summary.json`, then CSV files for detailed time histories.
5. Set `plots=True` or pass `--plots` only when image artifacts are needed for a human review.

For shell-based agents and debugging, use the JSON runner.

Validate a config:

```powershell
python run_network.py network_configs\tank_vent_to_atmosphere.json --validate-only
```

Run a config and export machine-readable results:

```powershell
python run_network.py network_configs\tank_vent_to_atmosphere.json --out results\tank_vent_to_atmosphere
```

Run a config and also save plots:

```powershell
python run_network.py network_configs\tank_vent_to_atmosphere.json --plots --out results\tank_vent_to_atmosphere
```

Override the JSON runtime settings:

```powershell
python run_network.py network_configs\tank_vent_to_atmosphere.json --duration 5 --dt 0.1 --out results\tank_vent_short
```

The runner writes:

- `nodes.csv`: node and engine histories.
- `connections.csv`: connection histories, including `Series` subcomponents as `series_name/component_name`.
- `nodes_summary.json`: per-node min/max/final/delta summaries for numeric fields.
- `connections_summary.json`: per-connection min/max/final/delta summaries, including `Series` subcomponents.
- `diagnostics.json`: agent-oriented checks such as step count, action window, all-zero flow, and unchanged non-ambient node states.
- `summary.json`: run metadata, component counts, final node states, diagnostics, warnings, and output paths.
- `nodes.png` and `connections.png`: generated only when `--plots` or `plots=True` is used.

The JSON format is documented in `network_schema.json`. Existing GUI-style JSON files remain supported by the loader.

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
from general_fluid_network import Node, Ambient, Connection, Network, PropsSI_auto

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
- For formal agent workflows, use `fluid_network_mcp.py`; for shell workflows, use JSON configs plus `run_network.py`.
