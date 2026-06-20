export type NodeType = "Node" | "Ambient" | "Tank" | "Engine";
export type ConnectionType =
  | "Connection"
  | "Line"
  | "Series"
  | "Regulator"
  | "BangBang"
  | "ThrottleValve";

export interface NetworkNode {
  id: number;
  type: NodeType;
  x?: number;
  y?: number;
  params?: Record<string, unknown>;
}

export interface SeriesSubconnection {
  type: Exclude<ConnectionType, "Series">;
  params?: Record<string, unknown>;
}

export interface NetworkConnection {
  type: ConnectionType;
  start_id: number;
  end_id: number;
  params?: Record<string, unknown> & {
    connections?: SeriesSubconnection[];
  };
}

export interface NetworkConfig {
  version?: number | string;
  settings?: Record<string, unknown>;
  nodes: NetworkNode[];
  connections: NetworkConnection[];
  actions?: Array<Record<string, unknown>>;
}

export interface RunResponse {
  ok: boolean;
  run_id: string;
  report?: RunReport;
  artifacts?: string[];
  message?: string;
  stdout?: string;
  stderr?: string;
}

export type StatusItem = string | { check?: string; message?: string; [key: string]: unknown };

export interface RunReport {
  ok: boolean;
  duration: number;
  dt: number;
  status?: {
    passed: boolean;
    /* The simulator emits failures as objects and warnings as a mix of
       strings and objects ({ check, message }). Keep this loose so the UI
       coerces them safely instead of trying to render an object. */
    failures: StatusItem[];
    warnings: StatusItem[];
    checks: Record<string, boolean>;
  };
  component_counts?: {
    nodes: number;
    connections: number;
    actions: number;
  };
  interpretation?: {
    outcome: string;
    summary: string;
    important_observations: string[];
    recommended_next_actions: string[];
  };
  artifacts?: Record<string, string>;
  key_stats?: {
    nodes?: Record<string, ComponentStats>;
    connections?: Record<string, ComponentStats>;
  };
}

export interface ComponentStats {
  component: string;
  kind: string;
  fields: Record<string, FieldStats>;
}

export interface FieldStats {
  first: number;
  final: number;
  min: number;
  max: number;
  delta: number;
  range: number;
  label?: string;
  unit?: string;
}

export interface SampleRow {
  component: string;
  kind: string;
  time: number;
  [key: string]: string | number | null;
}

export interface DiagramNode {
  id: number;
  name: string;
  type: NodeType;
  x: number;
  y: number;
  params: Record<string, unknown>;
}

export interface DiagramConnection {
  id: string;
  name: string;
  type: ConnectionType;
  startId: number;
  endId: number;
  params: NetworkConnection["params"];
}

export interface DiagramModel {
  nodes: DiagramNode[];
  connections: DiagramConnection[];
  bounds: {
    minX: number;
    minY: number;
    width: number;
    height: number;
  };
}
