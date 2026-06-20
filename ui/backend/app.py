import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from loop.agent import run_loop
from loop.session_state import FileSessionStore, new_state
from loop.spec_writer import nl_to_spec

ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "results" / "ui_runs"
DESIGN_RUN_ROOT = ROOT / "results" / "ui_design_runs"
LOOP_RUN_ROOT = ROOT / "results" / "loop_runs"
SPECS_DIR = ROOT / "loop" / "specs"
ALLOWED_ARTIFACTS = {
    "report.json",
    "nodes.csv",
    "connections.csv",
    "nodes_summary.json",
    "connections_summary.json",
    "diagnostics.json",
    "report.md",
}
ALLOWED_DESIGN_ARTIFACTS = ALLOWED_ARTIFACTS | {"design.json", "simulation_result.json"}
DESIGN_MAX_ITERS = int(os.environ.get("UI_DESIGN_MAX_ITERS", "8"))
ATMOSPHERIC_PRESSURE_TOLERANCE_PA = 100.0


class DesignRunRequest(BaseModel):
    message: str


app = FastAPI(title="General Fluid Network UI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json_response_file(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _run_dir(run_id: str) -> Path:
    if not run_id or any(ch not in "0123456789abcdef" for ch in run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return RUN_ROOT / run_id


def _design_session_dir(session_id: str) -> Path:
    if not session_id or any(ch not in "0123456789abcdef" for ch in session_id):
        raise HTTPException(status_code=404, detail="Design run not found")
    return DESIGN_RUN_ROOT / session_id


def _safe_spec_name(name: str, session_id: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(name).lower())
    cleaned = "_".join(part for part in cleaned.split("_") if part) or "design_request"
    return f"{cleaned[:48]}_{session_id[:8]}"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(session_dir: Path, payload: dict) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "manifest.json"
    current = _read_json(path) if path.exists() else {}
    current.update(payload)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def _design_log(session_id: str, message: str) -> None:
    print(f"[ui-design-run {session_id[:8]}] {message}", flush=True)


def _load_manifest(session_id: str) -> dict:
    path = _design_session_dir(session_id) / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Design run not found")
    return _read_json(path)


def _resolve_design_spec(message: str) -> tuple[dict, str]:
    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")

    first_token = text.split()[0].removesuffix(".json")
    if text.startswith("{"):
        spec = json.loads(text)
        source = "inline_json"
    elif first_token in _available_specs():
        spec = _read_json(SPECS_DIR / f"{first_token}.json")
        source = "builtin_spec"
    else:
        spec = nl_to_spec(text)
        source = "natural_language"

    if not isinstance(spec, dict) or "name" not in spec or "checks" not in spec:
        raise ValueError("resolved spec must be a JSON object with 'name' and 'checks'")
    return spec, source


def _is_atmospheric_pressure_equality_check(check: dict) -> bool:
    component = str(check.get("component", "")).lower()
    value = check.get("value")
    try:
        pressure = float(value)
    except (TypeError, ValueError):
        return False
    return (
        check.get("type") == "component"
        and check.get("field") == "P"
        and check.get("op") == "=="
        and 90_000.0 <= pressure <= 120_000.0
        and any(token in component for token in ("ambient", "atmosphere", "atm"))
    )


def _loosen_atmospheric_pressure_checks(spec: dict) -> tuple[dict, int]:
    checks = spec.get("checks", [])
    if not isinstance(checks, list):
        return spec, 0

    next_checks = []
    changed = 0
    for check in checks:
        if not isinstance(check, dict) or not _is_atmospheric_pressure_equality_check(check):
            next_checks.append(check)
            continue

        changed += 1
        pressure = float(check["value"])
        base_id = check.get("id", "ambient_pressure")
        description = check.get("description", "Ambient pressure stays near atmospheric pressure")
        common = {
            "type": "component",
            "component": check["component"],
            "field": "P",
            "stat": check.get("stat", "final"),
        }
        next_checks.extend([
            {
                **common,
                "id": f"{base_id}_min",
                "description": f"{description} (within +/- {ATMOSPHERIC_PRESSURE_TOLERANCE_PA:g} Pa lower bound)",
                "op": ">=",
                "value": pressure - ATMOSPHERIC_PRESSURE_TOLERANCE_PA,
            },
            {
                **common,
                "id": f"{base_id}_max",
                "description": f"{description} (within +/- {ATMOSPHERIC_PRESSURE_TOLERANCE_PA:g} Pa upper bound)",
                "op": "<=",
                "value": pressure + ATMOSPHERIC_PRESSURE_TOLERANCE_PA,
            },
        ])

    if changed:
        spec = dict(spec)
        spec["checks"] = next_checks
    return spec, changed


def _available_specs() -> set[str]:
    return {path.stem for path in SPECS_DIR.glob("*.json")}


def _session_state_path(session_id: str) -> Path:
    return _design_session_dir(session_id) / "session_state.json"


def _write_error_state(session_id: str, request: str, message: str) -> None:
    _design_log(session_id, f"error: {message}")
    state = new_state(session_id, request, "local", "local")
    state["status"] = "error"
    state["stage"] = "report"
    state["error"] = message
    state["report"] = {
        "passed": False,
        "headline": message,
        "iterations_used": 0,
        "unmet_requirements": [],
        "final_design": None,
    }
    store = FileSessionStore(root=DESIGN_RUN_ROOT)
    store.write(state)


def _latest_playable(manifest: dict, state: dict) -> dict | None:
    run_root = Path(manifest.get("loop_run_root", ""))
    iterations = state.get("iterations", [])
    for item in reversed(iterations):
        iteration = item.get("iteration")
        if not isinstance(iteration, int):
            continue
        iter_dir = run_root / f"iter_{iteration:02d}"
        required = {"design.json", "nodes.csv", "connections.csv", "report.json"}
        if all((iter_dir / name).exists() for name in required):
            artifacts = sorted(name for name in ALLOWED_DESIGN_ARTIFACTS if (iter_dir / name).exists())
            return {"iteration": iteration, "artifacts": artifacts}
    return None


def _run_design_loop_background(session_id: str, message: str) -> None:
    session_dir = _design_session_dir(session_id)
    try:
        _design_log(session_id, "resolving request into a requirements spec")
        spec, source = _resolve_design_spec(message)
        spec, loosened_checks = _loosen_atmospheric_pressure_checks(spec)
        original_name = spec.get("name", "design_request")
        spec = dict(spec)
        spec["name"] = _safe_spec_name(str(original_name), session_id)
        spec_path = session_dir / "spec.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        loop_run_root = LOOP_RUN_ROOT / spec["name"]
        _design_log(session_id, f"spec ready ({source}): {spec['name']}")
        if loosened_checks:
            _design_log(session_id, f"loosened {loosened_checks} exact ambient pressure check(s)")
        _write_manifest(session_dir, {
            "status": "running",
            "source": source,
            "original_spec_name": original_name,
            "spec_name": spec["name"],
            "spec_path": str(spec_path),
            "loop_run_root": str(loop_run_root),
            "started_at": time.time(),
        })
        _design_log(session_id, f"starting local design loop; max_iters={DESIGN_MAX_ITERS}")
        run_loop(
            spec_path,
            max_iters=DESIGN_MAX_ITERS,
            store=FileSessionStore(root=DESIGN_RUN_ROOT),
            session_id=session_id,
            request=message,
        )
        _design_log(session_id, "design loop completed")
        _write_manifest(session_dir, {"status": "completed", "completed_at": time.time()})
    except Exception as exc:  # noqa: BLE001 - background jobs must report failures as state
        error = f"{type(exc).__name__}: {exc}"
        _write_error_state(session_id, message, error)
        _write_manifest(session_dir, {"status": "error", "error": error, "completed_at": time.time()})


def _write_uploaded_config(config: dict, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def _build_cli_command(
    config_path: Path,
    run_dir: Path,
    duration: Optional[float],
    dt: Optional[float],
):
    command = [
        sys.executable,
        "-m",
        "simulator.run_network",
        str(config_path),
        "--out",
        str(run_dir),
    ]
    if duration is not None:
        command.extend(["--duration", str(float(duration))])
    if dt is not None:
        command.extend(["--dt", str(float(dt))])
    return command


def run_uploaded_config(config: dict, duration: Optional[float] = None, dt: Optional[float] = None):
    run_id = uuid.uuid4().hex
    run_dir = RUN_ROOT / run_id
    config_path = _write_uploaded_config(config, run_dir)
    command = _build_cli_command(config_path, run_dir, duration, dt)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        return {
            "ok": False,
            "run_id": run_id,
            "returncode": completed.returncode,
            "message": "Simulation failed",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "config_path": str(config_path),
        }

    report_path = run_dir / "report.json"
    if not report_path.exists():
        return {
            "ok": False,
            "run_id": run_id,
            "returncode": completed.returncode,
            "message": "Simulation completed without report.json",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "config_path": str(config_path),
        }

    artifacts = sorted(name for name in ALLOWED_ARTIFACTS if (run_dir / name).exists())
    return {
        "ok": True,
        "run_id": run_id,
        "report": _json_response_file(report_path),
        "artifacts": artifacts,
        "config_path": str(config_path),
        "output_dir": str(run_dir),
    }


@app.get("/api/schema")
def get_schema():
    return _json_response_file(ROOT / "simulator" / "network_schema.json")


@app.post("/api/design-runs")
def create_design_run(request: DesignRunRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    session_id = uuid.uuid4().hex
    _design_log(session_id, "queued from UI chat")
    session_dir = _design_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(session_dir, {
        "session_id": session_id,
        "request": message,
        "status": "queued",
        "created_at": time.time(),
    })

    state = new_state(session_id, message, "pending", "pending")
    state["stage"] = "requirements"
    FileSessionStore(root=DESIGN_RUN_ROOT).write(state)

    thread = threading.Thread(
        target=_run_design_loop_background,
        args=(session_id, message),
        daemon=True,
        name=f"design-run-{session_id[:8]}",
    )
    thread.start()
    return {"ok": True, "session_id": session_id}


@app.get("/api/design-runs/{session_id}")
def get_design_run(session_id: str):
    manifest = _load_manifest(session_id)
    state_path = _session_state_path(session_id)
    if state_path.exists():
        state = _read_json(state_path)
    else:
        state = new_state(session_id, manifest.get("request", ""), "pending", "pending")
    return {
        "ok": True,
        "session_id": session_id,
        "state": state,
        "latest_playable": _latest_playable(manifest, state),
        "manifest": manifest,
    }


@app.get("/api/design-runs/{session_id}/artifact/{iteration}/{name}")
def get_design_run_artifact(session_id: str, iteration: int, name: str):
    if name not in ALLOWED_DESIGN_ARTIFACTS:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if iteration < 0:
        raise HTTPException(status_code=404, detail="Artifact not found")

    manifest = _load_manifest(session_id)
    run_root = Path(manifest.get("loop_run_root", "")).resolve()
    target_dir = (run_root / f"iter_{iteration:02d}").resolve()
    target = (target_dir / name).resolve()
    try:
        target.relative_to(target_dir)
        target_dir.relative_to(run_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc

    if not target.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if target.suffix == ".json":
        return _json_response_file(target)
    media_type = "text/csv" if target.suffix == ".csv" else "text/markdown"
    return FileResponse(target, media_type=media_type, filename=name)


@app.post("/api/runs")
async def create_run(
    file: UploadFile = File(...),
    duration: Optional[float] = Form(None),
    dt: Optional[float] = Form(None),
):
    try:
        raw = await file.read()
        config = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON upload: {exc}") from exc

    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Uploaded JSON must be an object")

    result = run_uploaded_config(config, duration=duration, dt=dt)
    if not result["ok"]:
        return JSONResponse(status_code=400, content=result)
    return result


@app.get("/api/runs/{run_id}/config")
def get_run_config(run_id: str):
    run_dir = _run_dir(run_id)
    config_path = run_dir / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Run config not found")
    return _json_response_file(config_path)


@app.get("/api/runs/{run_id}/artifact/{name}")
def get_run_artifact(run_id: str, name: str):
    if name not in ALLOWED_ARTIFACTS:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run_dir = _run_dir(run_id)
    target = (run_dir / name).resolve()
    try:
        target.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc

    if not target.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    if target.suffix == ".json":
        return _json_response_file(target)
    media_type = "text/csv" if target.suffix == ".csv" else "text/markdown"
    return FileResponse(target, media_type=media_type, filename=name)
