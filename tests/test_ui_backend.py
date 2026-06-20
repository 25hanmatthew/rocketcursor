import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ui.backend.app import app


ROOT = Path(__file__).resolve().parents[1]


class UiBackendTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_schema_endpoint_returns_existing_schema(self):
        response = self.client.get("/api/schema")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["type"], "object")
        self.assertIn("nodes", payload["required"])

    def test_upload_config_runs_existing_cli_and_writes_artifacts(self):
        config_path = ROOT / "network_configs/tank_vent_to_atmosphere.json"
        with config_path.open("rb") as handle:
            response = self.client.post(
                "/api/runs",
                files={"file": ("tank_vent_to_atmosphere.json", handle, "application/json")},
                data={"duration": "0.1", "dt": "0.05"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["ok"], payload)
        self.assertIn("report.json", payload["artifacts"])
        self.assertIn("nodes.csv", payload["artifacts"])
        self.assertIn("connections.csv", payload["artifacts"])
        self.assertEqual(payload["report"]["duration"], 0.1)
        self.assertEqual(payload["report"]["dt"], 0.05)

        saved_config = self.client.get(f"/api/runs/{payload['run_id']}/config")
        self.assertEqual(saved_config.status_code, 200)
        original = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_config.json()["settings"], original["settings"])

    def test_failed_run_returns_structured_error(self):
        response = self.client.post(
            "/api/runs",
            files={
                "file": (
                    "bad.json",
                    json.dumps({"version": 1.1, "nodes": [], "connections": []}),
                    "application/json",
                )
            },
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["message"], "Simulation failed")
        self.assertIn("run_id", payload)

    def test_artifact_endpoint_blocks_unknown_names(self):
        response = self.client.get("/api/runs/abc/artifact/../report.json")
        self.assertIn(response.status_code, {404, 422})

        response = self.client.get("/api/runs/abc/artifact/summary.json")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
