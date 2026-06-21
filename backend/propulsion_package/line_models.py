"""Feed-line and valve physical estimates (thin-wall tube dry mass + envelopes)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.propulsion_package.material_models import MATERIALS

LINE_WALL_THICKNESS_M = 0.0009  # 0.9 mm tube wall
VALVE_MASS_KG = 0.35            # small ball/solenoid valve proxy


@dataclass
class LineSizing:
    inner_diameter_m: float
    routed_length_m: float
    dry_mass_kg: float


def size_line(inner_diameter_m: float, routed_length_m: float, material_name: str = "SS304L") -> LineSizing:
    mat = MATERIALS[material_name]
    r_in = inner_diameter_m / 2.0
    r_out = r_in + LINE_WALL_THICKNESS_M
    wall_area = math.pi * (r_out ** 2 - r_in ** 2)
    dry_mass = wall_area * routed_length_m * mat.density_kg_m3
    return LineSizing(inner_diameter_m, routed_length_m, dry_mass)
