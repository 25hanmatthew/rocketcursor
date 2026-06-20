import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Cylinder,
  Flame,
  Gauge,
  Pause,
  Play,
  RotateCcw,
  Spline,
  Upload,
  Wind,
  XCircle
} from "lucide-react";
import { PidCanvas } from "./components/PidCanvas";
import { buildDiagram } from "./lib/diagram";
import { parseSamplesCsv } from "./lib/csv";
import { interpolateSample, numericValue, rowsByComponent, timeRange } from "./lib/telemetry";
import type {
  DiagramModel,
  DiagramNode,
  NetworkConfig,
  RunReport,
  RunResponse,
  SampleRow,
  StatusItem
} from "./types";

const metrics = ["P", "T", "m", "fill_level"];
const PA_PER_PSI = 6894.757293168;
const NEWTONS_PER_LBF = 4.4482216152605;

const fieldMetadata: Record<string, { label: string; unit?: string }> = {
  time: { label: "Time", unit: "s" },
  P: { label: "Pressure", unit: "psi" },
  T: { label: "Temperature", unit: "F" },
  U: { label: "Internal energy", unit: "J" },
  h: { label: "Specific enthalpy", unit: "J/kg" },
  d: { label: "Density", unit: "kg/m^3" },
  m: { label: "Mass", unit: "kg" },
  m_l: { label: "Liquid mass", unit: "kg" },
  m_v: { label: "Vapor mass", unit: "kg" },
  fill_level: { label: "Fill level", unit: "fraction" },
  s: { label: "Specific entropy", unit: "J/(kg*K)" },
  Q: { label: "Vapor quality", unit: "fraction" },
  CdA: { label: "Effective flow area", unit: "m^2" },
  qdot: { label: "Heat flow", unit: "J/s" },
  state: { label: "Valve/component state", unit: "dimensionless" },
  mdot: { label: "Mass flow", unit: "kg/s" },
  Hdot: { label: "Enthalpy flow", unit: "J/s" },
  dP: { label: "Pressure drop", unit: "psi" },
  mdot_ox: { label: "Oxidizer mass flow", unit: "kg/s" },
  mdot_fu: { label: "Fuel mass flow", unit: "kg/s" },
  MR: { label: "Mixture ratio", unit: "dimensionless" },
  cstar: { label: "Characteristic velocity", unit: "m/s" },
  thrust: { label: "Thrust", unit: "lbf" },
  Isp: { label: "Specific impulse", unit: "s" }
};

function fieldDisplayName(key: string): string {
  const metadata = fieldMetadata[key];
  if (!metadata) return key;
  return metadata.unit
    ? `${metadata.label} (${key}, ${metadata.unit})`
    : `${metadata.label} (${key})`;
}

function fieldShortName(key: string): string {
  const metadata = fieldMetadata[key];
  if (!metadata) return key;
  return metadata.unit ? `${metadata.label} (${metadata.unit})` : metadata.label;
}

function formatValue(value: unknown): string {
  if (typeof value === "number") {
    if (Math.abs(value) >= 10000 || (Math.abs(value) > 0 && Math.abs(value) < 0.01)) return value.toExponential(3);
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (value === null || value === undefined || value === "") return "n/a";
  return String(value);
}

function displayValue(key: string, value: unknown): string {
  if (typeof value !== "number") return formatValue(value);
  if (key === "P" || key === "dP") return formatValue(value / PA_PER_PSI);
  if (key === "T") return formatValue(((value - 273.15) * 9) / 5 + 32);
  if (key === "thrust") return formatValue(value / NEWTONS_PER_LBF);
  return formatValue(value);
}

function selectedName(selectedId: string | null): string | null {
  return selectedId?.split(":").slice(1).join(":") ?? null;
}

/* The simulator returns status failures/warnings (and some observations) as
   either plain strings or objects like { check, message }. Coerce to a
   displayable string so React never receives an object as a child. */
function messageText(item: unknown): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    const obj = item as { message?: unknown; check?: unknown };
    if (typeof obj.message === "string") return obj.message;
    if (typeof obj.check === "string") return obj.check;
    try {
      return JSON.stringify(item);
    } catch {
      return String(item);
    }
  }
  return String(item);
}

type Tone = "ok" | "warn" | "danger" | "idle";

function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`status-badge tone-${tone}`}>
      <span className="dot" />
      {label}
    </span>
  );
}

function NodeGlyph({ type }: { type: DiagramNode["type"] }) {
  if (type === "Tank") return <Cylinder size={14} />;
  if (type === "Engine") return <Flame size={14} />;
  if (type === "Ambient") return <Wind size={14} />;
  return <Circle size={14} />;
}

export default function App() {
  const [config, setConfig] = useState<NetworkConfig | null>(null);
  const [diagram, setDiagram] = useState<DiagramModel | null>(null);
  const [report, setReport] = useState<RunReport | null>(null);
  const [nodeRows, setNodeRows] = useState<SampleRow[]>([]);
  const [connectionRows, setConnectionRows] = useState<SampleRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [metric, setMetric] = useState(metrics[0]);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [phase, setPhase] = useState(0);
  const [showPartLabels, setShowPartLabels] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const nodeSamples = useMemo(() => rowsByComponent(nodeRows), [nodeRows]);
  const connectionSamples = useMemo(() => rowsByComponent(connectionRows), [connectionRows]);
  const range = useMemo(() => timeRange(nodeRows, connectionRows), [nodeRows, connectionRows]);

  useEffect(() => {
    if (!playing) return;
    let previous = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const elapsed = ((now - previous) / 1000) * speed;
      previous = now;
      setTime((current) => {
        if (range.max <= range.min) return current;
        const next = current + elapsed;
        return next > range.max ? range.min : next;
      });
      setPhase((current) => (current + elapsed * 0.7) % 1);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, range.max, range.min, speed]);

  async function submitFile(file: File) {
    setBusy(true);
    setError(null);
    setPlaying(false);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as NetworkConfig;
      const form = new FormData();
      form.append("file", new Blob([text], { type: "application/json" }), file.name);

      const response = await fetch("/api/runs", { method: "POST", body: form });
      const payload = (await response.json()) as RunResponse;
      if (!response.ok || !payload.ok || !payload.report) {
        throw new Error(payload.stderr || payload.message || "Run failed");
      }

      const [nodesCsv, connectionsCsv] = await Promise.all([
        fetch(`/api/runs/${payload.run_id}/artifact/nodes.csv`).then((res) => res.text()),
        fetch(`/api/runs/${payload.run_id}/artifact/connections.csv`).then((res) => res.text())
      ]);

      const built = buildDiagram(parsed);
      setConfig(parsed);
      setDiagram(built);
      setReport(payload.report);
      setNodeRows(parseSamplesCsv(nodesCsv));
      setConnectionRows(parseSamplesCsv(connectionsCsv));
      setSelectedId(built.nodes[0] ? `node:${built.nodes[0].name}` : null);
      setTime(0);
      setPhase(0);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  const selected = selectedName(selectedId);
  const isConnection = selectedId?.startsWith("connection:") ?? false;
  const selectedRows = selectedId?.startsWith("node:") ? nodeSamples[selected ?? ""] : connectionSamples[selected ?? ""];
  const selectedSample = interpolateSample(selectedRows, time);
  const selectedNode = selectedId?.startsWith("node:")
    ? diagram?.nodes.find((node) => node.name === selected)
    : undefined;
  const selectedFillLevel = selectedNode?.type === "Tank" ? numericValue(selectedSample, "fill_level") : undefined;

  const statusTone: Tone = report?.status?.passed ? "ok" : report ? "warn" : "idle";
  const statusLabel = report?.status?.passed ? "Nominal" : report ? "Review" : "Idle";
  const observations = report?.interpretation?.important_observations ?? [];
  const failures = report?.status?.failures ?? [];
  const warnings = report?.status?.warnings ?? [];

  const timeSpan = range.max - range.min;
  const timePct = timeSpan > 0 ? ((time - range.min) / timeSpan) * 100 : 0;
  const scrubberStyle = {
    background: `linear-gradient(90deg, var(--accent) ${timePct}%, var(--surface-3) ${timePct}%)`
  };

  return (
    <div className="app-shell">
      <aside className="side-panel">
        <div className="brand-row">
          <span className="brand-mark">
            <Gauge size={20} />
          </span>
          <div>
            <h1>Fluid Network Viewer</h1>
            <span>P&amp;ID telemetry playback</span>
          </div>
        </div>

        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void submitFile(file);
          }}
        />
        <button className="primary-action" type="button" onClick={() => fileInput.current?.click()} disabled={busy}>
          <Upload size={18} />
          {busy ? "Running simulation..." : "Submit network JSON"}
        </button>

        {error && <pre className="error-box">{error}</pre>}

        <div className="status-card">
          <div className="status-card-head">
            <span className="label">Run summary</span>
            <StatusBadge tone={statusTone} label={statusLabel} />
          </div>
          <div className="run-metrics">
            <div className="metric">
              <span>Duration</span>
              <strong>{report ? `${formatValue(report.duration)} s` : "—"}</strong>
            </div>
            <div className="metric">
              <span>Time step</span>
              <strong>{report ? `${formatValue(report.dt)} s` : "—"}</strong>
            </div>
            <div className="metric">
              <span>Nodes</span>
              <strong>{config ? config.nodes.length : "—"}</strong>
            </div>
            <div className="metric">
              <span>Connections</span>
              <strong>{config ? config.connections.length : "—"}</strong>
            </div>
          </div>
        </div>

        {report && (failures.length > 0 || warnings.length > 0) && (
          <div>
            <h2 className="section-label">
              <Activity size={13} /> System checks
            </h2>
            <div className="checks-list">
              {failures.map((item, index) => (
                <div key={`fail-${index}`} className="check-chip tone-danger">
                  <XCircle size={14} />
                  <span>{messageText(item)}</span>
                </div>
              ))}
              {warnings.map((item, index) => (
                <div key={`warn-${index}`} className="check-chip tone-warn">
                  <AlertTriangle size={14} />
                  <span>{messageText(item)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {report && failures.length === 0 && warnings.length === 0 && (
          <div className="check-chip tone-ok">
            <CheckCircle2 size={14} />
            <span>All status checks passed.</span>
          </div>
        )}

        {diagram && (diagram.nodes.length > 0 || diagram.connections.length > 0) && (
          <div className="component-group">
            <h2 className="section-label">
              Nodes <span className="count">{diagram.nodes.length}</span>
            </h2>
            <div className="component-list">
              {diagram.nodes.map((node) => (
                <button
                  key={node.id}
                  className={selectedId === `node:${node.name}` ? "selected" : ""}
                  onClick={() => setSelectedId(`node:${node.name}`)}
                >
                  <span className="glyph">
                    <NodeGlyph type={node.type} />
                  </span>
                  <span className="name">{node.name}</span>
                  <span className="tag">{node.type}</span>
                </button>
              ))}
            </div>

            <h2 className="section-label" style={{ marginTop: "var(--sp-4)" }}>
              Connections <span className="count">{diagram.connections.length}</span>
            </h2>
            <div className="component-list">
              {diagram.connections.map((connection) => (
                <button
                  key={connection.id}
                  className={selectedId === `connection:${connection.name}` ? "selected" : ""}
                  onClick={() => setSelectedId(`connection:${connection.name}`)}
                >
                  <span className="glyph">
                    <Spline size={14} />
                  </span>
                  <span className="name">{connection.name}</span>
                  <span className="tag">{connection.type}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </aside>

      <main className="workspace">
        <div className="canvas-toolbar">
          <div className="toolbar-title">
            <strong>{config ? "Network P&ID" : "No run loaded"}</strong>
            <span>
              {config
                ? `${config.nodes.length} nodes · ${config.connections.length} connections`
                : "Submit a JSON config to run the existing simulator."}
            </span>
          </div>
          <div className="toolbar-controls">
            <label className="checkbox-control">
              <input
                type="checkbox"
                checked={showPartLabels}
                onChange={(event) => setShowPartLabels(event.target.checked)}
              />
              Labels
            </label>
            <label>
              Node metric
              <select value={metric} onChange={(event) => setMetric(event.target.value)}>
                {metrics.map((item) => (
                  <option key={item} value={item}>
                    {fieldDisplayName(item)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="canvas-wrap">
          <PidCanvas
            diagram={diagram}
            nodeSamples={nodeSamples}
            connectionSamples={connectionSamples}
            selectedId={selectedId}
            metric={metric}
            time={time}
            phase={phase}
            showPartLabels={showPartLabels}
            onSelect={setSelectedId}
          />
        </div>

        <div className="timeline">
          <button
            type="button"
            className={`icon-button${playing ? " is-active" : ""}`}
            onClick={() => setPlaying((value) => !value)}
            disabled={!report}
            title={playing ? "Pause" : "Play"}
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button
            type="button"
            className="icon-button"
            onClick={() => {
              setTime(range.min);
              setPhase(0);
            }}
            disabled={!report}
            title="Reset to start"
          >
            <RotateCcw size={18} />
          </button>
          <input
            type="range"
            min={range.min}
            max={range.max}
            step={report?.dt ?? 0.01}
            value={time}
            disabled={!report}
            style={scrubberStyle}
            onChange={(event) => setTime(Number(event.target.value))}
          />
          <span className="time-readout">
            {formatValue(time)} <small>s</small>
          </span>
          <select className="speed-select" value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
            <option value={0.25}>0.25×</option>
            <option value={0.5}>0.5×</option>
            <option value={1}>1×</option>
            <option value={2}>2×</option>
            <option value={5}>5×</option>
          </select>
        </div>
      </main>

      <aside className="inspector">
        <div className="inspector-head">
          <div>
            <h2 className="section-label">Inspector</h2>
            <div className="selected-title">{selected ?? "Nothing selected"}</div>
            {selected && (
              <span className="selected-sub">
                {isConnection ? "Connection" : selectedNode?.type ?? "Node"}
              </span>
            )}
          </div>
        </div>

        {selectedFillLevel !== undefined && (
          <div className="fill-gauge">
            <div className="fill-gauge-head">
              <span>Physical fill level</span>
              <strong>{formatValue(selectedFillLevel * 100)}%</strong>
            </div>
            <div className="fill-gauge-track">
              <div
                className="fill-gauge-bar"
                style={{ width: `${Math.max(0, Math.min(100, selectedFillLevel * 100))}%` }}
              />
            </div>
          </div>
        )}

        <div className="inspector-block">
          <h2 className="section-label">Live telemetry</h2>
          {selectedSample ? (
            <dl className="stat-grid">
              {Object.entries(selectedSample)
                .filter(([key]) => !["component", "kind"].includes(key))
                .map(([key, value]) => (
                  <div key={key} className="stat-tile">
                    <dt title={fieldDisplayName(key)}>{fieldShortName(key)}</dt>
                    <dd>{displayValue(key, value)}</dd>
                  </div>
                ))}
            </dl>
          ) : (
            <div className="inspector-empty">Select a component to inspect its telemetry.</div>
          )}
        </div>

        {selectedSample && isConnection && (
          <div className="flow-note">
            <span>
              Flow animation is a qualitative indicator. Current mass flow:{" "}
              <strong>{formatValue(numericValue(selectedSample, "mdot"))} kg/s</strong>.
            </span>
          </div>
        )}

        <div className="inspector-block">
          <h2 className="section-label">Observations</h2>
          <ul className="observations">
            {observations.length === 0 && <li className="empty">No run observations loaded.</li>}
            {observations.map((item, index) => (
              <li key={index}>{messageText(item)}</li>
            ))}
          </ul>
        </div>
      </aside>

      {busy && (
        <div className="run-overlay" role="alert" aria-live="assertive">
          <div className="run-modal">
            <div className="run-modal-header">
              <span className="brand-mark">
                <Gauge size={20} />
              </span>
              <div>
                <strong>Running simulation</strong>
                <span>Generating result artifacts and P&amp;ID playback data.</span>
              </div>
            </div>
            <div className="progress-track" aria-label="Simulation in progress">
              <div className="progress-bar" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
