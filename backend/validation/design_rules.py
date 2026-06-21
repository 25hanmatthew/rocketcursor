"""Deterministic engineering design rules for a synthesized vehicle.

Each rule reads the canonical artifacts (vehicle_model, propulsion_package,
flight_report, mission_spec) and emits a finding with severity fail | warn | pass,
the measured value, the threshold, and a one-line rationale. Thresholds are
documented hobby/amateur-HPR conventions; they're advisory, not regulatory.

A "fail" means a hard requirement is violated (won't fly safely or breaches a
mission constraint). A "warn" means outside the recommended band. The verdict
`passed` is True iff there are no fails.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

G0 = 9.80665


@dataclass
class Finding:
    rule: str
    severity: str          # "fail" | "warn" | "pass"
    passed: bool           # not a fail
    actual: float | None
    threshold: str
    detail: str


def _band(rule, value, *, hard_lo=None, hard_hi=None, soft_lo=None, soft_hi=None, unit="", detail="") -> Finding:
    """Classify `value` against hard (fail) and soft (warn) bounds."""
    sev = "pass"
    if (hard_lo is not None and value < hard_lo) or (hard_hi is not None and value > hard_hi):
        sev = "fail"
    elif (soft_lo is not None and value < soft_lo) or (soft_hi is not None and value > soft_hi):
        sev = "warn"
    bounds = []
    if soft_lo is not None or hard_lo is not None:
        bounds.append(f">= {soft_lo if soft_lo is not None else hard_lo}{unit}")
    if soft_hi is not None or hard_hi is not None:
        bounds.append(f"<= {soft_hi if soft_hi is not None else hard_hi}{unit}")
    return Finding(rule, sev, sev != "fail", round(float(value), 4), " and ".join(bounds), detail)


def check_design_rules(
    vehicle: dict, package: dict, flight_report: dict, mission: dict
) -> dict:
    """Return {passed, summary, findings:[...]} for the vehicle + its flight."""
    geom = vehicle["geometry"]
    mp = vehicle["mass_properties"]
    aero = vehicle["aerodynamics"]
    perf = package["performance"]
    cons = mission.get("constraints", {})

    loaded = float(mp["loaded_mass_kg"])
    peak_thrust = float(perf.get("peak_thrust_n", 0.0))
    twr = peak_thrust / (loaded * G0) if loaded > 0 else 0.0

    findings: list[Finding] = [
        _band("static_stability", aero["static_margin_cal"],
              hard_lo=1.0, hard_hi=3.0, soft_lo=1.5, soft_hi=2.5, unit=" cal",
              detail="CP aft of CG by 1-2 cal is the stable, non-overstable band."),
        _band("liftoff_thrust_to_weight", twr,
              hard_lo=1.5, soft_lo=3.0, unit="",
              detail=f"peak thrust {peak_thrust:.0f} N / loaded weight {loaded * G0:.0f} N."),
        _band("rail_exit_velocity", float(flight_report.get("rail_departure_velocity_ms", 0.0)),
              hard_lo=10.0, soft_lo=20.0, unit=" m/s",
              detail="fins need enough airspeed leaving the rail to stabilize."),
    ]

    # mission-constraint fits (only checked when the constraint is present)
    if cons.get("maximum_diameter_m"):
        findings.append(_band("fits_max_diameter", geom["body_diameter_m"],
                              hard_hi=float(cons["maximum_diameter_m"]), unit=" m",
                              detail="body diameter within the mission envelope."))
    if cons.get("maximum_length_m"):
        findings.append(_band("fits_max_length", geom["total_length_m"],
                              hard_hi=float(cons["maximum_length_m"]), unit=" m",
                              detail="overall length within the mission envelope."))
    if cons.get("maximum_launch_mass_kg"):
        findings.append(_band("fits_max_launch_mass", loaded,
                              hard_hi=float(cons["maximum_launch_mass_kg"]), unit=" kg",
                              detail="loaded mass within the mission envelope."))

    # apogee vs target (informational warn band, never a hard fail)
    target = (mission.get("mission", {}) or {}).get("target_apogee_m")
    apogee = flight_report.get("apogee_m")
    if target and apogee is not None:
        err_pct = abs(apogee - target) / target * 100.0
        findings.append(_band("apogee_vs_target", err_pct, soft_hi=25.0, unit="%",
                              detail=f"apogee {apogee:.0f} m vs target {target:.0f} m ({apogee - target:+.0f} m)."))

    fails = sum(f.severity == "fail" for f in findings)
    warns = sum(f.severity == "warn" for f in findings)
    passes = sum(f.severity == "pass" for f in findings)
    return {
        "passed": fails == 0,
        "summary": f"{passes} pass / {warns} warn / {fails} fail",
        "findings": [asdict(f) for f in findings],
    }
