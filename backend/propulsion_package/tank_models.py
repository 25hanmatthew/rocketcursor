"""Deterministic propellant-tank sizing: fluid mass -> internal volume (with
ullage + residual margin) -> length at a given diameter -> wall thickness from
operating pressure -> dry mass. Cylinder with two hemispherical end caps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.propulsion_package.material_models import SAFETY_FACTOR_BURST, Material

ULLAGE_FRACTION = 0.06     # gas volume above the liquid at load
RESIDUAL_FRACTION = 0.03   # unusable propellant left at burnout


@dataclass
class TankSizing:
    diameter_m: float
    length_m: float
    wall_thickness_m: float
    internal_volume_m3: float
    dry_mass_kg: float
    end_cap: str = "hemispherical"


def suggest_diameter(fluid_mass_kg: float, density_kg_m3: float, length_to_diameter: float = 3.0) -> float:
    """A natural tank outer diameter from volume at a target slenderness."""
    v_int = (fluid_mass_kg / density_kg_m3) / (1.0 - ULLAGE_FRACTION - RESIDUAL_FRACTION)
    # cylinder-only proxy: V = pi r^2 (L/D * 2r) -> r = (V / (2 pi (L/D)))^(1/3)
    r = (v_int / (2.0 * math.pi * length_to_diameter)) ** (1.0 / 3.0)
    return 2.0 * r


def size_tank(
    fluid_mass_kg: float,
    density_kg_m3: float,
    operating_pressure_pa: float,
    diameter_m: float,
    material: Material,
) -> TankSizing:
    """Size a tank to hold `fluid_mass_kg` at a fixed outer `diameter_m`."""
    v_int = (fluid_mass_kg / density_kg_m3) / (1.0 - ULLAGE_FRACTION - RESIDUAL_FRACTION)
    r = diameter_m / 2.0

    # Wall thickness from thin-wall hoop stress at burst pressure.
    p_burst = SAFETY_FACTOR_BURST * operating_pressure_pa
    t = p_burst * r / material.yield_stress_pa
    t = max(t, 0.0008)  # 0.8 mm manufacturing floor
    r_in = r - t

    # Two hemispherical caps form one sphere of internal volume (4/3) pi r_in^3.
    cap_volume = (4.0 / 3.0) * math.pi * r_in ** 3
    cyl_volume = max(v_int - cap_volume, 0.0)
    l_cyl = cyl_volume / (math.pi * r_in ** 2)
    total_length = l_cyl + 2.0 * r  # caps add one radius each

    # Dry mass = shell volume * material density (cylinder wall + spherical caps).
    shell_cyl = 2.0 * math.pi * r * l_cyl * t
    shell_caps = 4.0 * math.pi * r ** 2 * t
    dry_mass = (shell_cyl + shell_caps) * material.density_kg_m3

    return TankSizing(
        diameter_m=diameter_m,
        length_m=total_length,
        wall_thickness_m=t,
        internal_volume_m3=v_int,
        dry_mass_kg=dry_mass,
    )


def size_pressurant_bottle(
    gas_mass_kg: float,
    fluid: str,
    pressure_pa: float,
    temperature_k: float,
    diameter_m: float,
    material: Material,
) -> TankSizing:
    """Size a spherical-ish high-pressure bottle from stored gas mass."""
    import CoolProp.CoolProp as CP

    try:
        rho = float(CP.PropsSI("D", "T", temperature_k, "P", pressure_pa, fluid))
    except Exception:
        rho = pressure_pa / (296.8 * temperature_k)  # N2 ideal gas fallback
    v_int = gas_mass_kg / rho
    r = diameter_m / 2.0
    p_burst = SAFETY_FACTOR_BURST * pressure_pa
    t = max(p_burst * r / material.yield_stress_pa, 0.0015)
    r_in = r - t
    cap_volume = (4.0 / 3.0) * math.pi * r_in ** 3
    cyl_volume = max(v_int - cap_volume, 0.0)
    l_cyl = cyl_volume / (math.pi * r_in ** 2)
    total_length = l_cyl + 2.0 * r
    shell = (2.0 * math.pi * r * l_cyl + 4.0 * math.pi * r ** 2) * t
    return TankSizing(
        diameter_m=diameter_m,
        length_m=total_length,
        wall_thickness_m=t,
        internal_volume_m3=v_int,
        dry_mass_kg=shell * material.density_kg_m3,
    )
