import { useCallback, useEffect, useRef, useState } from "react";
import * as Sentry from "@sentry/react";
import { AlertTriangle, Loader2, Mic, Sparkles, Square } from "lucide-react";

/* Voice-driven requirements capture.
   - Streams mic audio to Deepgram (nova-3) over a WebSocket for live transcription.
   - Summarizes the final transcript via Anthropic into structured design changes.
   All failure modes are surfaced inline (never via alert) and reported to Sentry. */

const DEEPGRAM_URL =
  "wss://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&numerals=true&interim_results=true";
const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_MODEL = "claude-sonnet-4-6";
const AUDIO_CHUNK_MS = 250;
const WS_RETRY_DELAY_MS = 2000;

const SUMMARY_SYSTEM_PROMPT =
  "You are a rocket propulsion design assistant. Extract all design change requests " +
  "from this conversation transcript. Return a JSON array where each item has: " +
  "category (one of: pressure, geometry, material, constraint, general), " +
  "description (plain english), and value (specific number or spec if mentioned, otherwise null). " +
  "Respond with ONLY the raw JSON array and nothing else — no reasoning, explanations, " +
  "commentary, preamble, or markdown code fences.";

export type DesignChangeCategory = "pressure" | "geometry" | "material" | "constraint" | "general";

export interface DesignChange {
  category: DesignChangeCategory;
  description: string;
  value: string | number | null;
}

interface ConversationRecorderProps {
  onChangesExtracted: (changes: DesignChange[]) => void;
  /* Fallback hook used when Anthropic returns malformed JSON: the caller can still
     populate the requirements field with the raw transcript. */
  onRawTranscript?: (transcript: string) => void;
}

type RecorderStatus = "idle" | "connecting" | "recording" | "stopped";

interface DeepgramAlternative {
  transcript?: string;
}

interface DeepgramMessage {
  type?: string;
  is_final?: boolean;
  channel?: { alternatives?: DeepgramAlternative[] };
}

function pickTranscript(message: DeepgramMessage): string {
  return message.channel?.alternatives?.[0]?.transcript?.trim() ?? "";
}

/* Anthropic may wrap the JSON array in prose or a ```json fence. Pull the first
   bracketed array out before parsing so well-formed answers aren't rejected. */
function extractJsonArray(raw: string): DesignChange[] {
  const start = raw.indexOf("[");
  const end = raw.lastIndexOf("]");
  if (start === -1 || end === -1 || end < start) {
    throw new Error("No JSON array found in Anthropic response");
  }
  const parsed = JSON.parse(raw.slice(start, end + 1));
  if (!Array.isArray(parsed)) {
    throw new Error("Anthropic response was not a JSON array");
  }
  return parsed as DesignChange[];
}

export function ConversationRecorder({ onChangesExtracted, onRawTranscript }: ConversationRecorderProps) {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  /* Distinguishes an intentional stop() from an unexpected socket drop so we only
     auto-retry on genuine failures. */
  const intentionalCloseRef = useRef(false);
  const retriedRef = useRef(false);
  /* The latest full transcript, kept in a ref so socket callbacks (and summarize)
     read the current value without being re-created on every word. */
  const finalTranscriptRef = useRef("");
  /* When the user stops, we auto-summarize once Deepgram has flushed its final
     results. These refs let the socket's close handler trigger that without
     creating a render-time dependency on summarize(). */
  const pendingSummarizeRef = useRef(false);
  const summarizeRef = useRef<() => void>(() => {});

  const teardownAudio = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        /* recorder already stopped */
      }
    }
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const closeSocket = useCallback((intentional: boolean) => {
    intentionalCloseRef.current = intentional;
    const ws = wsRef.current;
    if (ws && ws.readyState !== WebSocket.CLOSED) {
      try {
        ws.close();
      } catch {
        /* socket already closing */
      }
    }
    wsRef.current = null;
  }, []);

  // Connects to Deepgram and starts streaming mic audio. Extracted so the
  // unexpected-close handler can re-invoke it once for the auto-retry.
  const startStreaming = useCallback(async () => {
    const apiKey = import.meta.env.VITE_DEEPGRAM_API_KEY;
    if (!apiKey) {
      const message = "Missing VITE_DEEPGRAM_API_KEY. Add it to your .env file to enable voice capture.";
      setError(message);
      setStatus("idle");
      Sentry.captureException(new Error(message));
      return;
    }

    setError(null);
    setStatus("connecting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (exc) {
      // Mic permission denied (or no device): inline message only, no alert.
      setError("Microphone access was denied. Enable mic permissions in your browser to record.");
      setStatus("idle");
      Sentry.captureException(exc);
      return;
    }
    streamRef.current = stream;

    // Deepgram browser auth uses the Sec-WebSocket-Protocol header: ["token", <key>].
    const ws = new WebSocket(DEEPGRAM_URL, ["token", apiKey]);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      // Guard against a race where the socket opens after the user already stopped.
      if (intentionalCloseRef.current) return;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0 && ws.readyState === WebSocket.OPEN) {
          ws.send(event.data);
        }
      };
      recorder.start(AUDIO_CHUNK_MS);
      setStatus("recording");
    };

    ws.onmessage = (event) => {
      let message: DeepgramMessage;
      try {
        message = JSON.parse(event.data as string) as DeepgramMessage;
      } catch (exc) {
        Sentry.captureException(exc);
        return;
      }
      const transcript = pickTranscript(message);
      if (!transcript) return;
      if (message.is_final) {
        // Only final results are committed to the durable transcript.
        const next = `${finalTranscriptRef.current}${finalTranscriptRef.current ? " " : ""}${transcript}`;
        finalTranscriptRef.current = next;
        setFinalTranscript(next);
        setInterimTranscript("");
      } else {
        setInterimTranscript(transcript);
      }
    };

    ws.onerror = (event) => {
      Sentry.captureException(new Error(`Deepgram WebSocket error: ${JSON.stringify(event)}`));
    };

    ws.onclose = () => {
      teardownAudio();
      if (intentionalCloseRef.current) {
        // Graceful stop: Deepgram has flushed its final results, so kick off
        // summarization automatically (no button click needed).
        if (pendingSummarizeRef.current) {
          pendingSummarizeRef.current = false;
          setStatus("stopped");
          summarizeRef.current();
        }
        return;
      }
      // Unexpected close: auto-retry once after a short delay, then surface an error.
      if (!retriedRef.current) {
        retriedRef.current = true;
        setError("Connection to Deepgram dropped. Reconnecting…");
        setStatus("connecting");
        window.setTimeout(() => {
          void startStreaming();
        }, WS_RETRY_DELAY_MS);
      } else {
        setError("Lost connection to Deepgram. Please stop and try recording again.");
        setStatus("stopped");
        Sentry.captureException(new Error("Deepgram WebSocket closed unexpectedly after retry"));
      }
    };
  }, [teardownAudio]);

  const start = useCallback(() => {
    retriedRef.current = false;
    intentionalCloseRef.current = false;
    setFinalTranscript("");
    setInterimTranscript("");
    finalTranscriptRef.current = "";
    void startStreaming();
  }, [startStreaming]);

  const stop = useCallback(() => {
    // Stop sending audio, but keep the socket open briefly so Deepgram can
    // return any pending final words before we auto-summarize.
    teardownAudio();
    setInterimTranscript("");
    setStatus("stopped");
    intentionalCloseRef.current = true;
    pendingSummarizeRef.current = true;

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      // Ask Deepgram to flush remaining results, then close on its own.
      ws.send(JSON.stringify({ type: "CloseStream" }));
      // Safety net: if Deepgram doesn't close promptly, force it so summarize still runs.
      window.setTimeout(() => {
        if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
          closeSocket(true);
        } else if (pendingSummarizeRef.current) {
          pendingSummarizeRef.current = false;
          summarizeRef.current();
        }
      }, 1500);
    } else {
      // No live socket — summarize whatever we already have.
      closeSocket(true);
      if (pendingSummarizeRef.current) {
        pendingSummarizeRef.current = false;
        summarizeRef.current();
      }
    }
  }, [teardownAudio, closeSocket]);

  const summarize = useCallback(async () => {
    const transcript = finalTranscriptRef.current.trim();
    if (!transcript) {
      setError("Nothing to summarize yet — record some conversation first.");
      return;
    }

    const apiKey = import.meta.env.VITE_ANTHROPIC_API_KEY;
    if (!apiKey) {
      const message = "Missing VITE_ANTHROPIC_API_KEY. Add it to your .env file to enable summarization.";
      setError(message);
      Sentry.captureException(new Error(message));
      return;
    }

    setError(null);
    setSummarizing(true);
    try {
      const response = await fetch(ANTHROPIC_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          // Required for calling Anthropic directly from a browser.
          "anthropic-dangerous-direct-browser-access": "true"
        },
        body: JSON.stringify({
          model: ANTHROPIC_MODEL,
          max_tokens: 1024,
          system: SUMMARY_SYSTEM_PROMPT,
          messages: [{ role: "user", content: transcript }]
        })
      });

      if (!response.ok) {
        throw new Error(`Anthropic API returned ${response.status}`);
      }

      const payload = (await response.json()) as { content?: Array<{ text?: string }> };
      const raw = payload.content?.map((block) => block.text ?? "").join("") ?? "";

      try {
        const changes = extractJsonArray(raw);
        onChangesExtracted(changes);
      } catch (parseExc) {
        // Malformed JSON: fall back to the raw transcript so the requirements
        // field is still populated and the agent loop can proceed.
        Sentry.captureException(parseExc);
        setError("Could not parse structured changes — using the raw transcript instead.");
        onRawTranscript?.(transcript);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Summarization failed.");
      Sentry.captureException(exc);
      onRawTranscript?.(transcript);
    } finally {
      setSummarizing(false);
    }
  }, [onChangesExtracted, onRawTranscript]);

  // Keep a stable ref to the latest summarize() so the socket close handler can
  // auto-trigger it without re-creating the connection logic.
  useEffect(() => {
    summarizeRef.current = () => {
      void summarize();
    };
  }, [summarize]);

  // Clean up audio + socket if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      teardownAudio();
      closeSocket(true);
    };
  }, [teardownAudio, closeSocket]);

  const isRecording = status === "recording";
  const isConnecting = status === "connecting";
  const hasTranscript = finalTranscript.trim().length > 0;

  return (
    <div className="voice-recorder">
      <div className="voice-controls">
        {isRecording || isConnecting ? (
          <button type="button" className="primary-action voice-stop" onClick={stop}>
            <Square size={16} />
            {isConnecting ? "Connecting…" : "Stop recording"}
          </button>
        ) : (
          <button type="button" className="primary-action" onClick={start}>
            <Mic size={16} />
            Start recording
          </button>
        )}
      </div>

      {(isRecording || isConnecting) && (
        <div className="voice-status">
          <span className={`voice-dot${isRecording ? " is-live" : ""}`} />
          {isRecording ? "Listening…" : "Connecting to Deepgram…"}
        </div>
      )}

      <div className="voice-transcript" aria-live="polite">
        {hasTranscript || interimTranscript ? (
          <p>
            {finalTranscript}
            {interimTranscript && (
              <span className="voice-interim">{finalTranscript ? " " : ""}{interimTranscript}</span>
            )}
          </p>
        ) : (
          <span className="voice-empty">
            Transcript will appear here as you speak. Describe the design changes you want.
          </span>
        )}
      </div>

      {summarizing && (
        <div className="voice-status">
          <Loader2 size={16} className="spin" />
          Extracting design changes…
        </div>
      )}

      {error && (
        <div className="voice-error" role="status">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      )}

      {/* Summarization runs automatically when recording stops. This manual
          button only appears as a retry path if something went wrong. */}
      {error && !summarizing && !isRecording && !isConnecting && hasTranscript && (
        <button
          type="button"
          className="primary-action voice-summarize"
          onClick={() => void summarize()}
        >
          <Sparkles size={16} />
          Summarize again
        </button>
      )}
    </div>
  );
}
