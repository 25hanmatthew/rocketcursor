"""Failure classifier: decide whether to REVISE the current design or SCRAP it
and start a fresh design line.

The PRD calls for the agent to "classify why something failed so it knows whether
to make a small revision or scrap the design and start over." This is that stage.

It is DETERMINISTIC Python, on purpose — same as the verdict. Given the outcomes of
the current design line (the iterations since the last restart), it returns a
strategy decision. The rationale:

  - crashed twice in a row    -> SCRAP  (the design region is numerically unstable;
                                          tweaking a crashing design tends to re-crash)
  - crashed once             -> REVISE (give one corrective attempt: smaller dt/CdA)
  - invalid_config           -> REVISE (a structural error the model can fix from the
                                          error message; restarting doesn't help more)
  - ran, but stalled         -> SCRAP  (no improvement in passing-check count for
                                          STALL_LIMIT iterations -> this line is stuck)
  - ran, making progress     -> REVISE (more checks passing than before -> keep refining)

SCRAP only happens while restarts remain (max_restarts); otherwise it falls back to
REVISE so the iteration budget is still spent productively.
"""

from __future__ import annotations

from dataclasses import dataclass

STALL_LIMIT = 2  # consecutive non-improving "ok" iterations before scrapping a line


@dataclass
class IterationOutcome:
    status: str          # "ok" | "invalid_config" | "crashed"
    passed: bool
    n_passed: int
    n_total: int


@dataclass
class Decision:
    action: str          # "revise" | "scrap" | "stop"
    reason: str


def _stall_count(line: list[IterationOutcome]) -> int:
    """Consecutive non-improving iterations ending at the last entry, where
    'improving' means n_passed exceeded the best seen so far in this line."""
    best = -1
    stall = 0
    for o in line:
        if o.n_passed > best:
            best = o.n_passed
            stall = 0
        else:
            stall += 1
    return stall


def classify(line: list[IterationOutcome], restarts_used: int, max_restarts: int) -> Decision:
    """`line` = outcomes since the last restart (most recent last)."""
    if not line:
        return Decision("revise", "no outcomes yet")
    last = line[-1]
    if last.passed:
        return Decision("stop", "all checks passed")

    can_scrap = restarts_used < max_restarts

    if last.status == "crashed":
        prev_also_crashed = len(line) >= 2 and line[-2].status == "crashed"
        if prev_also_crashed and can_scrap:
            return Decision("scrap", "repeated solver crashes in this design line; starting fresh")
        return Decision("revise", "solver crashed; attempting a corrective revision")

    if last.status == "invalid_config":
        return Decision("revise", "invalid configuration; fixing structural errors")

    # status == "ok" but some checks fail
    stall = _stall_count(line)
    if stall >= STALL_LIMIT and can_scrap:
        return Decision("scrap",
                        f"stalled at {last.n_passed}/{last.n_total} checks for {stall} "
                        f"iterations; scrapping this approach and starting over")
    best_before = max((o.n_passed for o in line[:-1]), default=-1)
    if last.n_passed > best_before:
        return Decision("revise",
                        f"making progress ({last.n_passed}/{last.n_total} checks passing); refining")
    return Decision("revise",
                    f"no improvement yet ({last.n_passed}/{last.n_total}); revising further")
