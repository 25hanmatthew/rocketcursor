"""Eval-driven improvement experiment (the Arize "use feedback to make it better").

This closes the observability loop with a NUMBER, not an anecdote:

  1. Run the agent over a suite of specs (the "dataset").
  2. Score each run two ways:
       - deterministic: did it pass? how many iterations / restarts?
       - LLM-as-judge (loop/judge.py): design SOUNDNESS (0..1) + label.
  3. Aggregate into metrics (pass rate, avg iterations, avg soundness).
  4. Compare two variants of the agent — baseline vs an "improved" system prompt
     that bakes in the soundness lessons the judge surfaced — and show the
     soundness metric move.

So the judge's feedback is fed back into the agent, and the experiment proves the
improvement. Results (and the per-run judgements) are saved as JSON artifacts and,
if ARIZE_* creds are set, the runs are traced in Arize automatically.

    # run both variants and print the before/after table:
    .venv/bin/python -m loop.experiment --compare

    # or a single variant:
    .venv/bin/python -m loop.experiment --variant improved --tag run1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from loop.agent import _load_dotenv, run_loop
from loop.judge import judge_design
from loop.llm import active_model, active_provider
from loop.session_state import FileSessionStore, requirements_view

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "results" / "experiments"

# the "dataset": specs spanning easy -> hard
SUITE = ["tank_blowdown", "pressure_window_blowdown", "lox_methane_engine"]


def _spec_path(name: str) -> Path:
    return REPO_ROOT / "loop" / "specs" / f"{name}.json"


def run_one(spec_name: str, variant: str, max_iters: int) -> dict:
    """Run the loop on one spec under a variant, then judge the final design."""
    soundness = variant == "improved"
    spec = json.loads(_spec_path(spec_name).read_text(encoding="utf-8"))
    # isolate session-state writes per variant so runs don't clobber each other
    store = FileSessionStore(root=EXPERIMENTS_DIR / "_state" / variant)
    t0 = time.time()
    trace = run_loop(_spec_path(spec_name), max_iters=max_iters, store=store,
                     session_id=f"{variant}-{spec_name}", request=spec_name,
                     soundness_guidance=soundness)
    elapsed = time.time() - t0

    # judge the final design (soundness — complements the deterministic verdict)
    quality = {"label": "n/a", "score": None, "explanation": "no design produced"}
    iters = trace.get("iterations", [])
    if iters and iters[-1].get("design_path"):
        design = json.loads(Path(iters[-1]["design_path"]).read_text(encoding="utf-8"))
        outcome = (f"verdict: {iters[-1]['verdict']['summary']}; passed={trace['passed']} "
                   f"in {trace['iterations_used']} iter(s), {trace.get('restarts', 0)} restart(s).")
        try:
            quality = judge_design(requirements_view(spec), design, outcome)
        except Exception as exc:  # noqa: BLE001
            quality = {"label": "error", "score": None, "explanation": f"{type(exc).__name__}: {exc}"}

    return {
        "spec": spec_name, "variant": variant,
        "passed": trace["passed"], "iterations": trace["iterations_used"],
        "restarts": trace.get("restarts", 0), "seconds": round(elapsed, 1),
        "soundness_label": quality["label"], "soundness_score": quality["score"],
        "soundness_explanation": quality["explanation"],
    }


def aggregate(rows: list[dict]) -> dict:
    scored = [r["soundness_score"] for r in rows if isinstance(r["soundness_score"], (int, float))]
    return {
        "n": len(rows),
        "pass_rate": round(sum(1 for r in rows if r["passed"]) / len(rows), 3) if rows else 0,
        "avg_iterations": round(sum(r["iterations"] for r in rows) / len(rows), 2) if rows else 0,
        "avg_soundness": round(sum(scored) / len(scored), 3) if scored else None,
        "soundness_labels": _label_counts(rows),
    }


def _label_counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["soundness_label"]] = counts.get(r["soundness_label"], 0) + 1
    return counts


def run_variant(variant: str, suite: list[str], max_iters: int, tag: str) -> dict:
    print(f"\n##### VARIANT: {variant} (suite: {', '.join(suite)}) #####")
    rows = []
    for name in suite:
        print(f"\n--- {variant} / {name} ---")
        try:
            row = run_one(name, variant, max_iters)
        except Exception as exc:  # noqa: BLE001 - one spec failing shouldn't kill the suite
            row = {"spec": name, "variant": variant, "passed": False, "iterations": 0,
                   "restarts": 0, "seconds": 0, "soundness_label": "error",
                   "soundness_score": None, "soundness_explanation": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
        print(f"  -> passed={row['passed']} iters={row['iterations']} "
              f"soundness={row['soundness_label']} ({row['soundness_score']})")
    result = {"variant": variant, "tag": tag, "provider": active_provider(),
              "model": active_model(), "rows": rows, "metrics": aggregate(rows)}
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPERIMENTS_DIR / f"{tag}_{variant}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{variant} metrics: {result['metrics']}  (saved {out})")
    return result


def _print_comparison(base: dict, impr: dict) -> None:
    b, i = base["metrics"], impr["metrics"]
    print("\n================ EVAL-DRIVEN IMPROVEMENT (baseline -> improved) ================")
    print(f"{'metric':<18}{'baseline':>14}{'improved':>14}")
    print(f"{'pass_rate':<18}{b['pass_rate']:>14}{i['pass_rate']:>14}")
    print(f"{'avg_iterations':<18}{b['avg_iterations']:>14}{i['avg_iterations']:>14}")
    print(f"{'avg_soundness':<18}{str(b['avg_soundness']):>14}{str(i['avg_soundness']):>14}")
    print(f"{'labels':<18}{str(b['soundness_labels']):>14}{str(i['soundness_labels']):>14}")
    if b["avg_soundness"] is not None and i["avg_soundness"] is not None:
        delta = round(i["avg_soundness"] - b["avg_soundness"], 3)
        print(f"\nsoundness delta: {delta:+}  "
              f"({'improved' if delta > 0 else 'no improvement'} by feeding the judge's "
              f"findings back into the design agent)")
    print("================================================================================")


def main(argv=None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Eval-driven improvement experiment.")
    parser.add_argument("--compare", action="store_true",
                        help="Run baseline AND improved variants and print the before/after table.")
    parser.add_argument("--variant", choices=["baseline", "improved"], default="improved")
    parser.add_argument("--tag", default="exp")
    parser.add_argument("--max-iters", type=int, default=6)
    parser.add_argument("--suite", nargs="*", default=SUITE)
    args = parser.parse_args(argv)

    if args.compare:
        base = run_variant("baseline", args.suite, args.max_iters, args.tag)
        impr = run_variant("improved", args.suite, args.max_iters, args.tag)
        _print_comparison(base, impr)
        return 0
    run_variant(args.variant, args.suite, args.max_iters, args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
