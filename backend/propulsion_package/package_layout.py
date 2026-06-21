"""Stack sized components along the vehicle axis and route feed lines.

Coordinate frame: origin at nozzle exit, +Z toward the nose. Components are
stacked bottom-up: engine, then propellant tanks (oxidizer above fuel by default
for CG/stability), then the pressurant bottle on top. Feed-line routed length is
the axial span from each tank outlet down to the engine inlet plus a bend margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BEND_MARGIN_M = 0.10        # extra routed length per line for bends/fittings
INTER_COMPONENT_GAP_M = 0.05  # bulkhead/clearance between stacked components
RADIAL_CLEARANCE_M = 0.02   # gap between tank wall and vehicle inner wall


@dataclass
class PlacedComponent:
    id: str
    z_bottom: float
    z_top: float
    diameter_m: float

    @property
    def z_center(self) -> float:
        return 0.5 * (self.z_bottom + self.z_top)


@dataclass
class Layout:
    placements: dict[str, PlacedComponent] = field(default_factory=dict)
    routed_line_lengths_m: dict[str, float] = field(default_factory=dict)
    min_inner_diameter_m: float = 0.0
    stack_length_m: float = 0.0


def stack_and_route(
    engine_length_m: float,
    engine_diameter_m: float,
    tanks: list[dict],          # ordered bottom->top: {id, length_m, diameter_m, role}
    bottle: dict | None,        # {id, length_m, diameter_m}
    feed_map: dict[str, str],   # line_id -> tank_id it draws from
) -> Layout:
    layout = Layout()
    z = 0.0

    eng = PlacedComponent("engine", z, z + engine_length_m, engine_diameter_m)
    layout.placements["engine"] = eng
    z = eng.z_top + INTER_COMPONENT_GAP_M
    engine_inlet_z = eng.z_top

    max_dia = engine_diameter_m
    for tank in tanks:
        comp = PlacedComponent(tank["id"], z, z + tank["length_m"], tank["diameter_m"])
        layout.placements[tank["id"]] = comp
        z = comp.z_top + INTER_COMPONENT_GAP_M
        max_dia = max(max_dia, tank["diameter_m"])

    if bottle is not None:
        comp = PlacedComponent(bottle["id"], z, z + bottle["length_m"], bottle["diameter_m"])
        layout.placements[bottle["id"]] = comp
        z = comp.z_top + INTER_COMPONENT_GAP_M
        max_dia = max(max_dia, bottle["diameter_m"])

    # Routed feed-line length: tank outlet (bottom of tank) down to engine inlet.
    for line_id, tank_id in feed_map.items():
        tank = layout.placements[tank_id]
        layout.routed_line_lengths_m[line_id] = (tank.z_bottom - engine_inlet_z) + BEND_MARGIN_M

    layout.min_inner_diameter_m = max_dia + 2.0 * RADIAL_CLEARANCE_M
    layout.stack_length_m = z
    return layout
