"""The design -> simulate -> evaluate -> revise loop, orchestrated end to end.

An LLM (ASI1 by default, or Anthropic) designs a fluid-network JSON for a
requirements spec; the simulator adapter runs it; the (pure-Python) evaluator
produces a verdict; the verdict is fed back to the LLM to revise; repeat until the
verdict passes or we hit the iteration cap. The provider is chosen by
LLM_PROVIDER (see loop.llm); the deterministic verdict never depends on it.

Run:
    # keys come from .env (ASI1_API_KEY / ANTHROPIC_API_KEY); auto-loaded
    python -m loop.agent loop/specs/tank_blowdown.json --max-iters 4

Outputs land in results/loop_runs/<spec-name>/iter_NN/ and a loop_trace.json
summarizing every iteration is written at the run root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from loop.classifier import IterationOutcome, classify
from loop.design_seeds import get_design_seed
from loop.evaluator import evaluate
from loop.llm import ToolLoopSession
from loop.monitoring import capture as sentry_capture
from loop.monitoring import init_sentry
from loop.session_state import (
    SessionStore,
    get_store,
    iteration_view,
    new_state,
    report_view,
    requirements_view,
)
from loop.simulator_adapter import run_design
from loop.tracing import enable_tracing

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader (no dependency). Does not overwrite existing env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _maybe_enable_compression(session: ToolLoopSession, use_compression: bool) -> None:
    """Wrap an Anthropic-provider session's client with the-token-company prompt
    compression. No-op for ASI1 (TTC's wrapper targets the Anthropic SDK only)."""
    if not use_compression:
        return
    if session.provider != "anthropic":
        print(f"[loop] --compress ignored: TTC compression is Anthropic-only "
              f"(active provider: {session.provider})")
        return
    ttc_key = os.environ.get("TTC_API_KEY")
    if not ttc_key:
        print("[loop] --compress requested but TTC_API_KEY not set; using uncompressed client")
        return
    try:
        from thetokencompany.anthropic import with_compression

        # TTC compression is lossy/paraphrasing and applies to system/user/tool
        # content. The static system prompt is safe to paraphrase; the spec (user)
        # and verdict (tool_result) carry precise numbers and are wrapped in
        # protect() (see _get_protect) so they pass through byte-exact.
        session._client = with_compression(
            session._client, compression_api_key=ttc_key, aggressiveness=0.3, web_search=False)
        print("[loop] the-token-company prompt compression ENABLED")
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        print(f"[loop] TTC compression unavailable ({exc}); using uncompressed client")


def _get_protect(use_compression: bool):
    """Return TTC's protect() (wraps a span so compression skips it) when
    compression is active, else an identity function."""
    if not use_compression or not os.environ.get("TTC_API_KEY"):
        return lambda s: s
    try:
        from thetokencompany import protect

        return protect
    except Exception:  # noqa: BLE001
        return lambda s: s

SUBMIT_DESIGN_TOOL = {
    "name": "submit_design",
    "description": "Submit a complete fluid-network design as JSON to be simulated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "settings": {
                "type": "object",
                "description": "Simulation settings: {\"duration\": seconds, \"dt\": seconds}.",
            },
            "nodes": {
                "type": "array",
                "description": (
                    "Nodes. Each: {\"id\": int, \"type\": \"Node\"|\"Ambient\"|\"Tank\"|\"Engine\", "
                    "\"params\": {...}}. Use Node for simple pressurized reservoirs: "
                    "fluid, P (Pa), V (liters), T (K), name. Ambient params: fluid, "
                    "P (Pa), T (K), name. Tank is only for liquid plus ullage and "
                    "does NOT accept simple fluid/P/V/T params; Tank requires "
                    "V_total_L, fluid_liq, m_liq, T_liq, fluid_ullage, P_ullage, "
                    "T_ullage, name."
                ),
            },
            "connections": {
                "type": "array",
                "description": (
                    "Connections. Each: {\"type\": \"Connection\"|\"Line\"|\"Regulator\"|"
                    "\"BangBang\"|\"ThrottleValve\"|\"Series\", \"start_id\": int, \"end_id\": int, "
                    "\"params\": {...}}. Connection params: CdA (m^2 effective area), name, "
                    "normal_state (1=open), checking (1), location (0.0)."
                ),
            },
            "actions": {
                "type": "array",
                "description": "Optional scheduled state changes: {time, component, state}.",
            },
        },
        "required": ["settings", "nodes", "connections"],
    },
}

SYSTEM_PROMPT = """\
You are a propulsion feed-system design agent. You design transient fluid
networks as JSON and submit them via the submit_design tool to be simulated.

Network format (SI units unless noted; Node/Tank volumes are in LITERS):
- A design has: settings {duration, dt}, nodes [], connections [], actions [].
- Node types: "Node" (a finite control volume; params: fluid, P[Pa], V[liters],
  T[K], name), "Ambient" (an infinite boundary; params: fluid, P[Pa], T[K],
  name), "Tank", "Engine".
- Use "Node" by default for simple pressurized reservoirs, bottles, feed sources,
  and sinks. Do not use "Tank" just because the component is called a tank.
- Use "Tank" only when you need liquid plus ullage behavior. Tank params are
  exactly: V_total_L, fluid_liq, m_liq, T_liq, fluid_ullage, P_ullage,
  T_ullage, name. Tank does NOT accept the simple Node params fluid/P/V/T.
- For kerosene-like liquid fuel inside simulator Tank nodes, use fluid_liq
  "n-Dodecane". Use Engine fuel "Kerosene" only in Engine params where needed.
- Connection types: "Connection" (an orifice; params: CdA[m^2], name,
  normal_state=1, checking=1, location=0.0), "Line", "Regulator", "BangBang",
  "ThrottleValve", "Series".
- Each connection has start_id and end_id referencing node ids.

Engine designs (liquid rocket engines):
- An "Engine" node burns an oxidizer and a fuel. params: fuel and oxidizer
  (CEA propellant names, e.g. fuel="CH4", oxidizer="LOX"), At (throat area, m^2),
  Ae (exit area, m^2), Pa (ambient pressure, Pa), eta_cstar (~0.9), eta_cf (~0.95), name.
- TOPOLOGY RULE (enforced by the validator): an Engine must have EXACTLY ONE
  oxidizer feed and EXACTLY ONE fuel feed (Connections) ending at it. Which feed
  is the oxidizer is decided by the SOURCE node's fluid: a source whose fluid is
  Oxygen / LOX / N2O is the oxidizer feed; any other source is the fuel feed.
- So a minimal engine is: an oxidizer source Node (fluid "Oxygen", high pressure)
  -> Connection -> Engine, and a fuel source Node (fluid "Methane", high pressure)
  -> Connection -> Engine.
- The Engine records these history fields you can target: P (chamber pressure Pc),
  thrust (N), Isp (s), MR (mixture ratio = mdot_ox/mdot_fuel), cstar, T (chamber temp).
- Sizing intuition: chamber pressure Pc ~ total_mdot * cstar / At, thrust ~ Cf * Pc * At,
  and MR is set by the ratio of the oxidizer-feed to fuel-feed flows. Tune the two
  feed CdAs: their magnitude sets total flow (thrust, Pc); their ratio sets MR.

Rules:
- You MUST call submit_design exactly once per turn with a full design.
- Use the EXACT component names the requirements ask for (they are checked by name).
- If the prompt includes a SEED DESIGN, preserve its working topology and
  component names. Tune numeric values first before changing component types.
- If a `physical` check fails, fix the warning component before tuning target
  checks. If a feed `mdot` check is zero, create pressure drop across that feed.
- When adding optional x/y coordinates for the UI, lay the network out top-down.
- After each simulation you receive a deterministic verdict listing which
  checks passed/failed with the actual measured values. Revise the design to
  fix the failing checks. Pay attention to the `actual` values: they tell you
  how far off you are and in which direction.
- The verdict is produced by Python, not by you. Do not argue with it; satisfy it.
"""

# Engineering-soundness guidance, derived from recurring LLM-as-judge findings
# (loop/judge.py). Appended to the system prompt to (hypothetically) lift design
# QUALITY beyond merely passing the numeric checks. Toggleable so we can measure it.
# NOTE: default OFF. The eval-driven experiment (loop/experiment.py) showed this
# guidance REGRESSED both pass-rate and judged soundness on our spec suite, so we
# don't ship it on by default — a worked example of an eval catching a bad change.
SOUNDNESS_GUIDANCE = """\

Engineering soundness (a reviewer will judge design QUALITY, not just whether the
checks pass — so get these right):
- Propellant thermal state: store each liquid at a temperature that is actually
  liquid at its tank pressure, and above its freezing point. Cryogens (LOX ~90 K,
  liquid methane ~110 K) are fine but keep them in their liquid range, not subcooled
  to implausible temperatures.
- Pressure-fed reality: with no separate pressurant, a tank blows down as it drains.
  Size tank volume so pressure stays adequate across the burn (or keep the burn short
  relative to tank volume); don't assume constant pressure from an empty-ing tank.
- Nozzle expansion ratio: choose Ae/At sensibly for the chamber pressure and ambient.
  At sea level a very low Ae/At over-expands and a very high one under-expands; pick a
  ratio that isn't grossly mismatched to Pc.
- Right-size components: propellant tanks should be commensurate with the burn (don't
  store orders of magnitude more propellant than the burn consumes); feed orifices
  should not choke flow far below what the engine throat passes.
"""


def effective_system_prompt(soundness_guidance: bool = True) -> str:
    return SYSTEM_PROMPT + (SOUNDNESS_GUIDANCE if soundness_guidance else "")


def _first_user_message(spec: dict, protect=lambda s: s, seed: dict | None = None) -> str:
    message = (
        "Design a fluid network that satisfies this requirements spec.\n\n"
        "SPEC:\n" + protect(json.dumps(spec, indent=2)) + "\n\n"
    )
    if seed:
        message += (
            "SEED DESIGN:\n"
            "Use this known-good simulator topology as the starting point. Preserve "
            "component names and topology unless the spec makes that impossible; tune "
            "numeric values first.\n\n"
            "SEED METADATA:\n" + protect(json.dumps(seed["metadata"], indent=2)) + "\n\n"
            "SEED JSON:\n" + protect(json.dumps(seed["design"], indent=2)) + "\n\n"
        )
    return message + "Call submit_design with your design now."


def _verdict_feedback(verdict, result) -> str:
    lines = [f"VERDICT: {verdict.summary}", ""]
    for c in verdict.checks:
        mark = "PASS" if c.passed else "FAIL"
        line = f"[{mark}] {c.id}: {c.description}"
        if not c.passed:
            line += f"\n        expected {c.op} {c.expected!r}; actual={c.actual!r}"
            if c.detail:
                line += f" ({c.detail})"
        lines.append(line)
    if result.get("errors"):
        lines += ["", "SIMULATION ERRORS:"] + [f"  - {e}" for e in result["errors"]]
    if verdict.notes:
        lines += [""] + verdict.notes
    if not verdict.passed:
        lines += ["", "Revise the design to fix the FAILing checks, then call submit_design again."]
    return "\n".join(lines)


def run_loop(spec_path: str | Path, max_iters: int = 4, use_compression: bool = False,
             store: SessionStore | None = None, session_id: str | None = None,
             request: str | None = None, max_restarts: int = 2,
             soundness_guidance: bool = False) -> dict:
    _load_dotenv()
    enable_tracing()  # Arize AX: auto-traces ASI1/OpenAI calls if ARIZE_* creds are set
    init_sentry(component="loop")  # error monitoring; no-op without SENTRY_DSN
    system_prompt = effective_system_prompt(soundness_guidance)
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    run_root = REPO_ROOT / "results" / "loop_runs" / spec["name"]
    run_root.mkdir(parents=True, exist_ok=True)

    protect = _get_protect(use_compression)
    session = ToolLoopSession(system_prompt, SUBMIT_DESIGN_TOOL, tool_name="submit_design")
    _maybe_enable_compression(session, use_compression)
    trace = {"spec": spec["name"], "provider": session.provider, "model": session.model,
             "compression": use_compression, "restarts": 0, "iterations": []}

    # session state for the Redis/UI seam (filesystem store unless REDIS_URL is set)
    store = store or get_store()
    session_id = session_id or spec["name"]
    state = new_state(session_id, request or spec["name"], session.provider, session.model)
    state["requirements"] = requirements_view(spec)   # -> UI requirements-review screen
    state["stage"] = "design"
    store.write(state)

    seed_name = (spec.get("design_guidance") or {}).get("design_seed")
    seed = get_design_seed(seed_name)
    if seed_name and seed is None:
        print(f"[loop] unknown design_seed {seed_name!r}; continuing without seed")
    first_msg = _first_user_message(spec, protect, seed=seed)
    final_verdict = None
    final_design = None
    line: list[IterationOutcome] = []   # outcomes since the last restart
    restarts_used = 0
    dead_ends: list[str] = []
    design = session.first(first_msg)
    for i in range(max_iters):
        if design is None:
            design = session.nudge("You did not call submit_design. Call it now with a full design.")
            if design is None:
                break
            continue
        final_design = design

        state["stage"] = "simulate"; state["current_iteration"] = i; store.write(state)
        iter_dir = run_root / f"iter_{i:02d}"
        result = run_design(design, iter_dir)
        verdict = evaluate(spec, result)
        final_verdict = verdict
        verdict_dict = verdict.to_dict()
        n_passed = sum(1 for c in verdict.checks if c.passed)

        feedback = _verdict_feedback(verdict, result)
        print(f"\n=== iteration {i} -> {verdict.summary} (sim status: {result['status']}) ===")
        print(feedback)

        # classify the failure: revise the current line, or scrap and start over
        line.append(IterationOutcome(result["status"], verdict.passed, n_passed, len(verdict.checks)))
        decision = classify(line, restarts_used, max_restarts)
        if not verdict.passed:
            print(f"[classifier] {decision.action.upper()}: {decision.reason}")

        trace["iterations"].append({
            "iteration": i, "status": result["status"], "verdict": verdict_dict,
            "design_path": result["design_path"],
            "decision": {"action": decision.action, "reason": decision.reason},
        })
        # emit the live design + per-node status + checklist + decision for the UI
        state["stage"] = "evaluate"
        iv = iteration_view(i, design, result, verdict_dict)
        iv["decision"] = {"action": decision.action, "reason": decision.reason}
        state["iterations"].append(iv)
        store.write(state)

        if verdict.passed:
            break

        if decision.action == "scrap":
            dead_ends.append(f"Attempt {restarts_used + 1}: {verdict.summary}; "
                             f"unmet checks: {sorted(c.id for c in verdict.checks if not c.passed)}")
            restarts_used += 1
            trace["restarts"] = restarts_used
            line = []
            state["stage"] = "design"; store.write(state)
            # fresh design line, but tell the model which approaches already failed
            session = ToolLoopSession(system_prompt, SUBMIT_DESIGN_TOOL, tool_name="submit_design")
            _maybe_enable_compression(session, use_compression)
            restart_msg = first_msg + "\n\n" + protect(
                "Your earlier design approaches FAILED — do NOT repeat them; try a "
                "materially different design:\n" + "\n".join(dead_ends))
            design = session.first(restart_msg)
        else:
            # feed the deterministic verdict back; protect() keeps numbers byte-exact under TTC
            design = session.tool_result(protect(feedback), is_error=not verdict.passed)

    trace["passed"] = bool(final_verdict and final_verdict.passed)
    trace["iterations_used"] = len(trace["iterations"])
    (run_root / "loop_trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")

    # final report state for the UI failure/success browser
    state["stage"] = "report"
    state["passed"] = trace["passed"]
    state["status"] = "passed" if trace["passed"] else "failed"
    state["iterations_used"] = trace["iterations_used"]
    state["report"] = report_view(
        trace["passed"], final_verdict.to_dict() if final_verdict else None,
        final_design, trace["iterations_used"])
    store.write(state)

    # optional LLM-as-judge layer (Arize eval track): scores design *soundness*
    # beyond the deterministic pass/fail. Opt-in via env LOOP_JUDGE=1 (extra LLM call).
    if os.environ.get("LOOP_JUDGE") == "1" and final_design is not None:
        try:
            from loop.judge import judge_design

            outcome = (f"Deterministic verdict: "
                       f"{final_verdict.summary if final_verdict else 'n/a'}; passed={trace['passed']} "
                       f"after {trace['iterations_used']} iteration(s), {trace['restarts']} restart(s).")
            quality = judge_design(requirements_view(spec), final_design, outcome)
            trace["quality"] = quality
            state["quality"] = quality
            store.write(state)
            (run_root / "loop_trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")
            print(f"[judge] soundness: {quality['label']} ({quality['score']}) — {quality['explanation'][:120]}")
        except Exception as exc:  # noqa: BLE001 - eval must never break the run
            print(f"[judge] skipped ({type(exc).__name__}: {exc})")

    print(f"\n{'PASSED' if trace['passed'] else 'DID NOT PASS'} "
          f"after {trace['iterations_used']} iteration(s). Trace: {run_root / 'loop_trace.json'}")
    return trace


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the design->simulate->evaluate->revise loop.")
    parser.add_argument("spec", help="Path to a requirements spec JSON (e.g. loop/specs/tank_blowdown.json).")
    parser.add_argument("--max-iters", type=int, default=4, help="Max design/revise iterations.")
    parser.add_argument("--compress", action="store_true",
                        help="Route Anthropic calls through the-token-company prompt compression (TTC_API_KEY).")
    args = parser.parse_args(argv)
    trace = run_loop(args.spec, max_iters=args.max_iters, use_compression=args.compress)
    return 0 if trace["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
