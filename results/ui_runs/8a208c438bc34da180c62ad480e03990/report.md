# Run Report: config

Status: PASS
Config: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\config.json`
Duration: 20.0 s
Time step: 0.05 s
Steps: 400

## Interpretation

Run completed nominally.

Outcome: `nominal`

### Important Observations

- pressurized_tank pressure changed from 9.54877e+06 Pa to 4.68112e+06 Pa (50.9767% drop).
- pressurized_tank mass changed from 0.769045 kg to 0.485336 kg.
- vent_orifice mass flow stayed nonzero; max mdot was 0.0190953 kg/s and final mdot was 0.0105192 kg/s.

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
| pressurized_tank | Node | 400 | pressure (P, Pa): final=4.68112e+06, delta=-4.86764e+06, min=4.68112e+06, max=9.54877e+06<br>temperature (T, K): final=237.11, delta=-55.8673, min=237.11, max=292.977<br>mass (m, kg): final=0.485336, delta=-0.283709, min=0.485336, max=0.769045<br>density (d, kg/m^3): final=69.3337, delta=-40.5299, min=69.3337, max=109.864<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |
| atmosphere | Ambient | 400 | pressure (P, Pa): final=101325, delta=0, min=101325, max=101325<br>temperature (T, K): final=293.15, delta=0, min=293.15, max=293.15<br>mass (m, kg): final=1, delta=0, min=1, max=1<br>density (d, kg/m^3): final=1.20458, delta=0, min=1.20458, max=1.20458<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |

## Key Connection Stats

| Connection | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| vent_orifice | Connection | 400 | mass flow (mdot, kg/s): final=0.0105192, delta=-0.00857607, min=0.0105192, max=0.0190953<br>pressure drop (dP, Pa): final=4.58742e+06, delta=-4.87904e+06, min=4.58742e+06, max=9.46647e+06<br>enthalpy flow (Hdot, J/s): final=2416.88, delta=-3015.18, min=2416.88, max=5432.06<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1e-06, delta=0, min=1e-06, max=1e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |

## Artifacts

- `nodes_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\nodes.csv`
- `connections_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\connections.csv`
- `summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\summary.json`
- `nodes_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\nodes_summary.json`
- `connections_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\connections_summary.json`
- `diagnostics_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\diagnostics.json`
- `report_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\report.json`
- `report_markdown`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\8a208c438bc34da180c62ad480e03990\report.md`
