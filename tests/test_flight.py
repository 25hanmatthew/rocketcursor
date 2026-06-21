"""Phase 4 smoke test: the full P&ID -> package -> vehicle -> 6DOF flight chain
produces a schema-valid flight_result with an ordered event sequence and a
positive apogee. Skipped where RocketPy is unavailable.

This is the heavy end-to-end test (it integrates a real trajectory), so it lives
on its own and uses the analytic-fallback package (no CEA needed).

    python -m unittest tests.test_flight
"""

import json
import tempfile
import unittest
from pathlib import Path

from backend.common.contracts import REPO_ROOT

try:
    import rocketpy  # noqa: F401
    HAVE_ROCKETPY = True
except Exception:
    HAVE_ROCKETPY = False

SEED = REPO_ROOT / "loop" / "design_seeds" / "pressure_fed_lox_kerosene.json"
MISSION = REPO_ROOT / "shared" / "examples" / "mission_spec.pressure_fed_kero_lox.json"


@unittest.skipUnless(HAVE_ROCKETPY, "rocketpy not installed")
class TestFlightEndToEnd(unittest.TestCase):
    def test_pipeline_produces_a_flight(self) -> None:
        import warnings

        warnings.filterwarnings("ignore")
        from backend.propulsion_package import build_package
        from backend.vehicle_synthesis import synthesize_vehicle
        from backend.flight.run_flight import COLUMNS, run_flight

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = json.loads(SEED.read_text(encoding="utf-8"))
            pkg = build_package(design, root / "package")
            veh = synthesize_vehicle(pkg, root / "package", MISSION, root / "vehicle")
            out = run_flight(veh, pkg, root / "package", root / "flight", target_apogee_m=10000, dt=0.2)

            # flight.csv exists with the contract columns
            header = (root / "flight" / "flight.csv").read_text().splitlines()[0].split(",")
            self.assertEqual(header, COLUMNS)
            self.assertGreater(out["rows"], 10)

            # events occur in a physically sensible order
            ev = out["events"]
            self.assertLessEqual(ev["ignition"], ev["rail_departure"])
            self.assertLessEqual(ev["rail_departure"], ev["burnout"])
            self.assertLessEqual(ev["burnout"], ev["apogee"])
            self.assertLessEqual(ev["apogee"], ev["landing"])

            # the rocket actually climbed
            self.assertGreater(out["report"]["apogee_m"], 0.0)
            self.assertEqual(out["report"]["backend"], "rocketpy")


if __name__ == "__main__":
    unittest.main()
