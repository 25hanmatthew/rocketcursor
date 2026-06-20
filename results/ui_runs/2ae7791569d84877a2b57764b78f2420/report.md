# Run Report: config

Status: PASS
Config: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\config.json`
Duration: 20.0 s
Time step: 0.05 s
Steps: 400

## Interpretation

Run completed with warnings.

Outcome: `warning`

### Important Observations

- kerosene_tank_500psi pressure changed from 3.18963e+06 Pa to -9.99999e+06 Pa (413.515% drop).
- kerosene_tank_500psi mass changed from 9.52267 kg to 1e-12 kg.
- gn2_pressurant_regulator mass flow stayed nonzero; max mdot was 0.0566121 kg/s and final mdot was 0.0287566 kg/s.
- ullage_vent_to_atmosphere mass flow stayed nonzero; max mdot was 3.54655 kg/s and final mdot was 2.19892 kg/s.

### Recommended Next Actions

- Compare final pressure, mass, and flow against design targets.
- Review warnings before comparing this run against requirements.

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

- Node 'kerosene_tank_500psi' has nonphysical P values.
- Node 'kerosene_tank_500psi' has nonphysical T values.
- Node 'kerosene_tank_500psi' has nonphysical d values.

## Key Node Stats

| Node | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_supply_4500psi | Node | 400 | pressure (P, Pa): final=1.49497e+07, delta=-1.60018e+07, min=1.49497e+07, max=3.09515e+07<br>temperature (T, K): final=238.973, delta=-53.9828, min=238.973, max=292.955<br>mass (m, kg): final=1.9919, delta=-0.794757, min=1.9919, max=2.78666<br>density (d, kg/m^3): final=221.322, delta=-88.3063, min=221.322, max=309.629<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |
| kerosene_tank_500psi | Tank | 400 | pressure (P, Pa): final=-9.99999e+06, delta=-1.31896e+07, min=-9.99999e+06, max=3.18963e+06<br>temperature (T, K): final=-9.99999e+06, delta=-1.00003e+07, min=-9.99999e+06, max=293.106<br>mass (m, kg): final=1e-12, delta=-9.52267, min=1e-12, max=9.52267<br>density (d, kg/m^3): final=-9.99999e+06, delta=-1.00007e+07, min=-9.99999e+06, max=751.663<br>fill level (fill_level, fraction): final=-6.25001e-18, delta=-0.791801, min=-6.25001e-18, max=0.791801 |
| ambient | Ambient | 400 | pressure (P, Pa): final=101325, delta=0, min=101325, max=101325<br>temperature (T, K): final=293.15, delta=0, min=293.15, max=293.15<br>mass (m, kg): final=1, delta=0, min=1, max=1<br>density (d, kg/m^3): final=1.20458, delta=0, min=1.20458, max=1.20458<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |

## Key Connection Stats

| Connection | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_pressurant_regulator | BangBang | 400 | mass flow (mdot, kg/s): final=0.0287566, delta=-0.0278555, min=0.0287566, max=0.0566121<br>pressure drop (dP, Pa): final=2.49711e+07, delta=-2.60794e+06, min=2.46229e+07, max=3.59576e+07<br>enthalpy flow (Hdot, J/s): final=5840.03, delta=-9056.39, min=5840.03, max=14896.4<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.02e-06, delta=0, min=1.02e-06, max=1.02e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| ullage_vent_to_atmosphere | Connection | 400 | mass flow (mdot, kg/s): final=2.19892, delta=-1.34763, min=2.19892, max=3.54655<br>pressure drop (dP, Pa): final=1.28833e+06, delta=-2.05772e+06, min=1.28833e+06, max=3.34605e+06<br>enthalpy flow (Hdot, J/s): final=-1.10623e+06, delta=668270, min=-1.7745e+06, max=-1.10623e+06<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=5e-05, delta=0, min=5e-05, max=5e-05<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |

## Artifacts

- `nodes_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\nodes.csv`
- `connections_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\connections.csv`
- `summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\summary.json`
- `nodes_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\nodes_summary.json`
- `connections_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\connections_summary.json`
- `diagnostics_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\diagnostics.json`
- `report_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\report.json`
- `report_markdown`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\2ae7791569d84877a2b57764b78f2420\report.md`
