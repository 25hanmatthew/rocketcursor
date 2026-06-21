"""Build a propulsion_package.json from a validated P&ID design.

Pipeline: performance (solver history preferred, analytic fallback) -> component
sizing -> stack & route -> mass/CG/inertia time series -> artifacts + schema check.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from backend.common.assumptions import AssumptionLedger
from backend.common.contracts import validate
from backend.propulsion_package import engine_models, line_models, tank_models
from backend.propulsion_package.material_models import select_tank_material, MATERIALS
from backend.propulsion_package.mass_properties import MassComponent, time_series
from backend.propulsion_package.package_layout import stack_and_route
from backend.propulsion_package.propellant_estimate import (
    PropulsionEstimate,
    estimate_from_design,
)

SCHEMA_VERSION = "1.0"
COORD_FRAME = {"name": "vehicle_body", "origin": "nozzle_exit", "long_axis": "+z_toward_nose", "handedness": "right"}


def _performance(design: dict, solver_run_dir: Path | None, ledger: AssumptionLedger) -> PropulsionEstimate:
    """Prefer real engine telemetry from a solver run; else analytic estimate."""
    if solver_run_dir is not None:
        nodes_csv = Path(solver_run_dir) / "nodes.csv"
        est = _performance_from_csv(design, nodes_csv)
        if est is not None:
            return est
    est = estimate_from_design(design)
    for note in est.notes:
        ledger.record("performance.thrust_curve", "engine_estimate", "engine_estimate", note)
    return est


def _performance_from_csv(design: dict, nodes_csv: Path) -> PropulsionEstimate | None:
    """Reconstruct curves from a solver nodes.csv if it carries engine thrust."""
    if not nodes_csv.exists():
        return None
    engine = next(n for n in design["nodes"] if n["type"] == "Engine")
    ename = engine["params"].get("name", "engine")
    tanks = {n["params"].get("name"): n for n in design["nodes"] if n["type"] == "Tank"}
    thrust_curve, mdot_curve = [], []
    tank_first_last: dict[str, list[float]] = {t: [] for t in tanks}
    with nodes_csv.open() as fh:
        for row in csv.DictReader(fh):
            comp, t = row.get("component"), float(row.get("time", 0))
            if comp == ename and row.get("thrust"):
                thrust_curve.append((t, float(row["thrust"])))
                mo = float(row.get("mdot_ox") or 0)
                mf = float(row.get("mdot_fu") or 0)
                mdot_curve.append((t, mo + mf))
            elif comp in tank_first_last and row.get("m"):
                tank_first_last[comp].append(float(row["m"]))
    if not thrust_curve:
        return None
    burn = max(t for t, f in thrust_curve if f > 1.0) if any(f > 1 for _, f in thrust_curve) else thrust_curve[-1][0]
    ep = engine["params"]
    Ae = float(ep["Ae"])
    ox_name = next((t for t, n in tanks.items() if n["params"].get("fluid_liq", "").lower() in {"oxygen", "lox", "o2"}), None)
    fu_name = next((t for t in tanks if t != ox_name), None)
    ox_mass = tank_first_last[ox_name][0] if ox_name and tank_first_last[ox_name] else 0.0
    fu_mass = tank_first_last[fu_name][0] if fu_name and tank_first_last[fu_name] else 0.0
    peak = max(f for _, f in thrust_curve)
    from backend.propulsion_package.propellant_estimate import EnginePoint
    pt = EnginePoint(0, 0, 0, 0, 0, 0, peak, 0)
    return PropulsionEstimate(
        engine=pt, burn_time_s=burn, propellant_mass_kg=ox_mass + fu_mass,
        ox_mass_kg=ox_mass, fu_mass_kg=fu_mass, thrust_curve=thrust_curve,
        mdot_curve=mdot_curve, nozzle_exit_area_m2=Ae,
        reference_ambient_pressure_pa=float(ep.get("Pa", 101325.0)),
        notes=[],
    )


def build_package(design: dict, run_dir: str | Path, solver_run_dir: str | Path | None = None) -> dict[str, Any]:
    """Build, write, validate, and return a propulsion_package for `design`."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = AssumptionLedger("propulsion_package")

    perf = _performance(design, Path(solver_run_dir) if solver_run_dir else None, ledger)

    by_id = {n["id"]: n for n in design["nodes"]}
    tank_nodes = [n for n in design["nodes"] if n["type"] == "Tank"]
    engine_node = next(n for n in design["nodes"] if n["type"] == "Engine")
    gas_nodes = [n for n in design["nodes"] if n["type"] == "Node"]

    # --- size tanks at a common diameter (max natural diameter across propellant tanks) ---
    import CoolProp.CoolProp as CP

    tank_info = []
    for n in tank_nodes:
        p = n["params"]
        fluid = p.get("fluid_liq", "")
        T = float(p.get("T_liq", 293.15))
        P = float(p.get("P_ullage", 3.0e6))
        cea_fluid = {"n-dodecane": "n-Dodecane", "oxygen": "Oxygen"}.get(fluid.lower(), fluid)
        try:
            rho = float(CP.PropsSI("D", "T", T, "P", P, cea_fluid))
        except Exception:
            rho = 1000.0
        m_liq = float(p.get("m_liq", 0.0))
        is_ox = fluid.lower() in {"oxygen", "lox", "o2"}
        tank_info.append(dict(node=n, name=p.get("name"), fluid=fluid, rho=rho, P=P, T=T, m_liq=m_liq, is_ox=is_ox))

    common_dia = max(tank_models.suggest_diameter(ti["m_liq"], ti["rho"]) for ti in tank_info)
    ledger.record("constraints.tank_common_diameter_m", round(common_dia, 4), "packaging_rule",
                  "common tank diameter = max natural diameter across propellant tanks")

    components: list[dict] = []
    mass_components: list[MassComponent] = []
    tanks_for_layout = []
    feed_map: dict[str, str] = {}

    for ti in tank_info:
        mat = select_tank_material(ti["fluid"], cryogenic=ti["T"] < 200.0)
        sz = tank_models.size_tank(ti["m_liq"], ti["rho"], ti["P"], common_dia, mat)
        role = "lox" if ti["is_ox"] else "kerosene"
        cid = f"tank.{role}.01"
        components.append({
            "id": cid, "source_pid_id": ti["name"], "type": "propellant_tank",
            "geometry": {"diameter_m": round(sz.diameter_m, 4), "length_m": round(sz.length_m, 4),
                          "wall_thickness_m": round(sz.wall_thickness_m, 5), "end_cap": sz.end_cap},
            "position_m": [0, 0, 0],  # filled after layout
            "dry_mass_kg": round(sz.dry_mass_kg, 3),
            "initial_fluid_mass_kg": round(ti["m_liq"], 3),
            "material": mat.name, "pressure_rating_pa": round(2.0 * ti["P"], 1),
            "provenance": {"diameter_m": "packaging_rule", "length_m": "tank_mass_model_v1",
                            "wall_thickness_m": "tank_mass_model_v1", "dry_mass_kg": "tank_mass_model_v1",
                            "initial_fluid_mass_kg": "thermofluid_solver" if not perf.notes else "design_input"},
            "_sizing": sz, "_ti": ti, "_role": role,
        })
        tanks_for_layout.append({"id": cid, "length_m": sz.length_m, "diameter_m": sz.diameter_m, "is_ox": ti["is_ox"]})

    # oxidizer tank above fuel tank (ox is denser/heavier -> lower CG penalty handled by stacking ox high)
    tanks_for_layout.sort(key=lambda t: 0 if not t["is_ox"] else 1)  # fuel first (bottom), ox above

    # --- engine ---
    eng_sz = engine_models.size_engine(float(engine_node["params"]["At"]), float(engine_node["params"]["Ae"]), perf.engine.thrust_n)

    # --- pressurant bottle ---
    bottle_layout = None
    for g in gas_nodes:
        p = g["params"]
        gas = p.get("fluid", "Nitrogen")
        mat = MATERIALS["COPV"]
        gas_mass = _gas_mass(p)
        dia = min(common_dia, tank_models.suggest_diameter(max(gas_mass, 0.1), 50.0))
        bsz = tank_models.size_pressurant_bottle(gas_mass, gas, float(p.get("P", 2.0e7)), float(p.get("T", 293.15)), dia, mat)
        cid = "bottle.gn2.01"
        components.append({
            "id": cid, "source_pid_id": p.get("name"), "type": "pressurant_bottle",
            "geometry": {"diameter_m": round(bsz.diameter_m, 4), "length_m": round(bsz.length_m, 4),
                          "wall_thickness_m": round(bsz.wall_thickness_m, 5), "end_cap": "hemispherical"},
            "position_m": [0, 0, 0], "dry_mass_kg": round(bsz.dry_mass_kg, 3),
            "initial_fluid_mass_kg": round(gas_mass, 3), "material": mat.name,
            "pressure_rating_pa": round(2.0 * float(p.get("P", 2.0e7)), 1),
            "provenance": {"diameter_m": "packaging_rule", "dry_mass_kg": "pressure_vessel_model_v1",
                            "initial_fluid_mass_kg": "design_input"},
            "_sizing": bsz,
        })
        bottle_layout = {"id": cid, "length_m": bsz.length_m, "diameter_m": bsz.diameter_m}
        break

    # --- feed lines (one per Series connection into the engine) ---
    line_specs = []
    for conn in design["connections"]:
        if conn["end_id"] != engine_node["id"]:
            continue
        tank_node = by_id[conn["start_id"]]
        role = "lox" if tank_node["params"].get("fluid_liq", "").lower() in {"oxygen", "lox", "o2"} else "kerosene"
        line_id = f"line.{role}.01"
        inner_d = _line_inner_diameter(conn)
        line_specs.append({"line_id": line_id, "tank_cid": f"tank.{role}.01", "inner_d": inner_d, "conn": conn})
        feed_map[line_id] = f"tank.{role}.01"

    # --- layout ---
    layout = stack_and_route(eng_sz.length_m, eng_sz.chamber_diameter_m, tanks_for_layout, bottle_layout, feed_map)

    # engine component entry (after sizing/layout)
    eng_place = layout.placements["engine"]
    components.insert(0, {
        "id": "engine.01", "source_pid_id": engine_node["params"].get("name", "engine"), "type": "engine",
        "geometry": {"diameter_m": round(eng_sz.chamber_diameter_m, 4), "length_m": round(eng_sz.length_m, 4),
                      "nozzle_exit_diameter_m": round(eng_sz.nozzle_exit_diameter_m, 4)},
        "position_m": [0, 0, round(eng_place.z_center, 4)], "dry_mass_kg": round(eng_sz.dry_mass_kg, 3),
        "provenance": {"diameter_m": "engine_mass_model_v1", "length_m": "engine_mass_model_v1",
                        "nozzle_exit_diameter_m": "thermofluid_solver", "dry_mass_kg": "engine_mass_model_v1"},
    })

    # fill tank/bottle positions from layout + build mass components
    for c in components:
        if c["id"] in layout.placements:
            c["position_m"] = [0, 0, round(layout.placements[c["id"]].z_center, 4)]

    # lines now that routed lengths are known
    for ls in line_specs:
        rl = layout.routed_line_lengths_m[ls["line_id"]]
        lsz = line_models.size_line(ls["inner_d"], rl)
        tank_c = next(c for c in components if c["id"] == ls["tank_cid"])
        z = tank_c["position_m"][2] - 0.5  # mid-route
        components.append({
            "id": ls["line_id"], "source_pid_id": ls["conn"]["params"].get("name"), "type": "feed_line",
            "geometry": {"diameter_m": round(ls["inner_d"], 4), "length_m": round(rl, 4)},
            "position_m": [0, 0, round(z, 4)], "dry_mass_kg": round(lsz.dry_mass_kg, 3),
            "material": "SS304L",
            "provenance": {"diameter_m": "design_input", "length_m": "packaging_rule", "dry_mass_kg": "line_model_v1"},
        })

    # --- mass properties time series ---
    burn = perf.burn_time_s
    for c in components:
        place = layout.placements.get(c["id"])
        z = c["position_m"][2]
        r = 0.5 * c["geometry"].get("diameter_m", 0.05)
        length = c["geometry"].get("length_m", 0.1)
        loaded = float(c.get("initial_fluid_mass_kg", 0.0))
        residual = 0.0
        deplete = burn
        if c["type"] == "propellant_tank":
            role = "ox" if c["id"].endswith("lox.01") else "fu"
            residual = tank_models.RESIDUAL_FRACTION * loaded
            deplete = (perf.ox_mass_kg / max(perf.engine.mdot_ox, 1e-9)) if role == "ox" else (perf.fu_mass_kg / max(perf.engine.mdot_fu, 1e-9))
            deplete = min(deplete, burn) if deplete and deplete != float("inf") else burn
        mass_components.append(MassComponent(c["id"], c["dry_mass_kg"], z, r, length, loaded, residual, deplete))

    ts_rows = time_series(mass_components, burn)
    _write_csv(run_dir / "package_mass.csv", ["time", "mass_kg"], [(r[0], r[1]) for r in ts_rows])
    _write_csv(run_dir / "package_cg.csv", ["time", "cg_z_m"], [(r[0], r[2]) for r in ts_rows])
    _write_csv(run_dir / "package_inertia.csv", ["time", "I11", "I22", "I33"], [(r[0], r[3], r[3], r[4]) for r in ts_rows])
    _write_csv(run_dir / "thrust_curve.csv", None, perf.thrust_curve)

    total_impulse = _trapz(perf.thrust_curve)
    package = {
        "schema_version": SCHEMA_VERSION,
        "source_design_ref": str((run_dir / "design.json")),
        "coordinate_frame": COORD_FRAME,
        "components": [_strip_private(c) for c in components],
        "performance": {
            "thrust_curve": "thrust_curve.csv",
            "burn_time_s": round(burn, 3),
            "nozzle_exit_area_m2": perf.nozzle_exit_area_m2,
            "reference_ambient_pressure_pa": perf.reference_ambient_pressure_pa,
            "total_impulse_ns": round(total_impulse, 1),
            "mean_thrust_n": round(total_impulse / burn, 1) if burn > 0 else 0.0,
            "peak_thrust_n": round(max((f for _, f in perf.thrust_curve), default=0.0), 1),
        },
        "time_series": {"total_mass": "package_mass.csv", "center_of_mass": "package_cg.csv", "inertia": "package_inertia.csv"},
        "constraints": {"minimum_vehicle_inner_diameter_m": round(layout.min_inner_diameter_m, 4)},
        "assumptions": ledger.to_list(),
    }

    (run_dir / "design.json").write_text(json.dumps(design, indent=2), encoding="utf-8")
    validate(package, "propulsion_package")
    (run_dir / "propulsion_package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
    return package


def _strip_private(c: dict) -> dict:
    return {k: v for k, v in c.items() if not k.startswith("_")}


def _gas_mass(node_params: dict) -> float:
    import CoolProp.CoolProp as CP
    P = float(node_params.get("P", 2.0e7))
    T = float(node_params.get("T", 293.15))
    V = float(node_params.get("V", 0.0)) / 1000.0  # liters -> m^3
    fluid = node_params.get("fluid", "Nitrogen")
    try:
        rho = float(CP.PropsSI("D", "T", T, "P", P, fluid))
    except Exception:
        rho = P / (296.8 * T)
    return rho * V


def _line_inner_diameter(conn: dict) -> float:
    for sub in conn.get("params", {}).get("connections", []):
        if "ID" in sub.get("params", {}):
            return float(sub["params"]["ID"])
    return float(conn.get("params", {}).get("ID", 0.008))


def _trapz(curve: list[tuple[float, float]]) -> float:
    total = 0.0
    for (t0, f0), (t1, f1) in zip(curve, curve[1:]):
        total += 0.5 * (f0 + f1) * (t1 - t0)
    return total


def _write_csv(path: Path, header: list[str] | None, rows) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        if header:
            w.writerow(header)
        for row in rows:
            w.writerow([round(x, 6) if isinstance(x, float) else x for x in row])
