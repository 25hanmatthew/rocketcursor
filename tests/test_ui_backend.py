import json
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from ui.backend.app import app


ROOT = Path(__file__).resolve().parents[1]


def _wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    return predicate()


def _fake_loop_run(spec_path, max_iters=8, use_compression=False, store=None,
                   session_id=None, request=None, max_restarts=2):
    from loop.session_state import new_state

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    run_root = ROOT / "results" / "loop_runs" / spec["name"] / "iter_00"
    run_root.mkdir(parents=True, exist_ok=True)
    design = {
        "settings": {"duration": 0.1, "dt": 0.05},
        "nodes": [
            {"id": 0, "type": "Node", "params": {"name": "tank", "fluid": "Nitrogen", "P": 1e6, "V": 1.0, "T": 293.15}},
            {"id": 1, "type": "Ambient", "params": {"name": "atm", "fluid": "Air", "P": 101325.0, "T": 293.15}},
        ],
        "connections": [
            {"type": "Connection", "start_id": 0, "end_id": 1, "params": {"name": "vent", "CdA": 1e-6}},
        ],
        "actions": [],
    }
    (run_root / "design.json").write_text(json.dumps(design), encoding="utf-8")
    (run_root / "simulation_result.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    (run_root / "report.json").write_text(json.dumps({
        "ok": True,
        "duration": 0.1,
        "dt": 0.05,
        "status": {"passed": True, "failures": [], "warnings": [], "checks": {"has_nonzero_flow": True}},
        "interpretation": {"important_observations": []},
    }), encoding="utf-8")
    (run_root / "nodes.csv").write_text(
        "component,kind,time,P,T,m\n"
        "tank,Node,0,1000000,293.15,1\n"
        "tank,Node,0.1,900000,293.15,0.9\n",
        encoding="utf-8",
    )
    (run_root / "connections.csv").write_text(
        "component,kind,time,mdot,state\n"
        "vent,Connection,0,0.1,1\n"
        "vent,Connection,0.1,0.05,1\n",
        encoding="utf-8",
    )
    state = new_state(session_id or spec["name"], request or "request", "test", "test")
    state["status"] = "passed"
    state["stage"] = "report"
    state["passed"] = True
    state["iterations_used"] = 1
    state["iterations"] = [{
        "iteration": 0,
        "status": "ok",
        "verdict": {
            "passed": True,
            "summary": "1/1 checks passed",
            "checks": [{
                "id": "ran",
                "description": "ran",
                "passed": True,
                "op": "==",
                "expected": "ok",
                "actual": "ok",
                "detail": "",
            }],
        },
    }]
    if store:
        store.write(state)
    return {"passed": True, "iterations_used": 1, "iterations": []}


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
        config_path = ROOT / "simulator/network_configs/tank_vent_to_atmosphere.json"
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

    @mock.patch("ui.backend.app.run_loop", side_effect=_fake_loop_run)
    def test_design_run_starts_and_exposes_latest_artifacts(self, _run_loop):
        response = self.client.post(
            "/api/design-runs",
            json={"message": json.dumps({"name": "inline_demo", "checks": []})},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["ok"])
        session_id = payload["session_id"]

        def ready_status():
            res = self.client.get(f"/api/design-runs/{session_id}")
            if res.status_code != 200:
                return None
            data = res.json()
            return data if data["state"]["status"] == "passed" else None

        status = _wait_for(ready_status)
        self.assertTrue(status["ok"], status)
        self.assertEqual(status["state"]["status"], "passed")
        self.assertEqual(status["latest_playable"]["iteration"], 0)
        self.assertIn("design.json", status["latest_playable"]["artifacts"])

        artifact = self.client.get(f"/api/design-runs/{session_id}/artifact/0/design.json")
        self.assertEqual(artifact.status_code, 200)
        self.assertEqual(artifact.json()["nodes"][0]["params"]["name"], "tank")

    @mock.patch("ui.backend.app.run_loop", side_effect=_fake_loop_run)
    def test_design_run_loosen_exact_ambient_pressure_check(self, _run_loop):
        spec = {
            "name": "ambient_exact",
            "checks": [
                {
                    "id": "ambient_pressure",
                    "description": "Ambient node must be at atmospheric pressure",
                    "type": "component",
                    "component": "ambient",
                    "field": "P",
                    "stat": "final",
                    "op": "==",
                    "value": 101325.0,
                }
            ],
        }
        response = self.client.post("/api/design-runs", json={"message": json.dumps(spec)})
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.json()["session_id"]
        status = _wait_for(
            lambda: (
                data if (data := self.client.get(f"/api/design-runs/{session_id}").json())["state"]["status"] == "passed"
                else None
            )
        )
        materialized = json.loads(Path(status["manifest"]["spec_path"]).read_text(encoding="utf-8"))
        checks = {check["id"]: check for check in materialized["checks"]}
        self.assertNotIn("ambient_pressure", checks)
        self.assertEqual(checks["ambient_pressure_min"]["op"], ">=")
        self.assertEqual(checks["ambient_pressure_min"]["value"], 101225.0)
        self.assertEqual(checks["ambient_pressure_max"]["op"], "<=")
        self.assertEqual(checks["ambient_pressure_max"]["value"], 101425.0)

    @mock.patch("ui.backend.app.run_loop", side_effect=_fake_loop_run)
    @mock.patch("ui.backend.app.nl_to_spec")
    def test_design_run_accepts_plain_english_via_mocked_spec_writer(self, spec_writer, _run_loop):
        spec_writer.return_value = {"name": "mocked_spec", "checks": []}
        response = self.client.post("/api/design-runs", json={"message": "vent a small tank"})
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.json()["session_id"]
        status = _wait_for(
            lambda: (
                data if (data := self.client.get(f"/api/design-runs/{session_id}").json())["state"]["status"] == "passed"
                else None
            )
        )
        self.assertEqual(status["state"]["status"], "passed")
        spec_writer.assert_called_once()

    @mock.patch("ui.backend.app.run_loop", side_effect=_fake_loop_run)
    def test_design_artifact_endpoint_blocks_unknown_names(self, _run_loop):
        response = self.client.post(
            "/api/design-runs",
            json={"message": json.dumps({"name": "artifact_block", "checks": []})},
        )
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.json()["session_id"]
        _wait_for(lambda: self.client.get(f"/api/design-runs/{session_id}").json().get("latest_playable"))

        response = self.client.get(f"/api/design-runs/{session_id}/artifact/0/secrets.txt")
        self.assertEqual(response.status_code, 404)

        response = self.client.get(f"/api/design-runs/{session_id}/artifact/0/../design.json")
        self.assertIn(response.status_code, {404, 422})


if __name__ == "__main__":
    unittest.main()
