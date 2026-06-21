"""The assumption ledger: every value not given by the user or computed from an
upstream artifact is recorded here, so nothing is silently invented."""

from __future__ import annotations

from typing import Any


class AssumptionLedger:
    """Ordered list of {field, value, source, rationale, stage} records."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        self._records: list[dict[str, Any]] = []

    def record(self, field: str, value: Any, source: str, rationale: str = "") -> Any:
        self._records.append(
            {
                "field": field,
                "value": value,
                "source": source,
                "rationale": rationale,
                "stage": self.stage,
            }
        )
        return value

    def extend(self, records: list[dict[str, Any]]) -> None:
        self._records.extend(records)

    def to_list(self) -> list[dict[str, Any]]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)
