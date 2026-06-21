from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCUREMENT_ROOT = REPO_ROOT / "results" / "procurement_runs"


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


def send_rfqs_via_poke(output_dir: str | Path) -> dict[str, Any]:
    resolved = Path(output_dir).resolve()

    command = [
        "npm",
        "run",
        "send-rfqs",
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

    sent_path = resolved / "rfq_sent.json"
    plan_path = resolved / "rfq_send_plan.json"
    gaps_path = resolved / "procurement_gaps.json"

    payload: dict[str, Any] | None = None
    for candidate in (sent_path, plan_path):
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            break

    return {
        "ok": completed.returncode == 0,
        "output_dir": str(resolved),
        "rfq_sent_path": str(sent_path) if sent_path.exists() else None,
        "rfq_send_plan_path": str(plan_path) if plan_path.exists() else None,
        "procurement_gaps_path": str(gaps_path) if gaps_path.exists() else None,
        "result": payload,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
