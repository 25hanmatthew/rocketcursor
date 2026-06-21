"""Map the canonical vehicle_model + propulsion_package onto RocketPy objects.

Mass bookkeeping (avoid double counting):
  * RocketPy Rocket(mass=...) is the airframe dry mass WITHOUT the motor.
  * The LiquidMotor carries the propulsion package: its dry_mass = sum of package
    dry components (engine + tanks + lines + bottle) + pressurant gas (folded in,
    since our model does not deplete it); its tanks carry the ox/fuel propellant.
  * Coordinate systems share our convention: origin at nozzle exit, +z to nose.
    Rocket uses 'tail_to_nose'; motor uses 'nozzle_to_combustion_chamber' with
    nozzle_position=0, so both origins coincide at the nozzle exit.

Altitude–thrust note: RocketPy uses the thrust curve as-is. We pass the solver's
reference-pressure curve directly (MVP); a vacuum-thrust + nozzle-area correction
is a later upgrade (see propulsion_package.performance.reference_ambient_pressure_pa).
"""

from __future__ import annotations

from pathlib import Path

from rocketpy import (
    CylindricalTank,
    Environment,
    Fluid,
    Flight,
    LiquidMotor,
    MassFlowRateBasedTank,
    Rocket,
)


def _density_for(role: str) -> float:
    return {"lox": 1140.0, "kerosene": 800.0}.get(role, 1000.0)


def build_environment(env_defaults: dict, wind_mps: float = 0.0) -> Environment:
    env = Environment(
        latitude=env_defaults.get("latitude_deg", 0.0) or 0.0,
        longitude=env_defaults.get("longitude_deg", 0.0) or 0.0,
        elevation=env_defaults.get("altitude_m", 0.0) or 0.0,
    )
    if wind_mps:
        # Constant cross-wind on a standard atmosphere (Monte Carlo dispersion).
        env.set_atmospheric_model(type="custom_atmosphere", wind_u=float(wind_mps), wind_v=0.0)
    else:
        env.set_atmospheric_model(type="standard_atmosphere")
    return env


def build_motor(package: dict, package_dir: Path, burn_time: float) -> LiquidMotor:
    comps = package["components"]
    engine = next(c for c in comps if c["type"] == "engine")
    tanks = [c for c in comps if c["type"] == "propellant_tank"]
    bottle = next((c for c in comps if c["type"] == "pressurant_bottle"), None)

    dry_components = [c for c in comps if c["type"] != "propellant_tank" or True]
    # motor dry mass = all package dry masses + pressurant gas (non-depleting)
    motor_dry = sum(c["dry_mass_kg"] for c in comps)
    if bottle:
        motor_dry += bottle.get("initial_fluid_mass_kg", 0.0)
    motor_dry_moment = sum(c["dry_mass_kg"] * c["position_m"][2] for c in comps)
    if bottle:
        motor_dry_moment += bottle.get("initial_fluid_mass_kg", 0.0) * bottle["position_m"][2]
    dry_cg = motor_dry_moment / motor_dry if motor_dry else 0.0

    nozzle_radius = 0.5 * engine["geometry"]["nozzle_exit_diameter_m"]
    pkg_len = max(c["position_m"][2] + 0.5 * c["geometry"].get("length_m", 0) for c in comps)
    i_trans = motor_dry * (pkg_len ** 2) / 12.0
    i_axial = 0.5 * motor_dry * (0.25 * package["constraints"]["minimum_vehicle_inner_diameter_m"]) ** 2

    motor = LiquidMotor(
        thrust_source=str(package_dir / package["performance"]["thrust_curve"]),
        dry_mass=motor_dry,
        dry_inertia=(i_trans, i_trans, max(i_axial, 1e-3)),
        nozzle_radius=nozzle_radius,
        center_of_dry_mass_position=dry_cg,
        nozzle_position=0.0,
        burn_time=burn_time,
        coordinate_system_orientation="nozzle_to_combustion_chamber",
    )

    for tank_c in tanks:
        role = "lox" if tank_c["id"].endswith("lox.01") else "kerosene"
        prop_mass = tank_c.get("initial_fluid_mass_kg", 0.0)
        wall = tank_c["geometry"].get("wall_thickness_m", 0.002)
        inner_r = max(0.5 * tank_c["geometry"]["diameter_m"] - wall, 0.01)
        # small capacity margin so liquid + ullage always fits the discretized geometry
        height = tank_c["geometry"]["length_m"] * 1.08
        geometry = CylindricalTank(radius=inner_r, height=height, spherical_caps=True)
        liquid = Fluid(name=role, density=_density_for(role))
        gas = Fluid(name=f"{role}_ullage", density=40.0)  # regulated N2 ullage
        # leave ~0.5% residual so the tank never integrates to negative mass at burnout
        mdot_out = 0.995 * prop_mass / burn_time if burn_time > 0 else 0.0
        tank = MassFlowRateBasedTank(
            name=tank_c["id"],
            geometry=geometry,
            flux_time=(0.0, burn_time),
            liquid=liquid,
            gas=gas,
            initial_liquid_mass=prop_mass,
            initial_gas_mass=0.02,
            liquid_mass_flow_rate_in=0.0,
            gas_mass_flow_rate_in=0.0,
            liquid_mass_flow_rate_out=mdot_out,
            gas_mass_flow_rate_out=0.0,
        )
        motor.add_tank(tank, position=tank_c["position_m"][2])
    return motor


def build_rocket(vehicle: dict, package: dict, package_dir: Path, mass_factor: float = 1.0) -> Rocket:
    geom = vehicle["geometry"]
    mp = vehicle["mass_properties"]
    body_radius = 0.5 * geom["body_diameter_m"]
    total_length = geom["total_length_m"]

    package_dry = sum(c["dry_mass_kg"] for c in package["components"])
    bottle_gas = sum(c.get("initial_fluid_mass_kg", 0.0) for c in package["components"] if c["type"] == "pressurant_bottle")
    # mass_factor perturbs the dry airframe mass for Monte Carlo dispersion (default 1.0 = nominal).
    struct_mass = (mp["dry_mass_kg"] - package_dry) * mass_factor  # airframe only (motor excluded)

    # structure CG: back out from vehicle loaded CG is complex; use body geometric proxy.
    struct_cg = 0.55 * total_length
    i_trans = struct_mass * (total_length ** 2) / 12.0
    i_axial = 0.5 * struct_mass * body_radius ** 2

    rocket = Rocket(
        radius=body_radius,
        mass=struct_mass,
        inertia=(i_trans, i_trans, max(i_axial, 1e-3)),
        power_off_drag=vehicle["aerodynamics"].get("cd_power_off", 0.55),
        power_on_drag=vehicle["aerodynamics"].get("cd_power_off", 0.55),
        center_of_mass_without_motor=struct_cg,
        coordinate_system_orientation="tail_to_nose",
    )

    burn_time = package["performance"]["burn_time_s"]
    motor = build_motor(package, package_dir, burn_time)
    rocket.add_motor(motor, position=0.0)

    nose = geom["nose"]
    rocket.add_nose(length=nose["length_m"], kind=nose.get("kind", "von karman"), position=total_length)

    f = geom["fins"]
    rocket.add_trapezoidal_fins(
        n=f["count"], root_chord=f["root_chord_m"], tip_chord=f["tip_chord_m"], span=f["span_m"],
        position=f["position_z_m"] + f["root_chord_m"], sweep_length=f.get("sweep_length_m"),
    )

    rec = vehicle.get("recovery", {})
    rocket.add_parachute(
        name="main", cd_s=rec.get("main_cd_s_m2", 1.5) or 1.5,
        trigger="apogee", sampling_rate=100, lag=1.0,
    )
    return rocket


def fly(
    vehicle: dict, package: dict, package_dir: Path,
    wind_mps: float = 0.0, mass_factor: float = 1.0,
) -> tuple[Flight, Rocket]:
    env = build_environment(vehicle.get("environment_defaults", {}), wind_mps=wind_mps)
    rocket = build_rocket(vehicle, package, package_dir, mass_factor=mass_factor)
    envd = vehicle.get("environment_defaults", {})
    flight = Flight(
        rocket=rocket,
        environment=env,
        rail_length=envd.get("rail_length_m", 6.0),
        inclination=envd.get("elevation_deg", 90.0),
        heading=envd.get("heading_deg", 0.0),
        max_time=600,
    )
    return flight, rocket
