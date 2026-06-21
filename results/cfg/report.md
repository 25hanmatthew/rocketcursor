# Run Report: cfg

Status: FAIL
Config: `/tmp/cfg.json`
Duration: 10.0 s
Time step: 0.01 s
Steps: 1000

## Interpretation

Run completed with failed status checks.

Outcome: `failed`

### Important Observations

- Restriction mass flow included zero samples; max mdot was 0 kg/s and final mdot was 0 kg/s.

### Recommended Next Actions

- Resolve failed status checks before using the run for analysis.
- Review warnings before comparing this run against requirements.

## Status Policy

Warnings fail run: `False`
Required checks: `has_node_samples`, `has_connection_samples`, `has_nonzero_flow`

## Status Checks

| Check | Result |
| --- | --- |
| has_node_samples | PASS |
| has_connection_samples | PASS |
| has_nonzero_flow | FAIL |

## Failures

- No nonzero mass-flow samples were detected. (`has_nonzero_flow`)

## Warnings

- Non-ambient node 'GasNode' has unchanged P history.
- Non-ambient node 'GasNode' has unchanged m history.
- Connection 'Restriction' has all-zero mdot history.

## Key Node Stats

| Node | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| GasNode | Node | 1000 | pressure (P, Pa): final=101325, delta=0, min=101325, max=101325<br>temperature (T, K): final=293.15, delta=0, min=293.15, max=293.15<br>mass (m, kg): final=0.00116483, delta=0, min=0.00116483, max=0.00116483<br>density (d, kg/m^3): final=1.16483, delta=0, min=1.16483, max=1.16483<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |
| Ambient | Ambient | 1000 | pressure (P, Pa): final=101325, delta=0, min=101325, max=101325<br>temperature (T, K): final=293.15, delta=0, min=293.15, max=293.15<br>mass (m, kg): final=1, delta=0, min=1, max=1<br>density (d, kg/m^3): final=1.16483, delta=0, min=1.16483, max=1.16483<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |

## Key Connection Stats

| Connection | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| Restriction | Connection | 1000 | mass flow (mdot, kg/s): final=0, delta=0, min=0, max=0<br>pressure drop (dP, Pa): final=0, delta=0, min=0, max=0<br>enthalpy flow (Hdot, J/s): final=0, delta=0, min=0, max=0<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1e-06, delta=0, min=1e-06, max=1e-06 |

## Artifacts

- `nodes_csv`: `results/cfg/nodes.csv`
- `connections_csv`: `results/cfg/connections.csv`
- `summary_json`: `results/cfg/summary.json`
- `nodes_summary_json`: `results/cfg/nodes_summary.json`
- `connections_summary_json`: `results/cfg/connections_summary.json`
- `diagnostics_json`: `results/cfg/diagnostics.json`
- `report_json`: `results/cfg/report.json`
- `report_markdown`: `results/cfg/report.md`
