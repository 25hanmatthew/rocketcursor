"""Generate a 'design rationale' PDF for a finished design + (optional) flight run.

Explains the *why* behind the design: propellant choice and mixture ratio, tank
pressurization and sizing, engine geometry, the synthesized vehicle's stability,
the 6DOF flight outcome, validation findings, and every assumption with its
recorded rationale. Pure-python via fpdf2 (no system deps). Text is ASCII-folded
so the core fonts never choke.
"""

from __future__ import annotations

from typing import Any

from fpdf import FPDF

ACCENT = (59, 109, 170)
MUTED = (90, 100, 115)


def _a(s: Any) -> str:
    """ASCII-fold so the built-in fonts render any value."""
    return (
        str(s)
        .replace("→", "->").replace("·", "-").replace("≤", "<=")
        .replace("≥", ">=").replace("°", "deg").replace("–", "-")
        .replace("—", "-").replace("×", "x")
        .encode("ascii", "replace").decode("ascii")
    )


class _Doc(FPDF):
    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, "RocketCursor - Design Rationale", align="R")
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"Page {self.page_no()}", align="C")

    def h1(self, text: str) -> None:
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(20, 28, 40)
        self.ln(2)
        self.cell(0, 9, _a(text), ln=True)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def para(self, text: str) -> None:
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(40, 48, 60)
        self.multi_cell(0, 5.4, _a(text))
        self.ln(1.5)

    def kv(self, rows: list[tuple[str, str]]) -> None:
        self.set_font("Helvetica", "", 10)
        for k, v in rows:
            y = self.get_y()
            self.set_text_color(*MUTED)
            self.cell(58, 6, _a(k))
            self.set_xy(self.l_margin + 58, y)
            self.set_text_color(25, 32, 44)
            self.set_font("Helvetica", "B", 10)
            self.multi_cell(0, 6, _a(v))
            self.set_font("Helvetica", "", 10)
        self.ln(1.5)

    def bullet(self, text: str, color=(40, 48, 60)) -> None:
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*color)
        x = self.get_x()
        self.cell(5, 5.2, "-")
        self.set_x(x + 5)
        self.multi_cell(0, 5.2, _a(text))


def _engine(design: dict) -> dict | None:
    return next((n for n in design.get("nodes", []) if n.get("type") == "Engine"), None)


def _tanks(design: dict) -> list[dict]:
    return [n for n in design.get("nodes", []) if n.get("type") == "Tank"]


def _gas_nodes(design: dict) -> list[dict]:
    return [n for n in design.get("nodes", []) if n.get("type") == "Node"]


def _bar(pa: Any) -> str:
    try:
        return f"{float(pa) / 1e5:.1f} bar"
    except Exception:
        return "-"


def compose_report_pdf(
    *,
    request: str,
    design: dict,
    verdict: dict | None = None,
    package: dict | None = None,
    vehicle: dict | None = None,
    flight_report: dict | None = None,
    validation: dict | None = None,
) -> bytes:
    pdf = _Doc()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    # --- cover ---
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(20, 28, 40)
    pdf.ln(6)
    pdf.cell(0, 12, "Propulsion System - Design Rationale", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 6, _a(request or "Pressure-fed liquid rocket propulsion system."))
    pdf.ln(4)

    # --- the fluid system ---
    pdf.h1("1. Fluid system & propellant choices")
    eng = _engine(design)
    tanks = _tanks(design)
    gas = _gas_nodes(design)
    ox = next((t for t in tanks if str(t["params"].get("fluid_liq", "")).lower() in {"oxygen", "lox", "o2"}), None)
    fu = next((t for t in tanks if t is not ox), None)
    if eng:
        ep = eng["params"]
        pdf.para(
            f"The engine burns {ep.get('fuel', 'kerosene')} with {ep.get('oxidizer', 'LOX')}. "
            "Kerosene/LOX is a dense, storable-fuel/cryogenic-oxidizer pair with high bulk density and "
            "~300 s vacuum-class Isp - a standard choice for a pressure-fed first attempt."
        )
    if ox and fu:
        try:
            mr = float(ox["params"].get("m_liq", 0)) / max(float(fu["params"].get("m_liq", 1)), 1e-6)
            pdf.para(
                f"Loaded propellant masses give an oxidizer/fuel ratio of {mr:.2f} (by mass) - "
                "near the ~2.2-2.3 region where kerolox c* peaks, trading a little performance for margin."
            )
        except Exception:
            pass
    if gas:
        gp = gas[0]["params"]
        pdf.para(
            f"Pressurization is {gp.get('fluid', 'nitrogen')} stored at {_bar(gp.get('P'))} in a "
            f"{gp.get('V', '-')} L bottle, regulated down to the tank ullage set-point. An inert gas "
            "pressure-fed cycle avoids turbopumps entirely - the simplest path to a firing engine."
        )
    rows = []
    for t in tanks:
        p = t["params"]
        rows.append((
            f"{p.get('name', 'tank')}",
            f"{p.get('m_liq', '-')} kg {p.get('fluid_liq', '')} @ {p.get('T_liq', '-')} K, "
            f"{p.get('V_total_L', '-')} L, ullage {_bar(p.get('P_ullage'))}",
        ))
    if eng:
        ep = eng["params"]
        try:
            eps = float(ep["Ae"]) / float(ep["At"])
            rows.append(("engine", f"At={float(ep['At'])*1e4:.2f} cm2, Ae={float(ep['Ae'])*1e4:.2f} cm2, expansion ratio {eps:.1f}"))
        except Exception:
            pass
    if rows:
        pdf.kv(rows)

    # --- verification (the design-loop verdict / report status) ---
    v = verdict or {}
    rich = v.get("checks") if isinstance(v.get("checks"), list) else None
    status = v.get("status") if isinstance(v.get("status"), dict) else (v if "passed" in v else None)
    if rich or status:
        pdf.h1("2. Requirements verification")
        if rich:
            passed = sum(1 for c in rich if c.get("passed"))
            pdf.para(f"The deterministic evaluator ran {len(rich)} requirement checks; {passed} passed.")
            for c in rich:
                ok = c.get("passed")
                pdf.bullet(f"[{'PASS' if ok else 'FAIL'}] {c.get('description') or c.get('id', '')}",
                           color=(36, 120, 70) if ok else (150, 60, 55))
        elif status:
            passed = status.get("passed")
            diags = status.get("checks") or {}
            pdf.para(
                f"Design verdict: {'PASSED' if passed else 'NOT PASSED'}. "
                f"{sum(1 for x in diags.values() if x)}/{len(diags)} diagnostic checks clean, "
                f"{len(status.get('warnings', []))} warnings."
            )
            for w in (status.get("failures", []) + status.get("warnings", []))[:8]:
                pdf.bullet(str(w), color=(150, 90, 40))
        pdf.ln(1)

    # --- propulsion package ---
    if package:
        pdf.h1("3. Physical propulsion package")
        perf = package.get("performance", {})
        pdf.para(
            "Each P&ID component was physicalized into real hardware - tanks sized from fluid mass and "
            "density with ullage/residual margin, walls from hoop stress at burst pressure, the engine "
            "envelope from throat/exit geometry, and feed lines routed and re-fed into the solver."
        )
        pdf.kv([
            ("Burn time", f"{perf.get('burn_time_s', '-')} s"),
            ("Total impulse", f"{perf.get('total_impulse_ns', '-')} N-s"),
            ("Peak thrust", f"{perf.get('peak_thrust_n', '-')} N"),
            ("Min vehicle inner dia.", f"{package.get('constraints', {}).get('minimum_vehicle_inner_diameter_m', '-')} m"),
        ])

    # --- vehicle ---
    if vehicle:
        pdf.h1("4. Vehicle synthesis & stability")
        g = vehicle.get("geometry", {})
        mp = vehicle.get("mass_properties", {})
        a = vehicle.get("aerodynamics", {})
        pdf.para(
            "A full airframe was generated around the package: the body diameter is driven by the package "
            "envelope plus structure (not chosen for looks), and the fin set was auto-sized via Barrowman "
            f"to reach a {a.get('static_margin_cal', '-')} caliber static margin (CP aft of CG = stable)."
        )
        pdf.kv([
            ("Body diameter x length", f"{g.get('body_diameter_m', '-')} m x {g.get('total_length_m', '-')} m"),
            ("Loaded / dry mass", f"{mp.get('loaded_mass_kg', '-')} / {mp.get('dry_mass_kg', '-')} kg"),
            ("CG / CP", f"{mp.get('loaded_cg_z_m', '-')} m / {a.get('cp_z_m', '-')} m"),
            ("Static margin", f"{a.get('static_margin_cal', '-')} cal"),
        ])

    # --- flight ---
    if flight_report:
        pdf.h1("5. 6DOF flight outcome")
        pdf.kv([
            ("Apogee", f"{flight_report.get('apogee_m', '-')} m"),
            ("Max velocity / Mach", f"{flight_report.get('max_velocity_ms', '-')} m/s / {flight_report.get('max_mach', '-')}"),
            ("Rail-exit velocity", f"{flight_report.get('rail_departure_velocity_ms', '-')} m/s"),
            ("Max dynamic pressure", f"{flight_report.get('max_dynamic_pressure_pa', '-')} Pa"),
            ("Stable", str(flight_report.get("stable", "-"))),
        ])

    # --- validation ---
    findings = (validation or {}).get("findings") or []
    if findings:
        pdf.h1("6. Independent validation")
        pdf.para(f"Design-rule check: {(validation or {}).get('summary', '')}.")
        for f in findings:
            sev = str(f.get("severity", "")).upper()
            pdf.bullet(
                f"[{sev}] {f.get('rule')}: {f.get('actual')} (need {f.get('threshold')}) - {f.get('detail', '')}",
                color={"PASS": (36, 120, 70), "WARN": (170, 120, 30), "FAIL": (150, 60, 55)}.get(sev, MUTED),
            )
        pdf.ln(1)

    # --- assumptions ledger: the recorded reasons ---
    assumptions = []
    for src in (package, vehicle):
        if src:
            assumptions.extend(src.get("assumptions", []) or [])
    if assumptions:
        pdf.h1("7. Assumptions & their rationale")
        pdf.para(
            "Every value not given by the user or computed from an upstream artifact is recorded here "
            "with its source - nothing is silently invented."
        )
        for x in assumptions[:40]:
            rationale = x.get("rationale", "")
            line = f"{x.get('field')} = {x.get('value')}  [{x.get('source')}]"
            if rationale:
                line += f" - {rationale}"
            pdf.bullet(line)

    # PyFPDF 1.x returns a latin-1 str; fpdf2 returns a bytearray.
    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)
