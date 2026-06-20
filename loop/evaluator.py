"""Deterministic requirements -> verdict evaluation. NO LLM involved.

This is the heart of the loop: it turns a `simulation_result` (from
`simulator_adapter`) plus a requirements spec into a pass/fail verdict, by
running each declared check against the simulation's recorded statistics. The
solver's diagnostics only tell you the sim ran cleanly; this layer is what
decides whether the design actually *meets requirements*.

A requirements spec is JSON:

    {
      "name": "...",
      "description": "...",            # context shown to the designer agent
      "design_guidance": {...},        # optional hints shown to the agent
      "checks": [ <check>, ... ]
    }

Each <check> has an `id`, a human `description`, an `op`, an expected `value`,
and a `type` that says where the actual value comes from:

    {"type": "status",       "op": "==", "value": "ok"}
    {"type": "sim",   "field": "has_nonzero_flow", "op": "==", "value": true}
    {"type": "no_warnings",  "op": "==", "value": true}
    {"type": "component", "component": "supply_tank", "field": "P",
                          "stat": "delta", "op": "<", "value": -500000.0}

`stat` for a component check is one of the per-field statistics the solver
records: first, final, min, max, delta, range, nonzero_count, sample_count.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


class _Missing(Exception):
    """The value a check refers to does not exist in the result."""


@dataclass
class CheckResult:
    id: str
    description: str
    passed: bool
    op: str
    expected: Any
    actual: Any
    detail: str = ""


@dataclass
class Verdict:
    passed: bool
    summary: str
    checks: list[CheckResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate(spec: dict[str, Any], result: dict[str, Any]) -> Verdict:
    """Evaluate a requirements `spec` against a `simulation_result`."""
    checks_spec = spec.get("checks", [])
    status = result.get("status")

    # Hard gate: if the sim never ran cleanly, nothing downstream is evaluable.
    if status != "ok":
        notes = [f"Simulation did not run cleanly (status={status!r})."]
        notes += [f"error: {e}" for e in result.get("errors", [])]
        results = [
            CheckResult(
                c.get("id", "?"),
                c.get("description", ""),
                False,
                c.get("op", "=="),
                c.get("value"),
                None,
                detail=f"not evaluated; simulation status={status!r}",
            )
            for c in checks_spec
        ]
        return Verdict(
            False,
            f"0/{len(checks_spec)} checks passed (simulation {status})",
            results,
            notes,
        )

    results = [_evaluate_check(c, result) for c in checks_spec]
    n_passed = sum(1 for r in results if r.passed)
    return Verdict(
        passed=all(r.passed for r in results),
        summary=f"{n_passed}/{len(results)} checks passed",
        checks=results,
        notes=[],
    )


def _evaluate_check(check: dict[str, Any], result: dict[str, Any]) -> CheckResult:
    cid = check.get("id", "?")
    desc = check.get("description", "")
    op = check.get("op", "==")
    expected = check.get("value")

    try:
        actual, detail = _resolve_actual(check, result)
    except _Missing as miss:
        return CheckResult(cid, desc, False, op, expected, None, detail=str(miss))

    if actual is None:
        return CheckResult(cid, desc, False, op, expected, None, detail="value unavailable")

    fn = _OPS.get(op)
    if fn is None:
        return CheckResult(cid, desc, False, op, expected, actual, detail=f"unknown operator {op!r}")

    try:
        passed = bool(fn(actual, expected))
    except TypeError as exc:
        return CheckResult(cid, desc, False, op, expected, actual, detail=f"type error: {exc}")

    return CheckResult(cid, desc, passed, op, expected, actual, detail=detail)


def _resolve_actual(check: dict[str, Any], result: dict[str, Any]) -> tuple[Any, str]:
    ctype = check.get("type")

    if ctype == "status":
        return result.get("status"), ""

    if ctype == "sim":
        fieldname = check["field"]
        checks = result.get("diagnostics", {}).get("checks", {})
        if fieldname not in checks:
            raise _Missing(f"diagnostics.checks has no field {fieldname!r}")
        return checks[fieldname], ""

    if ctype == "no_warnings":
        warns = result.get("diagnostics", {}).get("warnings", [])
        detail = "; ".join(w.get("message", str(w)) for w in warns)
        return (len(warns) == 0), detail

    if ctype == "diagnostics":
        fieldname = check["field"]
        diag = result.get("diagnostics", {})
        if fieldname not in diag:
            raise _Missing(f"diagnostics has no scalar field {fieldname!r}")
        return diag[fieldname], f"diagnostics.{fieldname}={diag[fieldname]}"

    if ctype == "component":
        comp = check["component"]
        fieldname = check["field"]
        stat = check.get("stat", "final")
        components = result.get("components", {})
        if comp not in components:
            have = ", ".join(sorted(components)[:10])
            raise _Missing(f"no component named {comp!r} (have: {have})")
        fields = components[comp].get("fields", {})
        if fieldname not in fields:
            have = ", ".join(sorted(fields))
            raise _Missing(f"component {comp!r} has no field {fieldname!r} (have: {have})")
        value = fields[fieldname].get(stat)
        if value is None:
            raise _Missing(f"{comp}.{fieldname} has no stat {stat!r}")
        return value, f"{comp}.{fieldname}.{stat}={value:.6g}"

    raise _Missing(f"unknown check type {ctype!r}")
