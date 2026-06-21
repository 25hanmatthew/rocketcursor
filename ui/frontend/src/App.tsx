import { useEffect, useMemo, useRef, useState } from "react";
import { FileJson, Gauge, MessageSquare, Mic, Pause, Play, RotateCcw, Send, Upload } from "lucide-react";
import { PidCanvas } from "./components/PidCanvas";
import { VoiceAgentCopilot } from "./components/VoiceAgentCopilot";
import type { DesignChangeExtraction } from "./components/ConversationRecorder";
import { buildDiagram } from "./lib/diagram";
import { parseSamplesCsv } from "./lib/csv";
import { interpolateSample, numericValue, rowsByComponent, timeRange } from "./lib/telemetry";
import type {
  ChatHistoryItem,
  DiagramModel,
  DesignRunRevisionResponse,
  DesignRunStartResponse,
  DesignRunStatusResponse,
  LatestPlayableRun,
  NetworkConfig,
  RunReport,
  RunResponse,
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

  const selected = selectedName(selectedId);
  const isConnection = selectedId?.startsWith("connection:") ?? false;
  const selectedRows = selectedId?.startsWith("node:") ? nodeSamples[selected ?? ""] : connectionSamples[selected ?? ""];
  const selectedSample = interpolateSample(selectedRows, time);
  const selectedNode = selectedId?.startsWith("node:")
    ? diagram?.nodes.find((node) => node.name === selected)
    : undefined;
  const selectedFillLevel = selectedNode?.type === "Tank" ? numericValue(selectedSample, "fill_level") : undefined;

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
          detail: designSessionId ? "Waiting for requirements status" : "Submitting JSON to simulator",
          tone: "current" as ActivityTone
        }
      ];
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
          <VoiceAgentCopilot
            onStartDesign={(summary) => void submitChatMessage(summary)}
            getDesignStatus={getDesignStatus}
            onSendToChat={handleVoiceSendToChat}
          />
        )}

        {error && <pre className="error-box">{error}</pre>}

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
          <TelemetryPlots rows={selectedRows} currentSample={selectedSample} time={time} />
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
