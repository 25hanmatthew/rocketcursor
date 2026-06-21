import { useCallback, useEffect, useRef, useState } from "react";
import * as Sentry from "@sentry/react";
import { AlertTriangle, Bot, Lightbulb, Loader2, MessageSquare, Mic, Play, Sparkles, Square, User } from "lucide-react";
import { ROCKET_KEYTERMS } from "../lib/keyterms";
import {
  buildDraftFromTurns,
  buildTranscriptText,
  extractionToRequirements,
  summarizeTranscript,
  type DesignChange,
  type DesignChangeExtraction,
} from "../lib/voiceSummary";

/* Conversational design copilot built on the Deepgram Voice Agent API.
   The engineer talks; the agent (listen=flux, think=gpt-4o-mini, speak=aura-2)
   talks back. Three modes:
     - design:  gather requirements, confirm, launch the design loop, and NARRATE
                each iteration verdict + final design aloud (voice in AND out).
     - advise:  discuss tradeoffs and recommend design changes WITHOUT acting.
     - dictate: listen only, summarize the description to the Chat tab.

   Key reliability rule: a function call (start_design_run / advise / submit) NEVER
   tears down the live conversation. The session ends only on explicit End, unmount,
   or a genuine socket error — so Nova can confirm, narrate, and answer follow-ups.

   Audio path:
   - Mic capture: getUserMedia -> 16 kHz AudioContext -> AudioWorklet -> linear16 PCM -> WS.
   - Agent audio: binary linear16 @ 24 kHz frames -> gapless Web Audio playback queue.
   - Barge-in: on UserStartedSpeaking we stop all scheduled playback immediately.
   - Narration: server-side InjectAgentMessage (behavior=queue) speaks loop verdicts. */

const AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse";
const INPUT_SAMPLE_RATE = 16000;
const OUTPUT_SAMPLE_RATE = 24000;
const KEEPALIVE_MS = 8000;
const NARRATION_POLL_MS = 2500;

const DESIGN_PROMPT = [
  "## CRITICAL: YOU ARE A TEXT GENERATOR FOR A VOICE SYSTEM",
  "Everything you write is read aloud by a text-to-speech engine. Generate ONLY plain conversational text.",
  "No markdown, no headers, no bold, no bullet points, no brackets, no stage directions. Keep every reply to one or two short sentences.",
  "You have instant access to information — never say 'one moment', 'let me check', or 'hold on'.",
  "",
  "## YOUR ROLE",
  "You are Nova, a propulsion design intake assistant for a rocket fluid-network simulator.",
  "Gather a clear set of design requirements from the engineer, then launch a design and simulation run.",
  "",
  "## PERSONALITY AND TONE",
  "Sharp, efficient, and technical. You speak like a fellow propulsion engineer. Never fawning, never chatty.",
  "",
  "## WHAT TO COLLECT",
  "Find out the system type, propellants, target pressures, tank volumes, flow rates, and run duration or constraints.",
  "Ask one focused question at a time. Two or three good questions is usually enough.",
  "",
  "## CONFIRM BEFORE YOU RUN",
  "Do NOT call start_design_run on your first reply. First gather the key requirements, then read them back in one sentence and ask the engineer to confirm.",
  "Only after they say yes (or 'go', 'run it', 'that's right') call start_design_run with a concise requirements summary.",
  "After you call it, tell them you'll read the results aloud as the simulation iterates. Do not end the conversation.",
  "",
  "## STATUS",
  "When the engineer asks how the run is going, call check_design_status and read the result back conversationally.",
  "Do not claim you can fix backend or API authentication errors — tell the engineer to check server API keys.",
  "",
  "## SPEAKING STYLE",
  "Read pressures in plain units, for example 'five hundred psi'. Read numbers naturally.",
].join("\n");

const ADVISE_PROMPT = [
  "## CRITICAL: YOU ARE A TEXT GENERATOR FOR A VOICE SYSTEM",
  "Generate ONLY plain conversational text. No markdown. One or two short sentences per turn.",
  "",
  "## YOUR ROLE",
  "You are Nova in advisory mode — a propulsion design reviewer. Discuss the engineer's design, ask sharp questions, and propose improvements.",
  "You DO NOT run, launch, or change anything. You only advise. Never claim you started a simulation or made a change.",
  "",
  "## WHEN TO CALL FUNCTIONS",
  "When you have a clear set of recommended changes — or the engineer asks 'what should I change' or says they're done — call advise_design_changes once with a summary and the specific key changes.",
  "After calling it, read the recommendations back to the engineer in plain speech and invite follow-up. Stay in the conversation.",
  "",
  "## RECOMMENDATION CONTENT",
  "Each change has a category (pressure, geometry, material, constraint, or general), a plain-English description, and a specific value if one was discussed.",
].join("\n");

const DICTATE_PROMPT = [
  "## CRITICAL: YOU ARE A TEXT GENERATOR FOR A VOICE SYSTEM",
  "Generate ONLY plain conversational text. No markdown. One or two short sentences per turn.",
  "",
  "## YOUR ROLE",
  "You are Nova in capture mode. Listen while the engineer describes a rocket fluid-network design.",
  "Do NOT ask clarifying questions. Do NOT interview them. Brief acknowledgments only, like 'Got it' or 'Understood'.",
  "",
  "## WHEN TO CALL FUNCTIONS",
  "When the engineer says they are done, finished, or that is correct, call submit_requirements once with a concise summary.",
  "If they gave a complete description without saying done, still call submit_requirements after their last substantive statement.",
  "",
  "## SUMMARY CONTENT",
  "The requirements summary must capture system type, propellants, pressures, tank volumes, durations, and constraints stated.",
].join("\n");

interface ConversationTurn {
  role: "user" | "agent";
  text: string;
}

type CopilotStatus = "idle" | "connecting" | "live" | "stopped";
type AgentActivity = "listening" | "thinking" | "speaking";
type Mode = "design" | "advise" | "dictate";

interface VoiceAgentCopilotProps {
  onStartDesign: (summary: string) => void;
  getDesignStatus: () => string;
  /* Populate the Chat tab requirements field (review before run). */
  onSendToChat: (text: string) => void;
  /* Advise mode: surface recommended design changes to the parent (panel). */
  onAdvise?: (extraction: DesignChangeExtraction) => void;
  /* Design mode narration: latest thing worth speaking, with a stable key for dedup.
     Return null when there is nothing new to say. */
  getDesignNarration?: () => { key: string; text: string } | null;
}

interface DeepgramFunctionCall {
  id?: string;
  name?: string;
  arguments?: string;
  client_side?: boolean;
}

interface DeepgramAgentMessage {
  type?: string;
  role?: string;
  content?: string;
  description?: string;
  message?: string;
  functions?: DeepgramFunctionCall[];
}

function getAudioContextCtor(): typeof AudioContext {
  if (typeof window === "undefined") {
    throw new Error("AudioContext is only available in the browser.");
  }
  return window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
}

function floatTo16BitPCM(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, input[i]));
    output[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return output;
}

function parseExtraction(args: Record<string, unknown>): DesignChangeExtraction {
  const summary = typeof args.summary === "string" ? args.summary : "";
  const rawChanges = Array.isArray(args.key_changes) ? args.key_changes : [];
  const key_changes: DesignChange[] = rawChanges.map((item) => {
    const obj = (item ?? {}) as Record<string, unknown>;
    const category = String(obj.category ?? "general") as DesignChange["category"];
    return {
      category: ["pressure", "geometry", "material", "constraint", "general"].includes(category)
        ? category
        : "general",
      description: String(obj.description ?? "").trim(),
      value:
        obj.value === null || obj.value === undefined || `${obj.value}`.trim() === ""
          ? null
          : (obj.value as string | number),
    };
  });
  return { summary, key_changes };
}

export function VoiceAgentCopilot({
  onStartDesign,
  getDesignStatus,
  onSendToChat,
  onAdvise,
  getDesignNarration,
}: VoiceAgentCopilotProps) {
  const [status, setStatus] = useState<CopilotStatus>("idle");
  const [activity, setActivity] = useState<AgentActivity>("listening");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [autoRun, setAutoRun] = useState(true);
  const [mode, setMode] = useState<Mode>("design");
  const [stagedSummary, setStagedSummary] = useState<string | null>(null);
  const [postConversationDraft, setPostConversationDraft] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [advice, setAdvice] = useState<DesignChangeExtraction | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const playbackCtxRef = useRef<AudioContext | null>(null);
  const playbackCursorRef = useRef(0);
  const scheduledSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const intentionalCloseRef = useRef(false);
  // Gate: only stream mic audio after the server confirms SettingsApplied.
  const sendingRef = useRef(false);
  const autoRunRef = useRef(true);
  const modeRef = useRef<Mode>("design");
  const activityRef = useRef<AgentActivity>("listening");
  const turnsRef = useRef<ConversationTurn[]>([]);
  const callbacksRef = useRef({ onStartDesign, getDesignStatus, onSendToChat, onAdvise, getDesignNarration });
  // Narration bookkeeping (design mode): a run is active and which verdict keys we've spoken.
  const runActiveRef = useRef(false);
  const spokenKeysRef = useRef<Set<string>>(new Set());
  const lastInjectKeyRef = useRef<string | null>(null);

  useEffect(() => {
    callbacksRef.current = { onStartDesign, getDesignStatus, onSendToChat, onAdvise, getDesignNarration };
  }, [onStartDesign, getDesignStatus, onSendToChat, onAdvise, getDesignNarration]);
  useEffect(() => {
    autoRunRef.current = autoRun;
  }, [autoRun]);
  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);
  useEffect(() => {
    activityRef.current = activity;
  }, [activity]);
  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);

  const stopPlayback = useCallback(() => {
    for (const source of scheduledSourcesRef.current) {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
    }
    scheduledSourcesRef.current = [];
    playbackCursorRef.current = 0;
  }, []);

  const enqueueAudio = useCallback((data: ArrayBuffer) => {
    const ctx = playbackCtxRef.current;
    if (!ctx || data.byteLength === 0) return;
    const int16 = new Int16Array(data);
    if (int16.length === 0) return;
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i += 1) {
      float32[i] = int16[i] / 0x8000;
    }
    const buffer = ctx.createBuffer(1, float32.length, OUTPUT_SAMPLE_RATE);
    buffer.copyToChannel(float32, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const startAt = Math.max(ctx.currentTime, playbackCursorRef.current);
    source.start(startAt);
    playbackCursorRef.current = startAt + buffer.duration;
    scheduledSourcesRef.current.push(source);
    source.onended = () => {
      scheduledSourcesRef.current = scheduledSourcesRef.current.filter((item) => item !== source);
    };
  }, []);

  const teardown = useCallback(
    (intentional: boolean) => {
      sendingRef.current = false;
      runActiveRef.current = false;
      intentionalCloseRef.current = intentional;

      const worklet = workletRef.current;
      if (worklet) {
        worklet.port.onmessage = null;
        try {
          worklet.disconnect();
        } catch {
          /* already disconnected */
        }
      }
      workletRef.current = null;

      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;

      const micCtx = micCtxRef.current;
      if (micCtx && micCtx.state !== "closed") {
        void micCtx.close();
      }
      micCtxRef.current = null;

      stopPlayback();
      const playbackCtx = playbackCtxRef.current;
      if (playbackCtx && playbackCtx.state !== "closed") {
        void playbackCtx.close();
      }
      playbackCtxRef.current = null;

      const ws = wsRef.current;
      if (ws && ws.readyState !== WebSocket.CLOSED) {
        try {
          ws.close();
        } catch {
          /* already closing */
        }
      }
      wsRef.current = null;
    },
    [stopPlayback]
  );

  const sendSettings = useCallback((ws: WebSocket) => {
    const activeMode = modeRef.current;
    const statusFn = {
      name: "check_design_status",
      description: "Call when the engineer asks how the design run is going.",
      parameters: { type: "object", properties: {}, required: [] },
    };
    const requirementsSummaryParam = {
      type: "object",
      properties: {
        requirements_summary: {
          type: "string",
          description:
            "Concise summary: system type, propellants, pressures, tank volumes, run duration, and constraints.",
        },
      },
      required: ["requirements_summary"],
    };

    let functions: unknown[];
    let prompt: string;
    let greeting: string;
    if (activeMode === "dictate") {
      prompt = DICTATE_PROMPT;
      greeting =
        "Describe the system you want to build. I won't ask questions — include propellants, pressures, volumes, and run time, then say you're done.";
      functions = [
        {
          name: "submit_requirements",
          description:
            "Call this when the engineer is done describing their design. Pass a concise plain-text requirements summary to send to the chat tab.",
          parameters: requirementsSummaryParam,
        },
        statusFn,
      ];
    } else if (activeMode === "advise") {
      prompt = ADVISE_PROMPT;
      greeting =
        "I'm Nova in review mode. Walk me through your design and I'll tell you what I'd change — I won't run anything.";
      functions = [
        {
          name: "advise_design_changes",
          description:
            "Call when you have a clear set of recommended design changes, or when the engineer asks what to change. Does NOT run anything.",
          parameters: {
            type: "object",
            properties: {
              summary: { type: "string", description: "One concise sentence summarizing the recommended direction." },
              key_changes: {
                type: "array",
                description: "The specific recommended design changes.",
                items: {
                  type: "object",
                  properties: {
                    category: {
                      type: "string",
                      enum: ["pressure", "geometry", "material", "constraint", "general"],
                    },
                    description: { type: "string", description: "Plain-English description of the change." },
                    value: { type: "string", description: "Specific number or spec if discussed, otherwise empty." },
                  },
                  required: ["category", "description"],
                },
              },
            },
            required: ["summary", "key_changes"],
          },
        },
      ];
    } else {
      prompt = DESIGN_PROMPT;
      greeting = "Hi, I'm Nova, your propulsion design assistant. Tell me what system you want to build and I'll run the simulation.";
      functions = [
        {
          name: "start_design_run",
          description:
            "Call to launch the design loop once requirements are gathered AND confirmed by the engineer. Pass a concise plain-text requirements summary.",
          parameters: requirementsSummaryParam,
        },
        statusFn,
      ];
    }

    const settings = {
      type: "Settings",
      audio: {
        input: { encoding: "linear16", sample_rate: INPUT_SAMPLE_RATE },
        output: { encoding: "linear16", sample_rate: OUTPUT_SAMPLE_RATE, container: "none" },
      },
      agent: {
        language: "en",
        listen: {
          provider: {
            type: "deepgram",
            model: "flux-general-en",
            version: "v2",
            keyterms: ROCKET_KEYTERMS,
            eot_threshold: 0.8,
            eot_timeout_ms: 8000,
          },
        },
        think: {
          provider: { type: "open_ai", model: "gpt-4o-mini", temperature: 0.5 },
          prompt,
          functions,
        },
        speak: {
          provider: { type: "deepgram", model: "aura-2-thalia-en" },
        },
        greeting,
      },
    };
    ws.send(JSON.stringify(settings));
  }, []);

  const endLiveConversation = useCallback(() => {
    const ws = wsRef.current;
    if (!sendingRef.current && (!ws || ws.readyState === WebSocket.CLOSED) && !streamRef.current) {
      return;
    }
    sendingRef.current = false;
    setStatus("stopped");
    setActivity("listening");
    teardown(true);
  }, [teardown]);

  // Kick off a design run WITHOUT ending the live conversation, so Nova can narrate.
  const launchDesignRun = useCallback((summary: string) => {
    const trimmed = summary.trim();
    if (!trimmed) return;
    spokenKeysRef.current = new Set();
    lastInjectKeyRef.current = null;
    runActiveRef.current = true;
    callbacksRef.current.onStartDesign(trimmed);
  }, []);

  const respondToFunctionCall = useCallback(
    (call: DeepgramFunctionCall) => {
      let content = "";
      let launch: string | null = null;
      try {
        const args = call.arguments ? (JSON.parse(call.arguments) as Record<string, unknown>) : {};
        if (call.name === "start_design_run") {
          const summary = String(args.requirements_summary ?? "").trim();
          if (!summary) {
            content = "I couldn't capture any requirements yet.";
          } else if (autoRunRef.current) {
            setPostConversationDraft(summary);
            launch = summary;
            content =
              "Starting the run now. The simulator is iterating, and I'll read you each verdict as it comes in.";
          } else {
            setStagedSummary(summary);
            setPostConversationDraft(summary);
            content =
              "I've put the requirements on screen for you to review. Edit them if you like, then press run design loop.";
          }
        } else if (call.name === "submit_requirements") {
          const summary = String(args.requirements_summary ?? "").trim();
          if (!summary) {
            content = "I couldn't capture any requirements yet.";
          } else {
            setPostConversationDraft(summary);
            callbacksRef.current.onSendToChat(summary);
            content = "I've sent the requirements to the chat tab for you to review.";
          }
        } else if (call.name === "advise_design_changes") {
          const extraction = parseExtraction(args);
          if (extraction.key_changes.length === 0 && !extraction.summary) {
            content = "I don't have concrete changes to recommend yet.";
          } else {
            setAdvice(extraction);
            callbacksRef.current.onAdvise?.(extraction);
            const spoken = extractionToRequirements(extraction);
            content = `Here are the changes I'd recommend. ${spoken}`;
          }
        } else if (call.name === "check_design_status") {
          content = callbacksRef.current.getDesignStatus();
        } else {
          content = "That action isn't available.";
        }
      } catch (exc) {
        Sentry.captureException(exc);
        content = "There was an error executing that action.";
      }

      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "FunctionCallResponse", id: call.id, name: call.name, content }));
      }
      // Launch AFTER responding to the function, and crucially WITHOUT tearing down
      // the socket — Nova keeps talking and narrates the run.
      if (launch) launchDesignRun(launch);
    },
    [launchDesignRun]
  );

  const handleAgentMessage = useCallback(
    (message: DeepgramAgentMessage) => {
      switch (message.type) {
        case "Welcome": {
          const ws = wsRef.current;
          if (ws) sendSettings(ws);
          break;
        }
        case "SettingsApplied": {
          sendingRef.current = true;
          setStatus("live");
          setActivity("listening");
          break;
        }
        case "ConversationText": {
          const text = (message.content ?? "").trim();
          if (!text) break;
          const role: ConversationTurn["role"] = message.role === "user" ? "user" : "agent";
          setTurns((prev) => [...prev, { role, text }]);
          break;
        }
        case "UserStartedSpeaking": {
          stopPlayback();
          setActivity("listening");
          break;
        }
        case "AgentThinking": {
          setActivity("thinking");
          break;
        }
        case "AgentStartedSpeaking": {
          setActivity("speaking");
          break;
        }
        case "AgentAudioDone": {
          setActivity("listening");
          break;
        }
        case "InjectionRefused": {
          // Narration was rejected (user mid-turn). Un-mark so we retry next tick.
          if (lastInjectKeyRef.current) {
            spokenKeysRef.current.delete(lastInjectKeyRef.current);
            lastInjectKeyRef.current = null;
          }
          break;
        }
        case "FunctionCallRequest": {
          for (const call of message.functions ?? []) {
            if (call.client_side) respondToFunctionCall(call);
          }
          break;
        }
        case "Error": {
          const detail = message.description ?? message.message ?? "Voice agent error";
          setError(detail);
          Sentry.captureException(new Error(`Deepgram Voice Agent error: ${detail}`));
          break;
        }
        default:
          break;
      }
    },
    [respondToFunctionCall, sendSettings, stopPlayback]
  );

  // KeepAlive + design-mode narration loops. Active only while the session is live;
  // both read refs so they never rebind the socket listeners.
  useEffect(() => {
    if (status !== "live") return;
    const keepAlive = window.setInterval(() => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "KeepAlive" }));
      }
    }, KEEPALIVE_MS);

    const narrate = window.setInterval(() => {
      if (modeRef.current !== "design" || !runActiveRef.current) return;
      // Only inject in a silent moment, else the server replies InjectionRefused.
      if (activityRef.current !== "listening") return;
      const next = callbacksRef.current.getDesignNarration?.();
      if (!next || spokenKeysRef.current.has(next.key)) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "InjectAgentMessage", message: next.text, behavior: "queue" }));
      spokenKeysRef.current.add(next.key);
      lastInjectKeyRef.current = next.key;
    }, NARRATION_POLL_MS);

    return () => {
      window.clearInterval(keepAlive);
      window.clearInterval(narrate);
    };
  }, [status]);

  const start = useCallback(async () => {
    const apiKey = import.meta.env.VITE_DEEPGRAM_API_KEY;
    if (!apiKey) {
      const message = "Missing VITE_DEEPGRAM_API_KEY. Add it to the repo-root .env (Vite envDir) to enable the voice copilot.";
      setError(message);
      Sentry.captureException(new Error(message));
      return;
    }

    setError(null);
    setTurns([]);
    setPostConversationDraft(null);
    setStagedSummary(null);
    setAdvice(null);
    setStatus("connecting");
    intentionalCloseRef.current = false;
    sendingRef.current = false;
    runActiveRef.current = false;
    spokenKeysRef.current = new Set();
    lastInjectKeyRef.current = null;
    playbackCursorRef.current = 0;

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (exc) {
      setError("Microphone access was denied. Enable mic permissions in your browser to talk to the copilot.");
      setStatus("idle");
      Sentry.captureException(exc);
      return;
    }
    streamRef.current = stream;

    try {
      const AudioContextCtor = getAudioContextCtor();
      const micCtx = new AudioContextCtor({ sampleRate: INPUT_SAMPLE_RATE });
      micCtxRef.current = micCtx;
      await micCtx.audioWorklet.addModule("/deepgram-recorder-worklet.js");
      await micCtx.resume();

      const source = micCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(micCtx, "deepgram-recorder");
      workletRef.current = worklet;
      const silentGain = micCtx.createGain();
      silentGain.gain.value = 0;
      source.connect(worklet);
      worklet.connect(silentGain);
      silentGain.connect(micCtx.destination);

      worklet.port.onmessage = (event: MessageEvent<Float32Array>) => {
        if (!sendingRef.current) return;
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const pcm = floatTo16BitPCM(event.data);
        ws.send(pcm.buffer);
      };

      const playbackCtx = new AudioContextCtor({ sampleRate: OUTPUT_SAMPLE_RATE });
      playbackCtxRef.current = playbackCtx;
      await playbackCtx.resume();
    } catch (exc) {
      setError("Could not initialize audio. Your browser may not support the required Web Audio features.");
      setStatus("idle");
      Sentry.captureException(exc);
      teardown(true);
      return;
    }

    // Deepgram browser auth uses the Sec-WebSocket-Protocol header: ["token", <key>].
    const ws = new WebSocket(AGENT_URL, ["token", apiKey]);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        enqueueAudio(event.data);
        return;
      }
      let message: DeepgramAgentMessage;
      try {
        message = JSON.parse(event.data as string) as DeepgramAgentMessage;
      } catch (exc) {
        Sentry.captureException(exc);
        return;
      }
      handleAgentMessage(message);
    };

    ws.onerror = (event) => {
      Sentry.captureException(new Error(`Deepgram Voice Agent WebSocket error: ${JSON.stringify(event)}`));
    };

    ws.onclose = () => {
      if (intentionalCloseRef.current) return;
      const draft = buildDraftFromTurns(turnsRef.current);
      if (draft) {
        setPostConversationDraft((current) => current ?? draft);
      }
      setError("Connection to the voice copilot dropped. Edit the transcript below and submit.");
      setStatus("stopped");
      teardown(true);
    };
  }, [enqueueAudio, handleAgentMessage, teardown]);

  const stop = useCallback(() => {
    const draft = buildDraftFromTurns(turnsRef.current);
    if (draft) {
      setPostConversationDraft((current) => current ?? draft);
    }
    setStatus("stopped");
    setActivity("listening");
    teardown(true);
  }, [teardown]);

  useEffect(() => {
    return () => {
      teardown(true);
    };
  }, [teardown]);

  const runStaged = () => {
    const summary = (stagedSummary ?? postConversationDraft ?? "").trim();
    if (!summary) return;
    callbacksRef.current.onStartDesign(summary);
    endLiveConversation();
    setStagedSummary(null);
  };

  const sendDraftToChat = () => {
    const text = (postConversationDraft ?? stagedSummary ?? "").trim();
    if (!text) return;
    callbacksRef.current.onSendToChat(text);
  };

  const summarizeDraftToChat = async () => {
    const transcript = buildTranscriptText(turnsRef.current);
    const source = transcript.trim() || (postConversationDraft ?? "").trim();
    if (!source) {
      setError("Nothing to summarize yet — talk to Nova first.");
      return;
    }
    setError(null);
    setSummarizing(true);
    try {
      const { requirements, rawFallback } = await summarizeTranscript(source);
      setPostConversationDraft(requirements);
      callbacksRef.current.onSendToChat(requirements);
      if (rawFallback) {
        setError("Could not parse structured changes — sent the raw transcript to chat instead.");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Summarization failed.");
      Sentry.captureException(exc);
    } finally {
      setSummarizing(false);
    }
  };

  const isActive = status === "live" || status === "connecting";
  const reviewText = stagedSummary ?? postConversationDraft ?? "";
  const showPostConversation = !isActive && (postConversationDraft !== null || turns.length > 0);
  const activityLabel =
    status === "connecting"
      ? "Connecting to Deepgram…"
      : activity === "thinking"
      ? "Nova is thinking…"
      : activity === "speaking"
      ? "Nova is speaking…"
      : "Listening…";

  return (
    <div className="voice-recorder copilot">
      <div className="voice-controls">
        {isActive ? (
          <button type="button" className="primary-action voice-stop" onClick={stop}>
            <Square size={16} />
            End conversation
          </button>
        ) : (
          <button type="button" className="primary-action" onClick={() => void start()}>
            <Mic size={16} />
            Talk to Nova
          </button>
        )}
      </div>

      {isActive && (
        <div className="voice-status">
          <span className={`voice-dot${status === "live" ? " is-live" : ""}`} />
          {activityLabel}
        </div>
      )}

      <fieldset className="copilot-mode" disabled={isActive}>
        <legend className="copilot-mode-label">Nova mode</legend>
        <label className="copilot-mode-option">
          <input type="radio" name="copilot-mode" checked={mode === "design"} onChange={() => setMode("design")} />
          Design — ask, confirm, run &amp; narrate
        </label>
        <label className="copilot-mode-option">
          <input type="radio" name="copilot-mode" checked={mode === "advise"} onChange={() => setMode("advise")} />
          Advise — discuss &amp; recommend (no run)
        </label>
        <label className="copilot-mode-option">
          <input type="radio" name="copilot-mode" checked={mode === "dictate"} onChange={() => setMode("dictate")} />
          Dictate — listen only, summarize to Chat
        </label>
      </fieldset>

      {mode === "design" && (
        <label className="checkbox-control copilot-autorun">
          <input
            type="checkbox"
            checked={autoRun}
            onChange={(event) => setAutoRun(event.target.checked)}
            disabled={isActive}
          />
          Run the design loop automatically (uncheck to review requirements first)
        </label>
      )}

      {advice && (
        <div className="copilot-advice">
          <span className="copilot-review-label">
            <Lightbulb size={13} /> Recommended changes (advisory — nothing was run)
          </span>
          {advice.summary && <p className="copilot-advice-summary">{advice.summary}</p>}
          <ul className="copilot-advice-list">
            {advice.key_changes.map((change, index) => (
              <li key={index}>
                <span className={`copilot-advice-tag tag-${change.category}`}>{change.category}</span>
                {change.description}
                {change.value !== null && change.value !== "" ? <em> ({change.value})</em> : null}
              </li>
            ))}
          </ul>
          <button type="button" className="primary-action" onClick={() => onSendToChat(extractionToRequirements(advice))}>
            <MessageSquare size={16} />
            Send to Chat
          </button>
        </div>
      )}

      {stagedSummary !== null && (
        <div className="copilot-review">
          <span className="copilot-review-label">Requirements to review</span>
          <textarea
            className="copilot-review-text"
            value={stagedSummary}
            onChange={(event) => {
              setStagedSummary(event.target.value);
              setPostConversationDraft(event.target.value);
            }}
            rows={5}
          />
          <button
            type="button"
            className="primary-action voice-summarize"
            onClick={runStaged}
            disabled={!stagedSummary.trim()}
          >
            <Play size={16} />
            Run design loop
          </button>
        </div>
      )}

      {showPostConversation && stagedSummary === null && (
        <div className="copilot-review">
          <span className="copilot-review-label">After conversation — edit and submit</span>
          <textarea
            className="copilot-review-text"
            value={postConversationDraft ?? ""}
            onChange={(event) => setPostConversationDraft(event.target.value)}
            rows={6}
            placeholder="Your spoken requirements appear here after you end the conversation."
          />
          <div className="copilot-review-actions">
            <button
              type="button"
              className="primary-action voice-summarize"
              onClick={() => void summarizeDraftToChat()}
              disabled={summarizing || !(postConversationDraft ?? "").trim()}
            >
              {summarizing ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
              Summarize to Chat
            </button>
            <button
              type="button"
              className="primary-action"
              onClick={sendDraftToChat}
              disabled={!(postConversationDraft ?? "").trim()}
            >
              <MessageSquare size={16} />
              Send to Chat
            </button>
            <button
              type="button"
              className="primary-action voice-summarize"
              onClick={runStaged}
              disabled={!reviewText.trim()}
            >
              <Play size={16} />
              Run design loop
            </button>
          </div>
        </div>
      )}

      <div className="copilot-transcript" aria-live="polite">
        {turns.length === 0 ? (
          <span className="voice-empty">
            {mode === "dictate"
              ? "Dictate mode: describe your full design without questions. End the conversation to edit and submit, or say you're done."
              : mode === "advise"
              ? "Advise mode: talk through your design with Nova. She'll recommend changes out loud and on screen — she won't run anything."
              : "Start a conversation and describe the system you want to design. Nova will confirm, run the simulation, and read the results aloud."}
          </span>
        ) : (
          turns.map((turn, index) => (
            <div key={index} className={`copilot-turn ${turn.role}`}>
              <span className="copilot-avatar">{turn.role === "user" ? <User size={13} /> : <Bot size={13} />}</span>
              <p>{turn.text}</p>
            </div>
          ))
        )}
      </div>

      {error && (
        <div className="voice-error" role="status">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
