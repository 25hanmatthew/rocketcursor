"""Known-good starting designs for common chat requests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DesignSeed:
    name: str
    path: Path
    keywords: tuple[str, ...]
    must_include_nodes: tuple[str, ...]
    must_include_connections: tuple[str, ...]
    tunable: tuple[str, ...]
    notes: tuple[str, ...]


DESIGN_SEEDS: dict[str, DesignSeed] = {
    "pressure_fed_lox_kerosene": DesignSeed(
        name="pressure_fed_lox_kerosene",
        path=REPO_ROOT / "loop" / "design_seeds" / "pressure_fed_lox_kerosene.json",
        keywords=("pressure fed", "pressure-fed", "lox", "kerosene", "rp-1", "gn2", "nitrogen"),
        must_include_nodes=("gn2_tank", "lox_tank", "kerosene_tank", "engine"),
        must_include_connections=(
            "gn2_to_lox_pressurization",
            "gn2_to_kerosene_pressurization",
            "lox_feed_line",
            "kerosene_feed_line",
        ),
        tunable=("tank pressures", "tank volumes", "feed CdA values", "engine throat/exit area"),
        notes=(
            "Preserve the Engine node and the two feed Series connections into it.",
            "Tune feed CdA values before changing topology.",
            "If physical warnings mention a component, fix that component first.",
        ),
    ),
    "tank_blowdown": DesignSeed(
        name="tank_blowdown",
        path=REPO_ROOT / "simulator" / "network_configs" / "tank_vent_to_atmosphere.json",
        keywords=("blowdown", "vent", "nitrogen tank", "pressure tank"),
        must_include_nodes=("pressurized_tank", "atmosphere"),
        must_include_connections=("vent_orifice",),
        tunable=("tank pressure", "tank volume", "vent CdA", "duration", "dt"),
        notes=("Tune vent CdA to control final pressure.",),
    ),
    "pressure_window_blowdown": DesignSeed(
        name="pressure_window_blowdown",
        path=REPO_ROOT / "simulator" / "network_configs" / "tank_vent_to_atmosphere.json",
        keywords=("pressure window", "final pressure", "target pressure", "about"),
        must_include_nodes=("pressurized_tank", "atmosphere"),
        must_include_connections=("vent_orifice",),
        tunable=("vent CdA", "duration", "dt"),
        notes=("Use final tank pressure checks as the main tuning target.",),
    ),
}


def available_design_seeds() -> list[str]:
    return sorted(DESIGN_SEEDS)


def get_design_seed(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    seed = DESIGN_SEEDS.get(str(name))
    if seed is None:
        return None
    return {
        "name": seed.name,
        "metadata": {
            "must_include_nodes": list(seed.must_include_nodes),
            "must_include_connections": list(seed.must_include_connections),
            "tunable": list(seed.tunable),
            "notes": list(seed.notes),
        },
        "design": json.loads(seed.path.read_text(encoding="utf-8")),
    }


def infer_design_seed(request: str) -> str | None:
    text = request.lower()
    if (
        ("lox" in text or "liquid oxygen" in text)
        and ("kerosene" in text or "rp-1" in text or "rp1" in text)
        and ("pressure fed" in text or "pressure-fed" in text or "pressurant" in text)
    ):
        return "pressure_fed_lox_kerosene"
    if ("blowdown" in text or "vent" in text) and ("target" in text or "about" in text or "window" in text):
        return "pressure_window_blowdown"
    if "blowdown" in text or "vent" in text:
        return "tank_blowdown"
    return None
