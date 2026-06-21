"""Structural mass estimates for airframe components (thin-shell correlations)."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Airframe materials (typical hobby/university composites & metals).
AIRFRAME_DENSITY = {"fiberglass": 1850.0, "carbon": 1550.0, "aluminum": 2700.0}
BODY_WALL_M = 0.0025      # 2.5 mm composite wall
FIN_THICKNESS_M = 0.004   # 4 mm fin stock
NOSE_WALL_M = 0.003


@dataclass
class StructureMass:
    body_tube_kg: float
    nose_kg: float
    fins_kg: float
    bulkheads_kg: float
    total_kg: float


def body_tube_mass(diameter_m: float, length_m: float, material: str = "fiberglass") -> float:
    rho = AIRFRAME_DENSITY[material]
    r = diameter_m / 2.0
    wall_area = math.pi * ((r) ** 2 - (r - BODY_WALL_M) ** 2)
    return wall_area * length_m * rho


def nose_mass(diameter_m: float, length_m: float, material: str = "fiberglass") -> float:
    """Conical-shell proxy: lateral surface area * wall thickness * density."""
    rho = AIRFRAME_DENSITY[material]
    r = diameter_m / 2.0
    slant = math.sqrt(r ** 2 + length_m ** 2)
    lateral_area = math.pi * r * slant
    return lateral_area * NOSE_WALL_M * rho


def fin_set_mass(count: int, root_chord_m: float, tip_chord_m: float, span_m: float, material: str = "fiberglass") -> float:
    rho = AIRFRAME_DENSITY[material]
    plate_area = 0.5 * (root_chord_m + tip_chord_m) * span_m
    return count * plate_area * FIN_THICKNESS_M * rho


def bulkhead_mass(diameter_m: float, count: int = 3, material: str = "fiberglass") -> float:
    rho = AIRFRAME_DENSITY[material]
    r = diameter_m / 2.0
    return count * math.pi * r ** 2 * 0.006 * rho  # 6 mm discs


def parachute_mass(descent_mass_kg: float) -> float:
    """Rough recovery-system mass (canopy + lines + hardware) ~ 4% of descent mass."""
    return max(0.2, 0.04 * descent_mass_kg)
