import json
import tempfile
import unittest
from pathlib import Path

from fluid_network_mcp import (
    get_network_schema,
    read_result,
    run_network,
    validate_network,
)

ROOT = Path(__file__).resolve().parents[1]


class FluidNetworkMcpTests(unittest.TestCase):
    def test_get_network_schema_returns_json_object(self):
        schema = get_network_schema()
        self.assertIsInstance(schema, dict)
        self.assertEqual(schema["type"], "object")
        self.assertIn("properties", schema)

    def test_validate_network_succeeds_for_tank_vent(self):
        result = validate_network(
            config_path=str(ROOT / "network_configs/tank_vent_to_atmosphere.json")
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["component_counts"]["nodes"], 2)
        self.assertEqual(result["component_counts"]["connections"], 1)
        self.assertGreater(result["duration"], 0)
        self.assertGreater(result["dt"], 0)

    def test_validate_network_rejects_both_config_sources(self):
        result = validate_network(
            config_path=str(ROOT / "network_configs/tank_vent_to_atmosphere.json"),
            config_json={"version": 1.1},
        )
        self.assertFalse(result["ok"])
        self.assertIn("not both", result["errors"][0])

    def test_run_network_inline_json_writes_outputs(self):
        data = json.loads(
            (ROOT / "network_configs/tank_vent_to_atmosphere.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "tank_vent"
            result = run_network(
                config_json=data,
                output_dir=str(out_dir),
                duration=0.1,
                dt=0.05,
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["duration"], 0.1)
            self.assertEqual(result["dt"], 0.05)
            for path in result["output_files"].values():
                self.assertTrue(Path(path).exists(), path)

            summary = read_result(str(out_dir), "summary.json")
            self.assertTrue(summary["ok"], summary)
            self.assertEqual(summary["content"]["duration"], 0.1)

    def test_read_result_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = read_result(tmp, "../summary.json")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "Unsupported result_name")


if __name__ == "__main__":
    unittest.main()
