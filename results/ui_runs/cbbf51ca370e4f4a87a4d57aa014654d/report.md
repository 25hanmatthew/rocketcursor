# Run Report: config

Status: PASS
Config: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\config.json`
Duration: 20.0 s
Time step: 0.05 s
Steps: 400

## Interpretation

Run completed with warnings.

Outcome: `warning`

### Important Observations

- lox_tank_500psi pressure changed from 3.54256e+06 Pa to 3.404e+06 Pa (3.91148% drop).
- lox_tank_500psi mass changed from 19.3703 kg to 9.68828 kg.
- kerosene_tank_500psi pressure changed from 3.47533e+06 Pa to 3.46913e+06 Pa (0.178125% drop).
- kerosene_tank_500psi mass changed from 9.66599 kg to 4.16058 kg.
- gn2_to_lox_tank_regulator mass flow stayed nonzero; max mdot was 0.113224 kg/s and final mdot was 0.0710928 kg/s.
- gn2_to_kerosene_tank_regulator mass flow stayed nonzero; max mdot was 0.0566121 kg/s and final mdot was 0.0354092 kg/s.
- lox_feed_series mass flow stayed nonzero; max mdot was 1.19484 kg/s and final mdot was 0.474423 kg/s.
- lox_feed_series/lox_tank_to_engine_line mass flow stayed nonzero; max mdot was 1.19484 kg/s and final mdot was 0.474423 kg/s.
- lox_feed_series/lox_engine_injector mass flow stayed nonzero; max mdot was 1.19484 kg/s and final mdot was 0.474423 kg/s.
- kerosene_feed_series mass flow stayed nonzero; max mdot was 0.680291 kg/s and final mdot was 0.284158 kg/s.
- kerosene_feed_series/kerosene_tank_to_engine_line mass flow stayed nonzero; max mdot was 0.680291 kg/s and final mdot was 0.284158 kg/s.
- kerosene_feed_series/kerosene_engine_injector mass flow stayed nonzero; max mdot was 0.680291 kg/s and final mdot was 0.284158 kg/s.

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

- Non-ambient node 'engine_block' has unchanged m history.

## Key Node Stats

| Node | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_supply_4500psi | Node | 400 | pressure (P, Pa): final=1.87485e+07, delta=-1.21656e+07, min=1.87485e+07, max=3.09141e+07<br>temperature (T, K): final=254.827, delta=-38.0309, min=254.827, max=292.858<br>mass (m, kg): final=4.45215, delta=-1.11833, min=4.45215, max=5.57049<br>density (d, kg/m^3): final=247.342, delta=-62.1296, min=247.342, max=309.471<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |
| lox_tank_500psi | Tank | 400 | pressure (P, Pa): final=3.404e+06, delta=-138566, min=3.35998e+06, max=3.58568e+06<br>temperature (T, K): final=89.9916, delta=-0.0267495, min=89.9831, max=90.0267<br>mass (m, kg): final=9.68828, delta=-9.68198, min=9.68828, max=19.3703<br>density (d, kg/m^3): final=1149.32, delta=-0.164325, min=1149.27, max=1149.53<br>fill level (fill_level, fraction): final=0.421479, delta=-0.421085, min=0.421479, max=0.842564 |
| kerosene_tank_500psi | Tank | 400 | pressure (P, Pa): final=3.46913e+06, delta=-6190.41, min=3.39256e+06, max=3.54655e+06<br>temperature (T, K): final=293.154, delta=-0.00105561, min=293.141, max=293.167<br>mass (m, kg): final=4.16058, delta=-5.50541, min=4.16058, max=9.66599<br>density (d, kg/m^3): final=751.823, delta=-0.00355123, min=751.779, max=751.868<br>fill level (fill_level, fraction): final=0.345874, delta=-0.457668, min=0.345874, max=0.803542 |
| engine_block | Engine | 400 | pressure (P, Pa): final=2.88028e+06, delta=687394, min=2.19289e+06, max=2.99372e+06<br>temperature (T, K): final=2832.85, delta=46.2626, min=2651.64, max=3263.4<br>mass (m, kg): final=0, delta=0, min=0, max=0<br>density (d, kg/m^3): final=1.2, delta=0, min=1.2, max=1.2<br>fill level (fill_level, fraction): final=0, delta=0, min=0, max=0 |

## Key Connection Stats

| Connection | Kind | Samples | Fields |
| --- | --- | ---: | --- |
| gn2_to_lox_tank_regulator | BangBang | 400 | mass flow (mdot, kg/s): final=0.0710928, delta=-0.0421315, min=0.0710928, max=0.113224<br>pressure drop (dP, Pa): final=1.53629e+07, delta=-1.22162e+07, min=1.53629e+07, max=2.7579e+07<br>enthalpy flow (Hdot, J/s): final=15610.1, delta=-14182.7, min=15610.1, max=29792.8<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=2.04e-06, delta=0, min=2.04e-06, max=2.04e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| gn2_to_kerosene_tank_regulator | BangBang | 400 | mass flow (mdot, kg/s): final=0.0354092, delta=-0.0212029, min=0.0354092, max=0.0566121<br>pressure drop (dP, Pa): final=1.52833e+07, delta=-1.22957e+07, min=1.52833e+07, max=2.7579e+07<br>enthalpy flow (Hdot, J/s): final=7763.72, delta=-7132.7, min=7763.72, max=14896.4<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.02e-06, delta=0, min=1.02e-06, max=1.02e-06<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| lox_feed_series | Series | 400 | mass flow (mdot, kg/s): final=0.474423, delta=-0.720421, min=0.455517, max=1.19484<br>pressure drop (dP, Pa): final=528446, delta=-2.81761e+06, min=487153, max=3.34605e+06<br>enthalpy flow (Hdot, J/s): final=-62582.3, delta=95005.5, min=-157588, max=-60097.2<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.36121e-05, delta=-1.17162e-08, min=1.36115e-05, max=1.36238e-05 |
| lox_feed_series/lox_tank_to_engine_line | Line | 400 | mass flow (mdot, kg/s): final=0.474423, delta=-0.720421, min=0.455517, max=1.19484<br>pressure drop (dP, Pa): final=110163, delta=-582815, min=101534, max=692979<br>enthalpy flow (Hdot, J/s): final=-62582.3, delta=95005.5, min=-157588, max=-60097.2<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=2.98132e-05, delta=-1.237e-07, min=2.98069e-05, max=2.99369e-05<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| lox_feed_series/lox_engine_injector | Connection | 400 | mass flow (mdot, kg/s): final=0.474423, delta=-0.720421, min=0.455517, max=1.19484<br>pressure drop (dP, Pa): final=418283, delta=-2.23479e+06, min=385619, max=2.65308e+06<br>enthalpy flow (Hdot, J/s): final=-62582.3, delta=95005.5, min=-157588, max=-60097.2<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.53e-05, delta=0, min=1.53e-05, max=1.53e-05<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| kerosene_feed_series | Series | 400 | mass flow (mdot, kg/s): final=0.284158, delta=-0.396134, min=0.245581, max=0.680291<br>pressure drop (dP, Pa): final=585636, delta=-2.76042e+06, min=437570, max=3.34605e+06<br>enthalpy flow (Hdot, J/s): final=-142166, delta=198216, min=-340382, max=-122891<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=9.57571e-06, delta=-1.51871e-08, min=9.5732e-06, max=9.5909e-06 |
| kerosene_feed_series/kerosene_tank_to_engine_line | Line | 400 | mass flow (mdot, kg/s): final=0.284158, delta=-0.396134, min=0.245581, max=0.680291<br>pressure drop (dP, Pa): final=107713, delta=-499041, min=80580.4, max=606754<br>enthalpy flow (Hdot, J/s): final=-142166, delta=198216, min=-340382, max=-122891<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=2.23281e-05, delta=-1.94594e-07, min=2.22963e-05, max=2.25226e-05<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |
| kerosene_feed_series/kerosene_engine_injector | Connection | 400 | mass flow (mdot, kg/s): final=0.284158, delta=-0.396134, min=0.245581, max=0.680291<br>pressure drop (dP, Pa): final=477923, delta=-2.26138e+06, min=356989, max=2.7393e+06<br>enthalpy flow (Hdot, J/s): final=-142166, delta=198216, min=-340382, max=-122891<br>heat flow (qdot, J/s): final=0, delta=0, min=0, max=0<br>effective flow area (CdA, m^2): final=1.06e-05, delta=0, min=1.06e-05, max=1.06e-05<br>valve/component state (state, dimensionless): final=1, delta=0, min=1, max=1 |

## Artifacts

- `nodes_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\nodes.csv`
- `connections_csv`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\connections.csv`
- `summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\summary.json`
- `nodes_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\nodes_summary.json`
- `connections_summary_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\connections_summary.json`
- `diagnostics_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\diagnostics.json`
- `report_json`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\report.json`
- `report_markdown`: `C:\Users\25han\OneDrive\Documents\GitHub\rocketcursor\results\ui_runs\cbbf51ca370e4f4a87a4d57aa014654d\report.md`
