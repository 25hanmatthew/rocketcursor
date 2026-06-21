"""Run Phase 6 validation over a completed pipeline run directory.

Loads the run's vehicle_model + propulsion_package + flight_report, applies the
deterministic design rules, and (optionally) a Monte Carlo dispersion, then
writes validation_report.json next to the other artifacts.

Independent of the nominal flight: the design rules check the design against
engineering conventions and mission constraints; the Monte Carlo re-flies under
perturbed wind/mass. Neither trusts the single nominal apogee on its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.validation.design_rules import check_design_rules
from backend.validation.monte_carlo import run_monte_carlo


def validate_run(
    run_dir: str | Path, mission: dict | str | Path, mc_trials: int = 0
) -> dict[str, Any]:
    """Validate the pipeline run under `run_dir` (expects package/ vehicle/ flight/)."""
    run_dir = Path(run_dir)
    package_dir = run_dir / "package"
    vehicle = json.loads((run_dir / "vehicle" / "vehicle_model.json").read_text())
    package = json.loads((package_dir / "propulsion_package.json").read_text())
    flight_report = json.loads((run_dir / "flight" / "flight_report.json").read_text())
    if isinstance(mission, (str, Path)):
        mission = json.loads(Path(mission).read_text())

    rules = check_design_rules(vehicle, package, flight_report, mission)

    monte_carlo = None
    if mc_trials > 0:
        monte_carlo = run_monte_carlo(vehicle, package, package_dir, trials=mc_trials)

    report = {
        "passed": rules["passed"],
        "design_rules": rules,
        "monte_carlo": monte_carlo,
        "nominal_apogee_m": flight_report.get("apogee_m"),
    }
    (run_dir / "validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
