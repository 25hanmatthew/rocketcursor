"""Load a mission_spec, fill missing fields from a named preset, and record
every filled value in the assumption ledger. Deterministic; no LLM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.common.assumptions import AssumptionLedger
from backend.common.contracts import REPO_ROOT, validate

PRESETS_PATH = REPO_ROOT / "shared" / "presets" / "mission_presets.json"


def _load_presets() -> dict[str, Any]:
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))["presets"]


def _fill(dst: dict, src: dict, prefix: str, preset_name: str, ledger: AssumptionLedger) -> None:
    """Recursively fill keys present in `src` but missing in `dst`, recording each."""
    for key, value in src.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            child = dst.setdefault(key, {})
            if isinstance(child, dict):
                _fill(child, value, path, preset_name, ledger)
        elif key not in dst:
            dst[key] = ledger.record(path, value, f"preset:{preset_name}", "filled from preset")


def load_mission_spec(spec: dict | str | Path) -> dict[str, Any]:
    """Return a complete, schema-valid mission_spec with an assumption ledger.

    `spec` may be a dict or a path to a JSON file. Fields absent from the spec
    are pulled from `spec['preset']` (default: small_sounding_rocket).
    """
    if isinstance(spec, (str, Path)):
        spec = json.loads(Path(spec).read_text(encoding="utf-8"))
    spec = json.loads(json.dumps(spec))  # deep copy

    ledger = AssumptionLedger("mission_spec")
    preset_name = spec.get("preset", "small_sounding_rocket")
    presets = _load_presets()
    if preset_name not in presets:
        raise ValueError(f"unknown mission preset: {preset_name}")
    _fill(spec, presets[preset_name], "", preset_name, ledger)

    spec.setdefault("assumptions", [])
    spec["assumptions"].extend(ledger.to_list())

    validate(spec, "mission_spec")
    return spec
