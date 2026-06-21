"""Tests for Phase 2 propulsion physicalization and the Phase 2b convergence loop.

These exercise the analytic-fallback path (no CEA engine required), so they run
in any environment where CoolProp is importable -- the same dependency the solver
tests already assume. The package is validated against its JSON Schema, so a
contract drift breaks the test.

    python -m unittest tests.test_propulsion_package
"""

import json
import tempfile
import unittest
from pathlib import Path

from backend.common.contracts import REPO_ROOT, is_valid
from backend.propulsion_package import build_package
from backend.propulsion_package.convergence import converge_package

SEED = REPO_ROOT / "loop" / "design_seeds" / "pressure_fed_lox_kerosene.json"


def _design() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


class TestBuildPackage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)
        self.pkg = build_package(_design(), self.run_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_schema_valid(self) -> None:
        self.assertTrue(is_valid(self.pkg, "propulsion_package"))

    def test_one_component_per_pid_part(self) -> None:
        types = sorted(c["type"] for c in self.pkg["components"])
        # 2 propellant tanks, 1 bottle, 1 engine, 2 feed lines
        self.assertEqual(types.count("propellant_tank"), 2)
        self.assertEqual(types.count("pressurant_bottle"), 1)
        self.assertEqual(types.count("engine"), 1)
        self.assertEqual(types.count("feed_line"), 2)

    def test_masses_and_geometry_positive(self) -> None:
        for c in self.pkg["components"]:
            self.assertGreater(c["dry_mass_kg"], 0.0, c["id"])
            self.assertGreaterEqual(c["geometry"].get("diameter_m", 0.0), 0.0, c["id"])

    def test_stack_is_ordered_and_non_overlapping(self) -> None:
        # Engine sits at the nozzle end (z=0 side); tanks and bottle are nose-ward.
        by_id = {c["id"]: c for c in self.pkg["components"]}
        self.assertLess(by_id["engine.01"]["position_m"][2], by_id["tank.lox.01"]["position_m"][2])
        self.assertLess(by_id["tank.kerosene.01"]["position_m"][2], by_id["bottle.gn2.01"]["position_m"][2])

    def test_every_component_field_has_provenance(self) -> None:
        for c in self.pkg["components"]:
            self.assertIn("provenance", c, c["id"])
            self.assertTrue(c["provenance"], c["id"])

    def test_performance_and_artifacts(self) -> None:
        perf = self.pkg["performance"]
        self.assertGreater(perf["burn_time_s"], 0.0)
        self.assertGreater(perf["peak_thrust_n"], 0.0)
        self.assertGreater(perf["total_impulse_ns"], 0.0)
        for rel in ("thrust_curve", ):
            self.assertTrue((self.run_dir / perf[rel]).exists())
        for key in ("total_mass", "center_of_mass", "inertia"):
            self.assertTrue((self.run_dir / self.pkg["time_series"][key]).exists())

    def test_min_inner_diameter_exceeds_largest_component(self) -> None:
        max_d = max(c["geometry"].get("diameter_m", 0.0) for c in self.pkg["components"])
        self.assertGreater(self.pkg["constraints"]["minimum_vehicle_inner_diameter_m"], max_d)


class TestConvergence(unittest.TestCase):
    def test_converges_and_writes_line_lengths_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = converge_package(_design(), tmp, max_iters=6)
            conv = pkg["convergence"]
            self.assertTrue(conv["converged"])
            self.assertLessEqual(conv["iterations"], 6)
            # routed feed-line lengths are reflected in the final package geometry
            lines = [c for c in pkg["components"] if c["type"] == "feed_line"]
            self.assertTrue(all(c["geometry"]["length_m"] > 0 for c in lines))
            self.assertTrue((Path(tmp) / "convergence.json").exists())


if __name__ == "__main__":
    unittest.main()
