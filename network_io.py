import csv
import inspect
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import general_fluid_network as gfn


class NetworkConfigError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


@dataclass
class LoadedNetwork:
    path: Path
    data: dict[str, Any]
    network: Any | None = None
    nodes: dict[int, Any] = field(default_factory=dict)
    node_names: dict[int, str] = field(default_factory=dict)
    connections: list[Any] = field(default_factory=list)
    connection_names: list[str] = field(default_factory=list)
    actions: dict[float, list[tuple[Any, float]]] = field(default_factory=dict)
    duration: float = 0.0
    dt: float = 0.0
    warnings: list[str] = field(default_factory=list)
    output_files: dict[str, str] = field(default_factory=dict)


def _vehicle_sim_eta_cstar(pc_psi):
    return 0.8 + (0.85 - 0.8) * max(1, (pc_psi - 100) / 200)


def _vehicle_sim_eta_cf(pc_psi):
    return 0.94 + (0.97 - 0.94) * max(1, (pc_psi - 100) / 150)


def _tank_sizing_eta_cstar(pc_psi):
    if pc_psi >= 250:
        return 0.92
    return 0.75 + (0.92 - 0.75) * max(0, (pc_psi - 100) / 150)


def _tank_sizing_eta_cf(pc_psi):
    if pc_psi >= 250:
        return 0.96
    return 0.80 + (0.96 - 0.80) * max(0, (pc_psi - 100) / 150)


ENGINE_EFFICIENCY_MODELS = {
    "vehicle_sim.dynamic_eta_cstar": _vehicle_sim_eta_cstar,
    "vehicle_sim.dynamic_eta_cf": _vehicle_sim_eta_cf,
    "tank_sizing_sims.dynamic_eta_cstar": _tank_sizing_eta_cstar,
    "tank_sizing_sims.dynamic_eta_cf": _tank_sizing_eta_cf,
}

NODE_TYPES = {
    "Node": gfn.Node,
    "Ambient": gfn.Ambient,
    "Tank": gfn.Tank,
    "Engine": gfn.Engine,
}

CONNECTION_TYPES = {
    "Connection": gfn.Connection,
    "Line": gfn.Line,
    "Series": gfn.Series,
    "Regulator": gfn.Regulator,
    "BangBang": gfn.BangBang,
    "ThrottleValve": gfn.ThrottleValve,
}

ENGINE_OX_FLUIDS = {"oxygen", "lox", "n2o"}


def _constructor_kwargs(cls, params):
    sig = inspect.signature(cls.__init__)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return dict(params)

    allowed = {
        name
        for name, param in sig.parameters.items()
        if name != "self"
        and param.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {key: value for key, value in params.items() if key in allowed}


def _normalize_action_component_label(text):
    text = str(text).strip()
    for arrow in ("↳", "â†³"):
        if arrow in text:
            text = text.split(arrow, 1)[1].strip()
    if text.startswith("?"):
        text = text[1:].strip()
    return text


def _node_fluid(node_data):
    params = node_data.get("params", {})
    return str(params.get("fluid") or params.get("fluid_liq") or "").lower()


def _resolve_engine_efficiency(params, key, default):
    model = params.get(f"{key}_model")
    if model:
        try:
            return ENGINE_EFFICIENCY_MODELS[model]
        except KeyError as e:
            raise NetworkConfigError([f"nodes[].params.{key}_model: unknown model '{model}'"]) from e
    return params.get(key, default)


def _as_float(value, path):
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise NetworkConfigError([f"{path}: expected a number, got {value!r}"]) from e


def _has_complete_pvt(params):
    return all(key in params for key in ("fluid", "P", "V", "T"))


def _has_complete_mvt(params):
    return all(key in params for key in ("fluid", "m", "V", "T"))


def _normalize_node_params(params, warnings=None, path="$.nodes[].params"):
    params = dict(params)
    if not _has_complete_pvt(params):
        return params

    if "m" in params and warnings is not None:
        name = params.get("name", path)
        warnings.append(
            f"{path}: Node {name!r} defines both P and m; using P/V/T and ignoring m."
        )

    fluid = params["fluid"]
    pressure = _as_float(params["P"], f"{path}.P")
    volume_l = _as_float(params["V"], f"{path}.V")
    temperature = _as_float(params["T"], f"{path}.T")
    density = gfn.PropsSI_auto("D", "P", pressure, "T", temperature, fluid)
    params["m"] = float(density) * (volume_l / 1000.0)
    params["type"] = params.get("type", "m")
    return params


def load_network_config(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise NetworkConfigError([f"{path}: failed to read JSON: {e}"]) from e

    loaded = LoadedNetwork(path=path, data=data)
    validate_loaded_network(loaded)
    _instantiate_loaded_network(loaded)
    return loaded


def validate_loaded_network(loaded):
    data = loaded.data
    errors = []

    if not isinstance(data, dict):
        raise NetworkConfigError(["$: expected a JSON object"])

    nodes = data.get("nodes")
    connections = data.get("connections")
    actions = data.get("actions", [])

    if not isinstance(nodes, list):
        errors.append("$.nodes: expected a list")
        nodes = []
    if not isinstance(connections, list):
        errors.append("$.connections: expected a list")
        connections = []
    if not isinstance(actions, list):
        errors.append("$.actions: expected a list")
        actions = []

    node_ids = {}
    for idx, node in enumerate(nodes):
        npath = f"$.nodes[{idx}]"
        if not isinstance(node, dict):
            errors.append(f"{npath}: expected an object")
            continue
        node_id = node.get("id")
        if node_id is None:
            errors.append(f"{npath}.id: required")
        elif node_id in node_ids:
            errors.append(f"{npath}.id: duplicate id {node_id!r}")
        else:
            node_ids[node_id] = node
        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            errors.append(f"{npath}.type: unsupported node type {node_type!r}")
        params = node.get("params")
        if not isinstance(params, dict):
            errors.append(f"{npath}.params: expected an object")
            params = {}
        if node_type == "Node" and isinstance(params, dict):
            has_pvt = _has_complete_pvt(params)
            has_mvt = _has_complete_mvt(params)
            if not has_pvt and not has_mvt:
                errors.append(
                    f"{npath}.params: Node requires preferred P/V/T/fluid "
                    "or legacy m/V/T/fluid"
                )
            if has_pvt:
                for key in ("P", "V", "T"):
                    try:
                        float(params.get(key))
                    except (TypeError, ValueError):
                        errors.append(f"{npath}.params.{key}: expected a number")
            elif has_mvt:
                for key in ("m", "V", "T"):
                    try:
                        float(params.get(key))
                    except (TypeError, ValueError):
                        errors.append(f"{npath}.params.{key}: expected a number")

    action_targets = {}
    connection_defs = []
    for idx, conn in enumerate(connections):
        cpath = f"$.connections[{idx}]"
        if not isinstance(conn, dict):
            errors.append(f"{cpath}: expected an object")
            continue
        conn_type = conn.get("type")
        params = conn.get("params")
        if conn_type not in CONNECTION_TYPES:
            errors.append(f"{cpath}.type: unsupported connection type {conn_type!r}")
        if not isinstance(params, dict):
            errors.append(f"{cpath}.params: expected an object")
            params = {}
        for endpoint in ("start_id", "end_id"):
            if conn.get(endpoint) not in node_ids:
                errors.append(f"{cpath}.{endpoint}: unknown node id {conn.get(endpoint)!r}")

        name = _normalize_action_component_label(params.get("name", ""))
        if name:
            action_targets.setdefault(name, []).append(cpath)
        connection_defs.append(conn)

        if conn_type == "Series":
            sub_connections = params.get("connections")
            if not isinstance(sub_connections, list) or not sub_connections:
                errors.append(f"{cpath}.params.connections: expected a non-empty list")
                sub_connections = []
            for sub_idx, sub in enumerate(sub_connections):
                spath = f"{cpath}.params.connections[{sub_idx}]"
                if not isinstance(sub, dict):
                    errors.append(f"{spath}: expected an object")
                    continue
                sub_type = sub.get("type")
                sub_params = sub.get("params")
                if sub_type not in CONNECTION_TYPES or sub_type == "Series":
                    errors.append(f"{spath}.type: unsupported series subcomponent type {sub_type!r}")
                if not isinstance(sub_params, dict):
                    errors.append(f"{spath}.params: expected an object")
                    sub_params = {}
                sub_name = _normalize_action_component_label(sub_params.get("name", ""))
                if sub_name:
                    action_targets.setdefault(sub_name, []).append(spath)

    for idx, node in enumerate(nodes):
        if not isinstance(node, dict) or node.get("type") != "Engine":
            continue
        engine_id = node.get("id")
        incoming = [conn for conn in connection_defs if conn.get("end_id") == engine_id]
        ox_count = 0
        fuel_count = 0
        for conn in incoming:
            source_node = node_ids.get(conn.get("start_id"), {})
            if _node_fluid(source_node) in ENGINE_OX_FLUIDS:
                ox_count += 1
            else:
                fuel_count += 1
        if ox_count != 1 or fuel_count != 1:
            errors.append(
                f"$.nodes[{idx}]: Engine requires exactly one oxidizer feed and "
                f"one fuel feed ending at the engine; found ox={ox_count}, fuel={fuel_count}"
            )

    for idx, action in enumerate(actions):
        apath = f"$.actions[{idx}]"
        if not isinstance(action, dict):
            errors.append(f"{apath}: expected an object")
            continue
        target = _normalize_action_component_label(action.get("component", ""))
        if not target:
            errors.append(f"{apath}.component: required")
        elif target not in action_targets:
            errors.append(f"{apath}.component: unknown action target {action.get('component')!r}")
        elif len(action_targets[target]) > 1:
            errors.append(
                f"{apath}.component: ambiguous target {target!r}; matches {action_targets[target]}"
            )
        for key in ("time", "state"):
            try:
                float(action.get(key))
            except (TypeError, ValueError):
                errors.append(f"{apath}.{key}: expected a number")

    settings = data.get("settings", {})
    if settings is not None and not isinstance(settings, dict):
        errors.append("$.settings: expected an object")
    else:
        for key in ("duration", "dt"):
            if key in settings:
                try:
                    float(settings[key])
                except (TypeError, ValueError):
                    errors.append(f"$.settings.{key}: expected a number")

    if errors:
        raise NetworkConfigError(errors)

    return True


def _instantiate_connection(conn_data):
    conn_type = conn_data["type"]
    params = conn_data["params"]
    if conn_type == "Series":
        sub_components = [
            _instantiate_connection(sub_data)
            for sub_data in params.get("connections", [])
        ]
        return gfn.Series(sub_components, params.get("name", "series"))

    cls = CONNECTION_TYPES[conn_type]
    return cls(**_constructor_kwargs(cls, params))


def _register_action_target(targets, name, obj):
    normalized = _normalize_action_component_label(name)
    if normalized:
        targets[normalized] = obj


def _instantiate_loaded_network(loaded):
    data = loaded.data
    nodes_data = data.get("nodes", [])
    connections_data = data.get("connections", [])
    settings = data.get("settings", {}) or {}

    node_defs = {node["id"]: node for node in nodes_data}
    graph = {}
    action_targets = {}

    for node_data in nodes_data:
        node_id = node_data["id"]
        node_type = node_data["type"]
        params = node_data["params"]
        loaded.node_names[node_id] = params.get("name", f"{node_type}_{node_id}")
        if node_type == "Engine":
            continue
        cls = NODE_TYPES[node_type]
        if node_type == "Node":
            params = _normalize_node_params(
                params,
                warnings=loaded.warnings,
                path=f"$.nodes[{node_id}].params",
            )
        loaded.nodes[node_id] = cls(**_constructor_kwargs(cls, params))

    for conn_data in connections_data:
        conn_obj = _instantiate_connection(conn_data)
        loaded.connections.append(conn_obj)
        conn_name = conn_data["params"].get("name", conn_obj.name)
        loaded.connection_names.append(conn_name)
        _register_action_target(action_targets, conn_name, conn_obj)
        if conn_data["type"] == "Series":
            for sub in conn_obj.connections:
                _register_action_target(action_targets, sub.name, sub)

    for node_data in nodes_data:
        if node_data["type"] != "Engine":
            continue

        engine_id = node_data["id"]
        params = node_data["params"]
        incoming = [
            (conn_data, conn_obj)
            for conn_data, conn_obj in zip(connections_data, loaded.connections)
            if conn_data["end_id"] == engine_id
        ]
        ox_conn = None
        fuel_conn = None
        for conn_data, conn_obj in incoming:
            source_node = node_defs[conn_data["start_id"]]
            if _node_fluid(source_node) in ENGINE_OX_FLUIDS:
                ox_conn = conn_obj
            else:
                fuel_conn = conn_obj

        loaded.nodes[engine_id] = gfn.Engine(
            fuel=params.get("fuel", "n-Dodecane"),
            oxidizer=params.get("oxidizer", "Oxygen"),
            ox_conn=ox_conn,
            fuel_conn=fuel_conn,
            eta_cstar=_resolve_engine_efficiency(params, "eta_cstar", 0.92),
            eta_cf=_resolve_engine_efficiency(params, "eta_cf", 0.98),
            At=params.get("At", 0.002),
            Ae=params.get("Ae", 0.01),
            Pa=params.get("Pa", 101325.0),
            name=params.get("name", "engine"),
        )

    for conn_data, conn_obj in zip(connections_data, loaded.connections):
        graph[conn_obj] = (
            loaded.nodes[conn_data["start_id"]],
            loaded.nodes[conn_data["end_id"]],
        )

    for action in data.get("actions", []):
        target = _normalize_action_component_label(action["component"])
        loaded.actions.setdefault(float(action["time"]), []).append(
            (action_targets[target], float(action["state"]))
        )

    loaded.duration = _as_float(settings.get("duration", 0.0), "$.settings.duration")
    loaded.dt = _as_float(settings.get("dt", 0.0), "$.settings.dt")
    loaded.network = gfn.Network(graph)


def run_loaded_network(loaded, duration=None, dt=None, verbose_steps=0):
    run_duration = loaded.duration if duration is None else float(duration)
    run_dt = loaded.dt if dt is None else float(dt)
    if run_duration <= 0:
        raise NetworkConfigError(["duration: must be greater than zero"])
    if run_dt <= 0:
        raise NetworkConfigError(["dt: must be greater than zero"])

    loaded.duration = run_duration
    loaded.dt = run_dt
    loaded.network.sim(run_duration, run_dt, actions=loaded.actions, verbose_steps=verbose_steps)
    return loaded


def _history_rows(component_name, kind, obj):
    history = getattr(obj, "history", {})
    times = history.get("time", [])
    keys = [key for key in history.keys() if key != "time"]
    rows = []
    for idx, time_value in enumerate(times):
        row = {"component": component_name, "kind": kind, "time": time_value}
        for key in keys:
            values = history.get(key, [])
            row[key] = values[idx] if idx < len(values) else None
        rows.append(row)
    return rows, keys


def _write_history_csv(path, rows, key_order):
    fieldnames = ["component", "kind", "time"] + sorted(key_order)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _final_state(obj):
    history = getattr(obj, "history", {})
    result = {}
    for key, values in history.items():
        if values:
            result[key] = _json_safe(values[-1])
    return result


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    try:
        if hasattr(value, "item"):
            return _json_safe(value.item())
    except Exception:
        pass
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except (TypeError, ValueError):
        return str(value)


def _numeric_values(values):
    numeric = []
    for value in values:
        safe_value = _json_safe(value)
        if isinstance(safe_value, (int, float)) and not isinstance(safe_value, bool):
            numeric.append(float(safe_value))
    return numeric


def _series_summary(values):
    numeric = _numeric_values(values)
    if not numeric:
        return None
    first = numeric[0]
    final = numeric[-1]
    min_value = min(numeric)
    max_value = max(numeric)
    return {
        "first": first,
        "final": final,
        "min": min_value,
        "max": max_value,
        "delta": final - first,
        "range": max_value - min_value,
        "nonzero_count": sum(1 for value in numeric if abs(value) > 1e-12),
        "sample_count": len(numeric),
    }


def _component_summary(component_name, kind, obj):
    history = getattr(obj, "history", {})
    fields = {}
    for key, values in history.items():
        if key == "time":
            continue
        summary = _series_summary(values)
        if summary is not None:
            fields[key] = summary

    time_values = _numeric_values(history.get("time", []))
    time_summary = {
        "first": time_values[0],
        "final": time_values[-1],
        "sample_count": len(time_values),
    } if time_values else {"sample_count": 0}

    return {
        "component": component_name,
        "kind": kind,
        "time": time_summary,
        "fields": fields,
    }


def _build_agent_summaries(loaded):
    node_summaries = {}
    for node_id, obj in loaded.nodes.items():
        name = loaded.node_names.get(node_id, getattr(obj, "name", f"node_{node_id}"))
        node_summaries[name] = _component_summary(name, type(obj).__name__, obj)

    connection_summaries = {}
    for name, obj in zip(loaded.connection_names, loaded.connections):
        connection_summaries[name] = _component_summary(name, type(obj).__name__, obj)
        if hasattr(obj, "connections"):
            for sub in obj.connections:
                sub_name = f"{name}/{sub.name}"
                connection_summaries[sub_name] = _component_summary(
                    sub_name, type(sub).__name__, sub
                )

    return node_summaries, connection_summaries


def _diagnostic_warning(message, component=None, field=None):
    warning = {"message": message}
    if component is not None:
        warning["component"] = component
    if field is not None:
        warning["field"] = field
    return warning


def _build_diagnostics(loaded, node_summaries, connection_summaries):
    warnings = []

    for name, summary in node_summaries.items():
        kind = summary["kind"]
        fields = summary["fields"]
        for field in ("P", "T", "d"):
            field_summary = fields.get(field)
            if field_summary and field_summary["min"] <= 0:
                warnings.append(
                    _diagnostic_warning(
                        f"Node {name!r} has nonphysical {field} values.",
                        component=name,
                        field=field,
                    )
                )
        mass_summary = fields.get("m")
        if mass_summary and mass_summary["min"] < 0:
            warnings.append(
                _diagnostic_warning(
                    f"Node {name!r} has negative mass values.",
                    component=name,
                    field="m",
                )
            )
        if kind == "Ambient":
            continue
        for field in ("P", "m"):
            field_summary = fields.get(field)
            if field_summary and field_summary["sample_count"] > 1 and abs(field_summary["range"]) <= 1e-9:
                warnings.append(
                    _diagnostic_warning(
                        f"Non-ambient node {name!r} has unchanged {field} history.",
                        component=name,
                        field=field,
                    )
                )

    for name, summary in connection_summaries.items():
        mdot = summary["fields"].get("mdot")
        if mdot and mdot["sample_count"] > 0 and mdot["nonzero_count"] == 0:
            warnings.append(
                _diagnostic_warning(
                    f"Connection {name!r} has all-zero mdot history.",
                    component=name,
                    field="mdot",
                )
            )

    action_times = sorted(loaded.actions.keys())
    out_of_window_actions = [
        time for time in action_times if time < 0 or time >= loaded.duration
    ]
    if out_of_window_actions:
        warnings.append(
            _diagnostic_warning(
                "Some actions are outside the simulated time window.",
                field="actions",
            )
        )

    return {
        "step_count": int(loaded.duration / loaded.dt) if loaded.dt else 0,
        "duration": loaded.duration,
        "dt": loaded.dt,
        "action_count": sum(len(items) for items in loaded.actions.values()),
        "action_times": action_times,
        "out_of_window_actions": out_of_window_actions,
        "node_count": len(loaded.nodes),
        "connection_count": len(loaded.connections),
        "warnings": warnings,
        "checks": {
            "has_node_samples": all(summary["time"]["sample_count"] > 0 for summary in node_summaries.values()),
            "has_connection_samples": all(summary["time"]["sample_count"] > 0 for summary in connection_summaries.values()),
            "has_nonzero_flow": any(
                summary["fields"].get("mdot", {}).get("nonzero_count", 0) > 0
                for summary in connection_summaries.values()
            ),
        },
    }


def _plot_results(loaded, output_dir):
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    node_plot = output_dir / "nodes.png"
    conn_plot = output_dir / "connections.png"

    fig, ax = plt.subplots(figsize=(10, 6))
    for obj in loaded.nodes.values():
        history = getattr(obj, "history", {})
        if history.get("time") and history.get("P"):
            ax.plot(history["time"], history["P"], label=getattr(obj, "name", type(obj).__name__))
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Pressure [Pa]")
    ax.set_title("Node Pressures")
    ax.grid(True)
    ax.legend(fontsize=8)
    fig.tight_layout()
    plt.savefig(node_plot)
    plt.close("all")

    fig, ax = plt.subplots(figsize=(10, 6))
    for name, obj in zip(loaded.connection_names, loaded.connections):
        history = getattr(obj, "history", {})
        if history.get("time") and history.get("mdot"):
            ax.plot(history["time"], history["mdot"], label=name)
        if hasattr(obj, "connections"):
            for sub in obj.connections:
                sub_history = getattr(sub, "history", {})
                if sub_history.get("time") and sub_history.get("mdot"):
                    ax.plot(sub_history["time"], sub_history["mdot"], label=f"{name}/{sub.name}")
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Mass flow [kg/s]")
    ax.set_title("Connection Mass Flow")
    ax.grid(True)
    ax.legend(fontsize=8)
    fig.tight_layout()
    plt.savefig(conn_plot)
    plt.close("all")

    return {"nodes_plot": str(node_plot), "connections_plot": str(conn_plot)}


def export_results(loaded, output_dir, save_plots=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    node_rows = []
    node_keys = set()
    for node_id, obj in loaded.nodes.items():
        name = loaded.node_names.get(node_id, getattr(obj, "name", f"node_{node_id}"))
        rows, keys = _history_rows(name, type(obj).__name__, obj)
        node_rows.extend(rows)
        node_keys.update(keys)

    conn_rows = []
    conn_keys = set()
    for name, obj in zip(loaded.connection_names, loaded.connections):
        rows, keys = _history_rows(name, type(obj).__name__, obj)
        conn_rows.extend(rows)
        conn_keys.update(keys)
        if hasattr(obj, "connections"):
            for sub in obj.connections:
                sub_name = f"{name}/{sub.name}"
                rows, keys = _history_rows(sub_name, type(sub).__name__, sub)
                conn_rows.extend(rows)
                conn_keys.update(keys)

    nodes_csv = output_dir / "nodes.csv"
    connections_csv = output_dir / "connections.csv"
    summary_json = output_dir / "summary.json"
    nodes_summary_json = output_dir / "nodes_summary.json"
    connections_summary_json = output_dir / "connections_summary.json"
    diagnostics_json = output_dir / "diagnostics.json"
    _write_history_csv(nodes_csv, node_rows, node_keys)
    _write_history_csv(connections_csv, conn_rows, conn_keys)

    node_summaries, connection_summaries = _build_agent_summaries(loaded)
    diagnostics = _build_diagnostics(loaded, node_summaries, connection_summaries)
    nodes_summary_json.write_text(json.dumps(node_summaries, indent=2), encoding="utf-8")
    connections_summary_json.write_text(json.dumps(connection_summaries, indent=2), encoding="utf-8")
    diagnostics_json.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    output_files = {
        "nodes_csv": str(nodes_csv),
        "connections_csv": str(connections_csv),
        "summary_json": str(summary_json),
        "nodes_summary_json": str(nodes_summary_json),
        "connections_summary_json": str(connections_summary_json),
        "diagnostics_json": str(diagnostics_json),
    }
    if save_plots:
        output_files.update(_plot_results(loaded, output_dir))

    summary = {
        "config_path": str(loaded.path),
        "duration": loaded.duration,
        "dt": loaded.dt,
        "component_counts": {
            "nodes": len(loaded.nodes),
            "connections": len(loaded.connections),
            "actions": sum(len(items) for items in loaded.actions.values()),
        },
        "warnings": loaded.warnings + diagnostics["warnings"],
        "final_nodes": {
            loaded.node_names.get(node_id, getattr(obj, "name", f"node_{node_id}")): _final_state(obj)
            for node_id, obj in loaded.nodes.items()
        },
        "diagnostics": diagnostics,
        "output_files": output_files,
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    loaded.output_files = output_files
    return summary
