"""End-to-end P&ID -> flight pipeline runner.

Stages: validated NetworkConfig design
  -> propulsion package (physicalize + converge)
  -> vehicle synthesis
  -> 6DOF flight (RocketPy)

Produces a single run directory containing every artifact, mirroring how the
existing solver runs are laid out under results/. Used by the backend endpoint
and the regression test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.propulsion_package.convergence import converge_package
from backend.vehicle_synthesis import synthesize_vehicle
from backend.flight.run_flight import run_flight
from backend.validation.design_rules import check_design_rules


def run_pipeline(
    design: dict, mission_spec: dict | str | Path, run_dir: str | Path
) -> dict[str, Any]:
    """Run all stages into `run_dir`; return a manifest of artifacts + key results."""
    run_dir = Path(run_dir)
    package_dir = run_dir / "package"
    vehicle_dir = run_dir / "vehicle"
    flight_dir = run_dir / "flight"

    # converge_package makes package_dir self-contained (final propulsion_package.json
    # plus its thrust/mass/cg/inertia CSVs at the root), so downstream stages read it directly.
    package = converge_package(design, package_dir)
    vehicle = synthesize_vehicle(package, package_dir, mission_spec, vehicle_dir)

    target = None
    try:
        ms = mission_spec if isinstance(mission_spec, dict) else json.loads(Path(mission_spec).read_text())
        target = ms.get("mission", {}).get("target_apogee_m")
    except Exception:
        pass

    flight = run_flight(vehicle, package, package_dir, flight_dir, target_apogee_m=target)

    # Phase 6: deterministic design-rule validation (fast; no extra flights).
    mission_dict = mission_spec if isinstance(mission_spec, dict) else json.loads(Path(mission_spec).read_text())
    validation = check_design_rules(vehicle, package, flight["report"], mission_dict)

    manifest = {
        "run_dir": str(run_dir),
        "stages": {
            "propulsion_package": {
                "path": str(package_dir / "propulsion_package.json"),
                "converged": package.get("convergence", {}).get("converged"),
                "burn_time_s": package["performance"]["burn_time_s"],
                "total_impulse_ns": package["performance"]["total_impulse_ns"],
                "loaded_mass_kg": None,
            },
            "vehicle_model": {
                "path": str(vehicle_dir / "vehicle_model.json"),
                "body_diameter_m": vehicle["geometry"]["body_diameter_m"],
                "total_length_m": vehicle["geometry"]["total_length_m"],
                "static_margin_cal": vehicle["aerodynamics"]["static_margin_cal"],
                "loaded_mass_kg": vehicle["mass_properties"]["loaded_mass_kg"],
            },
            "flight": {
                "path": str(flight_dir / "flight.csv"),
                "events": flight["events"],
                "report": flight["report"],
            },
            "validation": {
                "passed": validation["passed"],
                "summary": validation["summary"],
                "findings": validation["findings"],
            },
        },
    }
    (run_dir).mkdir(parents=True, exist_ok=True)
    (run_dir / "pipeline_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
