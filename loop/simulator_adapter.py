"""Adapter between a design dict and the fluid-network solver.

Wraps the load -> run -> export pipeline in `network_io` and returns a single
structured `simulation_result` dict that the evaluator consumes. It also
classifies the run into one of the failure modes the solver actually exhibits:

    "invalid_config" -- NetworkConfigError before the sim ran (schema/topology)
    "crashed"        -- solver raised mid-run (e.g. nonphysical mass overshoot)
    "ok"             -- sim ran to completion and exported results

Degenerate-but-clean runs (no nonzero flow, nonphysical warnings) still report
status "ok"; the *evaluator* decides whether they meet requirements. The
adapter answers "did it run?"; the evaluator answers "is it any good?".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from simulator import network_io


def run_design(
    design: dict[str, Any],
    run_dir: str | Path,
    save_plots: bool = False,
) -> dict[str, Any]:
    """Validate, run, and export `design`. Always returns a result dict and
    always writes it to `run_dir/simulation_result.json` (never raises)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    design_path = run_dir / "design.json"
    design_path.write_text(json.dumps(design, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "status": "ok",
        "errors": [],
        "design_path": str(design_path),
        "output_dir": str(run_dir),
        "components": {},
        "diagnostics": {},
        "final_nodes": {},
        "warnings": [],
    }

    try:
        loaded = network_io.load_network_config(design_path)
    except network_io.NetworkConfigError as exc:
        result["status"] = "invalid_config"
        result["errors"] = list(exc.errors)
        return _finish(run_dir, result)
    except Exception as exc:  # malformed JSON / unexpected loader failure
        result["status"] = "invalid_config"
        result["errors"] = [f"{type(exc).__name__}: {exc}"]
        return _finish(run_dir, result)

    try:
        network_io.run_loaded_network(loaded)
    except Exception as exc:  # solver blew up on this design
        result["status"] = "crashed"
        result["errors"] = [f"{type(exc).__name__}: {exc}"]
        return _finish(run_dir, result)

    summary = network_io.export_results(loaded, run_dir, save_plots=save_plots)
    node_summaries, connection_summaries = network_io._build_agent_summaries(loaded)
    result["components"] = {**node_summaries, **connection_summaries}
    result["diagnostics"] = summary["diagnostics"]
    result["final_nodes"] = summary["final_nodes"]
    result["warnings"] = summary["warnings"]
    return _finish(run_dir, result)


def _finish(run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    (run_dir / "simulation_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
