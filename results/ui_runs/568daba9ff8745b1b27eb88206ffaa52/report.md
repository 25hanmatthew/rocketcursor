# Run Report: config

Status: PASS
Config: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\config.json`
Duration: 20.0 s
Time step: 0.05 s
Steps: 400

## Interpretation

Run completed with warnings.

Outcome: `warning`

### Important Observations

- kerosene_tank_500psi pressure changed from 3.54104e+06 Pa to 3.4467e+06 Pa (2.66421% drop).
- gn2_pressurant_regulator mass flow stayed nonzero; max mdot was 0.0566121 kg/s and final mdot was 0.054804 kg/s.
- ullage_vent_to_atmosphere mass flow stayed nonzero; max mdot was 0.0038712 kg/s and final mdot was 0.00383031 kg/s.

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

- Non-ambient node 'kerosene_tank_500psi' has unchanged m history.

## Key Node Stats

| Node | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_supply_4500psi | Node | 400 | pressure (P, Pa): final=2.99364e+07, delta=-1.05252e+06, min=2.99364e+07, max=3.09889e+07<br>temperature (T, K): final=290.283, delta=-2.7696, min=290.283, max=293.053<br>mass (m, kg): final=5.49543, delta=-0.0807185, min=5.49543, max=5.57615<br>density (d, kg/m^3): final=305.302, delta=-4.48436, min=305.302, max=309.786<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |
| kerosene_tank_500psi | Tank | 400 | pressure (P, Pa): final=3.4467e+06, delta=-94340.7, min=3.40599e+06, max=3.54104e+06<br>temperature (T, K): final=293.15, delta=-0.0160841, min=293.143, max=293.166<br>mass (m, kg): final=9.7, delta=0, min=9.7, max=9.7<br>density (d, kg/m^3): final=751.81, delta=-0.0541113, min=751.787, max=751.865<br>fill level (fill_level, fraction): final=0.806387, delta=5.80352e-05, min=0.806329, max=0.806412 |
| ambient | Ambient | 400 | pressure (P, Pa): final=101325, delta=0, min=101325, max=101325<br>temperature (T, K): final=293.15, delta=0, min=293.15, max=293.15<br>mass (m, kg): final=1, delta=0, min=1, max=1<br>density (d, kg/m^3): final=1.20458, delta=0, min=1.20458, max=1.20458<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |

## Key Connection Stats

| Connection | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_pressurant_regulator | BangBang | 400 | mass flow (mdot, kg/s): final=0.054804, delta=-0.00180814, min=0.054804, max=0.0566121<br>pressure drop (dP, Pa): final=2.65632e+07, delta=-1.01583e+06, min=2.65632e+07, max=2.7579e+07<br>enthalpy flow (Hdot, J/s): final=14232.7, delta=-663.682, min=14232.7, max=14896.4<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.02e-06, delta=0, min=1.02e-06, max=1.02e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| ullage_vent_to_atmosphere | Connection | 400 | mass flow (mdot, kg/s): final=0.00383031, delta=7.57827e-05, min=0.0037233, max=0.0038712<br>pressure drop (dP, Pa): final=3.35266e+06, delta=6607.24, min=3.30467e+06, max=3.43971e+06<br>enthalpy flow (Hdot, J/s): final=1071.14, delta=-42.2612, min=1056.29, max=1145.72<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=5e-07, delta=0, min=5e-07, max=5e-07<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |

## Artifacts

- `nodes_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\nodes.csv`
- `connections_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\connections.csv`
- `summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\summary.json`
- `nodes_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\nodes_summary.json`
- `connections_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\connections_summary.json`
- `diagnostics_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\diagnostics.json`
- `report_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\report.json`
- `report_markdown`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\568daba9ff8745b1b27eb88206ffaa52\report.md`
