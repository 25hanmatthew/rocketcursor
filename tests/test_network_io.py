import json
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

warnings.simplefilter("ignore", ResourceWarning)

import general_fluid_network as gfn
from network_io import NetworkConfigError, load_network_config

ROOT = Path(__file__).resolve().parents[1]


class NetworkIoTests(unittest.TestCase):
    def test_load_known_good_configs(self):
        cases = [
            ("network_configs/impulse_ep.json", 2, 1, 0),
            ("network_configs/pressure_ladder_from_py.json", 4, 4, 22),
            ("network_configs/vehicle_sim.json", 4, 4, 40),
            ("network_configs/tank_sizing_sims.json", 4, 4, 72),
            ("network_configs/test_1.json", 3, 2, 0),
        ]
        for rel_path, node_count, conn_count, action_count in cases:
            with self.subTest(rel_path=rel_path):
                loaded = load_network_config(ROOT / rel_path)
                self.assertEqual(len(loaded.nodes), node_count)
                self.assertEqual(len(loaded.connections), conn_count)
                self.assertEqual(sum(len(v) for v in loaded.actions.values()), action_count)

    def test_stale_gui_params_do_not_break_construction(self):
        data = json.loads((ROOT / "network_configs/impulse_ep.json").read_text(encoding="utf-8"))
        data["connections"][0]["type"] = "ThrottleValve"
        data["connections"][0]["params"] = {
            "CdA_max": 1e-6,
            "target_mdot": 0.1,
            "step": 0.02,
            "qdot": 0.0,
            "location": 1,
            "normal_state": 1,
            "checking": 1,
            "name": "stale_throttle"
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stale.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_network_config(path)
        self.assertEqual(len(loaded.nodes), 2)
        self.assertEqual(len(loaded.connections), 1)

    def test_pvt_node_loads_and_computes_mass(self):
        loaded = load_network_config(ROOT / "network_configs/tank_vent_to_atmosphere.json")
        tank = loaded.nodes[0]
        params = loaded.data["nodes"][0]["params"]
        rho = gfn.PropsSI_auto(
            "D",
            "P",
            float(params["P"]),
            "T",
            float(params["T"]),
            params["fluid"],
        )
        expected_mass = rho * (float(params["V"]) / 1000.0)
        self.assertAlmostEqual(tank.m, expected_mass, places=8)

    def test_legacy_mvt_node_still_loads(self):
        data = json.loads((ROOT / "network_configs/impulse_ep.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_network_config(path)
        self.assertGreater(loaded.nodes[1].m, 0)

    def test_pvt_wins_over_legacy_mass_and_warns(self):
        data = json.loads((ROOT / "network_configs/tank_vent_to_atmosphere.json").read_text(encoding="utf-8"))
        data["nodes"][0]["params"]["m"] = 999.0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conflict.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_network_config(path)
        self.assertLess(loaded.nodes[0].m, 999.0)
        self.assertTrue(any("ignoring m" in warning for warning in loaded.warnings))

    def test_missing_endpoint_fails_validation(self):
        data = json.loads((ROOT / "network_configs/impulse_ep.json").read_text(encoding="utf-8"))
        data["connections"][0]["end_id"] = 999
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(NetworkConfigError) as ctx:
                load_network_config(path)
        self.assertIn("$.connections[0].end_id", str(ctx.exception))

    def test_unknown_component_type_fails_validation(self):
        data = json.loads((ROOT / "network_configs/impulse_ep.json").read_text(encoding="utf-8"))
        data["connections"][0]["type"] = "MadeUpValve"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(NetworkConfigError) as ctx:
                load_network_config(path)
        self.assertIn("unsupported connection type", str(ctx.exception))

    def test_unknown_action_target_fails_validation(self):
        data = json.loads((ROOT / "network_configs/impulse_ep.json").read_text(encoding="utf-8"))
        data["actions"] = [{"time": "0.1", "component": "missing", "state": "1"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(NetworkConfigError) as ctx:
                load_network_config(path)
        self.assertIn("unknown action target", str(ctx.exception))

    def test_node_missing_p_and_m_fails_validation(self):
        data = json.loads((ROOT / "network_configs/tank_vent_to_atmosphere.json").read_text(encoding="utf-8"))
        del data["nodes"][0]["params"]["P"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(NetworkConfigError) as ctx:
                load_network_config(path)
        self.assertIn("Node requires preferred P/V/T/fluid", str(ctx.exception))

    def test_node_non_numeric_pvt_fails_validation(self):
        data = json.loads((ROOT / "network_configs/tank_vent_to_atmosphere.json").read_text(encoding="utf-8"))
        data["nodes"][0]["params"]["P"] = "high"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(NetworkConfigError) as ctx:
                load_network_config(path)
        self.assertIn("$.nodes[0].params.P: expected a number", str(ctx.exception))

    def test_invalid_engine_wiring_fails_validation(self):
        data = json.loads((ROOT / "network_configs/vehicle_sim.json").read_text(encoding="utf-8"))
        data["connections"] = data["connections"][:3]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(NetworkConfigError) as ctx:
                load_network_config(path)
        self.assertIn("Engine requires exactly one oxidizer feed", str(ctx.exception))

    def test_cli_validate_only(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "run_network.py"),
                str(ROOT / "network_configs/impulse_ep.json"),
                "--validate-only",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        self.assertTrue(payload["ok"])

    def test_cli_run_exports_results_and_honors_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "tank_vent"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "run_network.py"),
                    str(ROOT / "network_configs/tank_vent_to_atmosphere.json"),
                    "--duration",
                    "0.2",
                    "--dt",
                    "0.1",
                    "--out",
                    str(out_dir),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out_dir / "nodes.csv").exists())
            self.assertTrue((out_dir / "connections.csv").exists())
            self.assertTrue((out_dir / "nodes_summary.json").exists())
            self.assertTrue((out_dir / "connections_summary.json").exists())
            diagnostics_path = out_dir / "diagnostics.json"
            self.assertTrue(diagnostics_path.exists())
            report_path = out_dir / "report.json"
            self.assertTrue(report_path.exists())
            self.assertTrue((out_dir / "report.md").exists())
            summary_path = out_dir / "summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["duration"], 0.2)
            self.assertEqual(summary["dt"], 0.1)
            self.assertIn("diagnostics", summary)
            self.assertIn("diagnostics_json", summary["output_files"])
            self.assertIn("report_json", summary["output_files"])
            self.assertIn("report_markdown", summary["output_files"])
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            self.assertEqual(diagnostics["step_count"], 2)
            self.assertIn("has_nonzero_flow", diagnostics["checks"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], "1.1")
            self.assertIn("status_policy", report)
            self.assertFalse(report["status_policy"]["warnings_fail_run"])
            self.assertIn("units", report)
            self.assertEqual(report["units"]["P"], "Pa")
            self.assertIn("components", report)
            self.assertIn("derived_stats", report)
            self.assertIn("interpretation", report)
            self.assertIsInstance(report["status"]["passed"], bool)
            self.assertIn("pressurized_tank", report["key_stats"]["nodes"])
            self.assertIn("vent_orifice", report["key_stats"]["connections"])
            self.assertEqual(report["components"]["pressurized_tank"]["role"], "tank")
            self.assertEqual(report["components"]["atmosphere"]["role"], "boundary")
            self.assertEqual(report["components"]["vent_orifice"]["role"], "vent")
            pressure_field = report["key_stats"]["nodes"]["pressurized_tank"]["fields"]["P"]
            self.assertEqual(pressure_field["unit"], "Pa")
            self.assertEqual(pressure_field["label"], "pressure")
            tank_stats = report["derived_stats"]["nodes"]["pressurized_tank"]
            self.assertIn("pressure_drop_pa", tank_stats)
            self.assertIn("mass_change_kg", tank_stats)
            self.assertEqual(report["interpretation"]["outcome"], "nominal")


if __name__ == "__main__":
    unittest.main()
