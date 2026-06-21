const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_MODEL = "claude-sonnet-4-6";

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

export function changesToRequirements(changes: DesignChange[]): string {
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

export function buildTranscriptText(turns: Array<{ role: "user" | "agent"; text: string }>): string {
  if (turns.length === 0) return "";
  return turns.map((turn) => `${turn.role === "user" ? "Engineer" : "Nova"}: ${turn.text}`).join("\n");
}

export function buildDraftFromTurns(turns: Array<{ role: "user" | "agent"; text: string }>): string {
  const userOnly = turns
    .filter((turn) => turn.role === "user")
    .map((turn) => turn.text.trim())
    .filter(Boolean)
    .join(" ");
  if (userOnly) return userOnly;
  return buildTranscriptText(turns);
}

export async function summarizeTranscript(transcript: string): Promise<{ requirements: string; rawFallback?: string }> {
  const trimmed = transcript.trim();
  if (!trimmed) {
    throw new Error("Nothing to summarize yet.");
  }

  const apiKey = import.meta.env.VITE_ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("Missing VITE_ANTHROPIC_API_KEY. Add it to ui/frontend/.env to enable summarization.");
  }

  const response = await fetch(ANTHROPIC_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify({
      model: ANTHROPIC_MODEL,
      max_tokens: 1024,
      system: SUMMARY_SYSTEM_PROMPT,
      messages: [{ role: "user", content: trimmed }],
    }),
  });

  if (!response.ok) {
    throw new Error(`Anthropic API returned ${response.status}`);
  }

  const payload = (await response.json()) as { content?: Array<{ text?: string }> };
  const raw = payload.content?.map((block) => block.text ?? "").join("") ?? "";

  try {
    return { requirements: changesToRequirements(extractJsonArray(raw)) };
  } catch {
    return { requirements: trimmed, rawFallback: trimmed };
  }
}
