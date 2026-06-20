import argparse
import json
import sys
from pathlib import Path

from network_io import (
    NetworkConfigError,
    export_results,
    load_network_config,
    run_loaded_network,
)


def _json_error(message, errors=None):
    payload = {"ok": False, "message": message}
    if errors:
        payload["errors"] = list(errors)
    print(json.dumps(payload, indent=2), file=sys.stderr)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate and run a fluid-network JSON configuration."
    )
    parser.add_argument("config", help="Path to a GUI-compatible network JSON file.")
    parser.add_argument(
        "--out",
        help="Output directory for nodes.csv, connections.csv, and summary.json. "
        "Defaults to results/<config-stem>.",
    )
    parser.add_argument("--duration", type=float, help="Override JSON duration in seconds.")
    parser.add_argument("--dt", type=float, help="Override JSON timestep in seconds.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate and instantiate the network without running a simulation.",
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Save simple PNG plots to the output directory.",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Accepted for explicit headless runs; this is the default.",
    )
    parser.add_argument(
        "--verbose-steps",
        type=int,
        default=0,
        help="Number of initial simulation steps to print from Network.sim.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        loaded = load_network_config(args.config)
        if args.duration is not None:
            loaded.duration = args.duration
        if args.dt is not None:
            loaded.dt = args.dt

        if args.validate_only:
            payload = {
                "ok": True,
                "config_path": str(Path(args.config)),
                "duration": loaded.duration,
                "dt": loaded.dt,
                "component_counts": {
                    "nodes": len(loaded.nodes),
                    "connections": len(loaded.connections),
                    "actions": sum(len(items) for items in loaded.actions.values()),
                },
                "warnings": loaded.warnings,
            }
            print(json.dumps(payload, indent=2))
            return 0

        output_dir = Path(args.out) if args.out else Path("results") / Path(args.config).stem
        run_loaded_network(
            loaded,
            duration=loaded.duration,
            dt=loaded.dt,
            verbose_steps=args.verbose_steps,
        )
        summary = export_results(loaded, output_dir, save_plots=args.plots and not args.no_plots)
        payload = {"ok": True, **summary}
        print(json.dumps(payload, indent=2))
        return 0

    except NetworkConfigError as e:
        _json_error("Network configuration error", e.errors)
        return 1
    except Exception as e:
        _json_error("Simulation failed", [str(e)])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
