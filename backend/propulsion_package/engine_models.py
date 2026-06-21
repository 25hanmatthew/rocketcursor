"""Engine envelope + dry-mass estimate from chamber/throat/nozzle geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass

CHARACTERISTIC_LENGTH_M = 1.0  # L* for kerolox, typical 0.9-1.1 m
CHAMBER_CONTRACTION_RATIO = 4.0  # Ac/At


@dataclass
class EngineSizing:
    throat_diameter_m: float
    nozzle_exit_diameter_m: float
    chamber_diameter_m: float
    length_m: float
    dry_mass_kg: float
    thrust_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)


def size_engine(throat_area_m2: float, exit_area_m2: float, thrust_n: float) -> EngineSizing:
    dt = math.sqrt(4.0 * throat_area_m2 / math.pi)
    de = math.sqrt(4.0 * exit_area_m2 / math.pi)
    ac = CHAMBER_CONTRACTION_RATIO * throat_area_m2
    dc = math.sqrt(4.0 * ac / math.pi)

    # Chamber length from L* (V_chamber = L* * At), plus a conical nozzle length
    # (15-deg half-angle proxy) and a short injector/converging section.
    v_chamber = CHARACTERISTIC_LENGTH_M * throat_area_m2
    l_chamber = v_chamber / ac
    l_nozzle = (de - dt) / 2.0 / math.tan(math.radians(15.0))
    length = l_chamber + l_nozzle + 0.5 * dc

    # Dry mass: thrust-based proxy (engine thrust-to-weight ~ 60 for small regen/ablative).
    dry_mass = max(1.5, thrust_n / (60.0 * 9.80665))

    return EngineSizing(dt, de, dc, length, dry_mass)
