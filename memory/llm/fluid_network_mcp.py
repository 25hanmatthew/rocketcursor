from .pdf_config_generator import generate_config_from_pdf
import json
import uuid
from pathlib import Path

from network_io import (
    NetworkConfigError,
    export_results,
    load_network_config,
    run_loaded_network,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_RUN_ROOT = ROOT / "results" / "mcp_runs"
ALLOWED_RESULT_FILES = {
    "summary.json",
    "diagnostics.json",
    "nodes_summary.json",
    "connections_summary.json",
    "report.json",
    "report.md",
    "nodes.csv",
    "connections.csv",
}


def _error_payload(message, errors=None):
    payload = {"ok": False, "message": message}
    if errors:
        payload["errors"] = list(errors)
    return payload


def _component_counts(loaded):
    return {
        "nodes": len(loaded.nodes),
        "connections": len(loaded.connections),
        "actions": sum(len(items) for items in loaded.actions.values()),
    }


def _resolve_config_source(config_path=None, config_json=None, run_dir=None):
    if config_path and config_json is not None:
        raise NetworkConfigError(["Provide either config_path or config_json, not both."])
    if not config_path and config_json is None:
        raise NetworkConfigError(["Provide one of config_path or config_json."])

    if config_path:
        return Path(config_path)

    if not isinstance(config_json, dict):
        raise NetworkConfigError(["config_json must be a JSON object."])

    run_dir = Path(run_dir) if run_dir else DEFAULT_RUN_ROOT / f"inline_{uuid.uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=True)
    config_file = run_dir / "config.json"
    config_file.write_text(json.dumps(config_json, indent=2), encoding="utf-8")
    return config_file


def get_network_schema():
    """Return the JSON schema used by run_network.py and the MCP tools."""
    schema_path = ROOT / "network_schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_network(config_path=None, config_json=None):
    """Validate and instantiate a network config without running simulation."""
    try:
        config_file = _resolve_config_source(config_path=config_path, config_json=config_json)
        loaded = load_network_config(config_file)
        return {
            "ok": True,
            "config_path": str(config_file),
            "duration": loaded.duration,
            "dt": loaded.dt,
            "component_counts": _component_counts(loaded),
            "warnings": loaded.warnings,
        }
    except NetworkConfigError as e:
        return _error_payload("Network configuration error", e.errors)
    except Exception as e:
        return _error_payload("Validation failed", [str(e)])


def run_network(
    config_path=None,
    config_json=None,
    output_dir=None,
    duration=None,
    dt=None,
    plots=False,
):
    """Run a network config and export compact machine-readable results."""
    try:
        run_id = uuid.uuid4().hex
        base_run_dir = Path(output_dir) if output_dir else DEFAULT_RUN_ROOT / run_id
        config_file = _resolve_config_source(
            config_path=config_path,
            config_json=config_json,
            run_dir=base_run_dir,
        )
        loaded = load_network_config(config_file)
        if duration is not None:
            loaded.duration = float(duration)
        if dt is not None:
            loaded.dt = float(dt)

        run_loaded_network(loaded, duration=loaded.duration, dt=loaded.dt, verbose_steps=0)
        summary = export_results(loaded, base_run_dir, save_plots=bool(plots))
        return {"ok": True, **summary}
    except NetworkConfigError as e:
        return _error_payload("Network configuration error", e.errors)
    except Exception as e:
        return _error_payload("Simulation failed", [str(e)])


def read_result(output_dir, result_name):
    """Read a known result file from an output directory."""
    try:
        if result_name not in ALLOWED_RESULT_FILES:
            return _error_payload(
                "Unsupported result_name",
                [f"Allowed values: {sorted(ALLOWED_RESULT_FILES)}"],
            )

        output_root = Path(output_dir).resolve()
        target = (output_root / result_name).resolve()
        try:
            target.relative_to(output_root)
        except ValueError:
            return _error_payload("Result path escapes output_dir")

        if not target.exists():
            return _error_payload("Result file does not exist", [str(target)])

        if target.suffix == ".json":
            return {
                "ok": True,
                "path": str(target),
                "content": json.loads(target.read_text(encoding="utf-8")),
            }
        return {"ok": True, "path": str(target), "content": target.read_text(encoding="utf-8")}
    except Exception as e:
        return _error_payload("Failed to read result", [str(e)])

def generate_network_config_from_pdf(
    pdf_path=None,
    pdf_url=None,
    prompt=None,
    output_config_path=None,
    model=None,
):
    """
    Generate a fluid-network config from a PDF document using Claude.

    Provide either:
    - pdf_path: local path to a PDF saved by the upstream web-search agent, or
    - pdf_url: direct URL to a PDF.

    If output_config_path is provided and validation succeeds, writes the config there.
    """
    try:
        result = generate_config_from_pdf(
            pdf_path=pdf_path,
            pdf_url=pdf_url,
            user_prompt=prompt or None,
            model=model or None,
        )

        if result.get("ok") and output_config_path:
            target = Path(output_config_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result["config"], indent=2), encoding="utf-8")
            result["output_config_path"] = str(target)

        return result
    except Exception as e:
        return _error_payload("PDF config generation failed", [str(e)])
    
def _build_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as e:
        raise RuntimeError(
            "The 'mcp' package is required to run the MCP server. "
            "Install requirements.txt first."
        ) from e
    
    mcp = FastMCP("general-fluid-network")
    mcp.tool()(get_network_schema)
    mcp.tool()(validate_network)
    mcp.tool()(run_network)
    mcp.tool()(read_result)
    mcp.tool()(generate_network_config_from_pdf)
    return mcp


def main():
    server = _build_mcp_server()
    try:
        server.run()
    except KeyboardInterrupt:
        print("MCP server stopped.")
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            print("MCP server stopped.")
        else:
            raise


if __name__ == "__main__":
    main()
