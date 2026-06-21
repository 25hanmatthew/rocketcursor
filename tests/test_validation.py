"""Phase 6 validation tests: deterministic design rules over a synthesized
vehicle, plus a small Monte Carlo dispersion (guarded on RocketPy).

The design-rule tests are hermetic and fast (build a package + vehicle via the
analytic fallback, then check rules). The Monte Carlo test is the slow one and
is skipped without RocketPy.

    python -m unittest tests.test_validation
"""

import json
import tempfile
import unittest
from pathlib import Path

from backend.common.contracts import REPO_ROOT
from backend.propulsion_package import build_package
from backend.vehicle_synthesis import synthesize_vehicle
from backend.validation.design_rules import check_design_rules

try:
    import rocketpy  # noqa: F401
    HAVE_ROCKETPY = True
except Exception:
    HAVE_ROCKETPY = False

SEED = REPO_ROOT / "loop" / "design_seeds" / "pressure_fed_lox_kerosene.json"
MISSION = REPO_ROOT / "shared" / "examples" / "mission_spec.pressure_fed_kero_lox.json"


def _vehicle_and_package(tmp: Path):
    design = json.loads(SEED.read_text())
    pkg = build_package(design, tmp / "package")
    veh = synthesize_vehicle(pkg, tmp / "package", MISSION, tmp / "vehicle")
    return veh, pkg


class TestDesignRules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.veh, self.pkg = _vehicle_and_package(Path(self._tmp.name))
        self.mission = json.loads(MISSION.read_text())

    def tearDown(self):
        self._tmp.cleanup()

    def test_structure_and_severities(self):
        report = check_design_rules(self.veh, self.pkg, {"apogee_m": 9000.0, "rail_departure_velocity_ms": 25.0}, self.mission)
        self.assertIn("passed", report)
        self.assertIn("findings", report)
        for f in report["findings"]:
            self.assertIn(f["severity"], {"pass", "warn", "fail"})
            self.assertEqual(f["passed"], f["severity"] != "fail")
        # a stable, in-envelope design with good rail velocity has no hard fails
        self.assertTrue(report["passed"], report["summary"])

    def test_overweight_design_fails_constraint(self):
        mission = json.loads(MISSION.read_text())
        mission["constraints"]["maximum_launch_mass_kg"] = 1.0  # force a fit failure
        report = check_design_rules(self.veh, self.pkg, {"rail_departure_velocity_ms": 25.0}, mission)
        mass_rule = next(f for f in report["findings"] if f["rule"] == "fits_max_launch_mass")
        self.assertEqual(mass_rule["severity"], "fail")
        self.assertFalse(report["passed"])

    def test_low_rail_velocity_warns(self):
        report = check_design_rules(self.veh, self.pkg, {"rail_departure_velocity_ms": 12.0}, self.mission)
        rail = next(f for f in report["findings"] if f["rule"] == "rail_exit_velocity")
        self.assertIn(rail["severity"], {"warn", "fail"})


@unittest.skipUnless(HAVE_ROCKETPY, "rocketpy not installed")
class TestMonteCarlo(unittest.TestCase):
    def test_dispersion_runs_and_is_reproducible(self):
        import warnings

        warnings.filterwarnings("ignore")
        from backend.validation.monte_carlo import run_monte_carlo

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            veh, pkg = _vehicle_and_package(tmp)
            a = run_monte_carlo(veh, pkg, tmp / "package", trials=3, seed=42)
            b = run_monte_carlo(veh, pkg, tmp / "package", trials=3, seed=42)
            self.assertEqual(a["completed"], 3)
            self.assertEqual(a["apogee_m"]["mean"], b["apogee_m"]["mean"])  # same seed -> same result
            self.assertGreater(a["apogee_m"]["mean"], 0.0)


if __name__ == "__main__":
    unittest.main()
