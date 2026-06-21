"""Tests for the design loop: the deterministic evaluator (the heart of P2),
the simulator adapter's run classification, and request resolution.

No API key required. The adapter tests run the real (fast, non-engine) solver.

    python -m unittest tests.test_loop
"""

import json
import tempfile
import unittest
from pathlib import Path

from loop.evaluator import evaluate
from loop.simulator_adapter import run_design


def _ok_result():
    """A synthetic 'clean run' simulation_result for evaluator tests."""
    return {
        "status": "ok",
        "errors": [],
        "diagnostics": {
            "checks": {
                "has_nonzero_flow": True,
                "has_node_samples": True,
                "has_connection_samples": True,
            },
            "warnings": [],
            "duration": 12.0,
            "dt": 0.01,
        },
        "components": {
            "tank": {"kind": "Node", "fields": {
                "P": {"first": 6.0e6, "final": 2.3e6, "min": 2.3e6, "max": 6.0e6,
                      "delta": -3.7e6, "range": 3.7e6, "nonzero_count": 200, "sample_count": 200},
            }},
            "vent": {"kind": "Connection", "fields": {
                "mdot": {"first": 0.04, "final": 0.0, "min": 0.0, "max": 0.04,
                         "delta": -0.04, "range": 0.04, "nonzero_count": 199, "sample_count": 200},
            }},
        },
    }


class TestEvaluator(unittest.TestCase):
    def _verdict(self, checks, result=None):
        return evaluate({"name": "t", "checks": checks}, result or _ok_result())

    def test_status_check_passes(self):
        v = self._verdict([{"id": "ran", "type": "status", "op": "==", "value": "ok"}])
        self.assertTrue(v.passed)

    def test_component_window_pass_and_fail(self):
        v = self._verdict([
            {"id": "hi", "type": "component", "component": "tank", "field": "P", "stat": "final", "op": "<=", "value": 2.5e6},
            {"id": "lo", "type": "component", "component": "tank", "field": "P", "stat": "final", "op": ">=", "value": 2.0e6},
        ])
        self.assertTrue(v.passed)
        # tighten the window so the actual 2.3 MPa fails the lower bound
        v2 = self._verdict([
            {"id": "lo", "type": "component", "component": "tank", "field": "P", "stat": "final", "op": ">=", "value": 2.4e6},
        ])
        self.assertFalse(v2.passed)
        self.assertEqual(v2.checks[0].actual, 2.3e6)

    def test_delta_stat(self):
        v = self._verdict([
            {"id": "drop", "type": "component", "component": "tank", "field": "P", "stat": "delta", "op": "<", "value": -5e5},
        ])
        self.assertTrue(v.passed)

    def test_sim_and_no_warnings_and_diagnostics(self):
        v = self._verdict([
            {"id": "flow", "type": "sim", "field": "has_nonzero_flow", "op": "==", "value": True},
            {"id": "clean", "type": "no_warnings", "op": "==", "value": True},
            {"id": "dur", "type": "diagnostics", "field": "duration", "op": ">=", "value": 11.9},
        ])
        self.assertTrue(v.passed)

    def test_no_warnings_fails_when_present(self):
        res = _ok_result()
        res["diagnostics"]["warnings"] = [{"message": "Node 'tank' has nonphysical P values."}]
        v = self._verdict([{"id": "clean", "type": "no_warnings", "op": "==", "value": True}], res)
        self.assertFalse(v.passed)

    def test_no_warnings_ignores_benign_engine_mass_warning_only(self):
        res = _ok_result()
        res["components"]["engine"] = {"kind": "Engine", "fields": {}}
        res["diagnostics"]["warnings"] = [
            {
                "message": "Non-ambient node 'engine' has unchanged m history.",
                "component": "engine",
                "field": "m",
            }
        ]
        v = self._verdict([{"id": "clean", "type": "no_warnings", "op": "==", "value": True}], res)
        self.assertTrue(v.passed)

        res["diagnostics"]["warnings"].append(
            {
                "message": "Node 'engine' has nonphysical P values.",
                "component": "engine",
                "field": "P",
            }
        )
        v = self._verdict([{"id": "clean", "type": "no_warnings", "op": "==", "value": True}], res)
        self.assertFalse(v.passed)

    def test_status_gate_fails_all_when_not_ok(self):
        res = {"status": "crashed", "errors": ["RuntimeError: boom"]}
        v = self._verdict([
            {"id": "ran", "type": "status", "op": "==", "value": "ok"},
            {"id": "flow", "type": "sim", "field": "has_nonzero_flow", "op": "==", "value": True},
        ], res)
        self.assertFalse(v.passed)
        self.assertTrue(all(not c.passed for c in v.checks))
        self.assertTrue(any("crashed" in n for n in v.notes))

    def test_missing_component_fails_with_detail(self):
        v = self._verdict([
            {"id": "x", "type": "component", "component": "nonexistent", "field": "P", "stat": "final", "op": "<", "value": 1.0},
        ])
        self.assertFalse(v.passed)
        self.assertIn("no component", v.checks[0].detail)

    def test_missing_field_fails_with_detail(self):
        v = self._verdict([
            {"id": "x", "type": "component", "component": "tank", "field": "mdot", "stat": "final", "op": "<", "value": 1.0},
        ])
        self.assertFalse(v.passed)
        self.assertIn("no field", v.checks[0].detail)

    def test_operators(self):
        res = _ok_result()
        cases = [(">", 2.0e6, True), ("<", 2.0e6, False), ("==", 2.3e6, True), ("!=", 2.3e6, False)]
        for op, val, expected in cases:
            v = self._verdict([{"id": "o", "type": "component", "component": "tank",
                                "field": "P", "stat": "final", "op": op, "value": val}], res)
            self.assertEqual(v.passed, expected, f"op {op} {val}")


class TestSimulatorAdapter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _vent_design(self, cda=1e-5):
        return {
            "settings": {"duration": 2.0, "dt": 0.1},
            "nodes": [
                {"id": 0, "type": "Node", "params": {"fluid": "Nitrogen", "P": 6e6, "V": 8.0, "T": 293.15, "name": "tank"}},
                {"id": 1, "type": "Ambient", "params": {"fluid": "Air", "P": 101325.0, "T": 293.15, "name": "atm"}},
            ],
            "connections": [
                {"type": "Connection", "start_id": 0, "end_id": 1,
                 "params": {"CdA": cda, "location": 0.0, "normal_state": 1, "checking": 1, "name": "vent"}},
            ],
            "actions": [],
        }

    def test_ok_run_populates_components(self):
        r = run_design(self._vent_design(), self.run_dir)
        self.assertEqual(r["status"], "ok")
        self.assertIn("tank", r["components"])
        self.assertIn("P", r["components"]["tank"]["fields"])
        self.assertTrue(r["diagnostics"]["checks"]["has_nonzero_flow"])
        # result is always written to disk
        self.assertTrue((self.run_dir / "simulation_result.json").exists())

    def test_invalid_config_classified(self):
        bad = {"settings": {"duration": 2.0, "dt": 0.1}, "nodes": [], "connections": [
            {"type": "Connection", "start_id": 99, "end_id": 100, "params": {"CdA": 1e-5, "name": "v"}}]}
        r = run_design(bad, self.run_dir)
        self.assertEqual(r["status"], "invalid_config")
        self.assertTrue(r["errors"])


class TestRequestResolution(unittest.TestCase):
    def test_resolve_name_inline_and_unknown(self):
        from loop.service import resolve_spec, available_specs

        self.assertIn("tank_blowdown", available_specs())

        path, err = resolve_spec("tank_blowdown")
        self.assertIsNone(err)
        self.assertTrue(path.exists())

        path, err = resolve_spec("nope_not_a_spec")
        self.assertIsNone(path)
        self.assertIn("unknown spec", err)

        path, err = resolve_spec(json.dumps({"name": "inline_t", "checks": []}))
        self.assertIsNone(err)
        self.assertEqual(json.loads(path.read_text())["name"], "inline_t")

        path, err = resolve_spec("{ not valid json")
        self.assertIsNone(path)
        self.assertIn("parse", err)


class TestSessionState(unittest.TestCase):
    def test_node_status_colors(self):
        from loop.session_state import node_status_from_verdict

        result = {
            "components": {"tank": {"fields": {}}, "vent": {"fields": {}}, "atm": {"fields": {}}},
            "diagnostics": {"warnings": [{"component": "vent", "message": "all-zero mdot"}]},
        }
        verdict = {"passed": False, "checks": [
            {"id": "w", "passed": False, "op": "<=", "expected": 2.5e6, "actual": 4.9e6,
             "detail": "tank.P.final=4.9e6"},
            {"id": "ran", "passed": True, "op": "==", "expected": "ok", "actual": "ok", "detail": ""},
        ]}
        status = node_status_from_verdict(result, verdict)
        self.assertEqual(status["tank"], "red")     # failed check references it
        self.assertEqual(status["vent"], "yellow")  # solver warning references it
        self.assertEqual(status["atm"], "green")    # untouched

    def test_requirements_view_flattens_checks(self):
        from loop.session_state import requirements_view

        spec = {"name": "s", "description": "d", "checks": [
            {"id": "p", "type": "component", "component": "tank", "field": "P", "stat": "final",
             "op": "<=", "value": 2.5e6, "description": "pressure cap"},
        ]}
        rv = requirements_view(spec)
        self.assertEqual(rv["name"], "s")
        self.assertEqual(rv["checks"][0]["target"], "tank.final")
        self.assertEqual(rv["checks"][0]["op"], "<=")

    def test_report_view_lists_unmet(self):
        from loop.session_state import report_view

        verdict = {"checks": [
            {"id": "a", "passed": True, "op": ">", "expected": 0, "actual": 1, "description": "x"},
            {"id": "b", "passed": False, "op": ">=", "expected": 2.0, "actual": 1.0, "description": "y"},
        ]}
        rep = report_view(False, verdict, {"nodes": []}, 3)
        self.assertFalse(rep["passed"])
        self.assertEqual(len(rep["unmet_requirements"]), 1)
        self.assertEqual(rep["unmet_requirements"][0]["id"], "b")

    def test_file_store_writes(self):
        import json
        import tempfile
        from pathlib import Path

        from loop.session_state import FileSessionStore, new_state

        with tempfile.TemporaryDirectory() as tmp:
            store = FileSessionStore(root=Path(tmp))
            state = new_state("sess1", "vent a tank", "asi1", "asi1")
            store.write(state)
            out = Path(tmp) / "sess1" / "session_state.json"
            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text())
            self.assertEqual(loaded["session_id"], "sess1")
            self.assertIn("updated_at", loaded)

    def test_get_store_defaults_to_file_without_redis(self):
        import os

        from loop.session_state import FileSessionStore, _GuardedStore, get_store

        had = os.environ.pop("REDIS_URL", None)
        try:
            store = get_store()
            self.assertIsInstance(store, _GuardedStore)
            self.assertIsInstance(store.inner, FileSessionStore)
        finally:
            if had is not None:
                os.environ["REDIS_URL"] = had

    def test_guarded_store_swallows_write_errors(self):
        from loop.session_state import _GuardedStore, new_state

        class _Boom:
            def write(self, state):
                raise RuntimeError("redis down")

        # must not raise
        _GuardedStore(_Boom()).write(new_state("s", "r", "asi1", "asi1"))


class TestDesignSeeds(unittest.TestCase):
    def test_seed_lookup_returns_pressure_fed_design(self):
        from loop.design_seeds import get_design_seed, infer_design_seed

        self.assertEqual(
            infer_design_seed("simple pressure fed LOX kerosene system with GN2 pressurant"),
            "pressure_fed_lox_kerosene",
        )
        seed = get_design_seed("pressure_fed_lox_kerosene")
        self.assertIsNotNone(seed)
        nodes = {node["params"]["name"]: node for node in seed["design"]["nodes"]}
        self.assertEqual(nodes["engine"]["type"], "Engine")
        self.assertIn("lox_tank", nodes)
        conn_names = {conn["params"]["name"] for conn in seed["design"]["connections"]}
        self.assertIn("lox_feed_line", conn_names)
        self.assertIn("kerosene_feed_line", conn_names)

    def test_unknown_seed_returns_none(self):
        from loop.design_seeds import get_design_seed

        self.assertIsNone(get_design_seed("missing_seed"))


class TestSpecWriterSeeds(unittest.TestCase):
    def test_pressure_fed_request_gets_seed_and_feed_checks(self):
        from loop.spec_writer import apply_seed_guidance

        spec = {"name": "s", "description": "d", "checks": []}
        out = apply_seed_guidance(
            spec,
            "Design a pressure fed LOX and kerosene system with GN2 pressurant",
        )
        self.assertEqual(out["design_guidance"]["design_seed"], "pressure_fed_lox_kerosene")
        checks = {check["id"]: check for check in out["checks"]}
        self.assertEqual(checks["ran"]["type"], "status")
        self.assertEqual(checks["physical"]["type"], "no_warnings")
        self.assertEqual(checks["lox_feed_flow"]["component"], "lox_feed_line")
        self.assertEqual(checks["lox_feed_flow"]["field"], "mdot")
        self.assertEqual(checks["lox_feed_flow"]["stat"], "nonzero_count")
        self.assertEqual(checks["kerosene_feed_flow"]["component"], "kerosene_feed_line")


class TestClassifier(unittest.TestCase):
    def _o(self, status="ok", passed=False, n=2, total=6):
        from loop.classifier import IterationOutcome
        return IterationOutcome(status, passed, n, total)

    def test_passed_stops(self):
        from loop.classifier import classify
        d = classify([self._o(passed=True, n=6)], 0, 2)
        self.assertEqual(d.action, "stop")

    def test_invalid_config_revises(self):
        from loop.classifier import classify
        d = classify([self._o(status="invalid_config", n=0)], 0, 2)
        self.assertEqual(d.action, "revise")

    def test_single_crash_revises_repeated_crash_scraps(self):
        from loop.classifier import classify
        self.assertEqual(classify([self._o(status="crashed", n=0)], 0, 2).action, "revise")
        line = [self._o(status="crashed", n=0), self._o(status="crashed", n=0)]
        self.assertEqual(classify(line, 0, 2).action, "scrap")

    def test_progress_revises(self):
        from loop.classifier import classify
        line = [self._o(n=2), self._o(n=4)]  # improving
        self.assertEqual(classify(line, 0, 2).action, "revise")

    def test_stall_scraps_when_restarts_remain(self):
        from loop.classifier import classify
        line = [self._o(n=3), self._o(n=3), self._o(n=3)]  # no improvement, 2+ stalls
        self.assertEqual(classify(line, 0, 2).action, "scrap")

    def test_stall_falls_back_to_revise_when_restarts_exhausted(self):
        from loop.classifier import classify
        line = [self._o(n=3), self._o(n=3), self._o(n=3)]
        self.assertEqual(classify(line, 2, 2).action, "revise")


class TestAgentPrompt(unittest.TestCase):
    def test_design_prompt_mentions_top_down_coordinates(self):
        from loop.agent import SYSTEM_PROMPT

        self.assertNotIn("AGENT_JSON_BEST_PRACTICES.md", SYSTEM_PROMPT)
        self.assertIn("optional x/y coordinates", SYSTEM_PROMPT)
        self.assertIn("top-down", SYSTEM_PROMPT)

    def test_first_prompt_includes_seed_design_when_present(self):
        from loop.agent import _first_user_message
        from loop.design_seeds import get_design_seed

        seed = get_design_seed("pressure_fed_lox_kerosene")
        prompt = _first_user_message(
            {"name": "s", "checks": [], "design_guidance": {"design_seed": "pressure_fed_lox_kerosene"}},
            seed=seed,
        )
        self.assertIn("SEED DESIGN", prompt)
        self.assertIn('"lox_feed_line"', prompt)
        self.assertIn('"kerosene_feed_line"', prompt)
        self.assertIn("Preserve component names", prompt)


if __name__ == "__main__":
    unittest.main()
