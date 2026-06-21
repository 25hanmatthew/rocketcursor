"""Barrowman center-of-pressure and static-stability estimate.

Standard subsonic Barrowman method: normal-force coefficient slopes (CN_alpha)
and centers of pressure for the nose and fin set are combined into a vehicle CP.
A cylindrical body contributes ~0 normal force in the basic method. Inputs are in
the from-nose-tip convention; the synthesizer converts to the nozzle-exit frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

NOSE_CP_FACTOR = {  # x_cp / length, from tip
    "conical": 0.666,
    "ogive": 0.466,
    "von karman": 0.500,
    "ellipsoid": 0.333,
    "lvhaack": 0.437,
    "power_series": 0.500,
}


@dataclass
class FinGeometry:
    count: int
    root_chord_m: float
    tip_chord_m: float
    span_m: float
    sweep_length_m: float          # axial sweep of leading edge, root LE to tip LE
    root_le_from_tip_m: float      # axial position of fin root leading edge, from nose tip
    body_radius_m: float


@dataclass
class CPResult:
    cn_alpha_total: float
    x_cp_from_tip_m: float
    components: dict


def nose_cp(kind: str, length_m: float) -> tuple[float, float]:
    """Return (CN_alpha, x_cp_from_tip). Nose CN_alpha is 2.0 per radian (ref area)."""
    factor = NOSE_CP_FACTOR.get(kind, 0.5)
    return 2.0, factor * length_m


def fin_cp(fins: FinGeometry) -> tuple[float, float]:
    """Return (CN_alpha, x_cp_from_tip) for the fin set with body interference."""
    R = fins.body_radius_m
    s = fins.span_m
    cr = fins.root_chord_m
    ct = fins.tip_chord_m
    d = 2.0 * R
    # mid-chord sweep length
    lf = math.sqrt(s ** 2 + (fins.sweep_length_m + 0.5 * (ct - cr)) ** 2)
    n = fins.count
    interference = 1.0 + R / (s + R)
    cn = interference * (4.0 * n * (s / d) ** 2) / (1.0 + math.sqrt(1.0 + (2.0 * lf / (cr + ct)) ** 2))

    xr = fins.sweep_length_m  # LE sweep
    x_cp_local = (xr / 3.0) * (cr + 2.0 * ct) / (cr + ct) + (1.0 / 6.0) * (
        (cr + ct) - cr * ct / (cr + ct)
    )
    x_cp = fins.root_le_from_tip_m + x_cp_local
    return cn, x_cp


def center_of_pressure(nose_kind: str, nose_length_m: float, fins: FinGeometry) -> CPResult:
    cn_n, x_n = nose_cp(nose_kind, nose_length_m)
    cn_f, x_f = fin_cp(fins)
    cn_total = cn_n + cn_f
    x_cp = (cn_n * x_n + cn_f * x_f) / cn_total
    return CPResult(
        cn_alpha_total=cn_total,
        x_cp_from_tip_m=x_cp,
        components={"nose": {"cn": cn_n, "x": x_n}, "fins": {"cn": cn_f, "x": x_f}},
    )


def static_margin_cal(cg_from_tip_m: float, cp_from_tip_m: float, diameter_m: float) -> float:
    """Calibers of static margin; positive (CP aft of CG) is stable."""
    return (cp_from_tip_m - cg_from_tip_m) / diameter_m
