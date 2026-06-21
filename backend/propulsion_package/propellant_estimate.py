"""Analytic engine + feed-system performance estimate.

PRIMARY source of truth is the thermofluid solver's engine history (thrust, Isp,
mdot, Pc, MR over time). This module is the FALLBACK used when that history is
unavailable in the current environment (e.g. the rocketcea native CEA extension
will not load) — it reconstructs the same quantities from the design with simple,
defensible physics so the downstream pipeline can run end to end. Every value it
produces is tagged provenance="engine_estimate" and recorded as an assumption.

Model:
  - Densities from CoolProp at tank conditions.
  - Chamber pressure from an injector-orifice / c*-throat fixed point:
      mdot_i = CdA_i * sqrt(2 * rho_i * (P_tank - Pc))      (incompressible orifice)
      Pc     = mdot_total * c* / At                          (c*-throat relation)
  - c* from rocketcea CEA if importable, else a kerolox c*(MR) fit, scaled by eta_cstar.
  - Thrust coefficient cf from isentropic nozzle relations (gamma=1.2) with the
    design area ratio and ambient pressure, scaled by eta_cf.
  - Pressure-fed + regulated ullage => near-constant thrust over the burn; the
    curve is flat at the steady value until the first propellant is depleted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import CoolProp.CoolProp as CP

G0 = 9.80665

# Coarse ideal c* (m/s) vs mixture ratio for LOX/Kerosene (RP-1), ~handbook.
_KEROLOX_CSTAR = [(1.5, 1700.0), (2.0, 1800.0), (2.27, 1825.0), (2.5, 1815.0), (3.0, 1740.0)]


def _interp(table: list[tuple[float, float]], x: float) -> float:
    if x <= table[0][0]:
        return table[0][1]
    if x >= table[-1][0]:
        return table[-1][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def _density(fluid: str, T: float, P: float) -> float:
    """Liquid density [kg/m^3] via CoolProp, with a safe fallback table."""
    name = {"n-dodecane": "n-Dodecane", "oxygen": "Oxygen", "lox": "Oxygen"}.get(
        fluid.lower(), fluid
    )
    try:
        return float(CP.PropsSI("D", "T", T, "P", P, name))
    except Exception:
        return {"Oxygen": 1140.0, "n-Dodecane": 800.0}.get(name, 1000.0)


_CEA_CACHE: dict[tuple[str, str], object | None] = {}


def _cea_obj(ox: str, fuel: str):
    """Return a cached CEA_Obj, or None if rocketcea can't be imported here."""
    key = (ox, fuel)
    if key not in _CEA_CACHE:
        try:
            from rocketcea.cea_obj import CEA_Obj  # noqa: PLC0415

            _CEA_CACHE[key] = CEA_Obj(oxName=_cea_name(ox, "ox"), fuelName=_cea_name(fuel, "fuel"))
        except Exception:
            _CEA_CACHE[key] = None
    return _CEA_CACHE[key]


def _cstar_ideal(MR: float, Pc_pa: float, fuel: str, ox: str) -> float:
    cea = _cea_obj(ox, fuel)
    if cea is not None:
        try:
            return float(cea.get_Cstar(Pc=Pc_pa / 6894.757, MR=MR))  # CEA wants psia
        except Exception:
            pass
    return _interp(_KEROLOX_CSTAR, MR)


def _cea_name(name: str, role: str) -> str:
    table = {"lox": "LOX", "oxygen": "LOX", "kerosene": "RP-1", "rp-1": "RP-1", "n-dodecane": "RP-1"}
    return table.get(name.lower(), name)


def _cf(eps: float, Pc: float, Pa: float, gamma: float = 1.2) -> float:
    """Thrust coefficient from isentropic nozzle relations at area ratio `eps`."""
    g = gamma
    # Solve area ratio -> exit Mach (supersonic branch) by bisection.
    def area_ratio(M: float) -> float:
        return (1.0 / M) * ((2.0 / (g + 1.0)) * (1.0 + (g - 1.0) / 2.0 * M * M)) ** (
            (g + 1.0) / (2.0 * (g - 1.0))
        )

    lo, hi = 1.0001, 12.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if area_ratio(mid) < eps:
            lo = mid
        else:
            hi = mid
    Me = 0.5 * (lo + hi)
    Pe_Pc = (1.0 + (g - 1.0) / 2.0 * Me * Me) ** (-g / (g - 1.0))
    term = (2.0 * g * g / (g - 1.0)) * (2.0 / (g + 1.0)) ** ((g + 1.0) / (g - 1.0)) * (
        1.0 - Pe_Pc ** ((g - 1.0) / g)
    )
    cf_mom = math.sqrt(max(term, 0.0))
    cf_press = (Pe_Pc - Pa / Pc) * eps
    return cf_mom + cf_press


@dataclass
class EnginePoint:
    Pc_pa: float
    mdot_ox: float
    mdot_fu: float
    MR: float
    cstar: float
    cf: float
    thrust_n: float
    isp_s: float


@dataclass
class PropulsionEstimate:
    engine: EnginePoint
    burn_time_s: float
    propellant_mass_kg: float
    ox_mass_kg: float
    fu_mass_kg: float
    thrust_curve: list[tuple[float, float]]  # (t, thrust_N)
    mdot_curve: list[tuple[float, float]]    # (t, total_mdot_kg/s)
    nozzle_exit_area_m2: float
    reference_ambient_pressure_pa: float
    notes: list[str] = field(default_factory=list)


def estimate_from_design(design: dict) -> PropulsionEstimate:
    """Reconstruct engine + propellant behavior from a NetworkConfig dict."""
    nodes = {n["params"].get("name", str(n["id"])): n for n in design["nodes"]}
    by_id = {n["id"]: n for n in design["nodes"]}

    engine = next(n for n in design["nodes"] if n["type"] == "Engine")
    ep = engine["params"]
    At = float(ep["At"])
    Ae = float(ep["Ae"])
    eps = Ae / At
    Pa = float(ep.get("Pa", 101325.0))
    eta_cstar = float(ep.get("eta_cstar", 0.92))
    eta_cf = float(ep.get("eta_cf", 0.96))
    fuel = ep.get("fuel", "Kerosene")
    ox = ep.get("oxidizer", "LOX")

    # Find the two feed connections terminating at the engine; pull injector CdA + tank.
    feeds = {"ox": None, "fu": None}
    for conn in design["connections"]:
        if conn["end_id"] != engine["id"]:
            continue
        tank = by_id[conn["start_id"]]
        tp = tank["params"]
        liq = tp.get("fluid_liq", "")
        # smallest CdA orifice in the series = injector
        cda = _series_min_cda(conn)
        P_tank = float(tp.get("P_ullage", tp.get("P", 3.0e6)))
        T_liq = float(tp.get("T_liq", 293.15))
        rho = _density(liq, T_liq, P_tank)
        m_liq = float(tp.get("m_liq", 0.0))
        slot = "ox" if liq.lower() in {"oxygen", "lox", "o2"} else "fu"
        feeds[slot] = dict(cda=cda, P_tank=P_tank, rho=rho, m_liq=m_liq, tank=tp.get("name"))

    o, f = feeds["ox"], feeds["fu"]
    if o is None or f is None:
        raise ValueError("could not identify ox/fuel feeds into the engine")

    # Fixed-point on chamber pressure.
    Pc = 0.5 * min(o["P_tank"], f["P_tank"])
    for _ in range(200):
        dP_o = max(o["P_tank"] - Pc, 0.0)
        dP_f = max(f["P_tank"] - Pc, 0.0)
        mdot_o = o["cda"] * math.sqrt(2.0 * o["rho"] * dP_o)
        mdot_f = f["cda"] * math.sqrt(2.0 * f["rho"] * dP_f)
        MR = mdot_o / mdot_f if mdot_f > 0 else 0.0
        cstar = eta_cstar * _cstar_ideal(MR or 2.0, Pc, fuel, ox)
        Pc_new = (mdot_o + mdot_f) * cstar / At
        Pc = 0.6 * Pc + 0.4 * Pc_new
        if abs(Pc_new - Pc) < 1.0:
            break

    cf = eta_cf * _cf(eps, Pc, Pa)
    thrust = cf * Pc * At
    mdot_total = mdot_o + mdot_f
    isp = thrust / (mdot_total * G0) if mdot_total > 0 else 0.0

    # Burn time limited by whichever propellant depletes first.
    t_ox = o["m_liq"] / mdot_o if mdot_o > 0 else math.inf
    t_fu = f["m_liq"] / mdot_f if mdot_f > 0 else math.inf
    burn = min(t_ox, t_fu)
    prop_mass = o["m_liq"] + f["m_liq"]

    pt = EnginePoint(Pc, mdot_o, mdot_f, MR, cstar, cf, thrust, isp)
    # Flat thrust over the burn (regulated ullage), then cut off.
    curve = [(0.0, thrust), (round(burn, 3), thrust), (round(burn + 1e-3, 3), 0.0)]
    mdotc = [(0.0, mdot_total), (round(burn, 3), mdot_total), (round(burn + 1e-3, 3), 0.0)]

    return PropulsionEstimate(
        engine=pt,
        burn_time_s=burn,
        propellant_mass_kg=prop_mass,
        ox_mass_kg=o["m_liq"],
        fu_mass_kg=f["m_liq"],
        thrust_curve=curve,
        mdot_curve=mdotc,
        nozzle_exit_area_m2=Ae,
        reference_ambient_pressure_pa=Pa,
        notes=[
            "thrust/Pc/Isp reconstructed analytically (engine_estimate fallback); "
            "solver engine history was unavailable in this environment."
        ],
    )


def _series_min_cda(conn: dict) -> float:
    """Smallest CdA among a connection's sub-orifices (the injector)."""
    params = conn.get("params", {})
    subs = params.get("connections")
    cdas = []
    if subs:
        for s in subs:
            sp = s.get("params", {})
            if "CdA" in sp:
                cdas.append(float(sp["CdA"]))
    if "CdA" in params:
        cdas.append(float(params["CdA"]))
    return min(cdas) if cdas else 1e-5
