# Run Report: config

Status: PASS
Config: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\config.json`
Duration: 20.0 s
Time step: 0.05 s
Steps: 400

## Interpretation

Run completed nominally.

Outcome: `nominal`

### Important Observations

- kerosene_tank_500psi pressure changed from 3.54475e+06 Pa to 3.43487e+06 Pa (3.09983% drop).
- kerosene_tank_500psi mass changed from 9.69823 kg to 8.98983 kg.
- gn2_pressurant_regulator mass flow stayed nonzero; max mdot was 0.0566121 kg/s and final mdot was 0.0557258 kg/s.
- ullage_vent_to_atmosphere mass flow stayed nonzero; max mdot was 0.0359791 kg/s and final mdot was 0.0354144 kg/s.

### Recommended Next Actions

- Compare final pressure, mass, and flow against design targets.

## Status Policy

Warnings fail run: `False`
Required checks: `has_node_samples`, `has_connection_samples`, `has_nonzero_flow`

## Status Checks

| Check | Result |
| --- | --- |
| has_node_samples | PASS |
| has_connection_samples | PASS |
| has_nonzero_flow | PASS |

## Failures

None.

## Warnings

None.

## Key Node Stats

| Node | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_supply_4500psi | Node | 400 | pressure (P, Pa): final=3.04728e+07, delta=-516145, min=3.04728e+07, max=3.09889e+07<br>temperature (T, K): final=291.704, delta=-1.34897, min=291.704, max=293.053<br>mass (m, kg): final=5.53685, delta=-0.0392946, min=5.53685, max=5.57615<br>density (d, kg/m^3): final=307.603, delta=-2.18303, min=307.603, max=309.786<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |
| kerosene_tank_500psi | Tank | 400 | pressure (P, Pa): final=3.43487e+06, delta=-109881, min=3.40983e+06, max=3.54475e+06<br>temperature (T, K): final=293.148, delta=-0.0187342, min=293.144, max=293.167<br>mass (m, kg): final=8.98983, delta=-0.7084, min=8.98983, max=9.69823<br>density (d, kg/m^3): final=751.804, delta=-0.0630267, min=751.789, max=751.867<br>fill level (fill_level, fraction): final=0.747355, delta=-0.0588241, min=0.747355, max=0.806179 |
| ambient | Ambient | 400 | pressure (P, Pa): final=101325, delta=0, min=101325, max=101325<br>temperature (T, K): final=293.15, delta=0, min=293.15, max=293.15<br>mass (m, kg): final=1, delta=0, min=1, max=1<br>density (d, kg/m^3): final=1.20458, delta=0, min=1.20458, max=1.20458<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |

## Key Connection Stats

| Connection | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_pressurant_regulator | BangBang | 400 | mass flow (mdot, kg/s): final=0.0557258, delta=-0.000886376, min=0.0557258, max=0.0566121<br>pressure drop (dP, Pa): final=2.70982e+07, delta=-480790, min=2.70982e+07, max=2.7579e+07<br>enthalpy flow (Hdot, J/s): final=14569.8, delta=-326.582, min=14569.8, max=14896.4<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.02e-06, delta=0, min=1.02e-06, max=1.02e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| ullage_vent_to_atmosphere | Connection | 400 | mass flow (mdot, kg/s): final=0.0354144, delta=-5.11109e-05, min=0.0352654, max=0.0359791<br>pressure drop (dP, Pa): final=3.33644e+06, delta=-9612.87, min=3.30851e+06, max=3.44342e+06<br>enthalpy flow (Hdot, J/s): final=-17719.9, delta=25.1216, min=-17997.4, max=-17646.7<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=5e-07, delta=0, min=5e-07, max=5e-07<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |

## Artifacts

- `nodes_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\nodes.csv`
- `connections_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\connections.csv`
- `summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\summary.json`
- `nodes_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\nodes_summary.json`
- `connections_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\connections_summary.json`
- `diagnostics_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\diagnostics.json`
- `report_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\report.json`
- `report_markdown`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2a5ab8e6751a47a5ad90e86a9d985ee6\report.md`
