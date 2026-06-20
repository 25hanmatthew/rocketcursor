import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Gauge, Maximize2, Thermometer, Waves, ZoomIn, ZoomOut } from "lucide-react";
import type { ConnectionType, DiagramConnection, DiagramModel, DiagramNode, SampleRow, SeriesSubconnection } from "../types";
import { interpolateSample, numericValue } from "../lib/telemetry";

interface PidCanvasProps {
  diagram: DiagramModel | null;
  nodeSamples: Record<string, SampleRow[]>;
  connectionSamples: Record<string, SampleRow[]>;
  selectedId: string | null;
  metric: string;
  time: number;
  phase: number;
  showPartLabels?: boolean;
  onSelect: (id: string) => void;
}

/* Visual-only body tint for a node, derived from the displayed metric value.
   These are presentation colors; they do not feed back into the simulation. */
function nodeColor(value: number | undefined, metric: string): string {
  if (value === undefined) return "#161d2a";
  if (metric === "fill_level") {
    return value > 0.65 ? "#14463a" : value > 0.2 ? "#163a55" : "#161d2a";
  }
  if (metric === "T") return value > 320 ? "#48261c" : value < 260 ? "#16314e" : "#161d2a";
  if (metric === "P") return value > 1_000_000 ? "#473512" : "#161d2a";
  return "#161d2a";
}

const COLOR_SELECTED = "#3b9dff";
const COLOR_STROKE = "#2e3a4d";
// Tubes are neutral metal — fluid identity is shown by the colored particles
// flowing inside them, not by the pipe color itself.
const COLOR_PIPE_ACTIVE = "#6b7787";
const COLOR_PIPE_IDLE = "#3a4759";
const COLOR_PIPE_CLOSED = "#5a2e2e";
const COLOR_ARROW = "#5d6b7d";

const PA_PER_PSI = 6894.757293168;
const NEWTONS_PER_LBF = 4.4482216152605;

function pressurePsi(pressurePa: number | undefined): string {
  if (pressurePa === undefined) return "Pressure: n/a";
  return `Pressure: ${(pressurePa / PA_PER_PSI).toLocaleString(undefined, { maximumFractionDigits: 1 })} psi`;
}

function temperatureF(temperatureK: number | undefined): string {
  if (temperatureK === undefined) return "Temperature: n/a";
  return `Temperature: ${(((temperatureK - 273.15) * 9) / 5 + 32).toLocaleString(undefined, { maximumFractionDigits: 1 })} F`;
}

function thrustLabel(thrustN: number | undefined): string {
  if (thrustN === undefined) return "Thrust: n/a";
  return `Thrust: ${(thrustN / NEWTONS_PER_LBF).toLocaleString(undefined, { maximumFractionDigits: 1 })} lbf`;
}

const fluidColors: Record<string, string> = {
  Nitrogen: "#2563eb",
  Air: "#64748b",
  Oxygen: "#0ea5e9",
  LOX: "#0ea5e9",
  "n-Dodecane": "#c97706",
  Kerosene: "#c97706",
  Krypton: "#7c3aed",
  CombustionGas: "#dc2626",
  Unknown: "#208a72"
};

function stringParam(params: Record<string, unknown>, key: string): string | undefined {
  const value = params[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

function connectionLocation(connection: DiagramConnection): number | undefined {
  const value = connection.params?.location;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function fluidForNode(node: DiagramNode, sample: SampleRow | undefined, location?: number): string {
  if (node.type === "Tank") {
    const fillLevel = Math.max(0, Math.min(1, numericValue(sample, "fill_level") ?? 0));
    if (location !== undefined) {
      return location <= fillLevel
        ? stringParam(node.params, "fluid_liq") ?? "Unknown"
        : stringParam(node.params, "fluid_ullage") ?? "Unknown";
    }
    return stringParam(node.params, "fluid_liq") ?? stringParam(node.params, "fluid_ullage") ?? "Unknown";
  }

  return stringParam(node.params, "fluid") ?? "Unknown";
}

function colorForFluid(fluid: string): string {
  return fluidColors[fluid] ?? fluidColors.Unknown;
}

function SymbolIcon({ type }: { type: DiagramNode["type"] }) {
  if (type === "Ambient") return <Waves size={18} />;
  return <Thermometer size={17} />;
}

function NodeSymbol({
  node,
  sample,
  selected,
  metric,
  phase,
  showPartLabels,
  onSelect
}: {
  node: DiagramNode;
  sample: SampleRow | undefined;
  selected: boolean;
  metric: string;
  phase: number;
  showPartLabels: boolean;
  onSelect: (id: string) => void;
}) {
  const value = numericValue(sample, metric);
  const fill = nodeColor(value, metric);
  const stroke = selected ? COLOR_SELECTED : COLOR_STROKE;
  const nodeKey = `node:${node.name}`;
  const pressureLabel = pressurePsi(numericValue(sample, "P"));
  const temperatureLabel = temperatureF(numericValue(sample, "T"));
  const telemetryX = node.x + 64;
  const telemetryY = node.y - 17;

  if (node.type === "Engine") {
    const thrust = Math.max(0, numericValue(sample, "thrust") ?? 0);
    const thrustText = thrustLabel(thrust);
    const chamberPressure = pressurePsi(numericValue(sample, "P"));
    const active = thrust > 1;
    const thrustScale = Math.min(1, thrust / 2500);
    const flicker = 0.82 + 0.18 * Math.sin(phase * Math.PI * 2);
    const flameLength = active ? 34 + 48 * thrustScale * flicker : 0;
    const flameWidth = active ? 16 + 16 * thrustScale * (1.1 - flicker * 0.25) : 0;
    const innerFlameLength = flameLength * 0.62;
    const innerFlameWidth = flameWidth * 0.45;
    const x = node.x;
    const y = node.y;
    const exitY = y + 34;
    const innerBase = exitY + 2;
    // Combustion chamber (domed injector head) -> converging throat -> diverging
    // nozzle bell. A recognizable liquid-rocket-engine silhouette.
    const enginePath =
      `M ${x - 22} ${y - 36} ` +
      `Q ${x} ${y - 45} ${x + 22} ${y - 36} ` +
      `L ${x + 22} ${y - 8} ` +
      `L ${x + 10} ${y + 2} ` +
      `C ${x + 16} ${y + 16} ${x + 26} ${y + 27} ${x + 30} ${exitY} ` +
      `L ${x - 30} ${exitY} ` +
      `C ${x - 26} ${y + 27} ${x - 16} ${y + 16} ${x - 10} ${y + 2} ` +
      `L ${x - 22} ${y - 8} Z`;

    return (
      <g className="pid-hit" onClick={() => onSelect(nodeKey)} tabIndex={0}>
        {active && (
          <g className="engine-flame">
            <path
              d={`M ${x - flameWidth} ${exitY} C ${x - flameWidth * 0.65} ${exitY + 22}, ${x - flameWidth * 0.2} ${exitY + 22 + flameLength * 0.55}, ${x} ${exitY + flameLength} C ${x + flameWidth * 0.2} ${exitY + 22 + flameLength * 0.5}, ${x + flameWidth * 0.7} ${exitY + 22}, ${x + flameWidth} ${exitY} Z`}
            />
            <path
              className="engine-flame-core"
              d={`M ${x - innerFlameWidth} ${innerBase} C ${x - innerFlameWidth * 0.55} ${innerBase + 16}, ${x - innerFlameWidth * 0.15} ${innerBase + 14 + innerFlameLength * 0.5}, ${x} ${innerBase + innerFlameLength} C ${x + innerFlameWidth * 0.15} ${innerBase + 14 + innerFlameLength * 0.45}, ${x + innerFlameWidth * 0.55} ${innerBase + 16}, ${x + innerFlameWidth} ${innerBase} Z`}
            />
          </g>
        )}
        <path
          filter="url(#node-shadow)"
          d={enginePath}
          fill="url(#engine-grad)"
          stroke={stroke}
          strokeWidth={selected ? 3 : 2}
        />
        {/* injector / chamber band */}
        <line x1={x - 22} y1={y - 8} x2={x + 22} y2={y - 8} stroke="#46556a" strokeWidth={1.6} />
        {/* throat */}
        <line x1={x - 10} y1={y + 2} x2={x + 10} y2={y + 2} stroke="#46556a" strokeWidth={1.2} opacity={0.8} />
        {/* nozzle bell cooling contours */}
        <g stroke="#46556a" strokeWidth={1} opacity={0.45} fill="none">
          <line x1={x - 5} y1={y + 5} x2={x - 16} y2={exitY - 1} />
          <line x1={x} y1={y + 5} x2={x} y2={exitY - 1} />
          <line x1={x + 5} y1={y + 5} x2={x + 16} y2={exitY - 1} />
        </g>
        {active && (
          <circle cx={x + 17} cy={y - 33} r={3.5} fill="#34d399">
            <title>Firing</title>
          </circle>
        )}
        <text x={x} y={y - 18} textAnchor="middle" className="pid-kind">Engine</text>
        {showPartLabels && <text x={x} y={exitY + flameLength + 16} textAnchor="middle" className="pid-label">{node.name}</text>}
        <g className="node-telemetry engine-telemetry">
          <rect x={telemetryX} y={telemetryY - 12} width={132} height={58} rx={6} />
          <rect x={telemetryX} y={telemetryY - 12} width={3} height={58} className="tag-accent" />
          <text x={telemetryX + 10} y={telemetryY + 3}>{chamberPressure}</text>
          <text x={telemetryX + 10} y={telemetryY + 20}>{temperatureLabel}</text>
          <text x={telemetryX + 10} y={telemetryY + 37}>{thrustText}</text>
        </g>
      </g>
    );
  }

  if (node.type === "Tank") {
    const level = Math.max(0, Math.min(1, numericValue(sample, "fill_level") ?? 0));
    const levelLabel = `${(level * 100).toFixed(1)}%`;
    const liquidTop = node.y + 56 - level * 112;
    return (
      <g className="pid-hit" onClick={() => onSelect(nodeKey)} tabIndex={0}>
        <rect
          filter="url(#node-shadow)"
          x={node.x - 44}
          y={node.y - 62}
          width={88}
          height={124}
          rx={28}
          fill="url(#tank-body-grad)"
          stroke={stroke}
          strokeWidth={selected ? 3 : 2}
        />
        <clipPath id={`tank-clip-${node.id}`}>
          <rect x={node.x - 38} y={node.y - 56} width={76} height={112} rx={24} />
        </clipPath>
        <rect
          x={node.x - 38}
          y={liquidTop}
          width={76}
          height={level * 112}
          fill="url(#liquid-grad)"
          clipPath={`url(#tank-clip-${node.id})`}
        />
        {level > 0.001 && level < 0.999 && (
          <line
            x1={node.x - 38}
            y1={liquidTop}
            x2={node.x + 38}
            y2={liquidTop}
            stroke="#aee3ff"
            strokeWidth={1.5}
            opacity={0.85}
            clipPath={`url(#tank-clip-${node.id})`}
          />
        )}
        {/* graduation ticks — visual scale only */}
        <g clipPath={`url(#tank-clip-${node.id})`} stroke="#3a4759" strokeWidth={1} opacity={0.6}>
          {[0.25, 0.5, 0.75].map((mark) => (
            <line key={mark} x1={node.x + 26} y1={node.y + 56 - mark * 112} x2={node.x + 38} y2={node.y + 56 - mark * 112} />
          ))}
        </g>
        <text x={node.x} y={node.y + 5} textAnchor="middle" className="pid-readout">{levelLabel}</text>
        {showPartLabels && <text x={node.x} y={node.y + 86} textAnchor="middle" className="pid-label">{node.name}</text>}
        <g className="node-telemetry">
          <rect x={telemetryX} y={telemetryY - 12} width={132} height={42} rx={6} />
          <rect x={telemetryX} y={telemetryY - 12} width={3} height={42} className="tag-accent" />
          <text x={telemetryX + 10} y={telemetryY + 3}>{pressureLabel}</text>
          <text x={telemetryX + 10} y={telemetryY + 20}>{temperatureLabel}</text>
        </g>
      </g>
    );
  }

  return (
    <g className="pid-hit" onClick={() => onSelect(nodeKey)} tabIndex={0}>
      <rect
        filter="url(#node-shadow)"
        x={node.x - 52}
        y={node.y - 32}
        width={104}
        height={64}
        rx={10}
        fill={fill}
        stroke={stroke}
        strokeWidth={selected ? 3 : 2}
      />
      <foreignObject x={node.x - 11} y={node.y - 22} width={22} height={22}>
        <div className="node-icon"><SymbolIcon type={node.type} /></div>
      </foreignObject>
      {showPartLabels && <text x={node.x} y={node.y + 52} textAnchor="middle" className="pid-label">{node.name}</text>}
      <text x={node.x} y={node.y + 8} textAnchor="middle" className="pid-kind">{node.type}</text>
      <g className="node-telemetry">
        <rect x={telemetryX} y={telemetryY - 12} width={132} height={42} rx={6} />
        <rect x={telemetryX} y={telemetryY - 12} width={3} height={42} className="tag-accent" />
        <text x={telemetryX + 10} y={telemetryY + 3}>{pressureLabel}</text>
        <text x={telemetryX + 10} y={telemetryY + 20}>{temperatureLabel}</text>
      </g>
    </g>
  );
}

function subcomponentName(part: Pick<SeriesSubconnection, "type" | "params">, index: number): string {
  const value = part.params?.name;
  return typeof value === "string" && value.trim() ? value : `${part.type}_${index + 1}`;
}

function ComponentGlyph({
  type,
  x,
  y,
  angle,
  label,
  showLabel,
  closed = false
}: {
  type: Exclude<ConnectionType, "Series">;
  x: number;
  y: number;
  angle: number;
  label?: string;
  showLabel?: boolean;
  closed?: boolean;
}) {
  let symbol: ReactNode;
  if (type === "Line") {
    symbol = <rect x={-22} y={-5} width={44} height={10} rx={5} className="series-line-glyph" />;
  } else if (type === "Regulator") {
    symbol = (
      <>
        <path className="glyph-body" d="M -18 0 L 0 -17 L 18 0 L 0 17 Z" />
        <path d="M 0 -17 L 0 -27 M -7 -27 L 7 -27" stroke="#9aa8bd" strokeWidth={1.5} fill="none" />
      </>
    );
  } else if (type === "BangBang" || type === "ThrottleValve") {
    symbol = (
      <>
        <path className="glyph-body" d="M -22 -15 L 0 0 L -22 15 Z" />
        <path className="glyph-body" d="M 22 -15 L 0 0 L 22 15 Z" />
        {type === "ThrottleValve" && (
          <path d="M 0 -16 L 0 -26" stroke="#9aa8bd" strokeWidth={1.5} fill="none" />
        )}
      </>
    );
  } else {
    symbol = <circle className="glyph-body" cx={0} cy={0} r={14} />;
  }

  return (
    <g className={`series-component${closed ? " is-closed" : ""}`} filter="url(#node-shadow)">
      {label && <title>{label}</title>}
      <g transform={`translate(${x} ${y}) rotate(${angle})`}>
        {symbol}
      </g>
      {showLabel && label && <text x={x} y={y - 26} textAnchor="middle" className="pid-kind">{label}</text>}
    </g>
  );
}

function SeriesConnectionGlyph({
  connection,
  start,
  end,
  showPartLabels,
  closed
}: {
  connection: DiagramConnection;
  start: DiagramNode;
  end: DiagramNode;
  showPartLabels: boolean;
  closed: boolean;
}) {
  const parts = connection.params?.connections ?? [];
  if (parts.length === 0) return null;

  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);

  return (
    <g>
      {parts.map((part, index) => {
        const t = (index + 1) / (parts.length + 1);
        const x = start.x + dx * t;
        const y = start.y + dy * t;
        return (
          <ComponentGlyph
            key={`${connection.id}:${index}`}
            type={part.type}
            x={x}
            y={y}
            angle={angle}
            label={subcomponentName(part, index)}
            showLabel={showPartLabels}
            closed={closed}
          />
        );
      })}
    </g>
  );
}

function ConnectionGlyph({
  type,
  x,
  y,
  angle,
  closed
}: {
  type: Exclude<ConnectionType, "Series">;
  x: number;
  y: number;
  angle: number;
  closed: boolean;
}) {
  return <ComponentGlyph type={type} x={x} y={y} angle={angle} closed={closed} />;
}

export function PidCanvas({
  diagram,
  nodeSamples,
  connectionSamples,
  selectedId,
  metric,
  time,
  phase,
  showPartLabels = false,
  onSelect
}: PidCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const [viewBox, setViewBox] = useState(diagram?.bounds ?? { minX: 0, minY: 0, width: 640, height: 420 });

  useEffect(() => {
    if (diagram) setViewBox(diagram.bounds);
  }, [diagram]);

  const zoomAt = useCallback((factor: number, clientX?: number, clientY?: number) => {
    setViewBox((current) => {
      const rect = svgRef.current?.getBoundingClientRect();
      const pivotX =
        rect && clientX !== undefined
          ? current.minX + ((clientX - rect.left) / rect.width) * current.width
          : current.minX + current.width / 2;
      const pivotY =
        rect && clientY !== undefined
          ? current.minY + ((clientY - rect.top) / rect.height) * current.height
          : current.minY + current.height / 2;
      const nextWidth = Math.max(80, Math.min(5000, current.width * factor));
      const nextHeight = Math.max(80, Math.min(5000, current.height * factor));
      return {
        minX: pivotX - ((pivotX - current.minX) / current.width) * nextWidth,
        minY: pivotY - ((pivotY - current.minY) / current.height) * nextHeight,
        width: nextWidth,
        height: nextHeight
      };
    });
  }, []);

  useEffect(() => {
    const element = svgRef.current;
    if (!element) return;

    const handleWheel = (event: WheelEvent) => {
      zoomAt(event.deltaY < 0 ? 0.9 : 1.1, event.clientX, event.clientY);
    };

    element.addEventListener("wheel", handleWheel);
    return () => element.removeEventListener("wheel", handleWheel);
  }, [zoomAt]);

  if (!diagram) {
    return (
      <div className="empty-canvas">
        <div className="empty-inner">
          <span className="empty-icon">
            <Gauge size={28} />
          </span>
          <strong>No P&amp;ID loaded</strong>
          <p>Submit a network JSON config to run the simulator and generate an interactive schematic.</p>
        </div>
      </div>
    );
  }

  const nodesById = new Map(diagram.nodes.map((node) => [node.id, node]));
  const legendFluids = new Map<string, string>();
  for (const connection of diagram.connections) {
    const start = nodesById.get(connection.startId);
    const end = nodesById.get(connection.endId);
    if (!start || !end) continue;
    const sample = interpolateSample(connectionSamples[connection.name], time);
    const mdot = numericValue(sample, "mdot") ?? 0;
    const flowSource = mdot >= 0 ? start : end;
    const sourceSample = interpolateSample(nodeSamples[flowSource.name], time);
    const fluid = fluidForNode(flowSource, sourceSample, connectionLocation(connection));
    legendFluids.set(fluid, colorForFluid(fluid));
  }
  const legendItems = [...legendFluids.entries()];

  return (
    <div className="pid-viewport">
      <div className="pid-view-controls" aria-label="Diagram view controls">
        <button type="button" title="Zoom in" onClick={() => zoomAt(0.82)}>
          <ZoomIn size={16} />
        </button>
        <button type="button" title="Zoom out" onClick={() => zoomAt(1.22)}>
          <ZoomOut size={16} />
        </button>
        <button type="button" title="Fit to screen" onClick={() => setViewBox(diagram.bounds)}>
          <Maximize2 size={16} />
        </button>
      </div>
      {legendItems.length > 0 && (
        <div className="flow-legend" aria-label="Flow key">
          <div className="flow-legend-title">Flow key</div>
          {legendItems.map(([fluid, color]) => (
            <div key={fluid} className="flow-legend-row">
              <span className="flow-legend-swatch" style={{ backgroundColor: color }} />
              <span>{fluid}</span>
            </div>
          ))}
        </div>
      )}
      <svg
        ref={svgRef}
        className="pid-canvas"
        viewBox={`${viewBox.minX} ${viewBox.minY} ${viewBox.width} ${viewBox.height}`}
        preserveAspectRatio="xMidYMid meet"
        onPointerDown={(event) => {
          dragRef.current = { x: event.clientX, y: event.clientY };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!dragRef.current || !svgRef.current) return;
          const rect = svgRef.current.getBoundingClientRect();
          const dx = ((event.clientX - dragRef.current.x) / rect.width) * viewBox.width;
          const dy = ((event.clientY - dragRef.current.y) / rect.height) * viewBox.height;
          dragRef.current = { x: event.clientX, y: event.clientY };
          setViewBox((current) => ({
            ...current,
            minX: current.minX - dx,
            minY: current.minY - dy
          }));
        }}
        onPointerUp={(event) => {
          dragRef.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => {
          dragRef.current = null;
        }}
      >
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={COLOR_ARROW} />
          </marker>

          <linearGradient id="tank-body-grad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#1b2331" />
            <stop offset="45%" stopColor="#232e3f" />
            <stop offset="55%" stopColor="#26303f" />
            <stop offset="100%" stopColor="#161d29" />
          </linearGradient>

          <linearGradient id="liquid-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3da3d8" />
            <stop offset="100%" stopColor="#1f6c9c" />
          </linearGradient>

          <linearGradient id="engine-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#333f50" />
            <stop offset="40%" stopColor="#283242" />
            <stop offset="100%" stopColor="#161d29" />
          </linearGradient>

          <linearGradient id="flame-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffd166" />
            <stop offset="45%" stopColor="#fb923c" />
            <stop offset="100%" stopColor="#ef4444" />
          </linearGradient>

          <filter id="node-shadow" x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#000000" floodOpacity="0.45" />
          </filter>

          <filter id="flow-glow" x="-120%" y="-120%" width="340%" height="340%">
            <feGaussianBlur stdDeviation="1.6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>

          <filter id="flame-glow" x="-120%" y="-60%" width="340%" height="260%">
            <feGaussianBlur stdDeviation="3.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {diagram.connections.map((connection) => {
          const start = nodesById.get(connection.startId);
          const end = nodesById.get(connection.endId);
          if (!start || !end) return null;

          const sample = interpolateSample(connectionSamples[connection.name], time);
          const mdot = numericValue(sample, "mdot") ?? 0;
          const state = numericValue(sample, "state") ?? 1;
          const closed = state <= 0;
          const active = state > 0 && Math.abs(mdot) > 0;
          const width = active ? Math.min(8, 2 + Math.abs(mdot) * 180) : 2;
          const selected = selectedId === `connection:${connection.name}`;
          const direction = mdot >= 0 ? 1 : -1;
          const flowSource = direction >= 0 ? start : end;
          const flowSourceSample = interpolateSample(nodeSamples[flowSource.name], time);
          const fluid = fluidForNode(flowSource, flowSourceSample, connectionLocation(connection));
          const flowColor = colorForFluid(fluid);
          const coreStroke = selected
            ? COLOR_SELECTED
            : closed
            ? COLOR_PIPE_CLOSED
            : active
            ? COLOR_PIPE_ACTIVE
            : COLOR_PIPE_IDLE;
          const dx = end.x - start.x;
          const dy = end.y - start.y;
          const mx = start.x + dx / 2;
          const my = start.y + dy / 2;
          const length = Math.hypot(dx, dy) || 1;
          const angle = Math.atan2(dy, dx) * (180 / Math.PI);
          const labelOffset = 34;
          const labelX = mx + (dy / length) * labelOffset;
          const labelY = my - (dx / length) * labelOffset;
          const labelAnchor = dy / length > 0.2 ? "start" : dy / length < -0.2 ? "end" : "middle";
          const particles = [0, 1, 2, 3, 4, 5].map((index) => {
            const offset = index / 6;
            const t = direction > 0 ? (phase + offset) % 1 : 1 - ((phase + offset) % 1);
            return { x: start.x + dx * t, y: start.y + dy * t };
          });

          return (
            <g key={connection.id} className="pid-hit" onClick={() => onSelect(`connection:${connection.name}`)}>
              <line
                className="pipe-casing"
                x1={start.x}
                y1={start.y}
                x2={end.x}
                y2={end.y}
                strokeWidth={(selected ? width + 1 : width) + 5}
              />
              <line
                className="pipe-core"
                x1={start.x}
                y1={start.y}
                x2={end.x}
                y2={end.y}
                stroke={coreStroke}
                strokeWidth={selected ? width + 1 : width}
                markerEnd="url(#arrow)"
                opacity={active ? 1 : closed ? 0.7 : 0.5}
              />
              {connection.type === "Series" ? (
                <SeriesConnectionGlyph
                  connection={connection}
                  start={start}
                  end={end}
                  showPartLabels={showPartLabels}
                  closed={closed}
                />
              ) : (
                <ConnectionGlyph type={connection.type} x={mx} y={my} angle={angle} closed={closed} />
              )}
              {active &&
                particles.map((particle, index) => (
                  <circle
                    key={index}
                    className="flow-particle"
                    cx={particle.x}
                    cy={particle.y}
                    r={Math.max(2.4, Math.min(4, width * 0.55))}
                    fill={flowColor}
                    opacity={0.95}
                  />
                ))}
              {showPartLabels && <text x={labelX} y={labelY} textAnchor={labelAnchor} className="pid-label">{connection.name}</text>}
            </g>
          );
        })}

        {diagram.nodes.map((node) => (
          <NodeSymbol
            key={node.id}
            node={node}
            sample={interpolateSample(nodeSamples[node.name], time)}
            selected={selectedId === `node:${node.name}`}
            metric={metric}
            phase={phase}
            showPartLabels={showPartLabels}
            onSelect={onSelect}
          />
        ))}
      </svg>
    </div>
  );
}
