"""Monte Carlo flight dispersion: re-fly the nominal vehicle many times with
perturbed cross-wind and dry mass, and report the apogee and landing scatter.

This turns the single nominal apogee into an uncertainty band -- the honest
answer for an unguided rocket whose real apogee depends on wind and as-built
mass. Perturbations are injected through the RocketPy adapter's backward-
compatible hooks (wind_mps, mass_factor); nothing else about the flight changes.

Deterministic given a seed (random module, fixed seed) so runs are reproducible.
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

from backend.flight.adapters import rocketpy_adapter


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def _stats(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return {
        "n": len(vals),
        "mean": round(mean, 2),
        "std": round(math.sqrt(var), 2),
        "min": round(s[0], 2),
        "p10": round(_percentile(s, 0.10), 2),
        "p50": round(_percentile(s, 0.50), 2),
        "p90": round(_percentile(s, 0.90), 2),
        "max": round(s[-1], 2),
    }


def run_monte_carlo(
    vehicle: dict, package: dict, package_dir: str | Path,
    trials: int = 20, wind_sigma_mps: float = 4.0, mass_sigma_frac: float = 0.05,
    seed: int = 12345,
) -> dict[str, Any]:
    """Fly `trials` perturbed copies; return apogee/landing-range statistics."""
    package_dir = Path(package_dir)
    rng = random.Random(seed)

    apogees: list[float] = []
    ranges: list[float] = []   # horizontal distance from pad at landing
    failures = 0
    for _ in range(trials):
        wind = rng.gauss(0.0, wind_sigma_mps)
        mass_factor = max(0.5, rng.gauss(1.0, mass_sigma_frac))
        try:
            flight, _ = rocketpy_adapter.fly(vehicle, package, package_dir,
                                             wind_mps=wind, mass_factor=mass_factor)
            apogee = float(flight.apogee) - float(flight.env.elevation)
            x, y = float(flight.x_impact), float(flight.y_impact)
            apogees.append(apogee)
            ranges.append(math.hypot(x, y))
        except Exception:
            failures += 1

    return {
        "trials": trials,
        "completed": len(apogees),
        "failures": failures,
        "perturbations": {
            "wind_sigma_mps": wind_sigma_mps,
            "mass_sigma_frac": mass_sigma_frac,
            "seed": seed,
        },
        "apogee_m": _stats(apogees),
        "landing_range_m": _stats(ranges),
    }
