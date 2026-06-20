import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "results" / "ui_runs"
ALLOWED_ARTIFACTS = {
    "report.json",
    "nodes.csv",
    "connections.csv",
    "nodes_summary.json",
    "connections_summary.json",
    "diagnostics.json",
    "report.md",
}


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
        str(ROOT / "run_network.py"),
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
    return _json_response_file(ROOT / "network_schema.json")


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
