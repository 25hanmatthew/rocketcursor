"""One-shot measured baseline for the paper: have a frontier LLM summarize the raw
simulator CSV (the naive 'just summarize the tool output' strategy), then measure
(a) its size in TTC's tokenizer and (b) whether it preserves the decision-relevant
failing actual (end-of-burn thrust = 1136.79 N) that our verdict keeps byte-exact.

    python -m loop._paper_summarization_baseline
"""
from __future__ import annotations

import json
import os

from loop.agent import _load_dotenv
from loop.compression_benchmark import _raw_sim_text


def main() -> None:
    _load_dotenv()
    d = "results/loop_runs/lox_methane_engine/iter_00"
    raw = _raw_sim_text(d)

    import anthropic
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (
        "You are assisting a rocket-engine design loop. Below is the full transient "
        "time-series output of a fluid-network simulation (nodes.csv then "
        "connections.csv). Summarize it for the design model so it can revise the "
        "design. Preserve every engineering quantity that could matter for a "
        "pass/fail decision. Be as concise as possible.\n\n" + raw
    )
    msg = client.messages.create(
        model=model, max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    summary = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    # Size in TTC's tokenizer (apples-to-apples with the head-to-head table).
    import thetokencompany as ttc
    tcli = ttc.TheTokenCompany(api_key=os.environ["TTC_API_KEY"])
    summ_tok = tcli.compress(summary, model="bear-2", aggressiveness=0.2).input_tokens

    # Does the summary preserve the exact failing actual our verdict keeps?
    preserves_exact = "1136.79" in summary or "1136.7886" in summary
    mentions_rounded = any(s in summary for s in ("1137", "1136", "1140", "1100"))

    print(json.dumps({
        "model": model,
        "summary_tokens_ttc": summ_tok,
        "summary_chars": len(summary),
        "preserves_exact_failing_thrust_1136_79": preserves_exact,
        "mentions_rounded_thrust": mentions_rounded,
        "api_out_tokens": msg.usage.output_tokens,
        "api_in_tokens": msg.usage.input_tokens,
    }, indent=2))
    with open("results/compression/summarization_baseline.json", "w") as f:
        json.dump({
            "summary": summary,
            "summary_tokens_ttc": summ_tok,
            "preserves_exact_failing_thrust_1136_79": preserves_exact,
            "model": model,
        }, f, indent=2)
    print("\n--- summary (first 1200 chars) ---\n" + summary[:1200])


if __name__ == "__main__":
    main()
