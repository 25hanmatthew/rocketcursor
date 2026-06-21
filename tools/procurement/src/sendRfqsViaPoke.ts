import fs from "node:fs";
import path from "node:path";
import { POKE_SOURCE, postToPoke } from "./pokeClient.js";

export type RfqDraftRecord = {
  item: string;
  supplier: string;
  partNumber?: string | null;
  productUrl: string;
  draftPath: string;
  approvalRequired?: boolean;
  sent?: boolean;
  transport?: "email" | "portal";
};

export type RfqSendResult = {
  item: string;
  supplier: string;
  partNumber: string | null;
  recipientEmail: string;
  subject: string;
  dryRun: boolean;
  /** How the send was triggered: direct MCP tool call, or Poke inbound API handoff. */
  transport: "mcp" | "poke" | "dry-run";
  /** True only when the MCP server confirmed the SMTP send. */
  emailSent: boolean;
  /** Poke inbound API accepted the handoff (not proof the email was sent). */
  pokeDelivered: boolean;
  pokeResponse?: unknown;
  error?: string;
  sentAt: string;
};

type PreparedRfq = {
  draft: RfqDraftRecord;
  subject: string;
  body: string;
  draftFile: string;
};

type PokeHandoffPayload = {
  message: string;
  source: string;
  run_id: string;
  user_approved_external_action: boolean;
  metadata: {
    runId: string;
    recipientEmail: string;
    items: string[];
    mode: "test";
  };
};

function isDryRun(): boolean {
  const value = process.env.RFQ_DRY_RUN?.trim().toLowerCase();
  return value !== "false" && value !== "0";
}

function resolveTestEmail(): string {
  const email = process.env.RFQ_TEST_EMAIL?.trim();
  if (!email) {
    throw new Error("Missing RFQ_TEST_EMAIL (all test sends route to this address)");
  }
  return email;
}

function parseSubject(rfqText: string): string {
  const match = rfqText.match(/^Subject:\s*(.+)$/m);
  return match?.[1]?.trim() ?? "RFQ Request";
}

function extractRfqBody(rfqText: string): string {
  return rfqText.replace(/^Subject:.*\n+/m, "").trim();
}

function mcpConnectionName(): string {
  return process.env.POKE_MCP_CONNECTION?.trim() || "RocketCursor Procurement";
}

function buildEmailObjects(params: {
  recipientEmail: string;
  rfqs: PreparedRfq[];
}): Array<{ to: string; subject: string; body: string }> {
  return params.rfqs.map((rfq) => ({
    to: params.recipientEmail,
    subject: rfq.subject,
    body: rfq.body
  }));
}

function buildPokeMessage(params: {
  runId: string;
  recipientEmail: string;
  rfqs: PreparedRfq[];
}): string {
  const connection = mcpConnectionName();
  const emails = buildEmailObjects(params);

  return `[${POKE_SOURCE}] Send ${params.rfqs.length} test RFQ email(s) now.

Use the "${connection}" integration's send_rfq_emails tool with the emails array below.
Do NOT email suppliers. Send only to ${params.recipientEmail}.
User approved this send via rocketcursor (RFQ_DRY_RUN=false).

Run ID: ${params.runId}

emails = ${JSON.stringify(emails, null, 2)}

After the tool returns, reply in iMessage confirming each email was sent.`;
}

function buildPokeHandoff(params: {
  runId: string;
  recipientEmail: string;
  rfqs: PreparedRfq[];
  dryRun: boolean;
}): PokeHandoffPayload {
  return {
    message: buildPokeMessage(params),
    source: POKE_SOURCE,
    run_id: params.runId,
    user_approved_external_action: !params.dryRun,
    metadata: {
      runId: params.runId,
      recipientEmail: params.recipientEmail,
      items: params.rfqs.map((row) => row.draft.item),
      mode: "test"
    }
  };
}

function resolveDraftPath(outputDir: string, draftPath: string): string {
  if (path.isAbsolute(draftPath) && fs.existsSync(draftPath)) {
    return draftPath;
  }

  const candidates = [
    path.resolve(outputDir, draftPath),
    path.resolve(outputDir, "rfqs", path.basename(draftPath)),
    path.resolve(process.cwd(), draftPath)
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return candidates[0];
}

async function postToPokeHandoff(payload: PokeHandoffPayload): Promise<{ ok: boolean; data: unknown }> {
  return postToPoke(payload);
}

type McmpEmailResult = { ok: boolean; to?: string; subject?: string; error?: string };

/**
 * Call the MCP server's send_rfq_emails tool directly over HTTP (JSON-RPC).
 * The MCP server performs the actual SMTP send, so this is fully automatic.
 */
async function sendViaMcp(
  serverUrl: string,
  emails: Array<{ to: string; subject: string; body: string }>
): Promise<{ ok: boolean; count: number; results: McmpEmailResult[] }> {
  const body = {
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: { name: "send_rfq_emails", arguments: { emails } }
  };

  const response = await fetch(serverUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      "ngrok-skip-browser-warning": "1"
    },
    body: JSON.stringify(body)
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`MCP server ${response.status}: ${text}`);
  }

  // FastMCP streams the JSON-RPC result as Server-Sent Events: a line beginning
  // with "data:" holds the JSON payload.
  const dataLine = text
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.startsWith("data:"));
  const jsonText = dataLine ? dataLine.slice("data:".length).trim() : text.trim();

  let parsed: unknown;
  try {
    parsed = JSON.parse(jsonText);
  } catch {
    throw new Error(`Could not parse MCP response: ${text}`);
  }

  const rpc = parsed as {
    error?: { message?: string };
    result?: { structuredContent?: { ok?: boolean; count?: number; results?: McmpEmailResult[] } };
  };

  if (rpc.error) {
    throw new Error(`MCP tool error: ${rpc.error.message ?? JSON.stringify(rpc.error)}`);
  }

  const structured = rpc.result?.structuredContent;
  if (!structured) {
    throw new Error(`MCP response missing structuredContent: ${jsonText}`);
  }

  return {
    ok: Boolean(structured.ok),
    count: structured.count ?? (structured.results?.length ?? 0),
    results: structured.results ?? []
  };
}

export async function sendRfqsViaPoke(outputDir: string) {
  const dryRun = isDryRun();
  const recipientEmail = resolveTestEmail();
  const runId = path.basename(path.resolve(outputDir));

  const draftsPath = path.join(outputDir, "rfq_drafts.json");
  if (!fs.existsSync(draftsPath)) {
    throw new Error(`Missing rfq_drafts.json in ${outputDir}`);
  }

  const drafts = JSON.parse(fs.readFileSync(draftsPath, "utf-8")) as RfqDraftRecord[];
  const emailDrafts = drafts.filter((draft) => (draft.transport ?? "email") === "email");
  if (emailDrafts.length === 0) {
    return {
      ok: true,
      dryRun,
      recipientEmail,
      results: [] as RfqSendResult[],
      message: drafts.length
        ? "No email RFQ drafts to send (portal transport only)"
        : "No RFQ-eligible drafts to send"
    };
  }

  const results: RfqSendResult[] = [];
  const prepared: PreparedRfq[] = [];
  const plannedHandoffs: PokeHandoffPayload[] = [];

  for (const draft of emailDrafts) {
    const draftFile = resolveDraftPath(outputDir, draft.draftPath);

    if (!fs.existsSync(draftFile)) {
      results.push({
        item: draft.item,
        supplier: draft.supplier,
        partNumber: draft.partNumber ?? null,
        recipientEmail,
        subject: "",
        dryRun,
        transport: dryRun ? "dry-run" : "mcp",
        emailSent: false,
        pokeDelivered: false,
        error: `Draft file not found: ${draftFile}`,
        sentAt: new Date().toISOString()
      });
      continue;
    }

    const rfqText = fs.readFileSync(draftFile, "utf-8");
    prepared.push({
      draft,
      subject: parseSubject(rfqText),
      body: extractRfqBody(rfqText),
      draftFile
    });
  }

  if (prepared.length > 0) {
    const handoff = buildPokeHandoff({
      runId,
      recipientEmail,
      rfqs: prepared,
      dryRun
    });

    const mcpServerUrl = process.env.MCP_SERVER_URL?.trim();

    if (dryRun) {
      plannedHandoffs.push(handoff);
      for (const rfq of prepared) {
        results.push({
          item: rfq.draft.item,
          supplier: rfq.draft.supplier,
          partNumber: rfq.draft.partNumber ?? null,
          recipientEmail,
          subject: rfq.subject,
          dryRun: true,
          transport: "dry-run",
          emailSent: false,
          pokeDelivered: true,
          sentAt: new Date().toISOString()
        });
      }
    } else if (mcpServerUrl) {
      // Preferred automatic path: call the MCP server's send tool directly.
      try {
        const mcp = await sendViaMcp(
          mcpServerUrl,
          prepared.map((rfq) => ({ to: recipientEmail, subject: rfq.subject, body: rfq.body }))
        );
        prepared.forEach((rfq, index) => {
          const row = mcp.results[index];
          const sent = row ? Boolean(row.ok) : mcp.ok;
          results.push({
            item: rfq.draft.item,
            supplier: rfq.draft.supplier,
            partNumber: rfq.draft.partNumber ?? null,
            recipientEmail,
            subject: rfq.subject,
            dryRun: false,
            transport: "mcp",
            emailSent: sent,
            pokeDelivered: false,
            pokeResponse: row,
            error: row && !row.ok ? row.error : undefined,
            sentAt: new Date().toISOString()
          });
        });
      } catch (err) {
        for (const rfq of prepared) {
          results.push({
            item: rfq.draft.item,
            supplier: rfq.draft.supplier,
            partNumber: rfq.draft.partNumber ?? null,
            recipientEmail,
            subject: rfq.subject,
            dryRun: false,
            transport: "mcp",
            emailSent: false,
            pokeDelivered: false,
            error: String(err),
            sentAt: new Date().toISOString()
          });
        }
      }
    } else {
      // Fallback: hand off to Poke's inbound API (requires the agent to act).
      try {
        const poke = await postToPokeHandoff(handoff);
        for (const rfq of prepared) {
          results.push({
            item: rfq.draft.item,
            supplier: rfq.draft.supplier,
            partNumber: rfq.draft.partNumber ?? null,
            recipientEmail,
            subject: rfq.subject,
            dryRun: false,
            transport: "poke",
            emailSent: false,
            pokeDelivered: true,
            pokeResponse: poke.data,
            sentAt: new Date().toISOString()
          });
        }
      } catch (err) {
        for (const rfq of prepared) {
          results.push({
            item: rfq.draft.item,
            supplier: rfq.draft.supplier,
            partNumber: rfq.draft.partNumber ?? null,
            recipientEmail,
            subject: rfq.subject,
            dryRun: false,
            transport: "poke",
            emailSent: false,
            pokeDelivered: false,
            error: String(err),
            sentAt: new Date().toISOString()
          });
        }
      }
    }
  }

  const usedMcp = results.some((row) => row.transport === "mcp");
  const emailSent = results.length > 0 && results.every((row) => row.emailSent);
  const payload = {
    ok: dryRun
      ? true
      : usedMcp
        ? emailSent
        : results.every((row) => row.pokeDelivered),
    dryRun,
    recipientEmail,
    runId,
    sentAt: new Date().toISOString(),
    transport: dryRun ? "dry-run" : usedMcp ? "mcp" : "poke",
    emailSent: !dryRun && emailSent,
    note: usedMcp
      ? "emailSent reflects the MCP server's SMTP result. Confirm in the recipient inbox."
      : "Poke handoff only. Set MCP_SERVER_URL to send automatically via the MCP server, or paste poke_mcp_instruction.txt into iMessage.",
    results
  };

  fs.writeFileSync(
    path.join(outputDir, dryRun ? "rfq_send_plan.json" : "rfq_sent.json"),
    JSON.stringify(payload, null, 2)
  );

  if (prepared.length > 0) {
    const instruction = buildPokeMessage({ runId, recipientEmail, rfqs: prepared });
    fs.writeFileSync(path.join(outputDir, "poke_mcp_instruction.txt"), instruction);
  }

  if (dryRun) {
    fs.writeFileSync(
      path.join(outputDir, "rfq_send_plan_messages.json"),
      JSON.stringify(plannedHandoffs, null, 2)
    );
  }

  const summaryPath = path.join(outputDir, "procurement_summary.json");
  if (fs.existsSync(summaryPath)) {
    const summary = JSON.parse(fs.readFileSync(summaryPath, "utf-8"));
    summary.rfqSend = payload;
    summary.sent = payload.emailSent;
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
  }

  return payload;
}
