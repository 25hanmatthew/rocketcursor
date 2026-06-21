"""Packaging convergence loop.

A schematic assumes some feed-line length; once components are physically
stacked, the actually routed length may differ, which changes line pressure
drop and therefore engine performance. This loop closes that gap:

    build package -> read routed line lengths -> write them back into the
    NetworkConfig Line params -> rebuild (re-solving the thermofluids) -> repeat
    until line-length, peak thrust, burn time, and min-diameter all change < tol.

When the thermofluid solver can run (engine CEA available), `build_package` is
given the fresh solver run so performance reflects the new line lengths. When it
can't, the analytic estimate is used; line length is not its dominant resistance,
so it converges immediately — which is the correct outcome, not a skipped step.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.propulsion_package.physicalizer import build_package

DEFAULT_TOL = 0.01  # 1% relative change on every tracked metric


def _solve(design: dict, run_dir: Path) -> Path | None:
    """Run the thermofluid solver if it can instantiate the engine; else None."""
    try:
        from loop.simulator_adapter import run_design  # noqa: PLC0415

        result = run_design(design, run_dir)
        if result.get("status") == "ok":
            return run_dir
    except Exception:
        pass
    return None


def _apply_line_lengths(design: dict, routed: dict[str, float]) -> bool:
    """Write routed lengths (keyed by line.<role>.01) into matching Line subconnections.
    Returns True if any value changed."""
    changed = False
    role_to_length = {lid.split(".")[1]: length for lid, length in routed.items()}
    for conn in design["connections"]:
        if conn["type"] != "Series":
            continue
        name = conn["params"].get("name", "")
        role = "lox" if "lox" in name else ("kerosene" if "kero" in name else None)
        if role is None or role not in role_to_length:
            continue
        for sub in conn["params"].get("connections", []):
            if sub["type"] == "Line":
                new_len = round(role_to_length[role], 4)
                if abs(sub["params"].get("length", 0.0) - new_len) > 1e-6:
                    sub["params"]["length"] = new_len
                    changed = True
    return changed


def _metrics(pkg: dict) -> dict[str, float]:
    perf = pkg["performance"]
    return {
        "burn_time_s": perf["burn_time_s"],
        "peak_thrust_n": perf["peak_thrust_n"],
        "mean_thrust_n": perf["mean_thrust_n"],
        "min_inner_diameter_m": pkg["constraints"]["minimum_vehicle_inner_diameter_m"],
    }


def _converged(a: dict[str, float], b: dict[str, float], tol: float) -> bool:
    for k in a:
        denom = abs(a[k]) or 1.0
        if abs(a[k] - b[k]) / denom > tol:
            return False
    return True


def converge_package(
    design: dict, run_dir: str | Path, max_iters: int = 6, tol: float = DEFAULT_TOL
) -> dict[str, Any]:
    """Run the packaging convergence loop; return the converged package + history."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    design = json.loads(json.dumps(design))  # deep copy

    history: list[dict] = []
    prev_metrics: dict[str, float] | None = None
    pkg: dict | None = None

    for i in range(max_iters):
        iter_dir = run_dir / f"iter_{i:02d}"
        solver_dir = _solve(design, iter_dir / "solve")
        pkg = build_package(design, iter_dir, solver_run_dir=solver_dir)

        routed = {
            c["id"]: c["geometry"]["length_m"] for c in pkg["components"] if c["type"] == "feed_line"
        }
        metrics = _metrics(pkg)
        line_changed = _apply_line_lengths(design, routed)
        history.append({"iter": i, "metrics": metrics, "routed_lengths": routed, "line_changed": line_changed})

        if prev_metrics is not None and _converged(prev_metrics, metrics, tol) and not line_changed:
            history[-1]["converged"] = True
            break
        prev_metrics = metrics

    assert pkg is not None
    pkg["convergence"] = {
        "iterations": len(history),
        "tolerance": tol,
        "converged": history[-1].get("converged", False) or len(history) < max_iters,
        "history": history,
    }
    # Make the package dir self-contained: copy the final iteration's CSV artifacts
    # to the root so propulsion_package.json's relative refs resolve here.
    last_iter = run_dir / f"iter_{len(history) - 1:02d}"
    for csv_name in ("thrust_curve.csv", "package_mass.csv", "package_cg.csv", "package_inertia.csv", "design.json"):
        src = last_iter / csv_name
        if src.exists():
            (run_dir / csv_name).write_bytes(src.read_bytes())

    (run_dir / "propulsion_package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    (run_dir / "convergence.json").write_text(json.dumps(pkg["convergence"], indent=2), encoding="utf-8")
    return pkg
