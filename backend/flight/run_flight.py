"""Run a 6DOF flight and emit flight.csv, flight_events.json, flight_report.json.

Primary backend: RocketPy. Samples the flight solution onto the column contract
in shared/schemas/flight_result.schema.json so the Flight Twin can replay it with
the same interpolation the Systems Twin already uses.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from backend.common.contracts import validate
from backend.flight.adapters import rocketpy_adapter

COLUMNS = [
    "time", "position_x", "position_y", "position_z",
    "latitude", "longitude", "altitude",
    "quaternion_w", "quaternion_x", "quaternion_y", "quaternion_z",
    "roll", "pitch", "yaw",
    "velocity_x", "velocity_y", "velocity_z",
    "angular_rate_x", "angular_rate_y", "angular_rate_z",
    "acceleration_x", "acceleration_y", "acceleration_z",
    "mass", "cg", "mach", "dynamic_pressure", "angle_of_attack",
    "thrust", "drag", "normal_force", "wind",
]


def _q_to_euler(w, x, y, z):
    """Quaternion (scalar-first) to roll/pitch/yaw in degrees."""
    sinr = 2 * (w * x + y * z)
    cosr = 1 - 2 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = 2 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2, sinp) if abs(sinp) >= 1 else math.asin(sinp)
    siny = 2 * (w * z + x * y)
    cosy = 1 - 2 * (y * y + z * z)
    yaw = math.atan2(siny, cosy)
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def _call(fn, t, default=0.0):
    try:
        return float(fn(t))
    except Exception:
        return default


def run_flight(
    vehicle: dict, package: dict, package_dir: str | Path, run_dir: str | Path,
    target_apogee_m: float | None = None, dt: float = 0.1,
) -> dict[str, Any]:
    package_dir = Path(package_dir)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    flight, rocket = rocketpy_adapter.fly(vehicle, package, package_dir)
    motor = rocket.motor

    t_final = float(flight.t_final)
    n = int(t_final / dt) + 1
    times = [round(i * dt, 3) for i in range(n)]

    # event times
    apogee_t = float(getattr(flight, "apogee_time", t_final))
    burnout_t = float(getattr(motor, "burn_out_time", package["performance"]["burn_time_s"]))
    rail_t = float(getattr(flight, "out_of_rail_time", 0.0))

    rows = []
    max_q = (0.0, 0.0)
    for t in times:
        e0, e1, e2, e3 = _call(flight.e0, t, 1.0), _call(flight.e1, t), _call(flight.e2, t), _call(flight.e3, t)
        roll, pitch, yaw = _q_to_euler(e0, e1, e2, e3)
        q = _call(flight.dynamic_pressure, t)
        if q > max_q[1]:
            max_q = (t, q)
        row = [
            t,
            _call(flight.x, t), _call(flight.y, t), _call(flight.z, t),
            _call(flight.latitude, t), _call(flight.longitude, t), _call(flight.altitude, t),
            e0, e1, e2, e3, roll, pitch, yaw,
            _call(flight.vx, t), _call(flight.vy, t), _call(flight.vz, t),
            _call(flight.w1, t), _call(flight.w2, t), _call(flight.w3, t),
            _call(flight.ax, t), _call(flight.ay, t), _call(flight.az, t),
            _call(rocket.total_mass, t), _call(getattr(rocket, "com_position", lambda _t: 0.0), t),
            _call(flight.mach_number, t), q, _call(flight.angle_of_attack, t),
            _call(motor.thrust, t), _call(getattr(flight, "aerodynamic_drag", lambda _t: 0.0), t),
            _call(getattr(flight, "aerodynamic_lift", lambda _t: 0.0), t),
            _call(getattr(flight, "wind_velocity_x", lambda _t: 0.0), t),
        ]
        rows.append([round(v, 6) if isinstance(v, float) else v for v in row])

    with (run_dir / "flight.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(rows)

    events = {
        "ignition": 0.0,
        "rail_departure": rail_t,
        "maximum_dynamic_pressure": round(max_q[0], 3),
        "burnout": round(burnout_t, 3),
        "apogee": round(apogee_t, 3),
        "parachute_deployment": round(apogee_t, 3),
        "landing": round(t_final, 3),
    }

    apogee_m = float(flight.apogee) - float(flight.env.elevation)
    report = {
        "apogee_m": round(apogee_m, 1),
        "max_velocity_ms": round(float(flight.speed.max), 2),
        "max_mach": round(float(getattr(flight, "max_mach_number", 0.0)), 3),
        "max_acceleration_ms2": round(float(getattr(flight, "max_acceleration", 0.0)), 2),
        "rail_departure_velocity_ms": round(float(getattr(flight, "out_of_rail_velocity", 0.0)), 2),
        "max_dynamic_pressure_pa": round(max_q[1], 1),
        "flight_time_s": round(t_final, 2),
        "apogee_vs_target_m": round(apogee_m - target_apogee_m, 1) if target_apogee_m else None,
        "stable": bool(vehicle["aerodynamics"].get("static_margin_cal", 0) > 1.0),
        "backend": "rocketpy",
    }

    result_doc = {"columns": COLUMNS, "events": events, "report": report}
    validate(result_doc, "flight_result")
    (run_dir / "flight_events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    (run_dir / "flight_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"events": events, "report": report, "flight_csv": str(run_dir / "flight.csv"), "rows": len(rows)}
