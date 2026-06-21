from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCUREMENT_ROOT = REPO_ROOT / "results" / "procurement_runs"


_FLUID_LABEL = {
    "oxygen": "LOX",
    "methane": "methane",
    "nitrogen": "GN2",
    "hydrogen": "GH2",
}


def materials_from_design(design: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive a procurable bill of materials from a finished fluid-network design.

    - Every non-ambient node holding a real propellant/pressurant fluid becomes a
      TANK requirement (fluid, pressure rating with margin, volume).
    - Every connection that is a valve (type Valve, or a name containing "valve")
      becomes a VALVE requirement (fluid, flow area, pressure, oxygen-clean).
    Vents, lines, and ambient/air nodes are skipped — they aren't catalog parts.
    """
    nodes = design.get("nodes", []) or []
    connections = design.get("connections", []) or []
    by_id: dict[Any, dict] = {n.get("id"): (n.get("params") or {}) for n in nodes}
    materials: list[dict[str, Any]] = []
    seen: set[str] = set()

    def label(fluid: str) -> str:
        return _FLUID_LABEL.get((fluid or "").lower(), fluid or "fluid")

    for node in nodes:
        if node.get("type") == "Ambient":
            continue
        p = node.get("params") or {}
        fluid = p.get("fluid")
        if not fluid or str(fluid).lower() == "air":
            continue
        pressure = p.get("P")
        volume = p.get("V")
        item = f"{label(fluid)} {p.get('name', 'tank')}".strip()
        if item in seen:
            continue
        seen.add(item)
        req: dict[str, Any] = {"fluid": fluid, "compatible_with": [fluid]}
        if isinstance(pressure, (int, float)) and pressure > 0:
            req["minimum_pressure_rating_pa"] = round(float(pressure) * 1.5)
        if isinstance(volume, (int, float)) and volume > 0:
            req["minimum_volume_l"] = float(volume)
        if str(fluid).lower() == "oxygen":
            req["cryogenic_compatible"] = True
        materials.append({"item": item, "quantity": 1, "requirements": req})

    for conn in connections:
        p = conn.get("params") or {}
        name = str(p.get("name", ""))
        is_valve = conn.get("type") == "Valve" or "valve" in name.lower()
        if not is_valve:
            continue
        upstream = by_id.get(conn.get("start_id"), {})
        fluid = upstream.get("fluid") or "fluid"
        item = f"{label(fluid)} {name or 'feed valve'}".strip()
        if item in seen:
            continue
        seen.add(item)
        req = {"fluid": fluid}
        cda = p.get("CdA")
        if isinstance(cda, (int, float)) and cda > 0:
            req["minimum_cda_m2"] = float(cda)
        up_p = upstream.get("P")
        if isinstance(up_p, (int, float)) and up_p > 0:
            req["pressure_rating_pa"] = round(float(up_p))
        if str(fluid).lower() == "oxygen":
            req["oxygen_clean"] = True
        materials.append({"item": item, "quantity": 1, "requirements": req})

    return materials


def build_procurement_input(
    design_path: Path | None,
    report_path: Path | None,
    materials: list[dict[str, Any]],
    project_name: str = "Rocketcursor procurement run",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "projectName": project_name,
        "materials": materials,
    }

    if design_path is not None:
        payload["designPath"] = str(design_path)

    if report_path is not None:
        payload["reportPath"] = str(report_path)

    return payload


def run_procurement(
    design_path: str | Path | None,
    report_path: str | Path | None,
    materials: list[dict[str, Any]],
    project_name: str = "Rocketcursor procurement run",
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    output_dir = PROCUREMENT_ROOT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    input_payload = build_procurement_input(
        Path(design_path) if design_path else None,
        Path(report_path) if report_path else None,
        materials,
        project_name=project_name,
    )

    input_path = output_dir / "procurement_input.json"
    input_path.write_text(json.dumps(input_payload, indent=2), encoding="utf-8")

    command = [
        "npm",
        "run",
        "procure",
        "--",
        str(input_path),
        str(output_dir),
    ]

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT / "tools" / "procurement",
        text=True,
        capture_output=True,
        check=False,
    )

    bom_path = output_dir / "bom.json"
    summary_path = output_dir / "procurement_summary.json"
    rfq_drafts_path = output_dir / "rfq_drafts.json"

    return {
        "ok": completed.returncode == 0 and bom_path.exists(),
        "run_id": run_id,
        "output_dir": str(output_dir),
        "input_path": str(input_path),
        "bom_path": str(bom_path) if bom_path.exists() else None,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "rfq_drafts_path": str(rfq_drafts_path) if rfq_drafts_path.exists() else None,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }


def park_quotes_in_portal(output_dir: str | Path) -> dict[str, Any]:
    """Park the generated RFQ draft text into each supplier's on-site quote box
    (McMaster "Get a Quote", Swagelok quote notes) WITHOUT submitting. Nothing is
    sent — the request sits in the portal for a human to review and submit.
    (The old Poke email-send path was scrapped.)"""
    resolved = Path(output_dir).resolve()

    command = [
        "npm",
        "run",
        "park-quotes",
        "--",
        str(resolved),
    ]

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT / "tools" / "procurement",
        text=True,
        capture_output=True,
        check=False,
    )

    portal_path = resolved / "portal_quotes.json"
    gaps_path = resolved / "procurement_gaps.json"

    payload: dict[str, Any] | None = None
    if portal_path.exists():
        payload = json.loads(portal_path.read_text(encoding="utf-8"))

    return {
        "ok": completed.returncode == 0,
        "output_dir": str(resolved),
        "portal_quotes_path": str(portal_path) if portal_path.exists() else None,
        "procurement_gaps_path": str(gaps_path) if gaps_path.exists() else None,
        "result": payload,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
