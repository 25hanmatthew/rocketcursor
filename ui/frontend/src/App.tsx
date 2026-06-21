import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Braces, FileText, Gauge, Layers, MessageSquare, Mic, Moon, PanelLeft, Pause, Play, Rocket, RotateCcw, Send, Sun, Workflow } from "lucide-react";
import { PidCanvas } from "./components/PidCanvas";

/* The 3D twin pulls in three.js (~600 KB) — lazy-load it so the default P&ID
   view stays light and only pays the cost when the user opens the 3D tab. */
const Twin3D = lazy(() => import("./components/Twin3D"));
const VehicleStudio = lazy(() => import("./features/vehicleStudio/VehicleStudio"));
const FlightTwin = lazy(() => import("./features/flightTwin/FlightTwin"));
import { VoiceAgentCopilot } from "./components/VoiceAgentCopilot";
import { TelemetryPlots } from "./components/TelemetryPlots";
import type { DesignChangeExtraction } from "./components/ConversationRecorder";
import { buildDiagram } from "./lib/diagram";
import { parseSamplesCsv } from "./lib/csv";
import { interpolateSample, numericValue, rowsByComponent, timeRange } from "./lib/telemetry";
import { FlightEvents, FlightRow, flightTimeRange, interpolateFlight, parseFlightCsv } from "./lib/flightModel";
import { classifyFluid, nodeFluidName } from "./lib/pidViewModel";
import type {
  ChatHistoryItem,
  DiagramModel,
  DesignRunRevisionResponse,
  DesignRunStartResponse,
  DesignRunStatusResponse,
  LatestPlayableRun,
  NetworkConfig,
  RunReport,
  SampleRow,
  SessionIteration,
  SessionState
} from "./types";

function formatValue(value: unknown): string {
  if (typeof value === "number") {
    if (Math.abs(value) >= 10000 || (Math.abs(value) > 0 && Math.abs(value) < 0.01)) return value.toExponential(3);
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (value === null || value === undefined || value === "") return "n/a";
  return String(value);
}

function selectedName(selectedId: string | null): string | null {
  return selectedId?.split(":").slice(1).join(":") ?? null;
}

type InputMode = "chat" | "json" | "voice";

/* Turn structured voice extraction into a plain-text requirements block so the
   existing chat/revision endpoint consumes it exactly like a typed request. */
export function changesToRequirements(extraction: DesignChangeExtraction): string {
  const changes = extraction.key_changes ?? [];
  const summary = extraction.summary.trim();
  if (changes.length === 0 && !summary) return "";
  const lines = changes.map((change) => {
    const category = change.category ? `[${change.category}] ` : "";
    const value =
      change.value !== null && change.value !== undefined && `${change.value}`.trim() !== ""
        ? ` (value: ${change.value})`
        : "";
    return `- ${category}${change.description}${value}`;
  });
  const sections = [];
  if (summary) sections.push(`Voice summary:\n${summary}`);
  if (lines.length) sections.push(`Key design changes:\n${lines.join("\n")}`);
  return sections.join("\n\n");
}
type ActivityTone = "done" | "current" | "upcoming" | "danger";
type ChatTarget = { kind: "revision"; url: string; iteration: number } | { kind: "new"; url: string };

function stageLabel(stage: string): string {
  if (stage === "requirements") return "Understanding request";
  if (stage === "design") return "Designing";
  if (stage === "simulate") return "Simulating";
  if (stage === "evaluate") return "Evaluating";
  if (stage === "report") return "Reporting";
  return stage || "Queued";
}

function currentActivity(state: SessionState | null): string {
  if (!state) return "";
  if (state.status === "error") return "Run failed";
  if (state.status === "passed") return "Design passed";
  if (state.status === "failed") return "Iteration budget finished";
  const iteration = state.current_iteration >= 0 ? `iteration ${state.current_iteration + 1}` : "first pass";
  if (state.stage === "requirements") return "Turning the request into deterministic checks";
  if (state.stage === "design") return `Designing ${iteration}`;
  if (state.stage === "simulate") return `Running simulator for ${iteration}`;
  if (state.stage === "evaluate") return `Checking simulator output for ${iteration}`;
  return stageLabel(state.stage);
}

function consoleCheckRows(iteration?: SessionIteration) {
  return (iteration?.verdict?.checks ?? []).map((check) => ({
    result: check.passed ? "PASS" : "FAIL",
    id: check.id,
    description: check.description,
    actual: check.actual,
    expected: `${check.op} ${String(check.expected)}`,
    detail: check.detail || ""
  }));
}

function consoleCheckSummary(iteration?: SessionIteration) {
  const checks = iteration?.verdict?.checks ?? [];
  const passed = checks.filter((check) => check.passed).length;
  return {
    passed,
    failed: checks.length - passed,
    total: checks.length
  };
}

function activitySteps(state: SessionState | null): Array<{ key: string; label: string; detail: string; tone: ActivityTone }> {
  if (!state) return [];
  const latest = state.iterations[state.iterations.length - 1];
  const failed = state.status === "error";
  const passed = state.status === "passed" || state.passed;
  const finished = passed || state.status === "failed" || failed;
  const activeStage = state.stage;
  const toneFor = (stage: string): ActivityTone => {
    if (failed && stage === activeStage) return "danger";
    if (activeStage === stage && !finished) return "current";
    const order = ["requirements", "design", "simulate", "evaluate", "report"];
    return order.indexOf(activeStage) > order.indexOf(stage) || finished ? "done" : "upcoming";
  };

  const steps = [
    {
      key: "requirements",
      label: "Requirements",
      detail: state.requirements?.name ? `Spec: ${state.requirements.name}` : "Deriving checks",
      tone: toneFor("requirements")
    },
    {
      key: "design",
      label: "Designing",
      detail: state.current_iteration >= 0 ? `Candidate ${state.current_iteration + 1}` : "Waiting for first design",
      tone: toneFor("design")
    },
    {
      key: "simulate",
      label: "Simulating",
      detail: latest?.status ? `Simulator status: ${latest.status}` : "No simulation result yet",
      tone: toneFor("simulate")
    },
    {
      key: "evaluate",
      label: "Evaluating",
      detail: latest?.verdict?.summary ?? "Waiting for verdict",
      tone: toneFor("evaluate")
    }
  ];

  if (latest?.decision && !latest.verdict?.passed) {
    steps.push({
      key: "revise",
      label: latest.decision.action === "scrap" ? "Restarting" : "Revising",
      detail: latest.decision.reason,
      tone: state.status === "running" ? "current" : "done"
    });
  }

  if (finished) {
    steps.push({
      key: "report",
      label: failed ? "Error" : passed ? "Passed" : "Stopped",
      detail: state.error || state.report?.headline || "Final report ready",
      tone: failed ? "danger" : passed ? "done" : "current"
    });
  }

  return steps;
}

export function loadedIterationForSession(key: string | null, sessionId: string | null): number | null {
  if (!key || !sessionId || !key.startsWith(`${sessionId}:`)) return null;
  const value = Number(key.split(":")[1]);
  return Number.isInteger(value) ? value : null;
}

export function chatSubmissionTarget(
  sessionId: string | null,
  latestLoadedKey: string | null,
  hasLoadedDesign: boolean
): ChatTarget {
  const iteration = loadedIterationForSession(latestLoadedKey, sessionId);
  if (sessionId && hasLoadedDesign && iteration !== null) {
    return { kind: "revision", url: `/api/design-runs/${sessionId}/revisions`, iteration };
  }
  return { kind: "new", url: "/api/design-runs" };
}

export function chatRequestBody(message: string, target: ChatTarget): { message: string; iteration?: number } {
  return target.kind === "revision" ? { message, iteration: target.iteration } : { message };
}

function chatId(prefix: string, now = Date.now()): string {
  return `${prefix}-${now.toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createUserChatItem(
  text: string,
  target: ChatTarget,
  parentSessionId: string | null,
  now = Date.now()
): ChatHistoryItem {
  return {
    id: chatId("user", now),
    role: "user",
    text,
    kind: target.kind === "revision" ? "revision" : "initial",
    parentSessionId: target.kind === "revision" ? parentSessionId ?? undefined : undefined,
    iteration: target.kind === "revision" ? target.iteration : undefined,
    createdAt: now
  };
}

export function createRunStatusChatItem(
  sessionId: string,
  target: ChatTarget,
  parentSessionId: string | null,
  now = Date.now()
): ChatHistoryItem {
  return {
    id: `status-${sessionId}`,
    role: "assistant",
    text: target.kind === "revision" ? "Revision started. Running simulator loop." : "Design run started. Running simulator loop.",
    kind: "status",
    sessionId,
    parentSessionId: target.kind === "revision" ? parentSessionId ?? undefined : undefined,
    iteration: target.kind === "revision" ? target.iteration : undefined,
    status: "running",
    createdAt: now
  };
}

export function summarizeRunState(state: SessionState): Pick<ChatHistoryItem, "text" | "status"> {
  if (state.status === "passed" || state.passed) {
    return {
      status: "passed",
      text: `Design passed in ${state.iterations_used || state.iterations.length} iteration(s).`
    };
  }
  if (state.status === "error") {
    return {
      status: "error",
      text: state.error || "Run failed."
    };
  }
  if (state.status === "failed") {
    return {
      status: "failed",
      text: `Stopped after ${state.iterations_used || state.iterations.length} iteration(s).`
    };
  }
  return {
    status: "running",
    text: currentActivity(state) || "Loop running."
  };
}

export function updateRunStatusChatItem(history: ChatHistoryItem[], sessionId: string, state: SessionState): ChatHistoryItem[] {
  const summary = summarizeRunState(state);
  return history.map((item) =>
    item.kind === "status" && item.sessionId === sessionId
      ? { ...item, text: summary.text, status: summary.status }
      : item
  );
}

export function ChatTranscript({ items }: { items: ChatHistoryItem[] }) {
  return (
    <div className="chat-history" aria-label="Chat history">
      {items.length === 0 ? (
        <div className="chat-empty">Messages will appear here.</div>
      ) : (
        items.map((item) => (
          <div key={item.id} className={`chat-message role-${item.role} status-${item.status ?? "idle"}`}>
            <div className="chat-message-meta">
              <span>{item.role === "user" ? "You" : "Design loop"}</span>
              {item.kind === "revision" && <span>Revision</span>}
              {item.status && <span>{item.status}</span>}
            </div>
            <div className="chat-message-text">{item.text}</div>
          </div>
        ))
      )}
    </div>
  );
}

interface SystemSummary {
  hasEngine: boolean;
  thrust?: number;
  pc?: number;
  mr?: number;
  isp?: number;
  oxFill?: number;
  fuelFill?: number;
  pressurantP?: number;
}

/* Whole-system telemetry at the current scrub time, so the inspector shows
   something alive before the user clicks anything. Classifies tanks/pressurant
   with the same helpers the P&ID uses, and reads the engine's operating point. */
function buildSystemSummary(
  diagram: DiagramModel | null,
  nodeSamples: Record<string, SampleRow[]>,
  time: number
): SystemSummary | null {
  if (!diagram) return null;
  const summary: SystemSummary = { hasEngine: false };
  for (const node of diagram.nodes) {
    const sample = interpolateSample(nodeSamples[node.name], time);
    if (node.type === "Engine") {
      summary.hasEngine = true;
      summary.thrust = numericValue(sample, "thrust");
      summary.pc = numericValue(sample, "P");
      summary.mr = numericValue(sample, "MR");
      summary.isp = numericValue(sample, "Isp");
      continue;
    }
    const fluid = classifyFluid(nodeFluidName(node, 0, 1));
    if (node.type === "Tank" && fluid === "oxidizer") summary.oxFill = numericValue(sample, "fill_level");
    else if (node.type === "Tank" && fluid === "fuel") summary.fuelFill = numericValue(sample, "fill_level");
    else if (fluid === "pressurant" && summary.pressurantP === undefined) summary.pressurantP = numericValue(sample, "P");
  }
  return summary;
}

const PA_PER_MPA = 1_000_000;

function summaryCell(label: string, value: number | undefined, format: (v: number) => string): { label: string; value: string } {
  return { label, value: value === undefined ? "—" : format(value) };
}

type ProcurementShot = {
  supplier?: string;
  item?: string;
  quoteStatus?: string;
  url: string;
};

type ProcurementUiState = {
  status: string; // idle | running | done | error
  stage?: string | null; // sourcing | requesting_quotes | done | error
  run_id?: string | null;
  screenshots?: ProcurementShot[];
  supplier_results?: Array<{ supplier?: string; item?: string; quoteStatus?: string }>;
  error?: string;
};

function procurementStageLabel(state: ProcurementUiState | null): string {
  if (!state) return "";
  if (state.status === "error") return state.error ?? "Procurement failed";
  switch (state.stage) {
    case "sourcing":
      return "Sourcing parts from McMaster-Carr & Swagelok…";
    case "requesting_quotes":
      return "Filling supplier quote forms with your RFQ…";
    case "done":
      return "Quote requests prepared — receipts ready";
    default:
      return "Starting procurement agents…";
  }
}

// Left sidebar resize/collapse limits. Dragging the divider narrower than
// SIDEBAR_COLLAPSE_AT collapses the panel to a thin rail; expanding snaps back
// to at least SIDEBAR_MIN (hysteresis so it doesn't flicker around the edge).
const SIDEBAR_DEFAULT = 380;
const SIDEBAR_MIN = 280;
const SIDEBAR_MAX = 560;
const SIDEBAR_COLLAPSE_AT = 200;
const SIDEBAR_RAIL = 40;

export default function App() {
  const [inputMode, setInputMode] = useState<InputMode>("chat");
  const [chatText, setChatText] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [chatHistory, setChatHistory] = useState<ChatHistoryItem[]>([]);
  const [designSessionId, setDesignSessionId] = useState<string | null>(null);
  const [designState, setDesignState] = useState<SessionState | null>(null);
  const [latestLoadedDesignKey, setLatestLoadedDesignKey] = useState<string | null>(null);
  const lastConsoleState = useRef<string>("");
  const [config, setConfig] = useState<NetworkConfig | null>(null);
  const [diagram, setDiagram] = useState<DiagramModel | null>(null);
  const [report, setReport] = useState<RunReport | null>(null);
  const [nodeRows, setNodeRows] = useState<SampleRow[]>([]);
  const [connectionRows, setConnectionRows] = useState<SampleRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const metric = "P";
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [phase, setPhase] = useState(0);
  const [showPartLabels, setShowPartLabels] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (typeof localStorage !== "undefined" && (localStorage.getItem("rc-theme") as "dark" | "light")) || "dark"
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("rc-theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  // Resizable / collapsible left sidebar, persisted across reloads.
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    const stored = typeof localStorage !== "undefined" ? Number(localStorage.getItem("rc-sidebar-w")) : NaN;
    return Number.isFinite(stored) && stored >= SIDEBAR_MIN && stored <= SIDEBAR_MAX ? stored : SIDEBAR_DEFAULT;
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(
    () => typeof localStorage !== "undefined" && localStorage.getItem("rc-sidebar-collapsed") === "1"
  );
  const sidebarDrag = useRef<{ startX: number; startW: number; moved: boolean } | null>(null);
  useEffect(() => {
    try {
      localStorage.setItem("rc-sidebar-w", String(sidebarWidth));
      localStorage.setItem("rc-sidebar-collapsed", sidebarCollapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [sidebarWidth, sidebarCollapsed]);

  const onSidebarResizeStart = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      sidebarDrag.current = { startX: event.clientX, startW: sidebarCollapsed ? SIDEBAR_RAIL : sidebarWidth, moved: false };
    },
    [sidebarCollapsed, sidebarWidth]
  );
  const onSidebarResizeMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const drag = sidebarDrag.current;
    if (!drag) return;
    const raw = drag.startW + (event.clientX - drag.startX);
    if (Math.abs(event.clientX - drag.startX) > 3) drag.moved = true;
    if (raw < SIDEBAR_COLLAPSE_AT) {
      setSidebarCollapsed(true);
      return;
    }
    setSidebarCollapsed(false);
    setSidebarWidth(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, raw)));
  }, []);
  const onSidebarResizeEnd = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const drag = sidebarDrag.current;
    sidebarDrag.current = null;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
    // A click without drag on the rail expands the collapsed sidebar.
    if (drag && !drag.moved && sidebarCollapsed) setSidebarCollapsed(false);
  }, [sidebarCollapsed]);

  const [view, setView] = useState<"2d" | "3d" | "vehicle" | "flight">(() =>
    typeof window !== "undefined" && /[?&]view=3d\b/.test(window.location.search) ? "3d" : "2d"
  );
  // P&ID -> flight pipeline artifacts (Vehicle Studio + Flight Twin)
  const [vehicleModel, setVehicleModel] = useState<any | null>(null);
  const [flightRows, setFlightRows] = useState<FlightRow[]>([]);
  const [flightEvents, setFlightEvents] = useState<FlightEvents | null>(null);
  const [flightReport, setFlightReport] = useState<any | null>(null);
  const [flightBusy, setFlightBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [procurement, setProcurement] = useState<ProcurementUiState | null>(null);
  const [showReceipts, setShowReceipts] = useState(false);

  const nodeSamples = useMemo(() => rowsByComponent(nodeRows), [nodeRows]);
  const connectionSamples = useMemo(() => rowsByComponent(connectionRows), [connectionRows]);
  const range = useMemo(() => timeRange(nodeRows, connectionRows), [nodeRows, connectionRows]);
  const flightRange = useMemo(() => flightTimeRange(flightRows), [flightRows]);
  // Flight Twin replays flight time; the other views replay thermofluid time.
  const activeRange = view === "flight" && flightRows.length ? flightRange : range;
  const loadedIteration = loadedIterationForSession(latestLoadedDesignKey, designSessionId);
  const canReviseDesign = Boolean(designSessionId && loadedIteration !== null && config && !busy);
  const hasFlight = flightRows.length > 0 && vehicleModel != null;
  const timelineEnabled = view === "flight" ? hasFlight : Boolean(report);

  // Run the P&ID -> propulsion package -> vehicle -> 6DOF flight pipeline for the
  // loaded design iteration, then load the artifacts and jump to the Flight Twin.
  const buildAndFly = useCallback(async () => {
    if (!designSessionId || loadedIteration == null || flightBusy) return;
    setFlightBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/design-runs/${designSessionId}/flight`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ iteration: loadedIteration }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `Flight failed (${res.status})`);
      const base = `/api/flight-runs/${designSessionId}/${loadedIteration}`;
      const [vehicle, flightCsv, eventsJson, reportJson] = await Promise.all([
        fetch(`${base}/vehicle/vehicle_model.json`).then((r) => r.json()),
        fetch(`${base}/flight/flight.csv`).then((r) => r.text()),
        fetch(`${base}/flight/flight_events.json`).then((r) => r.json()),
        fetch(`${base}/flight/flight_report.json`).then((r) => r.json()),
      ]);
      const rows = parseFlightCsv(flightCsv);
      setVehicleModel(vehicle);
      setFlightRows(rows);
      setFlightEvents(eventsJson);
      setFlightReport(reportJson);
      setTime(0);
      setView("flight");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Flight pipeline failed");
    } finally {
      setFlightBusy(false);
    }
  }, [designSessionId, loadedIteration, flightBusy]);

  // JSON input mode: load a pasted NetworkConfig straight into the viewer (no
  // backend / LLM) so any P&ID can be visualized in 2D + 3D. No telemetry until
  // it's simulated, so the timeline/summary stay empty until a run produces it.
  function loadDesignJson() {
    setError(null);
    let parsed: NetworkConfig;
    try {
      parsed = JSON.parse(jsonText) as NetworkConfig;
    } catch {
      setError("That is not valid JSON.");
      return;
    }
    if (!parsed || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.connections)) {
      setError("JSON must be a NetworkConfig with 'nodes' and 'connections' arrays.");
      return;
    }
    const built = buildDiagram(parsed);
    setConfig(parsed);
    setDiagram(built);
    setReport(null);
    setNodeRows([]);
    setConnectionRows([]);
    setSelectedId(built.nodes[0] ? `node:${built.nodes[0].name}` : null);
    setTime(0);
    setPhase(0);
    setView("2d");
  }

  function loadRunArtifacts(parsed: NetworkConfig, runReport: RunReport, nodesCsv: string, connectionsCsv: string) {
    const built = buildDiagram(parsed);
    setConfig(parsed);
    setDiagram(built);
    setReport(runReport);
    setNodeRows(parseSamplesCsv(nodesCsv));
    setConnectionRows(parseSamplesCsv(connectionsCsv));
    setSelectedId(built.nodes[0] ? `node:${built.nodes[0].name}` : null);
    setTime(0);
    setPhase(0);
  }

  // Cached demo P&ID: with ?demo in the URL, load the pre-generated pressure-fed
  // LOX/kerosene/N2 run from /public/demo (design.json + telemetry) instantly,
  // no backend or LLM loop. Lets the P&ID + 3D twin be shown/verified offline.
  useEffect(() => {
    if (!/[?&]demo\b/.test(window.location.search)) return;
    let cancelled = false;
    void (async () => {
      try {
        const [design, demoReport, nodesCsv, connectionsCsv] = await Promise.all([
          fetch("/demo/design.json").then((res) => res.json() as Promise<NetworkConfig>),
          fetch("/demo/report.json").then((res) => res.json() as Promise<RunReport>),
          fetch("/demo/nodes.csv").then((res) => res.text()),
          fetch("/demo/connections.csv").then((res) => res.text())
        ]);
        if (cancelled) return;
        loadRunArtifacts(design, demoReport, nodesCsv, connectionsCsv);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Could not load demo fixture");
      }
    })();
    return () => {
      cancelled = true;
    };
    // Mount-only: the demo fixture is static.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!playing) return;
    let previous = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const elapsed = ((now - previous) / 1000) * speed;
      previous = now;
      setTime((current) => {
        if (activeRange.max <= activeRange.min) return current;
        const next = current + elapsed;
        return next > activeRange.max ? activeRange.min : next;
      });
      setPhase((current) => (current + elapsed * 0.7) % 1);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, activeRange.max, activeRange.min, speed]);

  async function loadDesignIteration(sessionId: string, latest: LatestPlayableRun) {
    const key = `${sessionId}:${latest.iteration}`;
    if (latestLoadedDesignKey === key) return;
    const artifactBase = `/api/design-runs/${sessionId}/artifact/${latest.iteration}`;
    const [designJson, reportJson, nodesCsv, connectionsCsv] = await Promise.all([
      fetch(`${artifactBase}/design.json`).then((res) => res.json() as Promise<NetworkConfig>),
      fetch(`${artifactBase}/report.json`).then((res) => res.json() as Promise<RunReport>),
      fetch(`${artifactBase}/nodes.csv`).then((res) => res.text()),
      fetch(`${artifactBase}/connections.csv`).then((res) => res.text())
    ]);
    loadRunArtifacts(designJson, reportJson, nodesCsv, connectionsCsv);
    setLatestLoadedDesignKey(key);
    console.info(
      `[design-loop ${sessionId.slice(0, 8)}] loaded iteration ${latest.iteration + 1} artifacts`,
      { artifacts: latest.artifacts }
    );
  }

  async function refreshDesignRun(sessionId: string) {
    const response = await fetch(`/api/design-runs/${sessionId}`);
    const payload = (await response.json()) as DesignRunStatusResponse;
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || "Could not load design run");
    }
    setDesignState(payload.state);
    const latest = payload.state.iterations[payload.state.iterations.length - 1];
    const consoleKey = [
      payload.state.status,
      payload.state.stage,
      payload.state.current_iteration,
      latest?.status ?? "",
      latest?.verdict?.summary ?? "",
      latest?.decision?.action ?? "",
      payload.latest_playable?.iteration ?? "",
      payload.state.error ?? ""
    ].join("|");
    if (lastConsoleState.current !== consoleKey) {
      lastConsoleState.current = consoleKey;
      const checkRows = consoleCheckRows(latest);
      const checkSummary = consoleCheckSummary(latest);
      console.info(`[design-loop ${sessionId.slice(0, 8)}] ${currentActivity(payload.state)}`, {
        status: payload.state.status,
        stage: payload.state.stage,
        current_iteration: payload.state.current_iteration,
        latest_verdict: latest?.verdict?.summary,
        checks: checkSummary,
        check_rows: checkRows,
        decision: latest?.decision,
        latest_playable: payload.latest_playable,
        error: payload.state.error
      });
      if (checkRows.length) {
        console.table(checkRows);
      }
    }
    if (payload.latest_playable) {
      await loadDesignIteration(sessionId, payload.latest_playable);
    }
    return payload.state;
  }

  useEffect(() => {
    if (!designSessionId) return;
    let cancelled = false;
    let timer = 0;

    const poll = async () => {
      try {
        const state = await refreshDesignRun(designSessionId);
        if (cancelled) return;
        if (state.status === "running") {
          timer = window.setTimeout(poll, 2000);
        } else {
          setChatHistory((history) => updateRunStatusChatItem(history, designSessionId, state));
          setBusy(false);
        }
      } catch (exc) {
        if (!cancelled) {
          setBusy(false);
          const message = exc instanceof Error ? exc.message : String(exc);
          setError(message);
          setChatHistory((history) =>
            history.map((item) =>
              item.kind === "status" && item.sessionId === designSessionId
                ? { ...item, text: message, status: "error" }
                : item
            )
          );
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [designSessionId, latestLoadedDesignKey]);

  async function submitChatMessage(messageText: string): Promise<boolean> {
    const message = messageText.trim();
    if (!message) return false;
    if (busy) {
      setChatText(message);
      setInputMode("chat");
      setError("A design loop is already running. The voice revision is ready in chat and can be submitted when the run finishes.");
      return false;
    }
    const target = chatSubmissionTarget(designSessionId, latestLoadedDesignKey, Boolean(config));
    const parentSessionId = designSessionId;
    const userItem = createUserChatItem(message, target, parentSessionId);
    setChatHistory((history) => (target.kind === "new" ? [userItem] : [...history, userItem]));
    setBusy(true);
    setError(null);
    setPlaying(false);
    setDesignState(null);
    setLatestLoadedDesignKey(null);
    setChatText("");
    try {
      const response = await fetch(target.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(chatRequestBody(message, target))
      });
      const payload = (await response.json()) as DesignRunStartResponse | DesignRunRevisionResponse;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "Could not start design run");
      }
      if (target.kind === "revision") {
        console.info(`[design-loop ${payload.session_id.slice(0, 8)}] started revision from chat`, {
          message,
          parent_session_id: designSessionId,
          iteration: target.iteration
        });
      } else {
        console.info(`[design-loop ${payload.session_id.slice(0, 8)}] started from chat`, { message });
      }
      setChatHistory((history) => [...history, createRunStatusChatItem(payload.session_id, target, parentSessionId)]);
      setDesignSessionId(payload.session_id);
      return true;
    } catch (exc) {
      setBusy(false);
      const failureMessage = exc instanceof Error ? exc.message : String(exc);
      setError(failureMessage);
      setChatHistory((history) => [
        ...history,
        {
          id: chatId("error"),
          role: "assistant",
          text: failureMessage,
          kind: "status",
          status: "error",
          createdAt: Date.now()
        }
      ]);
      setChatText(message);
      return false;
    }
  }

  async function submitChatRequest() {
    await submitChatMessage(chatText);
  }

  function handleVoiceSendToChat(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setChatText(trimmed);
    setInputMode("chat");
  }

  function getDesignStatus(): string {
    const state = designState;
    if (!state) {
      return "No design run has started yet. Give me the requirements and I'll launch one.";
    }
    const latest = state.iterations[state.iterations.length - 1];
    const verdict = latest?.verdict;
    const iterations = state.iterations.length;
    if (state.status === "error") {
      const err = state.error ?? "unknown error";
      if (/auth|api.?key|401|403|credential/i.test(err)) {
        return (
          "The design loop failed because backend API keys are not configured. " +
          "Check ANTHROPIC_API_KEY in the server .env file, then retry from the Chat tab."
        );
      }
      return `The run hit an error: ${err}. You can edit the requirements in Chat and run again.`;
    }
    if (state.status === "passed" || state.passed) {
      return `The design passed all checks after ${iterations} iteration${iterations === 1 ? "" : "s"}.`;
    }
    if (state.status === "failed") {
      return `The run finished without passing after ${iterations} iterations.${verdict ? ` ${verdict.summary}` : ""}`;
    }
    const stage = stageLabel(state.stage).toLowerCase();
    const iter = state.current_iteration >= 0 ? `iteration ${state.current_iteration + 1}` : "the first pass";
    if (verdict) {
      const checks = verdict.checks ?? [];
      const passed = checks.filter((check) => check.passed).length;
      return `Still running. Currently ${stage} on ${iter}. Latest verdict: ${passed} of ${checks.length} checks passing.`;
    }
    return `Still running. Currently ${stage} on ${iter}.`;
  }

  // Design-mode narration feed: the latest thing worth speaking aloud, keyed for
  // dedup so the copilot reads each iteration verdict (and the final result) once.
  function getDesignNarration(): { key: string; text: string } | null {
    const state = designState;
    if (!state) return null;
    const sid = designSessionId ?? "run";
    if (state.status === "error") {
      return { key: `${sid}:error`, text: `The run hit an error: ${state.error ?? "unknown error"}.` };
    }
    const iters = state.iterations_used || state.iterations.length;
    if (state.status === "passed" || state.passed) {
      return { key: `${sid}:done`, text: `Done. The design passed all checks after ${iters} iteration${iters === 1 ? "" : "s"}.` };
    }
    if (state.status === "failed") {
      const verdict = state.iterations[state.iterations.length - 1]?.verdict;
      return { key: `${sid}:done`, text: `The run finished without passing after ${iters} iterations.${verdict ? ` ${verdict.summary}` : ""}` };
    }
    const latest = state.iterations[state.iterations.length - 1];
    const verdict = latest?.verdict;
    if (latest && verdict) {
      const checks = verdict.checks ?? [];
      const passed = checks.filter((check) => check.passed).length;
      const firstFail = checks.find((check) => !check.passed);
      const tail = firstFail ? ` Revising ${firstFail.id || "a failing check"}.` : "";
      return { key: `${sid}:i${latest.iteration}`, text: `Iteration ${latest.iteration + 1}: ${passed} of ${checks.length} checks passed.${tail}` };
    }
    return null;
  }

  const selected = selectedName(selectedId);
  const isConnection = selectedId?.startsWith("connection:") ?? false;
  const selectedRows = selectedId?.startsWith("node:") ? nodeSamples[selected ?? ""] : connectionSamples[selected ?? ""];
  const selectedSample = interpolateSample(selectedRows, time);
  const selectedNode = selectedId?.startsWith("node:")
    ? diagram?.nodes.find((node) => node.name === selected)
    : undefined;
  const selectedFillLevel = selectedNode?.type === "Tank" ? numericValue(selectedSample, "fill_level") : undefined;
  const systemSummary = useMemo(() => buildSystemSummary(diagram, nodeSamples, time), [diagram, nodeSamples, time]);

  // Per-node pass/fail status for the currently-displayed iteration, so the P&ID
  // colors the components that fail (red) or warn (yellow). Match the iteration
  // whose artifacts are loaded into the diagram; fall back to the latest evaluated.
  const diagramNodeStatus = useMemo(() => {
    const iters = designState?.iterations ?? [];
    if (iters.length === 0) return undefined;
    const loadedIteration = latestLoadedDesignKey
      ? Number(latestLoadedDesignKey.split(":")[1])
      : undefined;
    const match =
      (loadedIteration !== undefined
        ? iters.find((it) => it.iteration === loadedIteration)
        : undefined) ?? [...iters].reverse().find((it) => it.node_status);
    return match?.node_status;
  }, [designState, latestLoadedDesignKey]);
  const loopActivity = currentActivity(designState);
  const loopSteps = activitySteps(designState);
  const overlaySteps = loopSteps.length > 0
    ? loopSteps
    : [
        {
          key: "starting",
          label: designSessionId ? "Starting design loop" : "Starting simulation",
          detail: designSessionId ? "Waiting for requirements status" : "Starting run",
          tone: "current" as ActivityTone
        }
      ];
  const timeSpan = activeRange.max - activeRange.min;
  const timePct = timeSpan > 0 ? ((time - activeRange.min) / timeSpan) * 100 : 0;
  const scrubberStyle = {
    background: `linear-gradient(90deg, var(--accent) ${timePct}%, var(--surface-3) ${timePct}%)`
  };

  const designPassed = Boolean(designState?.status === "passed" || designState?.passed);
  const procurementRunning = procurement?.status === "running";
  const canProcure = Boolean(designSessionId && designPassed && !procurementRunning);

  const startProcurement = useCallback(async () => {
    if (!designSessionId || procurementRunning) return;
    setShowReceipts(true);
    setProcurement({ status: "running", stage: "sourcing" });
    try {
      const res = await fetch(`/api/design-runs/${designSessionId}/procure-and-quote`, {
        method: "POST"
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setProcurement({ status: "error", error: body.detail ?? "Could not start procurement" });
      }
    } catch (err) {
      setProcurement({ status: "error", error: String(err) });
    }
  }, [designSessionId, procurementRunning]);

  useEffect(() => {
    if (!designSessionId || !procurementRunning) return;
    let active = true;
    const id = window.setInterval(async () => {
      try {
        const res = await fetch(`/api/design-runs/${designSessionId}/procurement-status`);
        if (!res.ok || !active) return;
        const data = (await res.json()) as ProcurementUiState;
        if (active) setProcurement(data);
      } catch {
        /* transient — keep polling */
      }
    }, 3000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [designSessionId, procurementRunning]);

  const shellStyle = {
    ["--sidebar-w" as string]: `${sidebarCollapsed ? SIDEBAR_RAIL : sidebarWidth}px`
  } as React.CSSProperties;

  return (
    <div className={`app-shell${config ? "" : " no-inspector"}`} style={shellStyle}>
      <aside className={`side-panel${sidebarCollapsed ? " is-collapsed" : ""}`}>
        {sidebarCollapsed ? (
          <button
            type="button"
            className="sidebar-rail"
            onClick={() => setSidebarCollapsed(false)}
            title="Expand sidebar"
            aria-label="Expand sidebar"
          >
            <PanelLeft size={16} />
          </button>
        ) : (
          <>
        <div className="brand-row">
          <span className="brand-mark">
            <img src="/rocketcursor_logo.png" alt="RocketCursor" />
          </span>
          <div>
            <h1>RocketCursor</h1>
          </div>
        </div>

        <div className="mode-switch" role="tablist" aria-label="Input mode">
          <button
            type="button"
            className={inputMode === "chat" ? "selected" : ""}
            onClick={() => setInputMode("chat")}
          >
            <MessageSquare size={15} />
            Chat
          </button>
          <button
            type="button"
            className={inputMode === "json" ? "selected" : ""}
            onClick={() => setInputMode("json")}
          >
            <Braces size={15} />
            JSON
          </button>
          <button
            type="button"
            className={inputMode === "voice" ? "selected" : ""}
            onClick={() => setInputMode("voice")}
          >
            <Mic size={15} />
            Voice
          </button>
        </div>

        {inputMode === "chat" && (
          <form
            className="chat-runner"
            onSubmit={(event) => {
              event.preventDefault();
              void submitChatRequest();
            }}
          >
            <ChatTranscript items={chatHistory} />
            <textarea
              value={chatText}
              onChange={(event) => setChatText(event.target.value)}
              placeholder={
                canReviseDesign
                  ? "Ask for a revision to the displayed design."
                  : "Describe the system to design, or enter a spec name like pressure_window_blowdown."
              }
              disabled={busy}
              rows={5}
            />
            <button className="primary-action" type="submit" disabled={busy || !chatText.trim()}>
              <Send size={18} />
              {busy && designSessionId ? "Loop running..." : canReviseDesign ? "Revise design" : "Run design loop"}
            </button>
          </form>
        )}

        {inputMode === "json" && (
          <form
            className="chat-runner"
            onSubmit={(event) => {
              event.preventDefault();
              loadDesignJson();
            }}
          >
            <textarea
              className="json-input"
              value={jsonText}
              onChange={(event) => setJsonText(event.target.value)}
              placeholder='Paste a NetworkConfig design JSON ({ "nodes": [...], "connections": [...] }) to visualize it.'
              spellCheck={false}
              rows={16}
            />
            <button className="primary-action" type="submit" disabled={!jsonText.trim()}>
              <Braces size={18} />
              Load JSON
            </button>
          </form>
        )}

        {inputMode === "voice" && (
          <VoiceAgentCopilot
            onStartDesign={(summary) => void submitChatMessage(summary)}
            getDesignStatus={getDesignStatus}
            onSendToChat={handleVoiceSendToChat}
            getDesignNarration={getDesignNarration}
          />
        )}

        {error && <pre className="error-box">{error}</pre>}
          </>
        )}

        <div
          className="sidebar-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          title="Drag to resize · drag left to collapse · double-click to reset"
          onPointerDown={onSidebarResizeStart}
          onPointerMove={onSidebarResizeMove}
          onPointerUp={onSidebarResizeEnd}
          onDoubleClick={() => {
            setSidebarCollapsed(false);
            setSidebarWidth(SIDEBAR_DEFAULT);
          }}
        />
      </aside>

      <main className="workspace">
        <div className="canvas-toolbar">
          <div className="toolbar-controls">
            <div className="view-switch" role="tablist" aria-label="Diagram view">
              <button
                type="button"
                role="tab"
                aria-selected={view === "2d"}
                className={view === "2d" ? "selected" : ""}
                onClick={() => setView("2d")}
                title="Schematic P&ID"
              >
                <Workflow size={14} />
                P&amp;ID
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "3d"}
                className={view === "3d" ? "selected" : ""}
                onClick={() => setView("3d")}
                title="Systems twin — internal plumbing"
              >
                <Box size={14} />
                Systems
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "vehicle"}
                className={view === "vehicle" ? "selected" : ""}
                onClick={() => setView("vehicle")}
                disabled={!vehicleModel}
                title="Vehicle Studio — full generated rocket"
              >
                <Layers size={14} />
                Vehicle
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "flight"}
                className={view === "flight" ? "selected" : ""}
                onClick={() => setView("flight")}
                disabled={!hasFlight}
                title="Flight Twin — 6DOF trajectory playback"
              >
                <Rocket size={14} />
                Flight
              </button>
            </div>
            <button
              type="button"
              className="build-fly-button"
              onClick={buildAndFly}
              disabled={loadedIteration == null || flightBusy}
              title="Physicalize, build the vehicle, and fly it in 6DOF"
            >
              <Rocket size={14} />
              {flightBusy ? "Building & flying…" : "Build & Fly"}
            </button>
            <label className="checkbox-control">
              <input
                type="checkbox"
                checked={showPartLabels}
                onChange={(event) => setShowPartLabels(event.target.checked)}
              />
              Labels
            </label>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              aria-label="Toggle color theme"
            >
              {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
            </button>
          </div>
        </div>

        <div className="canvas-wrap">
          {view === "2d" ? (
            <PidCanvas
              diagram={diagram}
              nodeSamples={nodeSamples}
              connectionSamples={connectionSamples}
              selectedId={selectedId}
              metric={metric}
              time={time}
              phase={phase}
              showPartLabels={showPartLabels}
              nodeStatus={diagramNodeStatus}
              onSelect={setSelectedId}
            />
          ) : view === "3d" ? (
            <Suspense fallback={<div className="twin-empty">Loading systems twin…</div>}>
              <Twin3D
                diagram={diagram}
                nodeSamples={nodeSamples}
                connectionSamples={connectionSamples}
                selectedId={selectedId}
                time={time}
                phase={phase}
                showPartLabels={showPartLabels}
                nodeStatus={diagramNodeStatus}
                onSelect={setSelectedId}
              />
            </Suspense>
          ) : view === "vehicle" ? (
            <Suspense fallback={<div className="twin-empty">Loading vehicle studio…</div>}>
              {vehicleModel ? (
                <VehicleStudio vehicle={vehicleModel} />
              ) : (
                <div className="twin-empty">Run “Build &amp; Fly” to generate the vehicle.</div>
              )}
            </Suspense>
          ) : (
            <Suspense fallback={<div className="twin-empty">Loading flight twin…</div>}>
              {hasFlight && flightEvents ? (
                <FlightTwin
                  rows={flightRows}
                  events={flightEvents}
                  render={vehicleModel.geometry.render}
                  totalLength={vehicleModel.geometry.total_length_m}
                  time={time}
                />
              ) : (
                <div className="twin-empty">Run “Build &amp; Fly” to fly the rocket.</div>
              )}
            </Suspense>
          )}
        </div>

        <div className="timeline">
          <button
            type="button"
            className={`icon-button${playing ? " is-active" : ""}`}
            onClick={() => setPlaying((value) => !value)}
            disabled={!timelineEnabled}
            title={playing ? "Pause" : "Play"}
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button
            type="button"
            className="icon-button"
            onClick={() => {
              setTime(activeRange.min);
              setPhase(0);
            }}
            disabled={!timelineEnabled}
            title="Reset to start"
          >
            <RotateCcw size={18} />
          </button>
          <input
            type="range"
            min={activeRange.min}
            max={activeRange.max}
            step={view === "flight" ? 0.1 : report?.dt ?? 0.01}
            value={time}
            disabled={!timelineEnabled}
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

      {config && (
      <aside className="inspector">
        <div className="inspector-head">
          <div>
            <div className="selected-title">
              {view === "flight"
                ? "Flight summary"
                : view === "vehicle"
                  ? "Vehicle summary"
                  : selected ?? "System summary"}
            </div>
            {selected && view !== "flight" && view !== "vehicle" && (
              <span className="selected-sub">{isConnection ? "Connection" : selectedNode?.type ?? "Node"}</span>
            )}
          </div>
        </div>

        {view === "flight" && flightRows.length ? (
          (() => {
            // Flight Twin: trajectory metrics, live at the scrub time + run maxima.
            const base = flightRows[0]?.altitude ?? 0;
            const s = interpolateFlight(flightRows, time);
            const speed = s ? Math.hypot(s.velocity_x, s.velocity_y, s.velocity_z) : undefined;
            const cells = [
              summaryCell("Altitude", s ? s.altitude - base : undefined, (v) => `${v.toFixed(0)} m`),
              summaryCell("Velocity", speed, (v) => `${v.toFixed(0)} m/s`),
              summaryCell("Mach", s?.mach, (v) => v.toFixed(2)),
              summaryCell("Thrust", s?.thrust, (v) => `${(v / 1000).toFixed(2)} kN`),
              summaryCell("Mass", s?.mass, (v) => `${v.toFixed(1)} kg`),
              summaryCell("Apogee", flightReport?.apogee_m, (v) => `${v.toFixed(0)} m`),
              summaryCell("Max velocity", flightReport?.max_velocity_ms, (v) => `${v.toFixed(0)} m/s`),
              summaryCell("Max Mach", flightReport?.max_mach, (v) => v.toFixed(2)),
            ].filter((cell) => cell.value !== "—");
            return (
              <div className="inspector-block">
                <h2 className="section-label">Flight summary</h2>
                <div className="summary-grid">
                  {cells.map((cell) => (
                    <div key={cell.label} className="summary-cell">
                      <span className="summary-cell-label">{cell.label}</span>
                      <strong className="summary-cell-value">{cell.value}</strong>
                    </div>
                  ))}
                </div>
                {flightReport && (
                  <div className="summary-status">
                    <span className={`summary-pill ${flightReport.stable ? "ok" : "warn"}`}>
                      {flightReport.stable ? "Stable" : "Unstable"}
                    </span>
                    {flightReport.apogee_vs_target_m != null && (
                      <span className="summary-pill warn">
                        {flightReport.apogee_vs_target_m >= 0 ? "+" : ""}
                        {Number(flightReport.apogee_vs_target_m).toFixed(0)} m vs target
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })()
        ) : view === "vehicle" && vehicleModel ? (
          (() => {
            // Vehicle Studio: as-built mass, balance and stability (static).
            const g = vehicleModel.geometry ?? {};
            const mp = vehicleModel.mass_properties ?? {};
            const a = vehicleModel.aerodynamics ?? {};
            const stable = (a.static_margin_cal ?? 0) >= 1.0;
            const cells = [
              summaryCell("Length", g.total_length_m, (v) => `${v.toFixed(2)} m`),
              summaryCell("Diameter", g.body_diameter_m, (v) => `${(v * 1000).toFixed(0)} mm`),
              summaryCell("Loaded mass", mp.loaded_mass_kg, (v) => `${v.toFixed(1)} kg`),
              summaryCell("Dry mass", mp.dry_mass_kg, (v) => `${v.toFixed(1)} kg`),
              summaryCell("CG", mp.loaded_cg_z_m, (v) => `${v.toFixed(2)} m`),
              summaryCell("CP", a.cp_z_m, (v) => `${v.toFixed(2)} m`),
              summaryCell("Static margin", a.static_margin_cal, (v) => `${v.toFixed(2)} cal`),
            ].filter((cell) => cell.value !== "—");
            return (
              <div className="inspector-block">
                <h2 className="section-label">Vehicle summary</h2>
                <div className="summary-grid">
                  {cells.map((cell) => (
                    <div key={cell.label} className="summary-cell">
                      <span className="summary-cell-label">{cell.label}</span>
                      <strong className="summary-cell-value">{cell.value}</strong>
                    </div>
                  ))}
                </div>
                <div className="summary-status">
                  <span className={`summary-pill ${stable ? "ok" : "warn"}`}>
                    {stable ? "Statically stable" : "Unstable"}
                  </span>
                </div>
              </div>
            );
          })()
        ) : selected ? (
          <>
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
              <TelemetryPlots rows={selectedRows} currentSample={selectedSample} time={time} />
            </div>
          </>
        ) : systemSummary ? (
          (() => {
            const checks = designState?.iterations[designState.iterations.length - 1]?.verdict?.checks ?? [];
            const checksPassed = checks.filter((check) => check.passed).length;
            const warnings = report?.status?.warnings?.length ?? 0;
            const cells = [
              ...(systemSummary.hasEngine
                ? [
                    summaryCell("Thrust", systemSummary.thrust, (v) => `${v.toFixed(0)} N`),
                    summaryCell("Chamber P", systemSummary.pc, (v) => `${(v / PA_PER_MPA).toFixed(2)} MPa`),
                    summaryCell("Mixture ratio", systemSummary.mr, (v) => v.toFixed(2)),
                    summaryCell("Isp", systemSummary.isp, (v) => `${v.toFixed(0)} s`)
                  ]
                : []),
              summaryCell("LOX fill", systemSummary.oxFill, (v) => `${(v * 100).toFixed(0)}%`),
              summaryCell("Fuel fill", systemSummary.fuelFill, (v) => `${(v * 100).toFixed(0)}%`),
              summaryCell("Pressurant", systemSummary.pressurantP, (v) => `${(v / PA_PER_MPA).toFixed(2)} MPa`)
            ].filter((cell) => cell.value !== "—");

            return (
              <div className="inspector-block">
                <h2 className="section-label">System summary</h2>
                {cells.length > 0 ? (
                  <div className="summary-grid">
                    {cells.map((cell) => (
                      <div key={cell.label} className="summary-cell">
                        <span className="summary-cell-label">{cell.label}</span>
                        <strong className="summary-cell-value">{cell.value}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="summary-empty">Run a design loop to see live system telemetry.</p>
                )}
                <div className="summary-status">
                  <span className={`summary-pill ${checks.length && checksPassed === checks.length ? "ok" : "warn"}`}>
                    {checks.length ? `${checksPassed}/${checks.length} checks` : "No checks yet"}
                  </span>
                  <span className={`summary-pill ${warnings ? "warn" : "ok"}`}>
                    {warnings} warning{warnings === 1 ? "" : "s"}
                  </span>
                </div>
              </div>
            );
          })()
        ) : (
          <div className="inspector-block">
            <p className="summary-empty">Run a design loop to populate the inspector.</p>
          </div>
        )}

        {designPassed && (
          <div className="inspector-block procurement-block">
            <h2 className="section-label">Procurement</h2>
            <p className="procurement-hint">
              Design verified. Source the parts and stage RFQ quote requests with each supplier.
            </p>
            <button
              type="button"
              className="procurement-button"
              onClick={startProcurement}
              disabled={!canProcure}
            >
              <Workflow size={16} />
              {procurementRunning ? "Procuring parts…" : "Procure parts & request quotes"}
            </button>
            {procurement && (
              <button
                type="button"
                className="procurement-link"
                onClick={() => setShowReceipts(true)}
              >
                View receipts
              </button>
            )}
          </div>
        )}

        <div className="inspector-block report-block">
          <h2 className="section-label">Design report</h2>
          <p className="procurement-hint">
            A written rationale for every sizing choice — propellants, pressures, tank &amp; engine
            sizing, stability, flight and validation — with the assumptions behind each.
          </p>
          <a
            className={`report-button${designSessionId ? "" : " is-disabled"}`}
            href={designSessionId ? `/api/design-runs/${designSessionId}/report.pdf` : undefined}
            target="_blank"
            rel="noreferrer"
            aria-disabled={!designSessionId}
          >
            <FileText size={16} /> Download report (PDF)
          </a>
        </div>
      </aside>
      )}

      {showReceipts && procurement && (
        <div className="run-overlay" role="dialog" aria-label="Procurement receipts">
          <div className="run-modal receipts-modal">
            <div className="run-modal-header">
              <span className="brand-mark">
                <Workflow size={20} />
              </span>
              <div>
                <strong>RFQ quote requests</strong>
                <span>{procurementStageLabel(procurement)}</span>
              </div>
              <button
                type="button"
                className="receipts-close"
                onClick={() => setShowReceipts(false)}
                aria-label="Close receipts"
              >
                ✕
              </button>
            </div>

            {procurementRunning && (
              <div className="progress-track" aria-label="Procurement in progress">
                <div className="progress-bar" />
              </div>
            )}

            {procurement.status === "error" && (
              <p className="receipts-error">{procurement.error ?? "Procurement failed."}</p>
            )}

            {procurement.screenshots && procurement.screenshots.length > 0 ? (
              <div className="receipts-grid">
                {procurement.screenshots.map((shot) => (
                  <figure key={shot.url} className="receipt-card">
                    <figcaption className="receipt-caption">
                      <strong>{shot.supplier ?? "Supplier"}</strong>
                      <span>{shot.item}</span>
                      <span className={`receipt-pill ${shot.quoteStatus === "parked" ? "ok" : "warn"}`}>
                        {shot.quoteStatus === "parked"
                          ? "RFQ staged"
                          : shot.quoteStatus ?? "—"}
                      </span>
                    </figcaption>
                    <a href={shot.url} target="_blank" rel="noreferrer">
                      <img className="receipt-image" src={shot.url} alt={`${shot.supplier} quote form`} />
                    </a>
                  </figure>
                ))}
              </div>
            ) : (
              procurement.status !== "error" && (
                <p className="receipts-empty">
                  Agents are filling supplier quote forms — receipts will appear here. This can take a few minutes.
                </p>
              )
            )}
          </div>
        </div>
      )}

      {busy && (
        <div className="run-overlay" role="alert" aria-live="assertive">
          <div className="run-modal">
            <div className="run-modal-header">
              <span className="brand-mark">
                <Gauge size={20} />
              </span>
              <div>
                <strong>{designSessionId ? "Running design loop" : "Running simulation"}</strong>
                <span>{loopActivity || "Starting run and waiting for status."}</span>
              </div>
            </div>
            <div className="run-step-list" aria-label="Current run steps">
              {overlaySteps.map((step) => (
                <div key={step.key} className={`run-step tone-${step.tone}`}>
                  <span className="activity-dot" />
                  <div>
                    <strong>{step.label}</strong>
                    <span>{step.detail}</span>
                  </div>
                </div>
              ))}
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
