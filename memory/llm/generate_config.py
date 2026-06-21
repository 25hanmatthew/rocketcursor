import argparse
import json
from pathlib import Path

from memory.llm.pdf_config_generator import DEFAULT_USER_PROMPT, generate_config_from_pdf


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate a fluid-network JSON config from a PDF using Claude."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", help="Local PDF path.")
    source.add_argument("--pdf-url", help="Direct URL to a PDF.")

    parser.add_argument(
        "--prompt",
        default=DEFAULT_USER_PROMPT,
        help="Prompt describing what numbers/config to extract.",
    )
    parser.add_argument(
        "--out",
        default="generated_config.json",
        help="Where to write the generated config JSON.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Anthropic model override. Defaults to ANTHROPIC_MODEL or claude-sonnet-4-6.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    result = generate_config_from_pdf(
        pdf_path=args.pdf,
        pdf_url=args.pdf_url,
        user_prompt=args.prompt,
        model=args.model or None,
    )

    print(json.dumps(result, indent=2))

    if result["ok"]:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(result["config"], indent=2), encoding="utf-8")
        print(f"Wrote {out_path}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())