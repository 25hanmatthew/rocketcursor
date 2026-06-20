# Run Report: config

Status: PASS
Config: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\config.json`
Duration: 20.0 s
Time step: 0.05 s
Steps: 400

## Interpretation

Run completed nominally.

Outcome: `nominal`

### Important Observations

- kerosene_tank_500psi pressure changed from 3.50915e+06 Pa to 3.42278e+06 Pa (2.46133% drop).
- kerosene_tank_500psi mass changed from 9.68227 kg to 2.6087 kg.
- gn2_pressurant_regulator mass flow stayed nonzero; max mdot was 0.0566121 kg/s and final mdot was 0.0269273 kg/s.
- ullage_vent_to_atmosphere mass flow stayed nonzero; max mdot was 0.358646 kg/s and final mdot was 0.353363 kg/s.

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
| gn2_supply_4500psi | Node | 400 | pressure (P, Pa): final=1.38998e+07, delta=-1.69919e+07, min=1.38998e+07, max=3.08917e+07<br>temperature (T, K): final=234.031, delta=-58.7691, min=234.031, max=292.8<br>mass (m, kg): final=1.06642, delta=-0.480465, min=1.06642, max=1.54689<br>density (d, kg/m^3): final=213.284, delta=-96.093, min=213.284, max=309.377<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |
| kerosene_tank_500psi | Tank | 400 | pressure (P, Pa): final=3.42278e+06, delta=-86371.8, min=3.38458e+06, max=3.52292e+06<br>temperature (T, K): final=293.146, delta=-0.0147292, min=293.139, max=293.163<br>mass (m, kg): final=2.6087, delta=-7.07357, min=2.6087, max=9.68227<br>density (d, kg/m^3): final=751.797, delta=-0.0495508, min=751.775, max=751.854<br>fill level (fill_level, fraction): final=0.216872, delta=-0.588002, min=0.216872, max=0.804874 |
| ambient | Ambient | 400 | pressure (P, Pa): final=101325, delta=0, min=101325, max=101325<br>temperature (T, K): final=293.15, delta=0, min=293.15, max=293.15<br>mass (m, kg): final=1, delta=0, min=1, max=1<br>density (d, kg/m^3): final=1.20458, delta=0, min=1.20458, max=1.20458<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |

## Key Connection Stats

| Connection | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_pressurant_regulator | BangBang | 400 | mass flow (mdot, kg/s): final=0.0269273, delta=-0.0296848, min=0.0269273, max=0.0566121<br>pressure drop (dP, Pa): final=1.05109e+07, delta=-1.70682e+07, min=1.05109e+07, max=2.7579e+07<br>enthalpy flow (Hdot, J/s): final=5339.57, delta=-9556.85, min=5339.57, max=14896.4<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.02e-06, delta=0, min=1.02e-06, max=1.02e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| ullage_vent_to_atmosphere | Connection | 400 | mass flow (mdot, kg/s): final=0.353363, delta=-0.00129177, min=0.351302, max=0.358646<br>pressure drop (dP, Pa): final=3.32178e+06, delta=-24268.9, min=3.28325e+06, max=3.42159e+06<br>enthalpy flow (Hdot, J/s): final=-176816, delta=634.956, min=-179412, max=-175802<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=5e-06, delta=0, min=5e-06, max=5e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |

## Artifacts

- `nodes_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\nodes.csv`
- `connections_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\connections.csv`
- `summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\summary.json`
- `nodes_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\nodes_summary.json`
- `connections_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\connections_summary.json`
- `diagnostics_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\diagnostics.json`
- `report_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\report.json`
- `report_markdown`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\594db153013f4e6d97661a1785ec8ad3\report.md`
