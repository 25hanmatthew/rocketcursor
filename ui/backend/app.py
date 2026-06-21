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

from loop.agent import _load_dotenv, run_loop
from loop.monitoring import capture as sentry_capture
from loop.monitoring import init_sentry
from loop.procurement import run_procurement, send_rfqs_via_poke
from loop.session_state import FileSessionStore, new_state
from loop.spec_writer import drop_atmospheric_pressure_component_checks, nl_to_spec, revise_spec

# Initialize Sentry BEFORE the FastAPI app is created so it auto-instruments
# every route + middleware. Guarded: no-op without SENTRY_DSN.
_load_dotenv()
init_sentry(component="ui-backend")

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


class DesignRunRequest(BaseModel):
    message: str


class DesignRunRevisionRequest(BaseModel):
    message: str
    iteration: Optional[int] = None


class ProcurementRunRequest(BaseModel):
    iteration: int
    materials: list[dict]
    project_name: str = "Rocketcursor procurement run"


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


def _design_run_state(session_id: str, manifest: dict) -> dict:
    state_path = _session_state_path(session_id)
    if state_path.exists():
        return _read_json(state_path)
    return new_state(session_id, manifest.get("request", ""), "pending", "pending")


def _spec_path_from_manifest(session_id: str, manifest: dict) -> Path:
    spec_path = Path(manifest.get("spec_path", "")).resolve()
    session_dir = _design_session_dir(session_id).resolve()
    try:
        spec_path.relative_to(session_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Parent spec not found") from exc
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Parent spec not found")
    return spec_path


def _iteration_artifact_dir(manifest: dict, iteration: int) -> Path:
    if iteration < 0:
        raise HTTPException(status_code=404, detail="Design iteration not found")
    run_root = Path(manifest.get("loop_run_root", "")).resolve()
    try:
        run_root.relative_to(LOOP_RUN_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Design run artifacts not found") from exc
    target_dir = (run_root / f"iter_{iteration:02d}").resolve()
    try:
        target_dir.relative_to(run_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Design iteration not found") from exc
    return target_dir


def _playable_iteration(manifest: dict, state: dict, iteration: Optional[int]) -> dict:
    if iteration is None:
        playable = _latest_playable(manifest, state)
        if not playable:
            raise HTTPException(status_code=409, detail="Parent design has no playable iteration")
        return playable

    target_dir = _iteration_artifact_dir(manifest, iteration)
    required = {"design.json", "nodes.csv", "connections.csv", "report.json"}
    if not all((target_dir / name).exists() for name in required):
        raise HTTPException(status_code=404, detail="Design iteration not found")
    artifacts = sorted(name for name in ALLOWED_DESIGN_ARTIFACTS if (target_dir / name).exists())
    return {"iteration": iteration, "artifacts": artifacts}


def _revision_inputs(parent_session_id: str, iteration: Optional[int]) -> dict:
    parent_manifest = _load_manifest(parent_session_id)
    parent_state = _design_run_state(parent_session_id, parent_manifest)
    playable = _playable_iteration(parent_manifest, parent_state, iteration)
    parent_spec_path = _spec_path_from_manifest(parent_session_id, parent_manifest)
    iter_dir = _iteration_artifact_dir(parent_manifest, playable["iteration"])
    design_path = iter_dir / "design.json"
    report_path = iter_dir / "report.json"
    result_path = iter_dir / "simulation_result.json"
    if not design_path.exists() or not report_path.exists():
        raise HTTPException(status_code=404, detail="Parent design artifacts not found")
    return {
        "parent_manifest": parent_manifest,
        "parent_state": parent_state,
        "parent_spec_path": parent_spec_path,
        "parent_spec": _read_json(parent_spec_path),
        "parent_iteration": playable["iteration"],
        "base_design": _read_json(design_path),
        "base_report": _read_json(report_path),
        "base_simulation_result": _read_json(result_path) if result_path.exists() else {},
    }


def _run_design_loop_background(session_id: str, message: str) -> None:
    session_dir = _design_session_dir(session_id)
    try:
        _design_log(session_id, "resolving request into a requirements spec")
        spec, source = _resolve_design_spec(message)
        spec, dropped_checks = drop_atmospheric_pressure_component_checks(spec)
        original_name = spec.get("name", "design_request")
        spec = dict(spec)
        spec["name"] = _safe_spec_name(str(original_name), session_id)
        spec_path = session_dir / "spec.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        loop_run_root = LOOP_RUN_ROOT / spec["name"]
        _design_log(session_id, f"spec ready ({source}): {spec['name']}")
        if dropped_checks:
            _design_log(session_id, f"dropped {dropped_checks} ambient pressure telemetry check(s)")
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
        # background-thread crash: FastAPI's Sentry hook won't see it, so report explicitly
        sentry_capture(exc, session_id=session_id, request=message, stage="design-loop-background")
        _write_error_state(session_id, message, error)
        _write_manifest(session_dir, {"status": "error", "error": error, "completed_at": time.time()})


def _run_design_revision_background(session_id: str, parent_session_id: str, message: str, iteration: Optional[int]) -> None:
    session_dir = _design_session_dir(session_id)
    try:
        _design_log(session_id, f"resolving revision from parent {parent_session_id[:8]}")
        revision = _revision_inputs(parent_session_id, iteration)
        spec = revise_spec(
            revision["parent_spec"],
            message,
            revision["base_design"],
            revision["base_report"],
        )
        spec, dropped_checks = drop_atmospheric_pressure_component_checks(spec)
        original_name = spec.get("name") or f"{revision['parent_spec'].get('name', 'design_request')}_revision"
        spec = dict(spec)
        spec["name"] = _safe_spec_name(str(original_name), session_id)
        spec_path = session_dir / "spec.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        loop_run_root = LOOP_RUN_ROOT / spec["name"]
        _write_manifest(session_dir, {
            "status": "running",
            "source": "revision",
            "original_spec_name": original_name,
            "spec_name": spec["name"],
            "spec_path": str(spec_path),
            "loop_run_root": str(loop_run_root),
            "parent_session_id": parent_session_id,
            "parent_iteration": revision["parent_iteration"],
            "revision_request": message,
            "revision_of_spec": str(revision["parent_spec_path"]),
            "started_at": time.time(),
        })
        if dropped_checks:
            _design_log(session_id, f"dropped {dropped_checks} ambient pressure telemetry check(s)")

        revision_context = {
            "message": message,
            "parent_session_id": parent_session_id,
            "parent_iteration": revision["parent_iteration"],
            "base_design": revision["base_design"],
            "base_report": revision["base_report"],
            "base_simulation_result": revision["base_simulation_result"],
        }
        _design_log(session_id, f"starting linked revision loop; max_iters={DESIGN_MAX_ITERS}")
        run_loop(
            spec_path,
            max_iters=DESIGN_MAX_ITERS,
            store=FileSessionStore(root=DESIGN_RUN_ROOT),
            session_id=session_id,
            request=message,
            revision_context=revision_context,
        )
        _design_log(session_id, "revision loop completed")
        _write_manifest(session_dir, {"status": "completed", "completed_at": time.time()})
    except Exception as exc:  # noqa: BLE001 - background jobs must report failures as state
        error = f"{type(exc).__name__}: {exc}"
        sentry_capture(exc, session_id=session_id, request=message, stage="design-revision-background")
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


@app.get("/api/sentry-debug")
def sentry_debug():
    """Verify Sentry is wired: this intentionally raises so the error shows up in
    the Sentry dashboard (the standard Sentry setup check)."""
    _ = 1 / 0  # noqa: F841 - deliberate
    return {"ok": True}  # unreachable


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


@app.post("/api/design-runs/{parent_session_id}/revisions")
def create_design_run_revision(parent_session_id: str, request: DesignRunRevisionRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    revision = _revision_inputs(parent_session_id, request.iteration)
    parent_iteration = revision["parent_iteration"]
    session_id = uuid.uuid4().hex
    _design_log(session_id, f"queued revision of {parent_session_id[:8]} iter {parent_iteration}")
    session_dir = _design_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    parent_manifest = revision["parent_manifest"]
    _write_manifest(session_dir, {
        "session_id": session_id,
        "request": message,
        "status": "queued",
        "source": "revision",
        "created_at": time.time(),
        "parent_session_id": parent_session_id,
        "parent_iteration": parent_iteration,
        "revision_request": message,
        "revision_of_spec": str(revision["parent_spec_path"]),
        "parent_spec_name": parent_manifest.get("spec_name"),
    })

    state = new_state(session_id, message, "pending", "pending")
    state["stage"] = "requirements"
    state["revision"] = {
        "parent_session_id": parent_session_id,
        "parent_iteration": parent_iteration,
        "revision_request": message,
    }
    FileSessionStore(root=DESIGN_RUN_ROOT).write(state)

    thread = threading.Thread(
        target=_run_design_revision_background,
        args=(session_id, parent_session_id, message, parent_iteration),
        daemon=True,
        name=f"design-revision-{session_id[:8]}",
    )
    thread.start()
    return {"ok": True, "session_id": session_id, "parent_session_id": parent_session_id}


@app.get("/api/design-runs/{session_id}")
def get_design_run(session_id: str):
    manifest = _load_manifest(session_id)
    state = _design_run_state(session_id, manifest)
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


@app.post("/api/design-runs/{session_id}/procurement")
def create_procurement_run(session_id: str, request: ProcurementRunRequest):
    manifest = _load_manifest(session_id)
    run_root = Path(manifest.get("loop_run_root", "")).resolve()

    iter_dir = (run_root / f"iter_{request.iteration:02d}").resolve()
    design_path = iter_dir / "design.json"
    report_path = iter_dir / "report.json"

    if not design_path.exists() or not report_path.exists():
        raise HTTPException(status_code=404, detail="Design artifacts not found")

    # Safety: do not procure from an unreviewed/nonexistent design.
    report = _json_response_file(report_path)
    status = report.get("status", {})
    if isinstance(status, dict) and status.get("passed") is False:
        raise HTTPException(status_code=400, detail="Cannot procure from failed design")

    result = run_procurement(
        design_path=design_path,
        report_path=report_path,
        materials=request.materials,
        project_name=request.project_name,
    )

    if not result["ok"]:
        return JSONResponse(status_code=400, content=result)

    return result


@app.get("/api/procurement-runs/{run_id}/bom")
def get_procurement_bom(run_id: str):
    if not run_id or any(ch not in "0123456789abcdef" for ch in run_id):
        raise HTTPException(status_code=404, detail="Procurement run not found")

    bom_path = ROOT / "results" / "procurement_runs" / run_id / "bom.json"
    if not bom_path.exists():
        raise HTTPException(status_code=404, detail="BOM not found")

    return _json_response_file(bom_path)


class DirectProcurementRunRequest(BaseModel):
    materials: list[dict]
    project_name: str = "Rocketcursor procurement run"


@app.post("/api/procurement-runs")
def create_direct_procurement_run(request: DirectProcurementRunRequest):
    result = run_procurement(
        design_path=None,
        report_path=None,
        materials=request.materials,
        project_name=request.project_name,
    )

    if not result["ok"]:
        return JSONResponse(status_code=400, content=result)

    return result


@app.get("/api/procurement-runs/{run_id}/summary")
def get_procurement_summary(run_id: str):
    if not run_id or any(ch not in "0123456789abcdef" for ch in run_id):
        raise HTTPException(status_code=404, detail="Procurement run not found")

    summary_path = ROOT / "results" / "procurement_runs" / run_id / "procurement_summary.json"

    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="Procurement summary not found")

    return _json_response_file(summary_path)


@app.post("/api/procurement-runs/{run_id}/send-rfqs")
def send_procurement_rfqs(run_id: str):
    run_dir = ROOT / "results" / "procurement_runs" / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Procurement run not found")

    result = send_rfqs_via_poke(run_dir)
    if not result["ok"]:
        return JSONResponse(status_code=400, content=result)

    return result
