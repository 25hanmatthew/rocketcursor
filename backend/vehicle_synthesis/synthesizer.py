"""Synthesize a complete vehicle_model.json around a propulsion package.

Deterministic. Body diameter is driven by the package envelope (+ wall +
clearance), not chosen for looks. Fins are sized to reach a target static margin
via Barrowman. Mass/CG/inertia over time combine the package time series with the
constant structure. Emits the canonical vehicle_model.json plus procedural R3F
render hints and a vehicle_report.json. No LLM; every value carries provenance.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from backend.common.assumptions import AssumptionLedger
from backend.common.contracts import validate
from backend.common.mission_spec import load_mission_spec
from backend.vehicle_synthesis import barrowman, structures

SCHEMA_VERSION = "1.0"
COORD_FRAME = {"name": "vehicle_body", "origin": "nozzle_exit", "long_axis": "+z_toward_nose", "handedness": "right"}

TARGET_STATIC_MARGIN_CAL = 1.8
NOSE_FINENESS = 4.0          # nose length / diameter
AVIONICS_BAY_LEN_M = 0.30
AVIONICS_MASS_KG = 1.2
RADIAL_STRUCTURE_GAP_M = 0.01


def _read_cg_series(path: Path) -> list[tuple[float, float]]:
    rows = []
    with path.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            rows.append((float(row["time"]), float(row["cg_z_m"])))
    return rows


def _read_mass_series(path: Path) -> list[tuple[float, float]]:
    rows = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            rows.append((float(row["time"]), float(row["mass_kg"])))
    return rows


def synthesize_vehicle(
    package: dict, package_dir: str | Path, mission_spec: dict | str | Path, run_dir: str | Path
) -> dict[str, Any]:
    package_dir = Path(package_dir)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = AssumptionLedger("vehicle_synthesis")
    mission = load_mission_spec(mission_spec)

    # --- body diameter from package envelope ---
    min_inner = package["constraints"]["minimum_vehicle_inner_diameter_m"]
    payload = mission["payload"]
    body_inner = max(min_inner, payload.get("diameter_m", 0.0) + 0.02)
    body_diameter = round(body_inner + 2.0 * structures.BODY_WALL_M + 2.0 * RADIAL_STRUCTURE_GAP_M, 3)
    max_dia = mission.get("constraints", {}).get("maximum_diameter_m")
    if max_dia and body_diameter > max_dia:
        ledger.record("geometry.body_diameter_m", body_diameter, "packaging_rule",
                      f"package envelope needs {body_diameter} m, exceeds max_diameter {max_dia} m (fit warning)")

    # --- axial stack (nozzle-exit origin, +z toward nose) ---
    prop_top = max(c["position_m"][2] + 0.5 * c["geometry"].get("length_m", 0.0) for c in package["components"])
    payload_len = payload.get("length_m", 0.4)
    recovery_len = ledger.record("geometry.recovery_bay_length_m", round(0.6 * body_diameter + 0.3, 3),
                                 "vehicle_rule", "recovery bay length heuristic")
    nose_len = round(NOSE_FINENESS * body_diameter, 3)

    z_avionics = prop_top
    z_recovery = z_avionics + AVIONICS_BAY_LEN_M
    z_payload = z_recovery + recovery_len
    z_body_top = z_payload + payload_len
    total_length = round(z_body_top + nose_len, 3)
    body_length = round(z_body_top, 3)

    max_len = mission.get("constraints", {}).get("maximum_length_m")
    fit_warning = bool(max_len and total_length > max_len)

    # --- masses (structure) ---
    body_tube_kg = structures.body_tube_mass(body_diameter, body_length)
    nose_kg = structures.nose_mass(body_diameter, nose_len)
    bulkheads_kg = structures.bulkhead_mass(body_diameter)
    payload_kg = payload["mass_kg"]
    avionics_kg = ledger.record("mass.avionics_kg", AVIONICS_MASS_KG, "vehicle_rule", "assumed avionics bay mass")

    # --- package mass/CG time series + loaded values ---
    cg_series = _read_cg_series(package_dir / "package_cg.csv")
    mass_series = _read_mass_series(package_dir / "package_mass.csv")
    pkg_loaded_mass = mass_series[0][1]
    pkg_loaded_cg = cg_series[0][1]

    # structure lumped masses & positions (z in nozzle frame)
    struct_items = [
        ("body_tube", body_tube_kg, 0.5 * body_length),
        ("nose", nose_kg, body_length + 0.4 * nose_len),
        ("bulkheads", bulkheads_kg, 0.5 * body_length),
        ("avionics", avionics_kg, z_avionics + 0.5 * AVIONICS_BAY_LEN_M),
        ("payload", payload_kg, z_payload + 0.5 * payload_len),
    ]

    descent_mass = pkg_loaded_mass - package_propellant(package) + sum(m for _, m, _ in struct_items)
    recovery_kg = structures.parachute_mass(descent_mass)
    struct_items.append(("recovery", recovery_kg, z_recovery + 0.5 * recovery_len))

    # fins sized after we know loaded CG (depends on structure)
    struct_mass = sum(m for _, m, _ in struct_items)
    struct_moment = sum(m * z for _, m, z in struct_items)

    def loaded_cg() -> float:
        return (pkg_loaded_mass * pkg_loaded_cg + struct_moment) / (pkg_loaded_mass + struct_mass)

    fins, cp_res, margin = _size_fins(
        body_diameter, body_length, nose_len, mission, total_length, loaded_cg(), ledger
    )
    fins_kg = structures.fin_set_mass(fins["count"], fins["root_chord_m"], fins["tip_chord_m"], fins["span_m"])
    fin_z = fins["position_z_m"] + 0.5 * fins["root_chord_m"]
    struct_items.append(("fins", fins_kg, fin_z))

    # --- recompute combined mass/CG/inertia time series ---
    struct_mass = sum(m for _, m, _ in struct_items)
    struct_moment = sum(m * z for _, m, z in struct_items)
    body_radius = body_diameter / 2.0
    _write_vehicle_timeseries(run_dir, mass_series, cg_series, struct_items, struct_mass, struct_moment, body_radius, total_length)

    dry_mass = struct_mass + sum(c["dry_mass_kg"] for c in package["components"])
    loaded_mass = pkg_loaded_mass + struct_mass
    loaded_cg_z = (pkg_loaded_mass * pkg_loaded_cg + struct_moment) / loaded_mass
    cp_z = total_length - cp_res.x_cp_from_tip_m

    # --- assemble vehicle_model ---
    reference_area = 3.141592653589793 * body_radius ** 2
    vehicle = {
        "schema_version": SCHEMA_VERSION,
        "name": mission.get("name", "vehicle"),
        "coordinate_frame": COORD_FRAME,
        "propulsion_package_ref": str(package_dir / "propulsion_package.json"),
        "component_tree": _component_tree(package, fins, body_diameter, body_length, nose_len, struct_items),
        "geometry": {
            "body_diameter_m": body_diameter,
            "total_length_m": total_length,
            "reference_area_m2": round(reference_area, 5),
            "nose": {"kind": "von karman", "length_m": nose_len},
            "fins": fins,
            "render": _render_hints(package, body_diameter, body_length, nose_len, fins),
        },
        "mass_properties": {
            "dry_mass_kg": round(dry_mass, 3),
            "loaded_mass_kg": round(loaded_mass, 3),
            "loaded_cg_z_m": round(loaded_cg_z, 4),
            "time_series": {
                "total_mass": "vehicle_mass.csv",
                "center_of_mass": "vehicle_cg.csv",
                "inertia": "vehicle_inertia.csv",
            },
        },
        "aerodynamics": {
            "cp_z_m": round(cp_z, 4),
            "static_margin_cal": round(margin, 3),
            "cd_power_off": 0.55,
            "method": "barrowman_v1 + rocketpy",
        },
        "recovery": {"mode": mission.get("recovery", {}).get("mode", "parachute"),
                      "main_cd_s_m2": mission.get("recovery", {}).get("main_cd_s_m2", 1.5),
                      "mass_kg": round(recovery_kg, 3)},
        "controls": {"mode": mission.get("vehicle_mode", "passive_fin_stabilized")},
        "environment_defaults": {
            "rail_length_m": mission["launch"]["rail_length_m"],
            "elevation_deg": mission["launch"].get("elevation_deg", 90),
            "heading_deg": mission["launch"].get("heading_deg", 0),
            "altitude_m": mission["launch"].get("altitude_m", 0),
            "latitude_deg": mission["launch"].get("latitude_deg", 0),
            "longitude_deg": mission["launch"].get("longitude_deg", 0),
        },
        "assumptions": mission.get("assumptions", []) + ledger.to_list(),
        "provenance": {"body_diameter_m": "packaging_rule", "fins": "barrowman_v1",
                        "cp_z_m": "barrowman_v1", "mass_properties": "mass_model_v1"},
    }

    validate(vehicle, "vehicle_model")
    (run_dir / "vehicle_model.json").write_text(json.dumps(vehicle, indent=2), encoding="utf-8")

    report = {
        "body_diameter_m": body_diameter, "total_length_m": total_length,
        "dry_mass_kg": round(dry_mass, 3), "loaded_mass_kg": round(loaded_mass, 3),
        "static_margin_cal": round(margin, 3), "cp_z_m": round(cp_z, 4), "loaded_cg_z_m": round(loaded_cg_z, 4),
        "fit_warning": fit_warning,
        "constraints": {"max_diameter_m": max_dia, "max_length_m": max_len,
                         "max_mass_kg": mission.get("constraints", {}).get("maximum_launch_mass_kg")},
        "mass_ok": not (mission.get("constraints", {}).get("maximum_launch_mass_kg") and loaded_mass > mission["constraints"]["maximum_launch_mass_kg"]),
    }
    (run_dir / "vehicle_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return vehicle


def package_propellant(package: dict) -> float:
    return sum(c.get("initial_fluid_mass_kg", 0.0) for c in package["components"] if c["type"] == "propellant_tank")


def _size_fins(diameter, body_length, nose_len, mission, total_length, loaded_cg_z, ledger):
    """Pick a trapezoidal fin set that reaches the target static margin."""
    d = diameter
    root_chord = 1.6 * d
    tip_chord = 0.7 * d
    sweep = 0.8 * d
    te_z = 0.08  # trailing edge just above nozzle exit
    root_le_z = te_z + root_chord
    root_le_from_tip = total_length - root_le_z
    cg_from_tip = total_length - loaded_cg_z

    span = 0.8 * d
    margin = 0.0
    cp = None
    for _ in range(40):
        fins_geom = barrowman.FinGeometry(
            count=3, root_chord_m=root_chord, tip_chord_m=tip_chord, span_m=span,
            sweep_length_m=sweep, root_le_from_tip_m=root_le_from_tip, body_radius_m=d / 2.0,
        )
        cp = barrowman.center_of_pressure("von karman", nose_len, fins_geom)
        margin = barrowman.static_margin_cal(cg_from_tip, cp.x_cp_from_tip_m, d)
        if margin < TARGET_STATIC_MARGIN_CAL - 0.05:
            span += 0.05 * d
        elif margin > TARGET_STATIC_MARGIN_CAL + 0.05:
            span = max(0.4 * d, span - 0.05 * d)
        else:
            break
    ledger.record("geometry.fins.span_m", round(span, 4), "barrowman_v1",
                  f"sized for ~{TARGET_STATIC_MARGIN_CAL} cal static margin (got {margin:.2f})")
    fins = {
        "count": 3, "root_chord_m": round(root_chord, 4), "tip_chord_m": round(tip_chord, 4),
        "span_m": round(span, 4), "sweep_length_m": round(sweep, 4),
        "position_z_m": round(te_z, 4), "thickness_m": structures.FIN_THICKNESS_M,
    }
    return fins, cp, margin


def _write_vehicle_timeseries(run_dir, mass_series, cg_series, struct_items, struct_mass, struct_moment, body_radius, total_length):
    mass_rows, cg_rows, inertia_rows = [], [], []
    cg_map = dict(cg_series)
    for (t, pkg_mass), (_, pkg_cg) in zip(mass_series, cg_series):
        total = pkg_mass + struct_mass
        cg = (pkg_mass * pkg_cg + struct_moment) / total
        # transverse inertia: structure + package as lumped masses about vehicle CG
        i_trans = struct_mass and sum(m * (z - cg) ** 2 for _, m, z in struct_items)
        i_trans += pkg_mass * (pkg_cg - cg) ** 2 + pkg_mass * (total_length ** 2) / 48.0
        i_axial = 0.5 * total * body_radius ** 2
        mass_rows.append((t, round(total, 4)))
        cg_rows.append((t, round(cg, 5)))
        inertia_rows.append((t, round(i_trans, 4), round(i_trans, 4), round(i_axial, 4)))
    _write_csv(run_dir / "vehicle_mass.csv", ["time", "mass_kg"], mass_rows)
    _write_csv(run_dir / "vehicle_cg.csv", ["time", "cg_z_m"], cg_rows)
    _write_csv(run_dir / "vehicle_inertia.csv", ["time", "I11", "I22", "I33"], inertia_rows)


def _component_tree(package, fins, body_diameter, body_length, nose_len, struct_items):
    tree = [
        {"id": "nose.01", "type": "nose", "geometry": {"kind": "von karman", "length_m": nose_len, "diameter_m": body_diameter},
         "position_m": [0, 0, body_length], "provenance": {"geometry": "vehicle_rule"}},
        {"id": "body.01", "type": "body_tube", "geometry": {"diameter_m": body_diameter, "length_m": body_length},
         "position_m": [0, 0, body_length / 2.0], "provenance": {"geometry": "packaging_rule"}},
        {"id": "fins.01", "type": "fin_set", "geometry": fins, "position_m": [0, 0, fins["position_z_m"]],
         "provenance": {"geometry": "barrowman_v1"}},
        {"id": "package.01", "type": "propulsion_package", "source_package_id": "propulsion_package",
         "position_m": [0, 0, 0], "provenance": {"geometry": "propulsion_package"}},
    ]
    return tree


def _render_hints(package, body_diameter, body_length, nose_len, fins):
    """Procedural R3F primitives (no glTF). Frontend builds these directly."""
    return {
        "nose": {"kind": "von karman", "length_m": nose_len, "base_diameter_m": body_diameter, "z_base_m": body_length},
        "body": {"diameter_m": body_diameter, "length_m": body_length, "z_bottom_m": 0.0},
        "fins": {**fins, "shape": "trapezoidal"},
        "package": [
            {"id": c["id"], "type": c["type"], "diameter_m": c["geometry"].get("diameter_m"),
             "length_m": c["geometry"].get("length_m"), "z_center_m": c["position_m"][2]}
            for c in package["components"]
        ],
    }


def _write_csv(path: Path, header, rows):
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for row in rows:
            w.writerow(row)
