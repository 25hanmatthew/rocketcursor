"""Material property models for pressure vessels and lines.

Deterministic, catalog-style. Density and allowable stress drive wall-thickness
and dry-mass estimates. Values are typical engineering handbook figures; later
versions can swap in real certs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Material:
    name: str
    density_kg_m3: float
    yield_stress_pa: float  # tensile yield
    cryo_ok: bool


MATERIALS: dict[str, Material] = {
    # Al 6061-T6: light tanks, ambient/cryo service.
    "Al6061-T6": Material("Al6061-T6", 2700.0, 276e6, cryo_ok=True),
    # 304L stainless: cryo/LOX-clean service, heavier.
    "SS304L": Material("SS304L", 8000.0, 210e6, cryo_ok=True),
    # COPV-ish proxy for high-pressure pressurant bottle (wound composite over liner).
    "COPV": Material("COPV", 1600.0, 2400e6, cryo_ok=False),
}

# Design safety factor on burst vs operating pressure (typical proof/burst margin).
SAFETY_FACTOR_BURST = 2.0


def select_tank_material(fluid: str, cryogenic: bool) -> Material:
    """Pick a tank wall material from the stored fluid and temperature class."""
    if cryogenic or fluid.lower() in {"oxygen", "lox", "o2"}:
        return MATERIALS["SS304L"]
    return MATERIALS["Al6061-T6"]
