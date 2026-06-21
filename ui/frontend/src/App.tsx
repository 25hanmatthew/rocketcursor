import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Cylinder,
  FileJson,
  Flame,
  Gauge,
  MessageSquare,
  Mic,
  Pause,
  Play,
  RotateCcw,
  Send,
  Spline,
  Upload,
  Wind,
  XCircle
} from "lucide-react";
import { PidCanvas } from "./components/PidCanvas";
import { ConversationRecorder } from "./components/ConversationRecorder";
import type { DesignChange } from "./components/ConversationRecorder";
import { buildDiagram } from "./lib/diagram";
import { parseSamplesCsv } from "./lib/csv";
import { interpolateSample, numericValue, rowsByComponent, timeRange } from "./lib/telemetry";
import type {
  ChatHistoryItem,
  DiagramModel,
  DiagramNode,
  DesignRunRevisionResponse,
  DesignRunStartResponse,
  DesignRunStatusResponse,
  LatestPlayableRun,
  NetworkConfig,
  RunReport,
  RunResponse,
  SampleRow,
  SessionIteration,
  SessionState,
  StatusItem
} from "./types";

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
type InputMode = "chat" | "json" | "voice";

/* Turn structured design changes from the voice recorder into a plain-text
   requirements block so the existing chat field (and the agent loop behind it)
   consumes it exactly like a typed request. */
function changesToRequirements(changes: DesignChange[]): string {
  if (changes.length === 0) return "";
  const lines = changes.map((change) => {
    const category = change.category ? `[${change.category}] ` : "";
    const value =
      change.value !== null && change.value !== undefined && `${change.value}`.trim() !== ""
        ? ` (value: ${change.value})`
        : "";
    return `- ${category}${change.description}${value}`;
  });
  return `Design change requests:\n${lines.join("\n")}`;
}
type ActivityTone = "done" | "current" | "upcoming" | "danger";
type ChatTarget = { kind: "revision"; url: string; iteration: number } | { kind: "new"; url: string };

function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`status-badge tone-${tone}`}>
      <span className="dot" />
      {label}
    </span>
  );
}

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

function NodeGlyph({ type }: { type: DiagramNode["type"] }) {
  if (type === "Tank") return <Cylinder size={14} />;
  if (type === "Engine") return <Flame size={14} />;
  if (type === "Ambient") return <Wind size={14} />;
  return <Circle size={14} />;
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
  if (items.length === 0) return null;
  return (
    <div className="chat-history" aria-label="Chat history">
      {items.map((item) => (
        <div key={item.id} className={`chat-message role-${item.role} status-${item.status ?? "idle"}`}>
          <div className="chat-message-meta">
            <span>{item.role === "user" ? "You" : "Design loop"}</span>
            {item.kind === "revision" && <span>Revision</span>}
            {item.status && <span>{item.status}</span>}
          </div>
          <div className="chat-message-text">{item.text}</div>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [inputMode, setInputMode] = useState<InputMode>("chat");
  const [chatText, setChatText] = useState("");
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const nodeSamples = useMemo(() => rowsByComponent(nodeRows), [nodeRows]);
  const connectionSamples = useMemo(() => rowsByComponent(connectionRows), [connectionRows]);
  const range = useMemo(() => timeRange(nodeRows, connectionRows), [nodeRows, connectionRows]);
  const loadedIteration = loadedIterationForSession(latestLoadedDesignKey, designSessionId);
  const canReviseDesign = Boolean(designSessionId && loadedIteration !== null && config && !busy);

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

  async function submitFile(file: File) {
    setBusy(true);
    setError(null);
    setPlaying(false);
    setDesignSessionId(null);
    setDesignState(null);
    setLatestLoadedDesignKey(null);
    setChatHistory([]);
    lastConsoleState.current = "";
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

      loadRunArtifacts(parsed, payload.report, nodesCsv, connectionsCsv);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function submitChatRequest() {
    const message = chatText.trim();
    if (!message) return;
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
    }
  }

  function handleChangesExtracted(changes: DesignChange[]) {
    const requirements = changesToRequirements(changes);
    if (requirements) {
      setChatText(requirements);
      setInputMode("chat");
    }
  }

  function handleRawTranscript(transcript: string) {
    setChatText(transcript);
    setInputMode("chat");
  }

  const selected = selectedName(selectedId);
  const isConnection = selectedId?.startsWith("connection:") ?? false;
  const selectedRows = selectedId?.startsWith("node:") ? nodeSamples[selected ?? ""] : connectionSamples[selected ?? ""];
  const selectedSample = interpolateSample(selectedRows, time);
  const selectedNode = selectedId?.startsWith("node:")
    ? diagram?.nodes.find((node) => node.name === selected)
    : undefined;
  const selectedFillLevel = selectedNode?.type === "Tank" ? numericValue(selectedSample, "fill_level") : undefined;

  const latestIteration = designState?.iterations?.[designState.iterations.length - 1];
  const latestVerdict = latestIteration?.verdict;
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
  const statusTone: Tone = designState?.status === "error"
    ? "danger"
    : designState?.status === "running"
    ? "warn"
    : report?.status?.passed || designState?.passed
    ? "ok"
    : report || designState
    ? "warn"
    : "idle";
  const statusLabel = designState?.status === "error"
    ? "Error"
    : designState?.status === "running"
    ? `${designState.stage} ${designState.current_iteration >= 0 ? `#${designState.current_iteration}` : ""}`.trim()
    : report?.status?.passed || designState?.passed
    ? "Nominal"
    : report || designState
    ? "Review"
    : "Idle";
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
            <FileJson size={15} />
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
          <button className="primary-action" type="button" onClick={() => fileInput.current?.click()} disabled={busy}>
            <Upload size={18} />
            {busy ? "Running simulation..." : "Submit network JSON"}
          </button>
        )}

        {inputMode === "voice" && (
          <ConversationRecorder
            onChangesExtracted={handleChangesExtracted}
            onRawTranscript={handleRawTranscript}
          />
        )}

        {error && <pre className="error-box">{error}</pre>}

        {designState && (
          <div className="loop-card">
            <div className="status-card-head">
              <span className="label">Design loop</span>
              <StatusBadge tone={statusTone} label={statusLabel} />
            </div>
            <div className="loop-body">
              <div className="loop-request">{designState.request}</div>
              <div className="loop-meta">
                <span>{loopActivity || `Stage: ${designState.stage}`}</span>
                <span>Iterations: {designState.iterations.length}</span>
              </div>
              <div className="activity-timeline" aria-label="Design loop progress">
                {loopSteps.map((step) => (
                  <div key={step.key} className={`activity-step tone-${step.tone}`}>
                    <span className="activity-dot" />
                    <div>
                      <strong>{step.label}</strong>
                      <span>{step.detail}</span>
                    </div>
                  </div>
                ))}
              </div>
              {latestVerdict && (
                <div className="loop-verdict">
                  <strong>{latestVerdict.summary}</strong>
                  <div className="checks-list compact">
                    {latestVerdict.checks.map((check) => (
                      <div key={check.id} className={`check-chip ${check.passed ? "tone-ok" : "tone-danger"}`}>
                        {check.passed ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                        <span>
                          {check.id}: {check.passed ? "passed" : `actual ${formatValue(check.actual)}`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {latestIteration?.decision && !latestVerdict?.passed && (
                <div className="decision-note">{latestIteration.decision.reason}</div>
              )}
              {designState.error && <div className="decision-note tone-danger">{designState.error}</div>}
            </div>
          </div>
        )}

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
                : "Start a chat design loop or submit a JSON config."}
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
            nodeStatus={diagramNodeStatus}
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
                <strong>{designSessionId ? "Running design loop" : "Running simulation"}</strong>
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
