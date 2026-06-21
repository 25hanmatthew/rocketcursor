import { Browserbase } from "@browserbasehq/sdk";
import { Stagehand } from "@browserbasehq/stagehand";
import fs from "node:fs";
import path from "node:path";
import {
  BOM,
  QuoteConfirmationSchema,
  SupplierCandidate
} from "./schemas.js";
import { isRfqEligibleCandidate } from "./scoring.js";
import { createStagehandSession } from "./stagehandSession.js";
import {
  ensureLoggedIn,
  loginFailureReasonMessage
} from "./supplierAuth.js";
import {
  getSupplierTarget,
  resolveSupplierQuoteUrl,
  supplierSupportsPortalQuote,
  SupplierTarget
} from "./supplierTargets.js";

export type PortalQuoteResult = {
  item: string;
  supplier: string;
  partNumber: string | null;
  productUrl: string;
  transport: "portal";
  autoSubmitted: boolean;
  ok: boolean;
  quoteStatus?: string;
  quoteConfirmation?: string | null;
  quotedPrice?: string | null;
  quotedLeadTime?: string | null;
  error?: string;
  submittedAt: string;
};

function quoteAutoSubmitEnabled(): boolean {
  return process.env.QUOTE_AUTO_SUBMIT?.trim().toLowerCase() === "true";
}

function stagehandPage(stagehand: Stagehand) {
  return stagehand.context.pages()[0]!;
}

async function submitPortalQuoteForCandidate(params: {
  bb: Browserbase;
  stagehand: Stagehand;
  supplier: SupplierTarget;
  item: {
    item: string;
    quantity: number;
    requirements: Record<string, unknown>;
  };
  candidate: SupplierCandidate;
  runId?: string;
}): Promise<PortalQuoteResult> {
  const { bb, stagehand, supplier, item, candidate, runId } = params;
  const autoSubmit = quoteAutoSubmitEnabled();
  const quoteUrl = resolveSupplierQuoteUrl(
    supplier,
    candidate.partNumber,
    candidate.productUrl
  );
  const page = stagehandPage(stagehand);
  const submittedAt = new Date().toISOString();

  try {
    await page.goto(quoteUrl);

    await stagehand.act(
      "Add this item to the quote request, cart, or request-a-quote flow if available",
      { page }
    );

    await stagehand.act("Open the request-a-quote or quote submission form if it is not already visible", {
      page
    });

    await stagehand.act("Fill the quantity field with %quantity%", {
      page,
      variables: {
        quantity: {
          value: String(item.quantity),
          description: "BOM quantity to quote"
        }
      }
    });

    if (autoSubmit) {
      await stagehand.act("Submit the quote request", { page });
    }

    const extracted = await stagehand.extract(
      autoSubmit
        ? "Extract the quote or RFQ confirmation number and any quoted price and lead time shown after submission."
        : "Extract any draft quote confirmation number, quoted price, and lead time visible on the quote form without submitting.",
      QuoteConfirmationSchema,
      { page }
    );

    const parsed = QuoteConfirmationSchema.safeParse(extracted);
    const confirmation = parsed.success ? parsed.data : {};

    return {
      item: item.item,
      supplier: candidate.supplier,
      partNumber: candidate.partNumber,
      productUrl: quoteUrl,
      transport: "portal",
      autoSubmitted: autoSubmit,
      ok: true,
      quoteStatus:
        confirmation.quoteStatus ??
        (autoSubmit ? "submitted" : "pending_review"),
      quoteConfirmation: confirmation.confirmationNumber ?? null,
      quotedPrice: confirmation.quotedPrice ?? null,
      quotedLeadTime: confirmation.quotedLeadTime ?? null,
      submittedAt
    };
  } catch (err) {
    return {
      item: item.item,
      supplier: candidate.supplier,
      partNumber: candidate.partNumber,
      productUrl: quoteUrl,
      transport: "portal",
      autoSubmitted: autoSubmit,
      ok: false,
      quoteStatus: "failed",
      error: String(err),
      submittedAt
    };
  }
}

export async function submitPortalQuotes(
  bb: Browserbase,
  bom: BOM,
  outputDir: string,
  runId?: string
) {
  const results: PortalQuoteResult[] = [];
  const sessions = new Map<string, Stagehand>();

  try {
    for (const item of bom.items) {
      const candidate = (item.candidates ?? []).find(isRfqEligibleCandidate) as
        | SupplierCandidate
        | undefined;
      if (!candidate) continue;

      const supplier = getSupplierTarget(candidate.supplier);
      if (!supplier || !supplierSupportsPortalQuote(supplier)) {
        continue;
      }

      let stagehand = sessions.get(supplier.name);
      if (!stagehand) {
        stagehand = await createStagehandSession(supplier);
        const loginResult = await ensureLoggedIn({
          bb,
          stagehand,
          supplier,
          runId: runId ?? path.basename(outputDir)
        });

        if (!loginResult.ok && supplier.requiresLogin) {
          results.push({
            item: item.item,
            supplier: candidate.supplier,
            partNumber: candidate.partNumber,
            productUrl: candidate.productUrl,
            transport: "portal",
            autoSubmitted: quoteAutoSubmitEnabled(),
            ok: false,
            quoteStatus: "failed",
            error: loginFailureReasonMessage(loginResult.reason),
            submittedAt: new Date().toISOString()
          });
          await stagehand.close();
          continue;
        }

        sessions.set(supplier.name, stagehand);
      }

      results.push(
        await submitPortalQuoteForCandidate({
          bb,
          stagehand: stagehand!,
          supplier,
          item,
          candidate,
          runId: runId ?? path.basename(outputDir)
        })
      );
    }
  } finally {
    for (const stagehand of sessions.values()) {
      await stagehand.close();
    }
  }

  const payload = {
    ok: results.length > 0 && results.every((row) => row.ok),
    autoSubmitted: quoteAutoSubmitEnabled(),
    submittedAt: new Date().toISOString(),
    results
  };

  fs.writeFileSync(
    path.join(outputDir, "portal_quotes.json"),
    JSON.stringify(payload, null, 2)
  );

  const bomPath = path.join(outputDir, "bom.json");
  if (fs.existsSync(bomPath)) {
    const updatedBom = JSON.parse(fs.readFileSync(bomPath, "utf-8")) as BOM;
    for (const bomItem of updatedBom.items) {
      const result = results.find((row) => row.item === bomItem.item);
      if (!result) continue;

      bomItem.candidates = (bomItem.candidates ?? []).map((candidate) => {
        if (candidate.partNumber !== result.partNumber) return candidate;
        return {
          ...candidate,
          quoteStatus:
            (result.quoteStatus as SupplierCandidate["quoteStatus"]) ??
            candidate.quoteStatus,
          quoteConfirmation: result.quoteConfirmation ?? candidate.quoteConfirmation,
          quotedPrice: result.quotedPrice ?? candidate.quotedPrice,
          quotedLeadTime: result.quotedLeadTime ?? candidate.quotedLeadTime
        };
      });
    }

    updatedBom.sent = payload.ok;
    fs.writeFileSync(bomPath, JSON.stringify(updatedBom, null, 2));
  }

  const summaryPath = path.join(outputDir, "procurement_summary.json");
  if (fs.existsSync(summaryPath)) {
    const summary = JSON.parse(fs.readFileSync(summaryPath, "utf-8"));
    summary.portalQuotes = payload;
    summary.sent = payload.ok;
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
  }

  return payload;
}

export function bomApprovalGranted(argv: string[]): boolean {
  if (argv.includes("--approved")) return true;
  const value = process.env.BOM_APPROVED?.trim().toLowerCase();
  return value === "true" || value === "1";
}
