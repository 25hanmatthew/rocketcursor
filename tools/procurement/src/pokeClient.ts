export const POKE_SOURCE = "rocketcursor-procurement";
export const DEFAULT_POKE_API_URL = "https://poke.com/api/v1/inbound/api-message";

export type PokeInboundPayload = {
  message: string;
  source: string;
  run_id?: string;
  user_approved_external_action?: boolean;
  metadata?: Record<string, unknown>;
};

export async function postToPoke(
  payload: PokeInboundPayload
): Promise<{ ok: boolean; data: unknown }> {
  const apiKey = process.env.POKE_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("Missing POKE_API_KEY");
  }

  const apiUrl = process.env.POKE_API_URL?.trim() || DEFAULT_POKE_API_URL;

  const response = await fetch(apiUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  const text = await response.text();
  let data: unknown = text;
  try {
    data = JSON.parse(text);
  } catch {
    // keep raw text
  }

  if (!response.ok) {
    throw new Error(`Poke API ${response.status}: ${text}`);
  }

  return { ok: true, data };
}

export function buildSupplierLoginChallengeMessage(params: {
  supplierName: string;
  liveViewUrl: string;
  runId?: string;
}): string {
  const runLine = params.runId ? `\nRun ID: ${params.runId}` : "";
  return `[${POKE_SOURCE}] ${params.supplierName} login needs 2FA or CAPTCHA.

Open this Browserbase live view and complete the challenge in the browser:
${params.liveViewUrl}

Do not share credentials in chat. Complete the challenge in the live browser only.
The procurement run will resume automatically once you are signed in.${runLine}

Reply here when done (optional — the run polls for login state).`;
}
