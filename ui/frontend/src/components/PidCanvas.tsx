import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Gauge, Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import type { ConnectionType, DiagramConnection, DiagramModel, DiagramNode, SampleRow, SeriesSubconnection } from "../types";
import { interpolateSample, numericValue } from "../lib/telemetry";
import {
  classifyFluid,
  colorForVisualFluid,
  isRocketLikeDiagram,
  nodeFluidName,
  visualStateFromSample,
  type FlowVisualState,
  type VisualFluid
} from "../lib/pidViewModel";

interface PidCanvasProps {
  diagram: DiagramModel | null;
  nodeSamples: Record<string, SampleRow[]>;
  connectionSamples: Record<string, SampleRow[]>;
  selectedId: string | null;
  metric: string;
  time: number;
  phase: number;
  showPartLabels?: boolean;
  nodeStatus?: Record<string, string>;
  onSelect: (id: string) => void;
}

type Point = { x: number; y: number };
type VisualNode = DiagramNode & { vx: number; vy: number };
type InlineKind = "valve" | "check" | "filter" | "pressure" | "flow" | "relief" | "regulator" | "restriction" | "injector" | "line";
type InlineComponent = {
  id: string;
  name: string;
  kind: InlineKind;
  t: number;
  sourceType?: Exclude<ConnectionType, "Series">;
};
type RoutedConnection = {
  connection: DiagramConnection;
  start: VisualNode;
  end: VisualNode;
  points: Point[];
  fluid: VisualFluid;
  color: string;
  state: FlowVisualState;
  mdot: number;
  direction: 1 | -1;
  selected: boolean;
  warning: boolean;
  components: InlineComponent[];
};

const STATUS_RING: Record<string, string> = {
  red: "#ef4444",
  yellow: "#f59e0b",
  green: "#34d399"
};

const COLOR_SELECTED = "#3b9dff";
const COLOR_STROKE = "#64748b";
const COLOR_IDLE = "#566579";
const COLOR_CLOSED = "#6b3137";
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

function pressureTemperatureLines(sample: SampleRow | undefined): { pressure: string; temperature: string } {
  const pressure = numericValue(sample, "P");
  const temperature = numericValue(sample, "T");
  return {
    pressure: pressure === undefined ? "P: n/a" : `P: ${(pressure / PA_PER_PSI).toLocaleString(undefined, { maximumFractionDigits: 1 })} psi`,
    temperature: temperature === undefined ? "T: n/a" : `T: ${(((temperature - 273.15) * 9) / 5 + 32).toLocaleString(undefined, { maximumFractionDigits: 1 })} F`
  };
}

function thrustLabel(thrustN: number | undefined): string {
  if (thrustN === undefined) return "Thrust: n/a";
  return `Thrust: ${(thrustN / NEWTONS_PER_LBF).toLocaleString(undefined, { maximumFractionDigits: 1 })} lbf`;
}

function connectionLocation(connection: DiagramConnection): number | undefined {
  const direct = connection.params?.location;
  if (typeof direct === "number" && Number.isFinite(direct)) return direct;
  const firstLocated = connection.params?.connections?.find((part) => typeof part.params?.location === "number");
  const nested = firstLocated?.params?.location;
  return typeof nested === "number" && Number.isFinite(nested) ? nested : undefined;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function statusStroke(status: string | undefined, selected: boolean): { stroke: string; width: number; warning: boolean } {
  if (selected) return { stroke: COLOR_SELECTED, width: 3, warning: false };
  const color = status ? STATUS_RING[status] : undefined;
  if (!color || status === "green") return { stroke: COLOR_STROKE, width: 1.6, warning: false };
  return { stroke: color, width: 3, warning: true };
}

function nodeMetricColor(value: number | undefined, metric: string): string {
  if (value === undefined) return "#121a26";
  if (metric === "fill_level") return value > 0.65 ? "#153a34" : value > 0.2 ? "#15304b" : "#121a26";
  if (metric === "T") return value > 320 ? "#44251d" : value < 260 ? "#132f48" : "#121a26";
  if (metric === "P") return value > 1_000_000 ? "#3c3119" : "#121a26";
  return "#121a26";
}

function pointPath(points: Point[]): string {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

function pointAtPolyline(points: Point[], ratio: number): Point {
  const total = points.slice(1).reduce((sum, point, index) => {
    const previous = points[index];
    return sum + Math.hypot(point.x - previous.x, point.y - previous.y);
  }, 0);
  if (total <= 0) return points[0] ?? { x: 0, y: 0 };
  let distance = clamp(ratio, 0, 1) * total;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const point = points[index];
    const segmentLength = Math.hypot(point.x - previous.x, point.y - previous.y);
    if (distance <= segmentLength) {
      const t = segmentLength <= 0 ? 0 : distance / segmentLength;
      return { x: previous.x + (point.x - previous.x) * t, y: previous.y + (point.y - previous.y) * t };
    }
    distance -= segmentLength;
  }
  return points[points.length - 1];
}

function tangentAngleAtPolyline(points: Point[], ratio: number): number {
  const before = pointAtPolyline(points, clamp(ratio - 0.01, 0, 1));
  const after = pointAtPolyline(points, clamp(ratio + 0.01, 0, 1));
  return (Math.atan2(after.y - before.y, after.x - before.x) * 180) / Math.PI;
}

function fluidFromNode(node: DiagramNode, sample: SampleRow | undefined, location?: number): VisualFluid {
  const fillLevel = clamp(numericValue(sample, "fill_level") ?? 0, 0, 1);
  return classifyFluid(nodeFluidName(node, location, fillLevel));
}

function connectionFluid(connection: DiagramConnection, start: VisualNode, end: VisualNode, nodeSamples: Record<string, SampleRow[]>, time: number, direction: 1 | -1): VisualFluid {
  if (start.type === "Engine" || end.type === "Engine") {
    const nonEngine = start.type === "Engine" ? end : start;
    const sample = interpolateSample(nodeSamples[nonEngine.name], time);
    return fluidFromNode(nonEngine, sample, connectionLocation(connection));
  }
  const source = direction >= 0 ? start : end;
  const sample = interpolateSample(nodeSamples[source.name], time);
  return fluidFromNode(source, sample, connectionLocation(connection));
}

function visualStateForRoute(sample: SampleRow | undefined, status: string | undefined, fluid: VisualFluid): FlowVisualState {
  const state = visualStateFromSample(sample, status);
  if (fluid !== "pressurant" || state !== "blocked") return state;

  const mdot = numericValue(sample, "mdot") ?? 0;
  const dP = Math.abs(numericValue(sample, "dP") ?? Number.POSITIVE_INFINITY);
  if (Math.abs(mdot) <= 1e-9) return state;
  return dP < 1_000 ? "lowPressure" : "flowing";
}

function nodeLabel(node: DiagramNode): string {
  return node.name.replace(/_/g, " ");
}

function isFuelTank(node: DiagramNode): boolean {
  return node.type === "Tank" && classifyFluid(nodeFluidName(node, 0, 1)) === "fuel";
}

function isOxidizerTank(node: DiagramNode): boolean {
  return node.type === "Tank" && classifyFluid(nodeFluidName(node, 0, 1)) === "oxidizer";
}

function isPressurantNode(node: DiagramNode): boolean {
  return classifyFluid(nodeFluidName(node)) === "pressurant" && node.type !== "Engine" && !isFuelTank(node) && !isOxidizerTank(node);
}

function visualNodesForDiagram(diagram: DiagramModel): { nodes: VisualNode[]; rocketLike: boolean; bounds: DiagramModel["bounds"] } {
  const rocketLike = isRocketLikeDiagram(diagram);
  if (!rocketLike) {
    return {
      rocketLike,
      bounds: diagram.bounds,
      nodes: diagram.nodes.map((node) => ({ ...node, vx: node.x, vy: node.y }))
    };
  }

  const pressurants = diagram.nodes.filter(isPressurantNode);
  const fuelTanks = diagram.nodes.filter(isFuelTank);
  const oxidizerTanks = diagram.nodes.filter(isOxidizerTank);
  const engines = diagram.nodes.filter((node) => node.type === "Engine");
  const otherNodes = diagram.nodes.filter(
    (node) => !pressurants.includes(node) && !fuelTanks.includes(node) && !oxidizerTanks.includes(node) && !engines.includes(node)
  );
  const nextOther = { index: 0 };
  const placeOther = () => {
    const point = { x: 160 + nextOther.index * 120, y: -270 + (nextOther.index % 2) * 540 };
    nextOther.index += 1;
    return point;
  };

  const placed = diagram.nodes.map((node): VisualNode => {
    if (pressurants.includes(node)) return { ...node, vx: pressurants.indexOf(node) * 150, vy: -380 };
    if (fuelTanks.includes(node)) return { ...node, vx: -260, vy: -125 + fuelTanks.indexOf(node) * 110 };
    if (oxidizerTanks.includes(node)) return { ...node, vx: 260, vy: -125 + oxidizerTanks.indexOf(node) * 110 };
    if (engines.includes(node)) return { ...node, vx: 0, vy: 360 + engines.indexOf(node) * 170 };
    const fallback = otherNodes.includes(node) ? placeOther() : { x: 0, y: node.y };
    return { ...node, vx: fallback.x, vy: fallback.y };
  });

  return {
    rocketLike,
    nodes: placed,
    bounds: { minX: -540, minY: -520, width: 1080, height: 1040 }
  };
}

function sideAnchor(node: VisualNode, side: "left" | "right" | "top" | "bottom"): Point {
  const pressurant = isPressurantNode(node);
  const halfWidth = node.type === "Tank" ? 96 : node.type === "Engine" ? 78 : pressurant ? 55 : 58;
  const halfHeight = node.type === "Tank" ? 66 : node.type === "Engine" ? 94 : pressurant ? 88 : 34;
  if (side === "left") return { x: node.vx - halfWidth, y: node.vy };
  if (side === "right") return { x: node.vx + halfWidth, y: node.vy };
  if (side === "top") return { x: node.vx, y: node.vy - halfHeight };
  return { x: node.vx, y: node.vy + halfHeight };
}

function routeConnection(connection: DiagramConnection, start: VisualNode, end: VisualNode, fluid: VisualFluid, rocketLike: boolean): Point[] {
  if (!rocketLike) {
    const startPoint = start.vx <= end.vx ? sideAnchor(start, "right") : sideAnchor(start, "left");
    const endPoint = start.vx <= end.vx ? sideAnchor(end, "left") : sideAnchor(end, "right");
    const midX = (startPoint.x + endPoint.x) / 2;
    return [
      startPoint,
      { x: midX, y: startPoint.y },
      { x: midX, y: endPoint.y },
      endPoint
    ];
  }

  if (fluid === "pressurant") {
    const startPoint = sideAnchor(start, "bottom");
    const endPoint = sideAnchor(end, "top");
    const manifoldY = -245;
    return [
      startPoint,
      { x: startPoint.x, y: manifoldY },
      { x: endPoint.x, y: manifoldY },
      endPoint
    ];
  }

  if (end.type === "Engine" || start.type === "Engine") {
    const tank = start.type === "Engine" ? end : start;
    const engine = start.type === "Engine" ? start : end;
    const tankPoint = sideAnchor(tank, "bottom");
    const branchX = fluid === "fuel" ? -130 : fluid === "oxidizer" ? 130 : tank.vx;
    const feedY = 80;
    const mergeY = engine.vy - 172;
    const enginePoint = { x: engine.vx + (fluid === "fuel" ? -36 : fluid === "oxidizer" ? 36 : 0), y: mergeY };
    return [
      tankPoint,
      { x: tankPoint.x, y: feedY },
      { x: branchX, y: feedY },
      { x: branchX, y: mergeY },
      enginePoint
    ];
  }

  const startPoint = sideAnchor(start, "right");
  const endPoint = sideAnchor(end, "left");
  const midX = (startPoint.x + endPoint.x) / 2;
  return [
    startPoint,
    { x: midX, y: startPoint.y },
    { x: midX, y: endPoint.y },
    endPoint
  ];
}

function partName(part: Pick<SeriesSubconnection, "type" | "params">, index: number): string {
  const value = part.params?.name;
  return typeof value === "string" && value.trim() ? value : `${part.type}_${index + 1}`;
}

function componentKind(type: Exclude<ConnectionType, "Series">, name: string): InlineKind {
  const value = name.toLowerCase();
  if (/prv|relief|vent/.test(value)) return "relief";
  if (/chk|check/.test(value)) return "check";
  if (/fil|filter|strainer/.test(value)) return "filter";
  if (/\bpt\b|pressure/.test(value)) return "pressure";
  if (/\bft\b|flow/.test(value)) return "flow";
  if (/inj|injector/.test(value)) return "injector";
  if (type === "Regulator" || /reg/.test(value)) return "regulator";
  if (type === "BangBang" || type === "ThrottleValve" || /valve|fcv|mov|otv|ftv/.test(value)) return "valve";
  if (type === "Line") return "line";
  return "restriction";
}

function syntheticRocketComponents(connection: DiagramConnection, fluid: VisualFluid, end: VisualNode): InlineComponent[] | null {
  if (fluid === "pressurant") {
    return [
      { id: `${connection.id}:fil-pr`, name: "FIL-PR", kind: "filter", t: 0.25 },
      { id: `${connection.id}:reg-pr`, name: "REG-PR", kind: "regulator", t: 0.48 },
      { id: `${connection.id}:pv-pr`, name: end.type === "Tank" && isOxidizerTank(end) ? "PV-PR-OX" : "PV-PR-F", kind: "valve", t: 0.76 }
    ];
  }
  if ((fluid === "fuel" || fluid === "oxidizer") && end.type === "Engine") {
    const suffix = fluid === "fuel" ? "F" : "OX";
    return [
      { id: `${connection.id}:fcv`, name: `FCV-${suffix}`, kind: "valve", t: 0.23 },
      { id: `${connection.id}:fil`, name: `FIL-${suffix}`, kind: "filter", t: 0.42 },
      { id: `${connection.id}:chk`, name: `CHK-${suffix}`, kind: "check", t: 0.64 },
      { id: `${connection.id}:prv`, name: `PRV-${suffix}`, kind: "relief", t: 0.82 }
    ];
  }
  return null;
}

function inlineComponents(connection: DiagramConnection, fluid: VisualFluid, end: VisualNode, rocketLike: boolean): InlineComponent[] {
  const synthetic = rocketLike ? syntheticRocketComponents(connection, fluid, end) : null;
  if (synthetic) return synthetic;
  const parts =
    connection.type === "Series"
      ? connection.params?.connections ?? []
      : [{ type: connection.type as Exclude<ConnectionType, "Series">, params: connection.params }];
  const gap = 1 / (parts.length + 1);
  return parts.map((part, index) => {
    const name = partName(part, index);
    const type = part.type as Exclude<ConnectionType, "Series">;
    return {
      id: `${connection.id}:${index}`,
      name,
      kind: componentKind(type, name),
      sourceType: type,
      t: gap * (index + 1)
    };
  });
}

function routedConnections({
  diagram,
  visualNodes,
  rocketLike,
  nodeSamples,
  connectionSamples,
  nodeStatus,
  selectedId,
  time
}: {
  diagram: DiagramModel;
  visualNodes: VisualNode[];
  rocketLike: boolean;
  nodeSamples: Record<string, SampleRow[]>;
  connectionSamples: Record<string, SampleRow[]>;
  nodeStatus?: Record<string, string>;
  selectedId: string | null;
  time: number;
}): RoutedConnection[] {
  const nodesById = new Map(visualNodes.map((node) => [node.id, node]));
  return diagram.connections.flatMap((connection) => {
    const start = nodesById.get(connection.startId);
    const end = nodesById.get(connection.endId);
    if (!start || !end) return [];
    const sample = interpolateSample(connectionSamples[connection.name], time);
    const mdot = numericValue(sample, "mdot") ?? 0;
    const direction: 1 | -1 = mdot >= 0 ? 1 : -1;
    const fluid = connectionFluid(connection, start, end, nodeSamples, time, direction);
    const warning = nodeStatus?.[connection.name] === "red" || nodeStatus?.[connection.name] === "yellow";
    const state = visualStateForRoute(sample, nodeStatus?.[connection.name], fluid);
    return [
      {
        connection,
        start,
        end,
        points: routeConnection(connection, start, end, fluid, rocketLike),
        fluid,
        color: state === "warning" ? colorForVisualFluid("warning") : colorForVisualFluid(fluid),
        state,
        mdot,
        direction,
        selected: selectedId === `connection:${connection.name}`,
        warning,
        components: inlineComponents(connection, fluid, end, rocketLike)
      }
    ];
  });
}

function isSelectableTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(".pid-hit") !== null;
}

function TankNode({
  node,
  sample,
  selected,
  status,
  showPartLabels,
  onSelect
}: {
  node: VisualNode;
  sample: SampleRow | undefined;
  selected: boolean;
  status?: string;
  showPartLabels: boolean;
  onSelect: (id: string) => void;
}) {
  const ring = statusStroke(status, selected);
  const level = clamp(numericValue(sample, "fill_level") ?? 0, 0, 1);
  const levelLabel = `${(level * 100).toFixed(1)}%`;
  const fluid = classifyFluid(nodeFluidName(node, 0, 1));
  const color = colorForVisualFluid(fluid);
  const telemetry = pressureTemperatureLines(sample);
  const x = node.vx;
  const y = node.vy;
  const tankClipId = `tank-clip-${node.id}`;
  const liquidTop = y + 56 - level * 112;
  return (
    <g className={`pid-hit pid-node ${ring.warning ? "is-warning" : ""}`} onClick={() => onSelect(`node:${node.name}`)} tabIndex={0}>
      <rect x={x - 92} y={y - 60} width={184} height={120} rx={44} fill="url(#tank-body-grad)" stroke={ring.stroke} strokeWidth={ring.width} filter="url(#node-shadow)" />
      <rect x={x - 86} y={y - 54} width={172} height={108} rx={38} fill="none" stroke={color} strokeWidth={1.1} opacity={0.55} />
      <clipPath id={tankClipId}>
        <rect x={x - 82} y={y - 50} width={164} height={100} rx={34} />
      </clipPath>
      <rect x={x - 82} y={liquidTop} width={164} height={level * 112} fill={color} opacity={0.25} clipPath={`url(#${tankClipId})`} />
      <path d={`M ${x - 80} ${liquidTop} C ${x - 42} ${liquidTop - 7} ${x - 15} ${liquidTop + 8} ${x + 12} ${liquidTop} S ${x + 54} ${liquidTop - 7} ${x + 80} ${liquidTop}`} stroke={color} strokeWidth={1.4} opacity={0.75} fill="none" clipPath={`url(#${tankClipId})`} />
      <line x1={x - 92} y1={y} x2={x + 92} y2={y} stroke="#d9e4ef" strokeWidth={0.8} opacity={0.28} />
      <line x1={x - 64} y1={y - 60} x2={x - 64} y2={y + 60} stroke="#d9e4ef" strokeWidth={0.8} opacity={0.28} />
      <line x1={x + 64} y1={y - 60} x2={x + 64} y2={y + 60} stroke="#d9e4ef" strokeWidth={0.8} opacity={0.28} />
      <text x={x} y={y - 8} textAnchor="middle" className="pid-tank-title">{nodeLabel(node)}</text>
      <text x={x} y={y + 18} textAnchor="middle" className="pid-fluid-label">{fluid === "fuel" ? "RP-1" : fluid === "oxidizer" ? "LOX" : nodeFluidName(node) ?? "TANK"}</text>
      <text x={x} y={y + 40} textAnchor="middle" className="pid-readout">{levelLabel}</text>
      <NodeTelemetryLabel x={x + 112} y={y - 36} pressure={telemetry.pressure} temperature={telemetry.temperature} color={color} />
      {showPartLabels && <text x={x} y={y + 86} textAnchor="middle" className="pid-label">{node.name}</text>}
    </g>
  );
}

function GasNode({
  node,
  sample,
  selected,
  status,
  phase,
  showPartLabels,
  onSelect
}: {
  node: VisualNode;
  sample: SampleRow | undefined;
  selected: boolean;
  status?: string;
  phase: number;
  showPartLabels: boolean;
  onSelect: (id: string) => void;
}) {
  const ring = statusStroke(status, selected);
  const fluid = fluidFromNode(node, sample);
  const color = colorForVisualFluid(fluid);
  const x = node.vx;
  const y = node.vy;
  const clipId = `node-clip-${node.id}`;
  const pressure = numericValue(sample, "P");
  const telemetry = pressureTemperatureLines(sample);
  const activity = clamp(((pressure ?? 101325) - 101325) / 4_000_000, 0.2, 1);
  const particles = Array.from({ length: node.type === "Ambient" ? 6 : 12 }, (_, index) => {
    const angle = phase * Math.PI * 2 * (0.65 + activity) + index * 1.9;
    return {
      x: x + Math.sin(angle) * (16 + (index % 4) * 5),
      y: y + Math.cos(angle * 1.3) * (10 + (index % 3) * 4),
      r: 1.3 + activity * 1.1
    };
  });
  if (fluid === "pressurant") {
    return (
      <g className={`pid-hit pid-node ${ring.warning ? "is-warning" : ""}`} onClick={() => onSelect(`node:${node.name}`)} tabIndex={0}>
        <rect x={x - 55} y={y - 86} width={110} height={172} rx={46} fill="url(#tank-body-grad)" stroke={ring.stroke} strokeWidth={ring.width} filter="url(#node-shadow)" />
        <rect x={x - 48} y={y - 78} width={96} height={156} rx={40} fill="none" stroke={color} strokeWidth={1.3} opacity={0.65} />
        <clipPath id={clipId}>
          <rect x={x - 45} y={y - 74} width={90} height={148} rx={38} />
        </clipPath>
        <g className="node-particles" clipPath={`url(#${clipId})`}>
          {particles.map((particle, index) => (
            <circle key={index} cx={particle.x * 0.72 + x * 0.28} cy={particle.y * 1.5 - y * 0.5} r={particle.r} fill={color} opacity={0.3 + activity * 0.45} />
          ))}
        </g>
        <line x1={x - 36} y1={y - 10} x2={x + 36} y2={y - 10} stroke="#d9e4ef" strokeWidth={0.8} opacity={0.25} />
        <line x1={x - 36} y1={y + 32} x2={x + 36} y2={y + 32} stroke="#d9e4ef" strokeWidth={0.8} opacity={0.2} />
        <text x={x} y={y - 15} textAnchor="middle" className="pid-tank-title">PRESSURANT</text>
        <text x={x} y={y + 12} textAnchor="middle" className="pid-tank-title">TANK</text>
        <text x={x} y={y + 39} textAnchor="middle" className="pid-fluid-label">{nodeFluidName(node) ?? "GN2"}</text>
        <NodeTelemetryLabel x={x + 72} y={y - 78} pressure={telemetry.pressure} temperature={telemetry.temperature} color={color} />
        {showPartLabels && <text x={x} y={y + 116} textAnchor="middle" className="pid-label">{node.name}</text>}
      </g>
    );
  }
  return (
    <g className={`pid-hit pid-node ${ring.warning ? "is-warning" : ""}`} onClick={() => onSelect(`node:${node.name}`)} tabIndex={0}>
      <rect x={x - 58} y={y - 34} width={116} height={68} rx={10} fill="url(#node-grad)" stroke={ring.stroke} strokeWidth={ring.width} filter="url(#node-shadow)" />
      <clipPath id={clipId}>
        <rect x={x - 52} y={y - 28} width={104} height={56} rx={8} />
      </clipPath>
      <g className="node-particles" clipPath={`url(#${clipId})`}>
        {particles.map((particle, index) => (
          <circle key={index} cx={particle.x} cy={particle.y} r={particle.r} fill={color} opacity={0.25 + activity * 0.4} />
        ))}
      </g>
      <text x={x} y={y - 5} textAnchor="middle" className="pid-tank-title">{node.type === "Ambient" ? "VENT" : nodeLabel(node)}</text>
      <text x={x} y={y + 15} textAnchor="middle" className="pid-fluid-label">{nodeFluidName(node) ?? node.type}</text>
      <NodeTelemetryLabel x={x + 72} y={y - 28} pressure={telemetry.pressure} temperature={telemetry.temperature} color={color} />
      {showPartLabels && <text x={x} y={y + 56} textAnchor="middle" className="pid-label">{node.name}</text>}
    </g>
  );
}

function EngineNode({
  node,
  sample,
  active,
  selected,
  status,
  showPartLabels,
  onSelect
}: {
  node: VisualNode;
  sample: SampleRow | undefined;
  active: boolean;
  selected: boolean;
  status?: string;
  showPartLabels: boolean;
  onSelect: (id: string) => void;
}) {
  const ring = statusStroke(status, selected);
  const thrust = Math.max(0, numericValue(sample, "thrust") ?? 0);
  const flameActive = active || thrust > 1;
  const scale = clamp(thrust / 2500, 0.25, 1);
  const flameLength = flameActive ? 98 * scale : 0;
  const flameWidth = flameActive ? 36 + 22 * scale : 0;
  const telemetry = pressureTemperatureLines(sample);
  const x = node.vx;
  const y = node.vy;
  const exitY = y + 92;
  const chamberPath =
    `M ${x - 40} ${y - 98} Q ${x} ${y - 116} ${x + 40} ${y - 98} L ${x + 40} ${y - 38} ` +
    `L ${x + 19} ${y - 16} C ${x + 31} ${y + 22} ${x + 51} ${y + 55} ${x + 61} ${exitY} ` +
    `L ${x - 61} ${exitY} C ${x - 51} ${y + 55} ${x - 31} ${y + 22} ${x - 19} ${y - 16} L ${x - 40} ${y - 38} Z`;
  return (
    <g className={`pid-hit pid-node ${ring.warning ? "is-warning" : ""}`} onClick={() => onSelect(`node:${node.name}`)} tabIndex={0}>
      {flameActive && (
        <g className="engine-flame">
          <path d={`M ${x - flameWidth} ${exitY} C ${x - flameWidth * 0.6} ${exitY + 24}, ${x - 12} ${exitY + flameLength * 0.65}, ${x} ${exitY + flameLength} C ${x + 12} ${exitY + flameLength * 0.65}, ${x + flameWidth * 0.6} ${exitY + 24}, ${x + flameWidth} ${exitY} Z`} />
          <path className="engine-flame-core" d={`M ${x - flameWidth * 0.35} ${exitY + 4} C ${x - 8} ${exitY + 24}, ${x - 4} ${exitY + flameLength * 0.45}, ${x} ${exitY + flameLength * 0.65} C ${x + 4} ${exitY + flameLength * 0.45}, ${x + 8} ${exitY + 24}, ${x + flameWidth * 0.35} ${exitY + 4} Z`} />
        </g>
      )}
      <path d={chamberPath} fill="url(#engine-grad)" stroke={ring.stroke} strokeWidth={ring.width} filter="url(#node-shadow)" />
      <g stroke="#8b98aa" strokeWidth={1.1} opacity={0.58} fill="none">
        <line x1={x - 40} y1={y - 38} x2={x + 40} y2={y - 38} />
        <line x1={x - 19} y1={y - 16} x2={x + 19} y2={y - 16} />
        <path d={`M ${x - 30} ${y + 2} C ${x - 17} ${y + 35} ${x - 15} ${y + 58} ${x - 16} ${exitY - 4}`} />
        <path d={`M ${x} ${y + 2} C ${x} ${y + 36} ${x} ${y + 58} ${x} ${exitY - 4}`} />
        <path d={`M ${x + 30} ${y + 2} C ${x + 17} ${y + 35} ${x + 15} ${y + 58} ${x + 16} ${exitY - 4}`} />
      </g>
      <text x={x} y={y - 62} textAnchor="middle" className="pid-tank-title">ENGINE</text>
      <text x={x} y={y - 39} textAnchor="middle" className="pid-fluid-label">CHAMBER</text>
      {showPartLabels && <text x={x} y={exitY + flameLength + 18} textAnchor="middle" className="pid-label">{node.name}</text>}
      <g className="node-telemetry engine-telemetry">
        <rect x={x + 86} y={y - 74} width={142} height={58} rx={6} />
        <rect x={x + 86} y={y - 74} width={3} height={58} className="tag-accent" />
        <text x={x + 97} y={y - 58}>{telemetry.pressure}</text>
        <text x={x + 97} y={y - 41}>{telemetry.temperature}</text>
        <text x={x + 97} y={y - 24}>{thrustLabel(thrust)}</text>
      </g>
    </g>
  );
}

function NodeTelemetryLabel({ x, y, pressure, temperature, color }: { x: number; y: number; pressure: string; temperature: string; color: string }) {
  return (
    <g className="node-telemetry compact-node-telemetry">
      <rect x={x} y={y} width={136} height={42} rx={6} />
      <rect x={x} y={y} width={3} height={42} fill={color} />
      <text x={x + 11} y={y + 16}>{pressure}</text>
      <text x={x + 11} y={y + 33}>{temperature}</text>
    </g>
  );
}

function ComponentGlyph({
  component,
  point,
  angle,
  fluidColor,
  state,
  selected,
  showPartLabels
}: {
  component: InlineComponent;
  point: Point;
  angle: number;
  fluidColor: string;
  state: FlowVisualState;
  selected: boolean;
  showPartLabels: boolean;
}) {
  const closed = state === "closed" || state === "blocked";
  const warning = state === "warning";
  const classes = `series-component component-${component.kind}${closed ? " is-closed" : ""}${warning ? " is-warning" : ""}${selected ? " is-selected" : ""}`;

  if (component.kind === "pressure" || component.kind === "flow") {
    return null;
  }

  return (
    <g className={classes} transform={`translate(${point.x} ${point.y}) rotate(${angle})`} filter="url(#node-shadow)">
      <title>{component.name}</title>
      {component.kind === "valve" && (
        <>
          <path className="glyph-body" d="M -22 -14 L 0 0 L -22 14 Z" />
          <path className="glyph-body" d="M 22 -14 L 0 0 L 22 14 Z" />
          <line className="valve-stem" x1="0" y1="-15" x2="0" y2="-29" />
          <rect className="valve-handle" x="-6" y="-33" width="12" height="6" rx="1" />
          {closed && <line className="closed-blade" x1="-20" y1="-18" x2="20" y2="18" />}
        </>
      )}
      {component.kind === "regulator" && (
        <>
          <path className="glyph-body" d="M -20 0 L 0 -18 L 20 0 L 0 18 Z" />
          <path className="reg-spring" d="M -8 -26 C -4 -31 4 -21 8 -26 C 12 -31 20 -21 24 -26" />
          <line className="valve-stem" x1="0" y1="-18" x2="0" y2="-29" />
        </>
      )}
      {component.kind === "filter" && (
        <>
          <path className="glyph-body" d="M -22 0 L 0 -22 L 22 0 L 0 22 Z" />
          <g className="filter-mesh">
            <line x1="-11" y1="-11" x2="11" y2="11" />
            <line x1="-3" y1="-15" x2="15" y2="3" />
            <line x1="-15" y1="-3" x2="3" y2="15" />
            <line x1="-11" y1="11" x2="11" y2="-11" />
            <line x1="-3" y1="15" x2="15" y2="-3" />
            <line x1="-15" y1="3" x2="3" y2="-15" />
          </g>
        </>
      )}
      {component.kind === "check" && (
        <>
          <path className="glyph-body" d="M -21 -17 L -21 17 L 4 0 Z" />
          <line className="glyph-line" x1="13" y1="-18" x2="13" y2="18" />
        </>
      )}
      {component.kind === "relief" && (
        <>
          <path className="glyph-body" d="M -15 15 L 15 15 L 15 -8 L -15 -8 Z" />
          <path className="reg-spring" d="M -6 -9 C -3 -15 3 -3 6 -9 C 9 -15 15 -3 18 -9" />
          <line className="vent-line" x1="0" y1="-9" x2="0" y2="-34" />
          <path className="vent-arrow" d="M 0 -34 L 25 -34 M 18 -40 L 25 -34 L 18 -28" />
        </>
      )}
      {component.kind === "injector" && (
        <>
          <circle className="glyph-body" cx="0" cy="0" r="15" />
          <path className="filter-mesh" d="M -8 -8 L 8 8 M 8 -8 L -8 8 M -11 0 L 11 0 M 0 -11 L 0 11" />
        </>
      )}
      {(component.kind === "restriction" || component.kind === "line") && (
        <rect x="-22" y="-5" width="44" height="10" rx="5" className="series-line-glyph" />
      )}
      {showPartLabels && (
        <text x="0" y={component.kind === "relief" ? -46 : -28} textAnchor="middle" className="pid-kind" transform={`rotate(${-angle})`}>
          {component.name}
        </text>
      )}
    </g>
  );
}

function ArrowGlyph({ point, angle, color, state }: { point: Point; angle: number; color: string; state: FlowVisualState }) {
  const opacity = state === "closed" || state === "idle" ? 0.42 : 0.9;
  return (
    <g transform={`translate(${point.x} ${point.y}) rotate(${angle})`} className="flow-direction" opacity={opacity}>
      <path d="M -10 -6 L 4 0 L -10 6" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </g>
  );
}

function CombinedEngineFeed({
  engine,
  phase,
  showPartLabels
}: {
  engine: VisualNode;
  phase: number;
  showPartLabels: boolean;
}) {
  const color = colorForVisualFluid("combined");
  const splitY = engine.vy - 172;
  const inletY = engine.vy - 94;
  const verticalPoints = [
    { x: engine.vx, y: splitY },
    { x: engine.vx, y: inletY }
  ];
  const verticalPath = pointPath(verticalPoints);
  const manifoldPath = `M ${engine.vx - 48} ${splitY} L ${engine.vx + 48} ${splitY}`;
  const particles = Array.from({ length: 5 }, (_, index) => pointAtPolyline(verticalPoints, (phase + index / 5) % 1));

  return (
    <g className="combined-feed-assembly">
      <path className="pipe-casing" d={`${manifoldPath} ${verticalPath}`} strokeWidth={13} />
      <path className="combined-engine-feed" d={manifoldPath} stroke={color} strokeWidth={6} />
      <path
        className="combined-engine-feed"
        d={verticalPath}
        stroke={color}
        strokeWidth={6}
        style={{ strokeDashoffset: `${-phase * 42}` }}
      />
      <ArrowGlyph point={pointAtPolyline(verticalPoints, 0.64)} angle={90} color={color} state="flowing" />
      {particles.map((particle, index) => (
        <circle key={index} className="flow-particle combined-flow-particle" cx={particle.x} cy={particle.y} r={2.8} fill={color} opacity={0.92} />
      ))}
      <ComponentGlyph
        component={{ id: `main-valves:${engine.id}`, name: "MAIN VALVES", kind: "valve", t: 0.5 }}
        point={{ x: engine.vx, y: engine.vy - 146 }}
        angle={90}
        fluidColor={color}
        state="flowing"
        selected={false}
        showPartLabels={showPartLabels}
      />
    </g>
  );
}

function PipeRun({ route, phase, showPartLabels, onSelect, connectionSamples, time }: { route: RoutedConnection; phase: number; showPartLabels: boolean; onSelect: (id: string) => void; connectionSamples: Record<string, SampleRow[]>; time: number }) {
  const selectedColor = route.selected ? COLOR_SELECTED : route.color;
  const active = route.state === "flowing" || route.state === "lowPressure" || route.state === "warning";
  const dim = route.state === "closed" || route.state === "idle";
  const width = route.state === "lowPressure" ? 3.2 : active ? clamp(3 + Math.abs(route.mdot) * 70, 3.2, 7) : 2.4;
  const points = route.direction > 0 ? route.points : [...route.points].reverse();
  const path = pointPath(route.points);
  const directionPath = pointPath(points);
  const labelPoint = pointAtPolyline(route.points, 0.5);
  const particles = active
    ? Array.from({ length: route.state === "lowPressure" ? 4 : 9 }, (_, index) => {
        const travel = (phase * (route.state === "lowPressure" ? 0.45 : 1) + index / (route.state === "lowPressure" ? 4 : 9)) % 1;
        const limited = route.state === "warning" ? travel : route.state === "blocked" ? Math.min(travel, 0.72) : travel;
        return pointAtPolyline(points, limited);
      })
    : [];
  const arrowPoint = pointAtPolyline(points, 0.72);
  const arrowAngle = tangentAngleAtPolyline(points, 0.72);

  return (
    <g className={`pid-hit pipe-run is-${route.state} fluid-${route.fluid}${route.selected ? " is-selected" : ""}${route.warning ? " is-warning" : ""}`} onClick={() => onSelect(`connection:${route.connection.name}`)}>
      <title>{route.connection.name}</title>
      <path className="pipe-casing" d={path} strokeWidth={width + 7} />
      <path className="pipe-shadowline" d={path} strokeWidth={width + 2} />
      <path
        className="pipe-core"
        d={path}
        stroke={route.selected ? COLOR_SELECTED : dim ? (route.state === "closed" ? COLOR_CLOSED : COLOR_IDLE) : selectedColor}
        strokeWidth={route.selected ? width + 1.2 : width}
        opacity={dim ? 0.48 : 0.92}
      />
      {active && (
        <>
          <path className="pipe-glow" d={path} stroke={selectedColor} strokeWidth={width + 5} opacity={route.state === "lowPressure" ? 0.22 : 0.36} />
          <path
            className="pipe-flow-dash"
            d={directionPath}
            stroke={selectedColor}
            strokeWidth={Math.max(2, width - 0.5)}
            style={{ strokeDashoffset: `${-phase * 42}` }}
          />
        </>
      )}
      {route.state === "warning" && <path className="pipe-warning-pulse" d={path} strokeWidth={width + 13} />}
      <ArrowGlyph point={arrowPoint} angle={arrowAngle} color={active ? selectedColor : COLOR_IDLE} state={route.state} />
      {particles.map((particle, index) => (
        <circle key={index} className="flow-particle" cx={particle.x} cy={particle.y} r={route.state === "lowPressure" ? 2 : 2.8} fill={selectedColor} opacity={route.state === "lowPressure" ? 0.55 : 0.9} />
      ))}
      {route.components.map((component) => {
        const point = pointAtPolyline(route.points, component.t);
        const angle = tangentAngleAtPolyline(route.points, component.t);
        const sample = interpolateSample(connectionSamples[component.name] ?? connectionSamples[route.connection.name], time);
        const state =
          route.fluid === "pressurant"
            ? route.state
            : visualStateFromSample(sample, route.warning ? "red" : undefined);
        return (
          <ComponentGlyph
            key={component.id}
            component={component}
            point={point}
            angle={angle}
            fluidColor={selectedColor}
            state={state === "idle" ? route.state : state}
            selected={route.selected}
            showPartLabels={showPartLabels}
          />
        );
      })}
      {showPartLabels && <text x={labelPoint.x} y={labelPoint.y + 42} textAnchor="middle" className="pid-label">{route.connection.name}</text>}
    </g>
  );
}

function NodeRenderer({
  node,
  sample,
  selected,
  metric,
  phase,
  status,
  showPartLabels,
  engineActive,
  onSelect
}: {
  node: VisualNode;
  sample: SampleRow | undefined;
  selected: boolean;
  metric: string;
  phase: number;
  status?: string;
  showPartLabels: boolean;
  engineActive: boolean;
  onSelect: (id: string) => void;
}) {
  if (node.type === "Tank") {
    return <TankNode node={node} sample={sample} selected={selected} status={status} showPartLabels={showPartLabels} onSelect={onSelect} />;
  }
  if (node.type === "Engine") {
    return <EngineNode node={node} sample={sample} active={engineActive} selected={selected} status={status} showPartLabels={showPartLabels} onSelect={onSelect} />;
  }

  const metricValue = numericValue(sample, metric);
  if (fluidFromNode(node, sample) === "pressurant") {
    return <GasNode node={node} sample={sample} selected={selected} status={status} phase={phase} showPartLabels={showPartLabels} onSelect={onSelect} />;
  }
  return (
    <g>
      <rect x={node.vx - 62} y={node.vy - 38} width={124} height={76} rx={12} fill={nodeMetricColor(metricValue, metric)} opacity={0.4} />
      <GasNode node={node} sample={sample} selected={selected} status={status} phase={phase} showPartLabels={showPartLabels} onSelect={onSelect} />
    </g>
  );
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
  nodeStatus,
  onSelect
}: PidCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const visualModel = useMemo(() => (diagram ? visualNodesForDiagram(diagram) : null), [diagram]);
  const [viewBox, setViewBox] = useState(visualModel?.bounds ?? { minX: 0, minY: 0, width: 640, height: 420 });

  useEffect(() => {
    if (visualModel) setViewBox(visualModel.bounds);
  }, [visualModel]);

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

  if (!diagram || !visualModel) {
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

  const routes = routedConnections({
    diagram,
    visualNodes: visualModel.nodes,
    rocketLike: visualModel.rocketLike,
    nodeSamples,
    connectionSamples,
    nodeStatus,
    selectedId,
    time
  });
  const activeEngineIds = new Set(
    visualModel.nodes
      .filter((node) => node.type === "Engine")
      .filter((engine) => {
        const engineRoutes = routes.filter((route) => route.end.id === engine.id || route.start.id === engine.id);
        return engineRoutes.some((route) => route.fluid === "fuel") && engineRoutes.some((route) => route.fluid === "oxidizer");
      })
      .map((engine) => engine.id)
  );
  const legendItems: Array<[VisualFluid, string, string]> = [
    ["pressurant", "PRESSURANT", colorForVisualFluid("pressurant")],
    ["fuel", "FUEL", colorForVisualFluid("fuel")],
    ["oxidizer", "OXIDIZER", colorForVisualFluid("oxidizer")],
    ["combined", "COMBINED", colorForVisualFluid("combined")],
    ["warning", "WARNING", colorForVisualFluid("warning")]
  ];

  return (
    <div className="pid-viewport">
      <div className="pid-view-controls" aria-label="Diagram view controls">
        <button type="button" title="Zoom in" onClick={() => zoomAt(0.82)}>
          <ZoomIn size={16} />
        </button>
        <button type="button" title="Zoom out" onClick={() => zoomAt(1.22)}>
          <ZoomOut size={16} />
        </button>
        <button type="button" title="Fit to screen" onClick={() => setViewBox(visualModel.bounds)}>
          <Maximize2 size={16} />
        </button>
      </div>
      <div className="flow-legend" aria-label="Flow key">
        <div className="flow-legend-title">Legend</div>
        {legendItems.map(([fluid, label, color]) => (
          <div key={fluid} className="flow-legend-row">
            <span className="flow-legend-swatch" style={{ backgroundColor: color }} />
            <span>{label}</span>
          </div>
        ))}
      </div>
      <div className="system-status-card">
        <span className="flow-arrow-mini">-&gt;</span>
        <span>FLOW DIRECTION</span>
        <strong>{routes.some((route) => route.state === "warning") ? "SYSTEM WARNING" : "SYSTEM NOMINAL"}</strong>
      </div>
      <svg
        ref={svgRef}
        className="pid-canvas"
        viewBox={`${viewBox.minX} ${viewBox.minY} ${viewBox.width} ${viewBox.height}`}
        preserveAspectRatio="xMidYMid meet"
        onPointerDown={(event) => {
          if (event.button !== 0 || isSelectableTarget(event.target)) return;
          dragRef.current = { x: event.clientX, y: event.clientY };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!dragRef.current || !svgRef.current) return;
          const rect = svgRef.current.getBoundingClientRect();
          const dx = ((event.clientX - dragRef.current.x) / rect.width) * viewBox.width;
          const dy = ((event.clientY - dragRef.current.y) / rect.height) * viewBox.height;
          dragRef.current = { x: event.clientX, y: event.clientY };
          setViewBox((current) => ({ ...current, minX: current.minX - dx, minY: current.minY - dy }));
        }}
        onPointerUp={(event) => {
          dragRef.current = null;
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => {
          dragRef.current = null;
        }}
      >
        <defs>
          <pattern id="pid-noise" width="80" height="80" patternUnits="userSpaceOnUse">
            <path d="M 0 40 H 80 M 40 0 V 80" stroke="#8da2c0" strokeWidth="0.4" opacity="0.05" />
            <circle cx="18" cy="21" r="0.7" fill="#dbeafe" opacity="0.08" />
            <circle cx="64" cy="53" r="0.6" fill="#dbeafe" opacity="0.06" />
          </pattern>
          <linearGradient id="tank-body-grad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#101721" />
            <stop offset="18%" stopColor="#1c2938" />
            <stop offset="50%" stopColor="#293442" />
            <stop offset="82%" stopColor="#182230" />
            <stop offset="100%" stopColor="#0e141d" />
          </linearGradient>
          <linearGradient id="node-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#172232" />
            <stop offset="100%" stopColor="#0d141e" />
          </linearGradient>
          <linearGradient id="engine-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#424c5d" />
            <stop offset="45%" stopColor="#202a37" />
            <stop offset="100%" stopColor="#0e141d" />
          </linearGradient>
          <linearGradient id="flame-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fff7bc" />
            <stop offset="35%" stopColor="#ff9f43" />
            <stop offset="100%" stopColor="#f15b2a" stopOpacity="0.15" />
          </linearGradient>
          <filter id="node-shadow" x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="0" dy="2" stdDeviation="5" floodColor="#000000" floodOpacity="0.5" />
          </filter>
          <filter id="flow-glow" x="-150%" y="-150%" width="400%" height="400%">
            <feGaussianBlur stdDeviation="2.6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="instrument-glow" x="-120%" y="-120%" width="340%" height="340%">
            <feGaussianBlur stdDeviation="1.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="flame-glow" x="-120%" y="-70%" width="340%" height="280%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <rect x={viewBox.minX - 200} y={viewBox.minY - 200} width={viewBox.width + 400} height={viewBox.height + 400} fill="url(#pid-noise)" pointerEvents="none" />
        <g className="pipe-layer">
          {routes.map((route) => (
            <PipeRun key={route.connection.id} route={route} phase={phase} showPartLabels={showPartLabels} onSelect={onSelect} connectionSamples={connectionSamples} time={time} />
          ))}
          {visualModel.rocketLike &&
            visualModel.nodes
              .filter((node) => node.type === "Engine" && activeEngineIds.has(node.id))
              .map((engine) => (
                <CombinedEngineFeed key={`combined:${engine.id}`} engine={engine} phase={phase} showPartLabels={showPartLabels} />
              ))}
        </g>
        <g className="node-layer">
          {visualModel.nodes.map((node) => (
            <NodeRenderer
              key={node.id}
              node={node}
              sample={interpolateSample(nodeSamples[node.name], time)}
              selected={selectedId === `node:${node.name}`}
              metric={metric}
              phase={phase}
              status={nodeStatus?.[node.name]}
              showPartLabels={showPartLabels}
              engineActive={activeEngineIds.has(node.id)}
              onSelect={onSelect}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}
