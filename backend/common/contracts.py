"""Load and validate the pipeline's JSON Schema contracts.

All schemas live in `shared/schemas/` and reference each other by absolute
`$id` URIs (https://rocketcursor.local/shared/schemas/<name>.schema.json). We
load every schema into a `referencing` registry so cross-references resolve
without network access, then validate instances against a named schema.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "shared" / "schemas"


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    schema_id = f"https://rocketcursor.local/shared/schemas/{schema_name}.schema.json"
    schema = _registry().get_or_retrieve(schema_id).value.contents
    return Draft202012Validator(schema, registry=_registry())


def validate(instance: Any, schema_name: str) -> None:
    """Validate `instance` against `<schema_name>.schema.json`.

    Raises jsonschema.ValidationError on the first failure (with a path).
    `schema_name` is the bare stem, e.g. "mission_spec" or "vehicle_model".
    """
    errors = sorted(_validator(schema_name).iter_errors(instance), key=lambda e: e.path)
    if errors:
        first = errors[0]
        loc = "/".join(str(p) for p in first.path) or "<root>"
        raise ValueError(f"{schema_name} schema violation at {loc}: {first.message}")


def is_valid(instance: Any, schema_name: str) -> bool:
    return _validator(schema_name).is_valid(instance)
