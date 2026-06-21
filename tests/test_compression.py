"""Tests for the requirement-aware context compression (Token Company challenge).

Verifies the compressor actually reduces tokens hard while keeping the
decision-relevant signal (the failing check's name and actual value).

    python -m unittest tests.test_compression
"""

import unittest

from loop.compression import (
    compress_simulation_result,
    compress_tabular_context,
    compression_stats,
    estimate_tokens,
)


def _spec():
    return {
        "name": "unit_spec",
        "checks": [
            {"id": "thrust_min", "type": "diagnostics",
             "description": "End-of-burn thrust is at least 1500 N.",
             "field": "thrust_final", "op": ">=", "value": 1500.0},
        ],
    }


def _result(thrust):
    return {
        "status": "ok",
        "sim": {"ran": True},
        "diagnostics": {"thrust_final": thrust},
        "warnings": [],
    }


# A stand-in for the raw simulator time-series a naive loop would send back.
_RAW_CSV = ("t,node,P,T,mdot\n" +
            "\n".join(f"{i*0.001},tank,{3e6-i},290.0,{1.2}" for i in range(8000)))


class CompressionStatsTests(unittest.TestCase):
    def test_estimate_tokens_monotonic_and_positive(self):
        self.assertGreaterEqual(estimate_tokens("x"), 1)
        self.assertGreater(estimate_tokens("x" * 4000), estimate_tokens("x" * 40))

    def test_stats_reduction_math(self):
        st = compression_stats("a" * 1000, "a" * 10)
        self.assertEqual(st.raw_chars, 1000)
        self.assertEqual(st.compressed_chars, 10)
        self.assertAlmostEqual(st.kept_fraction, 0.01, places=5)
        self.assertAlmostEqual(st.reduction_pct, 99.0, places=2)
        self.assertGreater(st.tokens_saved, 0)

    def test_empty_raw_does_not_divide_by_zero(self):
        st = compression_stats("", "anything")
        self.assertEqual(st.kept_fraction, 1.0)


class CompressVerdictTests(unittest.TestCase):
    def test_huge_reduction_on_failing_run(self):
        text, st = compress_simulation_result(_spec(), _result(1136.79), _RAW_CSV)
        # Massive reduction vs the raw time-series.
        self.assertGreater(st.reduction_pct, 95.0)
        self.assertLess(st.compressed_tokens, st.raw_tokens)

    def test_keeps_decision_relevant_signal(self):
        text, _ = compress_simulation_result(_spec(), _result(1136.79), _RAW_CSV)
        # The failing check id and the offending actual value survive compression.
        self.assertIn("thrust_min", text)
        self.assertIn("1136", text)
        self.assertIn("FAIL", text)

    def test_passing_run_reports_pass(self):
        text, _ = compress_simulation_result(_spec(), _result(1800.0), _RAW_CSV)
        self.assertIn("PASS", text)


class TabularKernelTests(unittest.TestCase):
    """The domain-agnostic kernel — same idea, no rockets. Here: a generic
    request-latency log compressed against an SLO requirement set."""

    def _log(self, p99):
        # 5000 rows of a metrics time-series, like a service would emit.
        rows = [{"t": i, "latency_ms": 40 + (i % 20), "status": 200}
                for i in range(4999)]
        rows.append({"t": 4999, "latency_ms": p99, "status": 200})
        return rows

    def test_compresses_generic_metrics_log(self):
        reqs = [
            {"id": "p99_latency", "description": "Max latency under 500ms.",
             "field": "latency_ms", "stat": "max", "op": "<", "value": 500},
            {"id": "all_ok", "description": "No error statuses.",
             "field": "status", "stat": "max", "op": "<", "value": 400},
        ]
        text, st = compress_tabular_context(self._log(900), reqs)
        # Huge reduction over the raw 5000-row log.
        self.assertGreater(st.reduction_pct, 95.0)
        # Failing requirement and the offending value survive.
        self.assertIn("p99_latency", text)
        self.assertIn("FAIL", text)
        self.assertIn("900", text)
        # The satisfied requirement is reported as passing.
        self.assertIn("[PASS] all_ok", text)

    def test_all_pass_when_within_slo(self):
        reqs = [{"id": "p99_latency", "description": "Max latency under 500ms.",
                 "field": "latency_ms", "stat": "max", "op": "<", "value": 500}]
        text, _ = compress_tabular_context(self._log(120), reqs)
        self.assertIn("1/1 checks passed", text)

    def test_missing_field_fails_gracefully(self):
        reqs = [{"id": "x", "field": "nonexistent", "op": ">=", "value": 1}]
        text, _ = compress_tabular_context([{"a": 1}], reqs)
        self.assertIn("no data", text)


if __name__ == "__main__":
    unittest.main()
