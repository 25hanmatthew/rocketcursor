"""Tests for Phase 3 vehicle synthesis: a propulsion package + mission_spec is
turned into a schema-valid vehicle_model with a stable, auto-sized fin set.

Hermetic (analytic-fallback package, no CEA). Runs wherever CoolProp imports.

    python -m unittest tests.test_vehicle_synthesis
"""

import json
import tempfile
import unittest
from pathlib import Path

from backend.common.contracts import REPO_ROOT, is_valid
from backend.propulsion_package import build_package
from backend.vehicle_synthesis import synthesize_vehicle

SEED = REPO_ROOT / "loop" / "design_seeds" / "pressure_fed_lox_kerosene.json"
MISSION = REPO_ROOT / "shared" / "examples" / "mission_spec.pressure_fed_kero_lox.json"


class TestSynthesizeVehicle(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.pkg_dir = root / "package"
        self.veh_dir = root / "vehicle"
        design = json.loads(SEED.read_text(encoding="utf-8"))
        self.pkg = build_package(design, self.pkg_dir)
        self.veh = synthesize_vehicle(self.pkg, self.pkg_dir, MISSION, self.veh_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_schema_valid(self) -> None:
        self.assertTrue(is_valid(self.veh, "vehicle_model"))

    def test_body_diameter_driven_by_package(self) -> None:
        min_inner = self.pkg["constraints"]["minimum_vehicle_inner_diameter_m"]
        self.assertGreaterEqual(self.veh["geometry"]["body_diameter_m"], min_inner)

    def test_statically_stable(self) -> None:
        margin = self.veh["aerodynamics"]["static_margin_cal"]
        self.assertGreaterEqual(margin, 1.0)  # CP aft of CG by >= 1 caliber
        # CP must be aft (lower z, toward nozzle) of the loaded CG.
        self.assertLess(self.veh["aerodynamics"]["cp_z_m"], self.veh["mass_properties"]["loaded_cg_z_m"])

    def test_loaded_heavier_than_dry(self) -> None:
        mp = self.veh["mass_properties"]
        self.assertGreater(mp["loaded_mass_kg"], mp["dry_mass_kg"])

    def test_fins_have_three_or_more(self) -> None:
        self.assertGreaterEqual(self.veh["geometry"]["fins"]["count"], 3)

    def test_render_hints_present(self) -> None:
        render = self.veh["geometry"]["render"]
        self.assertIn("nose", render)
        self.assertIn("body", render)
        self.assertIn("fins", render)
        self.assertTrue(render["package"])  # package primitives passed through for R3F

    def test_timeseries_written(self) -> None:
        for key in ("total_mass", "center_of_mass", "inertia"):
            self.assertTrue((self.veh_dir / self.veh["mass_properties"]["time_series"][key]).exists())


if __name__ == "__main__":
    unittest.main()
