"""LLM-as-a-judge evaluator (the Arize "create an evaluator" track).

Two-layer evaluation:
  1. DETERMINISTIC verdict (loop/evaluator.py) -> does the design MEET the spec?
  2. LLM JUDGE (this file)                     -> is the design actually GOOD engineering?

The judge catches what the numeric checks can't: a design can pass every requirement
yet be physically questionable (absurd tank volume, a CdA an order of magnitude off,
a temperature that doesn't match the fluid state). It scores design SOUNDNESS and
returns a label + score + explanation — the same shape Arize logs as feedback.

The EVAL_PROMPT below is written so it can be pasted directly into Arize's Evaluator
Hub (online eval over traced spans) — {requirements}/{design}/{outcome} are the
variable placeholders. Here we also run it locally over a finished loop run so you
get the eval without needing the Arize UI.

    python -m loop.judge results/loop_runs/<spec>/loop_trace.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from loop.agent import _load_dotenv
from loop.llm import one_tool_call

LABELS = ["sound", "questionable", "unsound"]

EVAL_PROMPT = """\
You are a demanding senior propulsion engineer doing a critical design review of an
automated rocket feed-system design. A separate deterministic checker already
confirmed whether the design meets its numeric requirements — that is NOT your job.
Your job is to judge whether it is GOOD ENGINEERING. Be strict: most first-draft
designs are "questionable". Reserve "sound" for designs with no real red flags.

Units in the design JSON (do NOT misread these): node/tank `V` is in LITERS;
`P` is Pa; `T` is K; connection `CdA` and engine `At`/`Ae` are in m^2; durations in s.

Score by deduction. Start at 1.0 and subtract for each real flaw you find:
- Propellant thermal state implausible for its tank pressure, or below freezing (-0.3)
- Tanks grossly over/under-sized for the burn (mass consumed vs stored) (-0.2)
- Pressure-fed system with no pressurant where the tank would blow down too far
  during the burn to sustain operation (-0.2)
- Nozzle expansion ratio (Ae/At) badly mismatched to chamber pressure / ambient (-0.15)
- Feed orifices that choke flow far below the engine throat, or other topology issues (-0.15)
- Any other concrete physical or integration red flag (-0.1 each)
Clamp to [0,1]. label: sound (>=0.8), questionable (0.4-0.8), unsound (<0.4).

<requirements>
{requirements}
</requirements>

<design>
{design}
</design>

<outcome>
{outcome}
</outcome>

Give the score, the matching label, and a one-paragraph explanation that names each
deduction with the specific value that triggered it. Call submit_judgement."""

SUBMIT_JUDGEMENT_TOOL = {
    "name": "submit_judgement",
    "description": "Submit the design-soundness judgement.",
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": LABELS},
            "score": {"type": "number", "description": "0.0 unsound .. 1.0 sound"},
            "explanation": {"type": "string", "description": "one paragraph, cite specific values"},
        },
        "required": ["label", "score", "explanation"],
    },
}


def judge_design(requirements: dict, design: dict, outcome: str) -> dict:
    """Run the LLM-as-judge over one design. Returns {label, score, explanation}."""
    prompt = EVAL_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        design=json.dumps(design, indent=2),
        outcome=outcome,
    )
    return one_tool_call(
        "You are a meticulous propulsion design reviewer.",
        prompt, SUBMIT_JUDGEMENT_TOOL, tool_name="submit_judgement", max_tokens=2000)


def judge_run(trace_path: str | Path) -> dict:
    """Judge a finished loop run from its loop_trace.json (uses the final design)."""
    trace_path = Path(trace_path)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    iters = trace.get("iterations", [])
    if not iters:
        raise ValueError("no iterations in trace")
    last = iters[-1]
    design_path = last.get("design_path")
    design = json.loads(Path(design_path).read_text(encoding="utf-8")) if design_path else {}

    # requirements live next to the run as the session state, or re-read the spec
    requirements = {"name": trace.get("spec")}
    outcome = (f"Deterministic verdict: {last['verdict']['summary']}; "
               f"passed={trace.get('passed')} after {trace.get('iterations_used')} iteration(s), "
               f"{trace.get('restarts', 0)} restart(s).")
    return judge_design(requirements, design, outcome)


def main(argv=None) -> int:
    _load_dotenv()
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m loop.judge <loop_trace.json>")
        return 2
    result = judge_run(args[0])
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
