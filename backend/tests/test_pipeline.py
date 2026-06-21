"""End-to-end regression for the P&ID -> flight pipeline on the kerolox fixture.

Asserts the spine holds: schema-valid artifacts at each stage, a stable vehicle
within mission constraints, and a physically sane 6DOF flight (rises to an apogee
in a sane band, ordered events). Tolerant bands, not exact values, so the test
survives small model tweaks but catches a broken stage.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "simulator" / "network_configs" / "pressure_fed_kero_lox.json"
MISSION = REPO / "shared" / "examples" / "mission_spec.pressure_fed_kero_lox.json"


@pytest.fixture(scope="module")
def manifest(tmp_path_factory):
    from backend.pipeline import run_pipeline

    design = json.loads(FIXTURE.read_text())
    run_dir = tmp_path_factory.mktemp("pipeline_run")
    return run_pipeline(design, str(MISSION), run_dir)


def test_package_stage(manifest):
    pkg = json.loads(Path(manifest["stages"]["propulsion_package"]["path"]).read_text())
    from backend.common.contracts import validate

    validate(pkg, "propulsion_package")
    assert manifest["stages"]["propulsion_package"]["converged"] is True
    assert pkg["performance"]["burn_time_s"] > 1.0
    assert pkg["performance"]["total_impulse_ns"] > 1000.0
    # every component carries provenance
    assert all(c.get("provenance") for c in pkg["components"])


def test_vehicle_stage(manifest):
    veh = json.loads(Path(manifest["stages"]["vehicle_model"]["path"]).read_text())
    from backend.common.contracts import validate

    validate(veh, "vehicle_model")
    margin = veh["aerodynamics"]["static_margin_cal"]
    assert 1.0 <= margin <= 3.0, f"unstable/over-stable: {margin} cal"
    # body diameter is driven by the package envelope, not arbitrary
    assert veh["geometry"]["body_diameter_m"] >= 0.2


def test_flight_stage(manifest):
    report = manifest["stages"]["flight"]["report"]
    events = manifest["stages"]["flight"]["events"]
    assert report["apogee_m"] > 1000.0, "rocket barely left the pad"
    assert report["stable"] is True
    # events are ordered ignition < rail < burnout < apogee < landing
    assert events["ignition"] <= events["rail_departure"] < events["burnout"] < events["apogee"] <= events["landing"]


def test_flight_csv_columns(manifest):
    csv_path = Path(manifest["stages"]["flight"]["path"])
    with csv_path.open() as fh:
        header = next(csv.reader(fh))
    for col in ("time", "position_z", "altitude", "quaternion_w", "velocity_z", "mass", "thrust"):
        assert col in header
