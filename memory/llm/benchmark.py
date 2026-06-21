"""Compression benchmark CLI.

Runs the fluid-network compressor on a PDF at a given token budget and writes a
compression_report.json with token savings and downstream-quality evidence
(simulator-runnable + optional QA round-trip). This is the demo deliverable for
the compression challenge.

Usage:
    python -m memory.llm.benchmark --pdf report.pdf --token-budget 4000 --qa 3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from memory.llm import prefilter
from memory.llm.evaluate import evaluate_config_runnable, qa_roundtrip
from memory.llm.pdf_config_generator import generate_config_from_pdf

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "results" / "compression_report.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark context compression on a PDF -> fluid-network config."
    )
    parser.add_argument("--pdf", required=True, help="Local PDF path.")
    parser.add_argument(
        "--token-budget",
        type=int,
        default=4000,
        dest="token_budget",
        help="Max tokens of source text sent to the frontier model (default: 4000).",
    )
    parser.add_argument(
        "--qa",
        type=int,
        default=0,
        metavar="N",
        help="Run an N-question QA round-trip vs the full document (default: 0 = skip).",
    )
    parser.add_argument("--model", default=None, help="Anthropic model override.")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"Where to write the report (default: {DEFAULT_OUT}).",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    result = generate_config_from_pdf(
        pdf_path=args.pdf,
        model=args.model or None,
        token_budget=args.token_budget,
    )

    report: dict = {
        "pdf": args.pdf,
        "token_budget": args.token_budget,
        "ok": result.get("ok"),
        "attempts": result.get("attempts"),
        "validation_errors": result.get("validation_errors", []),
        "metrics": result.get("metrics", {}),
        "manifest": result.get("manifest", {}),
    }

    if result.get("ok"):
        report["downstream_runnable"] = evaluate_config_runnable(result["config"])
    else:
        report["downstream_runnable"] = {
            "runnable": False,
            "errors": result.get("validation_errors", []),
        }

    if args.qa > 0 and result.get("ok"):
        full_text = prefilter.extract_pdf_text(args.pdf)
        report["qa_roundtrip"] = qa_roundtrip(
            full_text,
            json.dumps(result["config"]),
            n=args.qa,
            model=args.model or None,
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    metrics = report["metrics"]
    print(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")
    if metrics:
        print(
            f"Frontier token reduction: {metrics.get('frontier_reduction_pct')}% "
            f"({metrics.get('baseline_tokens_to_frontier')} -> "
            f"{metrics.get('tokens_to_frontier')} tokens); "
            f"runnable={report['downstream_runnable'].get('runnable')}"
        )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
