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
from loop.design_seeds import DESIGN_SEEDS, infer_design_seed
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
                    "Hints for the designer: design_seed (optional known-good seed name), "
                    "must_include_nodes (list of names), "
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

Available design_seed values:
- pressure_fed_lox_kerosene: pressure-fed LOX/kerosene feed system using GN2
  pressurization and a real Engine node; exact component names are gn2_tank, lox_tank,
  kerosene_tank, engine, gn2_to_lox_pressurization,
  gn2_to_kerosene_pressurization, lox_feed_line, kerosene_feed_line.
- tank_blowdown: simple pressurized gas tank venting to atmosphere.
- pressure_window_blowdown: tank blowdown with a final pressure target/window.

Rules:
- Always include baseline checks: id "ran" (status==ok) and "physical"
  (no_warnings==true). Add "flow_happens" only as a secondary broad check; do
  not rely on it as the only proof of mission-critical flow.
- For feed/engine requests, include separate per-path flow checks on the actual
  feed connections, e.g. lox_feed_line.mdot.nonzero_count > 0 and
  kerosene_feed_line.mdot.nonzero_count > 0.
- For pressure-fed LOX/kerosene/GN2 requests, set
  design_guidance.design_seed="pressure_fed_lox_kerosene" and use the seed's
  exact component names in checks.
- For engine designs, do not create Ambient/atm/atmosphere pressure component
  checks. Ambient pressure is an Engine design parameter (Pa), such as
  design_guidance.fixed_constraints.engine_Pa=101325, not sampled telemetry
  unless the design explicitly includes a real Ambient node for another reason.
- Use SI units. Convert the user's units to SI in the check values: bar->Pa (x1e5),
  MPa->Pa (x1e6), psi->Pa (x6894.76), liters stay liters in design guidance.
- A target "about X" or "between A and B" becomes a WINDOW: two component checks
  (>= low and <= high) on the relevant field's final/min/max as appropriate.
- Do NOT use "==" for numeric component or diagnostics checks. Exact equality is
  only appropriate for status strings and booleans. Fixed numeric quantities must
  be checked with a tolerance window. For atmospheric pressure, use 101325 Pa +/-
  100 Pa unless the user gives a different tolerance.
- A fixed start condition becomes a check on stat "first" (e.g. tank starts at 6 MPa
  -> two checks bracketing P.first). A fixed duration becomes diagnostics duration checks.
- Name every component explicitly, list them in design_guidance.must_include_nodes /
  must_include_connections, restate the fixed-vs-tunable split in the description, and
  reference those EXACT names in the component checks.
- Pick concrete thresholds. If the user gives a target without tolerance, choose a
  sensible window (e.g. +/- 5-10%) and say so in the description.
- You MUST call submit_spec exactly once.
"""

REVISION_SPEC_WRITER_SYSTEM = SPEC_WRITER_SYSTEM + """\

Revision mode:
- You are revising an EXISTING requirements spec based on a follow-up user
  message. Emit a complete replacement spec, not a patch.
- Preserve the base spec's checks, component names, design_guidance, and
  deterministic pass/fail intent unless the follow-up explicitly changes a
  target, constraint, component, topology requirement, or operating condition.
- If the follow-up is only a design preference (for example, "make the tank
  smaller"), keep the original checks and put the preference in
  design_guidance.notes or design_guidance.tunable.
- If the follow-up changes a numeric requirement, replace the relevant old
  check(s) with a new tolerance/window check. Do not leave contradictory checks.
- Keep the design_seed from the base spec unless the follow-up explicitly asks
  for a different architecture that makes that seed inappropriate.
"""


def _append_unique(items: list, values) -> None:
    for value in values:
        if value not in items:
            items.append(value)


def _has_check(checks: list[dict], check_id: str) -> bool:
    return any(check.get("id") == check_id for check in checks)


def _ensure_check(checks: list[dict], check: dict) -> None:
    if not _has_check(checks, check["id"]):
        checks.append(check)


_BLOWDOWN_COMPONENT_ALIASES = {
    "gn2_tank": "pressurized_tank",
    "nitrogen_tank": "pressurized_tank",
    "pressure_tank": "pressurized_tank",
    "tank": "pressurized_tank",
    "ambient": "atmosphere",
    "orifice": "vent_orifice",
    "vent": "vent_orifice",
}


def _canonical_component_name(seed_name: str, name: str) -> str:
    if seed_name in {"tank_blowdown", "pressure_window_blowdown"}:
        return _BLOWDOWN_COMPONENT_ALIASES.get(name, name)
    return name


def _canonicalize_component_list(seed_name: str, values: list) -> list:
    out = []
    for value in values:
        normalized = _canonical_component_name(seed_name, value) if isinstance(value, str) else value
        if normalized not in out:
            out.append(normalized)
    return out


def _canonicalize_check_components(seed_name: str, checks: list[dict]) -> list[dict]:
    out = []
    for check in checks:
        item = dict(check)
        component = item.get("component")
        if isinstance(component, str):
            item["component"] = _canonical_component_name(seed_name, component)
        out.append(item)
    return out


def _is_atmospheric_pressure_component_check(check: dict) -> bool:
    component = str(check.get("component", "")).lower()
    return (
        check.get("type") == "component"
        and check.get("field") == "P"
        and any(token in component for token in ("ambient", "atmosphere", "atm"))
    )


def drop_atmospheric_pressure_component_checks(spec: dict) -> tuple[dict, int]:
    """Remove ambient pressure telemetry checks that engine designs cannot satisfy.

    Engine ambient pressure is carried by Engine.params.Pa, not necessarily by a
    sampled Ambient component in simulation_result.components.
    """
    checks = spec.get("checks", [])
    if not isinstance(checks, list):
        return spec, 0

    next_checks = [
        check
        for check in checks
        if not (isinstance(check, dict) and _is_atmospheric_pressure_component_check(check))
    ]
    dropped = len(checks) - len(next_checks)
    if not dropped:
        return spec, 0
    out = dict(spec)
    out["checks"] = next_checks
    return out, dropped


def apply_seed_guidance(spec: dict, request: str) -> dict:
    """Attach deterministic seed hints/checks to an LLM-derived spec."""
    seed_name = infer_design_seed(request)
    if not seed_name:
        return spec

    spec = dict(spec)
    guidance = dict(spec.get("design_guidance") or {})
    seed = DESIGN_SEEDS[seed_name]
    guidance.setdefault("design_seed", seed_name)
    nodes = _canonicalize_component_list(seed_name, list(guidance.get("must_include_nodes") or []))
    connections = _canonicalize_component_list(seed_name, list(guidance.get("must_include_connections") or []))
    tunable = list(guidance.get("tunable") or [])
    notes = list(guidance.get("notes") or [])
    _append_unique(nodes, seed.must_include_nodes)
    _append_unique(connections, seed.must_include_connections)
    _append_unique(tunable, seed.tunable)
    _append_unique(notes, seed.notes)
    guidance["must_include_nodes"] = nodes
    guidance["must_include_connections"] = connections
    guidance["tunable"] = tunable
    guidance["notes"] = notes
    if seed_name == "pressure_fed_lox_kerosene":
        fixed_constraints = dict(guidance.get("fixed_constraints") or {})
        fixed_constraints.setdefault("engine_Pa", 101325.0)
        guidance["fixed_constraints"] = fixed_constraints
    spec["design_guidance"] = guidance

    checks = _canonicalize_check_components(seed_name, list(spec.get("checks") or []))
    _ensure_check(checks, {
        "id": "ran",
        "description": "Simulation runs without invalid configuration or solver crash.",
        "type": "status",
        "op": "==",
        "value": "ok",
    })
    _ensure_check(checks, {
        "id": "physical",
        "description": "No nonphysical or degenerate warnings during simulation.",
        "type": "no_warnings",
        "op": "==",
        "value": True,
    })

    if seed_name == "pressure_fed_lox_kerosene":
        spec["checks"] = checks
        spec, _ = drop_atmospheric_pressure_component_checks(spec)
        checks = list(spec.get("checks") or [])
        _ensure_check(checks, {
            "id": "lox_feed_flow",
            "description": "LOX feed line delivers non-zero mass flow to the engine.",
            "type": "component",
            "component": "lox_feed_line",
            "field": "mdot",
            "stat": "nonzero_count",
            "op": ">",
            "value": 0,
        })
        _ensure_check(checks, {
            "id": "kerosene_feed_flow",
            "description": "Kerosene feed line delivers non-zero mass flow to the engine.",
            "type": "component",
            "component": "kerosene_feed_line",
            "field": "mdot",
            "stat": "nonzero_count",
            "op": ">",
            "value": 0,
        })
    spec["checks"] = checks
    return spec


def nl_to_spec(request: str) -> dict:
    """Translate a natural-language request into a requirements spec dict."""
    _load_dotenv()
    seed_name = infer_design_seed(request)
    seed_hint = f"\nLikely design_seed: {seed_name}\n" if seed_name else ""
    user = (f"Translate this design request into a requirements spec:\n\n{request}\n"
            f"{seed_hint}\nCall submit_spec now.")
    spec = one_tool_call(SPEC_WRITER_SYSTEM, user, SUBMIT_SPEC_TOOL, tool_name="submit_spec")
    return apply_seed_guidance(spec, request)


def revise_spec(base_spec: dict, revision_message: str, base_design: dict, base_report: dict | None = None) -> dict:
    """Rewrite a complete spec for a follow-up revision request.

    The spec writer may update checks if the user changes requirements, but
    design-only preferences should preserve the original checks.
    """
    _load_dotenv()
    base_report = base_report or {}
    user = (
        "Revise this existing requirements spec for a follow-up chat message.\n\n"
        "FOLLOW-UP MESSAGE:\n"
        f"{revision_message}\n\n"
        "BASE SPEC:\n"
        f"{json.dumps(base_spec, indent=2)}\n\n"
        "CURRENT DESIGN JSON:\n"
        f"{json.dumps(base_design, indent=2)}\n\n"
        "CURRENT RUN REPORT SUMMARY:\n"
        f"{json.dumps(_compact_report(base_report), indent=2)}\n\n"
        "Emit the complete revised spec with submit_spec now."
    )
    spec = one_tool_call(REVISION_SPEC_WRITER_SYSTEM, user, SUBMIT_SPEC_TOOL, tool_name="submit_spec")
    return spec


def _compact_report(report: dict) -> dict:
    status = report.get("status") if isinstance(report, dict) else None
    return {
        "duration": report.get("duration") if isinstance(report, dict) else None,
        "dt": report.get("dt") if isinstance(report, dict) else None,
        "status": {
            "passed": status.get("passed") if isinstance(status, dict) else None,
            "failures": status.get("failures", [])[:10] if isinstance(status, dict) else [],
            "warnings": status.get("warnings", [])[:10] if isinstance(status, dict) else [],
            "checks": status.get("checks", {}) if isinstance(status, dict) else {},
        },
        "component_counts": report.get("component_counts") if isinstance(report, dict) else None,
    }


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
