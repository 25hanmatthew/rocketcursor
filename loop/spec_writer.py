"""Translate a natural-language design request into a machine-checkable spec.

This is the human-facing front-end: it lets someone say "blow a nitrogen tank
down from 8 MPa to about 3 MPa in 10 s" instead of hand-writing the checks.

Crucially, it preserves the loop's core principle. Claude proposes the
*structure* of the requirements (which components, which deterministic checks,
what numeric thresholds) by emitting a spec via the `submit_spec` tool. Once that
spec exists, the verdict is still produced entirely by the pure-Python evaluator
against those explicit checks. The LLM never decides pass/fail at runtime — it
only writes down, up front and inspectably, what "pass" means.

    python -m loop.spec_writer "vent a 6 MPa nitrogen tank to atmosphere; it
        should end between 2 and 2.5 MPa after 12 seconds"
"""

from __future__ import annotations

import json
import sys

from loop.agent import _load_dotenv
from loop.llm import one_tool_call

SUBMIT_SPEC_TOOL = {
    "name": "submit_spec",
    "description": "Emit a structured, machine-checkable requirements spec for the design agent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "short snake_case identifier"},
            "description": {
                "type": "string",
                "description": (
                    "Design brief shown to the designer agent. Restate the intent, name the "
                    "required components, and say which quantities are FIXED vs TUNABLE."
                ),
            },
            "design_guidance": {
                "type": "object",
                "description": (
                    "Hints for the designer: must_include_nodes (list of names), "
                    "must_include_connections (list of names), fixed_constraints (object), "
                    "tunable (list), notes (list of strings)."
                ),
            },
            "checks": {
                "type": "array",
                "description": "Deterministic pass/fail checks evaluated against the simulation result.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string"},
                        "type": {"type": "string", "enum": ["status", "sim", "no_warnings", "component", "diagnostics"]},
                        "op": {"type": "string", "enum": [">", ">=", "<", "<=", "==", "!="]},
                        "value": {"description": "Expected value: number, boolean, or string."},
                        "field": {"type": "string", "description": "field name for sim/component/diagnostics checks"},
                        "component": {"type": "string", "description": "node/connection name for component checks"},
                        "stat": {
                            "type": "string",
                            "enum": ["first", "final", "min", "max", "delta", "range", "nonzero_count", "sample_count"],
                            "description": "which recorded statistic, for component checks",
                        },
                    },
                    "required": ["id", "description", "type", "op", "value"],
                },
            },
        },
        "required": ["name", "description", "checks"],
    },
}

SPEC_WRITER_SYSTEM = """\
You translate a natural-language rocket feed-system design request into a
STRUCTURED, machine-checkable requirements spec, emitted via the submit_spec tool.
A downstream agent will design a fluid network to satisfy it, and a deterministic
Python evaluator will judge it against your checks. So your checks must be precise,
numeric, and reference components by exact name.

The simulator records, per component, these history fields with summary statistics:
- Nodes/Tanks: P (Pa), T (K), m (kg), d (density kg/m^3)
- Connections: mdot (mass flow, kg/s)
Statistics available per field: first, final, min, max, delta (final-first), range,
nonzero_count, sample_count.

Check vocabulary (each check needs id, description, type, op, value):
- {"type":"status","op":"==","value":"ok"}  -> simulation ran (no crash/invalid config)
- {"type":"sim","field":"has_nonzero_flow","op":"==","value":true}  (also has_node_samples, has_connection_samples)
- {"type":"no_warnings","op":"==","value":true}  -> no nonphysical/degenerate warnings
- {"type":"component","component":"<name>","field":"P","stat":"final","op":"<=","value":2500000.0}
- {"type":"diagnostics","field":"duration","op":">=","value":11.9}  (also dt, step_count, node_count, connection_count)
Operators: > >= < <= == !=.

Rules:
- Always include three baseline checks: id "ran" (status==ok), "flow_happens"
  (sim has_nonzero_flow==true), and "physical" (no_warnings==true).
- Use SI units. Convert the user's units to SI in the check values: bar->Pa (x1e5),
  MPa->Pa (x1e6), psi->Pa (x6894.76), liters stay liters in design guidance.
- A target "about X" or "between A and B" becomes a WINDOW: two component checks
  (>= low and <= high) on the relevant field's final/min/max as appropriate.
- A fixed start condition becomes a check on stat "first" (e.g. tank starts at 6 MPa
  -> two checks bracketing P.first). A fixed duration becomes diagnostics duration checks.
- Name every component explicitly, list them in design_guidance.must_include_nodes /
  must_include_connections, restate the fixed-vs-tunable split in the description, and
  reference those EXACT names in the component checks.
- Pick concrete thresholds. If the user gives a target without tolerance, choose a
  sensible window (e.g. +/- 5-10%) and say so in the description.
- You MUST call submit_spec exactly once.
"""


def nl_to_spec(request: str) -> dict:
    """Translate a natural-language request into a requirements spec dict."""
    _load_dotenv()
    user = (f"Translate this design request into a requirements spec:\n\n{request}\n\n"
            "Call submit_spec now.")
    return one_tool_call(SPEC_WRITER_SYSTEM, user, SUBMIT_SPEC_TOOL, tool_name="submit_spec")


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print('usage: python -m loop.spec_writer "<natural-language design request>"')
        return 2
    spec = nl_to_spec(" ".join(args))
    print(json.dumps(spec, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
