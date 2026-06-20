"""Seed Redis with documented aerospace failure cases for semantic search.

Re-running overwrites the same failure:external:{id} keys (idempotent).
Requires VOYAGE_API_KEY and Redis Stack (local localhost:6379 or REDIS_URL for Redis Cloud).
"""

from memory.core import Memory

SEED_CASES = [
    {"id": "titan2_fuel_tank_puncture",
     "source_type": "external",
     "failure_mode": "Hypergolic fuel tank puncture and toxic vapor release during silo maintenance.",
     "system_config": "Titan II ICBM Stage 1 with pressurized Aerozine 50 fuel and NTO oxidizer tanks and Aerojet LR-87 engines.",
     "operating_conditions": "Crew servicing the oxidizer tank in a silo near Damascus, Arkansas when a dropped socket punctured the adjacent fuel tank.",
     "root_cause": "An 8-pound socket from a ratchet fell and pierced the Stage 1 fuel tank, leaking Aerozine 50 and triggering fire and eventual rupture.",
     "corrective_action": "Revised maintenance procedures, mandatory tool tethering, and enhanced hypergolic silo safety."},
    {"id": "apollo13_o2_tank",
     "source_type": "external",
     "failure_mode": "Cryogenic oxygen tank rupture causing loss of CSM electrical power and life support.",
     "system_config": "Apollo CSM with dual cryogenic O2/H2 tanks in Service Module Bay 4.",
     "operating_conditions": "Translunar flight at ~56 hours during a routine cryogenic oxygen tank stir.",
     "root_cause": "Damaged Teflon wiring and underrated thermostat in O2 tank #2 from prior ground testing caused internal short and rupture.",
     "corrective_action": "Redesigned tanks with stainless thermostats, improved wiring, pre-flight testing, and emergency LiOH cartridges."},
    {"id": "apollo1_cabin_fire",
     "source_type": "external",
     "failure_mode": "Electrical arc ignition of pure-oxygen cabin atmosphere causing rapid fatal fire.",
     "system_config": "Apollo Block I Command Module with 100% oxygen at 16.7 psi during pad test.",
     "operating_conditions": "Plugs-out integrated test on the launch pad, January 27, 1967.",
     "root_cause": "Chafed wiring under a crew couch and flammable Velcro/nylon in high-pressure pure oxygen allowed arc propagation.",
     "corrective_action": "Block II used mixed-gas prelaunch atmosphere, fire-resistant materials, revised wiring, and outward-opening hatch."},
    {"id": "challenger_o_ring",
     "source_type": "external",
     "failure_mode": "Solid rocket booster joint leak and catastrophic vehicle breakup.",
     "system_config": "Space Shuttle with two field-jointed SRBs using rubber O-ring seals in tang-and-clevis joints.",
     "operating_conditions": "Launch January 28, 1986 with ambient temperature ~36°F, well below prior SRB experience.",
     "root_cause": "Cold-stiffened primary O-ring failed to seat; blow-by eroded the secondary seal and the joint opened, breaching the ET.",
     "corrective_action": "Redesigned joints with capture feature, third O-ring, joint heaters, and tighter launch temperature criteria."},
    {"id": "ssme_turbopump",
     "source_type": "external",
     "failure_mode": "High-pressure turbopump bearing or seal failures causing engine shutdown or abort.",
     "system_config": "RS-25 SSME with staged-combustion cycle and high-speed LOX/LH2 turbopumps.",
     "operating_conditions": "High thrust with rapid start/shutdown cycles across reusable engine operational lifetime.",
     "root_cause": "Turbine blade fatigue, bearing lubrication limits, and oxidizer compatibility caused multiple test-stand and early-flight failures.",
     "corrective_action": "Turbopump redesigns with improved bearings/seals, material substitutions, and stricter hot-fire acceptance testing."},
    {"id": "n1_engine_cascade",
     "source_type": "external",
     "failure_mode": "First-stage engine cluster shutdown and loss of vehicle control leading to explosion.",
     "system_config": "Soviet N1 with 30 NK-33 engines in an annular first-stage cluster.",
     "operating_conditions": "Unmanned test flights from Baikonur with simultaneous ignition of the full engine complement.",
     "root_cause": "Explosive turbopump or engine failure triggered KORD shutdown of surrounding engines, causing cascading thrust loss and breakup.",
     "corrective_action": "Attempted KORD logic and engine isolation improvements before cancellation after four failed launches."},
    {"id": "ariane5_f501_sw",
     "source_type": "external",
     "failure_mode": "Inertial guidance software exception causing erroneous autopilot commands and vehicle breakup.",
     "system_config": "Ariane 5 with redundant Inertial Reference Systems carrying Ariane 4 software heritage.",
     "operating_conditions": "Maiden flight June 4, 1996 with higher horizontal velocity at SRI cutoff than Ariane 4.",
     "root_cause": "64-bit horizontal velocity converted to 16-bit signed integer overflowed; unprotected exception shut down active SRI computers.",
     "corrective_action": "Added range checks before conversion, removed dead Ariane 4 code paths, strengthened embedded software review."},
    {"id": "mco_unit_error",
     "source_type": "external",
     "failure_mode": "Trajectory error causing atmospheric entry at wrong altitude and spacecraft loss.",
     "system_config": "NASA Mars Climate Orbiter with ground navigation software using mixed unit conventions.",
     "operating_conditions": "Mars orbit insertion burn computed from Deep Space Network tracking during approach.",
     "root_cause": "Thruster impulse supplied in pound-force-seconds while JPL assumed newton-seconds, underestimating maneuvers by ~4.45×.",
     "corrective_action": "Mandated unit verification in interface documents, ground software peer review, and standardized metric usage."},
    {"id": "hubble_mirror_aberration",
     "source_type": "external",
     "failure_mode": "Primary mirror spherical aberration causing blurred images across all instruments.",
     "system_config": "2.4 m Hubble primary mirror polished using a reflective null-corrector at Perkin-Elmer.",
     "operating_conditions": "Ground optical certification before Shuttle deployment in 1990.",
     "root_cause": "Null-corrector reflective null lens installed reversed (~1.3 mm spacing error), producing incorrect figure undetected by cross-checks.",
     "corrective_action": "COSTAR and later WFPC2 installed on servicing missions to optically compensate for the aberration."},
    {"id": "atlas_centaur_insulation",
     "source_type": "external",
     "failure_mode": "LOX tank pressurization failure and structural collapse during extended pad hold.",
     "system_config": "Atlas-Centaur AC-67 with fiberglass insulation on Centaur LOX tank and helium pressurization.",
     "operating_conditions": "Extended pad hold at Cape Canaveral with LOX loaded, March 2, 1983.",
     "root_cause": "Insulation panels disbonded and fell off, exposing tank to heating and causing pressurization loss and collapse.",
     "corrective_action": "Improved adhesive bonding, added panel retention mechanisms, and revised LOX load/hold procedures."},
    {"id": "saturn5_pogo",
     "source_type": "external",
     "failure_mode": "Longitudinal pogo oscillation causing engine shutdown and high structural loads on second stage.",
     "system_config": "Saturn V S-II stage with five J-2 engines fed by common LOX/LH2 propellant lines.",
     "operating_conditions": "Apollo 6 and earlier missions near max-Q with engine–structure resonance coupling.",
     "root_cause": "Propellant line and combustion feedback created ~16 Hz oscillations, amplifying loads and shutting down J-2 #2 on Apollo 6.",
     "corrective_action": "Added POGO suppression accumulators in propellant lines and tuned engine operation to detune resonance."},
    {"id": "falcon9_copv_helium",
     "source_type": "external",
     "failure_mode": "Composite overwrapped pressure vessel overpressurization and rupture during Stage 2 operations.",
     "system_config": "Falcon 9 Stage 2 with COPV helium bottles for tank pressurization, including submerged LOX configurations.",
     "operating_conditions": "CRS-7 in-flight loss (2015) and Amos-6 pad static fire (2016) during helium/LOX loading.",
     "root_cause": "CRS-7: helium COPV support strut failed; Amos-6: LOX pooled in COPV overwrap voids, triggering frictional ignition.",
     "corrective_action": "Redesigned COPV mounting and acceptance testing, revised fill sequences to prevent LOX trapping in overwrap."},
]

FIELD_KEYS = ("failure_mode", "system_config", "operating_conditions", "root_cause", "corrective_action")


def main():
    mem = Memory()
    for case in SEED_CASES:
        id_ = case["id"]
        mem.write_failure("external", id_, {k: case[k] for k in FIELD_KEYS})
        print(id_)

    try:
        results = mem.search_failures("high pressure tank rupture due to material defect", k=3)
        print("\nSanity search results:")
        for r in results:
            print(f"  {r['id']}  score={r['score']:.4f}  {r['failure_mode']}")
    except Exception as e:
        print(f"\nSanity search skipped: {e}")


if __name__ == "__main__":
    main()
