"""Benchmark the requirement-aware compression over real design runs.

For every saved iteration we compare what a naive agent loop would feed back to the
LLM (the simulator's full time-series: nodes.csv + connections.csv) against what we
actually send (the deterministic verdict from loop.compression). Savings compound:
the raw cost recurs *every* iteration of a multi-step design loop.

    python -m loop.compression_benchmark            # table + totals
    python -m loop.compression_benchmark --json     # also writes results/compression/benchmark.json
"""

from __future__ import annotations

import glob
import json
import os
import sys

from loop.compression import compress_verdict, compression_stats, estimate_tokens

SPECS = {json.load(open(p))["name"]: json.load(open(p))
         for p in glob.glob("loop/specs/*.json")}


def _raw_sim_text(iter_dir: str) -> str:
    parts = []
    for fname in ("nodes.csv", "connections.csv"):
        path = os.path.join(iter_dir, fname)
        if os.path.exists(path):
            parts.append(open(path).read())
    return "".join(parts)


def run() -> dict:
    runs = []
    for spec_dir in sorted(glob.glob("results/loop_runs/*")):
        spec_name = os.path.basename(spec_dir)
        spec = SPECS.get(spec_name)
        if not spec:
            continue  # ephemeral/probe run with no curated spec — skip
        iters = sorted(glob.glob(f"{spec_dir}/iter_*"))
        per_iter = []
        for d in iters:
            raw = _raw_sim_text(d)
            rpath = os.path.join(d, "simulation_result.json")
            if not raw or not os.path.exists(rpath):
                continue
            result = json.load(open(rpath))
            try:
                compressed = compress_verdict(spec, result)
            except Exception:  # noqa: BLE001 - a bad saved run shouldn't sink the benchmark
                continue
            st = compression_stats(raw, compressed)
            per_iter.append(st)
        if not per_iter:
            continue
        raw_tok = sum(s.raw_tokens for s in per_iter)
        comp_tok = sum(s.compressed_tokens for s in per_iter)
        runs.append({
            "spec": spec_name,
            "iterations": len(per_iter),
            "raw_tokens": raw_tok,
            "compressed_tokens": comp_tok,
            "tokens_saved": raw_tok - comp_tok,
            "reduction_pct": round((1 - comp_tok / raw_tok) * 100, 2) if raw_tok else 0.0,
        })

    total_raw = sum(r["raw_tokens"] for r in runs)
    total_comp = sum(r["compressed_tokens"] for r in runs)
    total_iters = sum(r["iterations"] for r in runs)
    summary = {
        "runs_measured": len(runs),
        "iterations_measured": total_iters,
        "raw_tokens": total_raw,
        "compressed_tokens": total_comp,
        "tokens_saved": total_raw - total_comp,
        "reduction_pct": round((1 - total_comp / total_raw) * 100, 2) if total_raw else 0.0,
        "avg_raw_tokens_per_iter": round(total_raw / total_iters) if total_iters else 0,
        "avg_compressed_tokens_per_iter": round(total_comp / total_iters) if total_iters else 0,
    }
    return {"runs": runs, "summary": summary}


def _fmt(n: int) -> str:
    return f"{n:,}"


def main() -> None:
    report = run()
    print(f"\n{'spec':<30} {'iters':>5} {'raw tok':>12} {'sent tok':>10} {'reduction':>10}")
    print("-" * 70)
    for r in report["runs"]:
        print(f"{r['spec']:<30} {r['iterations']:>5} {_fmt(r['raw_tokens']):>12} "
              f"{_fmt(r['compressed_tokens']):>10} {r['reduction_pct']:>9.2f}%")
    s = report["summary"]
    print("-" * 70)
    print(f"{'TOTAL':<30} {s['iterations_measured']:>5} {_fmt(s['raw_tokens']):>12} "
          f"{_fmt(s['compressed_tokens']):>10} {s['reduction_pct']:>9.2f}%")
    print(f"\nAcross {s['runs_measured']} runs / {s['iterations_measured']} iterations: "
          f"compressed ~{_fmt(s['raw_tokens'])} tokens of raw simulator output down to "
          f"~{_fmt(s['compressed_tokens'])} ({s['reduction_pct']:.2f}% reduction).")
    print(f"Per iteration: ~{_fmt(s['avg_raw_tokens_per_iter'])} raw -> "
          f"~{_fmt(s['avg_compressed_tokens_per_iter'])} sent.")
    print("(~tokens estimated at 4 chars/token; the ratio is tokenizer-robust.)")

    if "--json" in sys.argv:
        os.makedirs("results/compression", exist_ok=True)
        out = "results/compression/benchmark.json"
        with open(out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
