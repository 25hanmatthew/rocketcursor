"""Time-varying mass, center of mass, and inertia of the propulsion package as
propellant depletes. Each propellant tank's liquid mass drops linearly from its
loaded value to residual over its own depletion time; dry components are constant.

Inertia is taken about the instantaneous package CG:
  I_axial  (I33) = sum  1/2 m_i r_i^2
  I_trans  (I11=I22) = sum [ m_i (z_i - z_cg)^2 + self_term_i ]
with a thin-cylinder self term for elongated components.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MassComponent:
    id: str
    dry_mass_kg: float
    z_center_m: float
    radius_m: float
    length_m: float
    # propellant payload (0 for dry parts)
    fluid_loaded_kg: float = 0.0
    fluid_residual_kg: float = 0.0
    deplete_time_s: float = 0.0


def _fluid_mass(c: MassComponent, t: float, burn_time: float) -> float:
    if c.fluid_loaded_kg <= 0.0:
        return 0.0
    dt = c.deplete_time_s or burn_time
    if dt <= 0.0 or t >= dt:
        return c.fluid_residual_kg
    frac = t / dt
    return c.fluid_loaded_kg + (c.fluid_residual_kg - c.fluid_loaded_kg) * frac


def time_series(components: list[MassComponent], burn_time: float, dt: float = 0.1):
    """Return list of rows: (t, total_mass, cg_z, I11, I33)."""
    rows = []
    n = max(int(round(burn_time / dt)), 1)
    times = [round(i * dt, 4) for i in range(n + 1)]
    if times[-1] < burn_time:
        times.append(round(burn_time, 4))

    for t in times:
        total = 0.0
        moment = 0.0
        masses = []
        for c in components:
            m = c.dry_mass_kg + _fluid_mass(c, t, burn_time)
            masses.append((c, m))
            total += m
            moment += m * c.z_center_m
        z_cg = moment / total if total > 0 else 0.0

        i_axial = 0.0
        i_trans = 0.0
        for c, m in masses:
            i_axial += 0.5 * m * c.radius_m ** 2
            self_trans = m * (3.0 * c.radius_m ** 2 + c.length_m ** 2) / 12.0
            i_trans += m * (c.z_center_m - z_cg) ** 2 + self_trans
        rows.append((t, total, z_cg, i_trans, i_axial))
    return rows
