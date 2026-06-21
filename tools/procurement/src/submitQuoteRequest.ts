import { Browserbase } from "@browserbasehq/sdk";
import { Stagehand } from "@browserbasehq/stagehand";
import fs from "node:fs";
import path from "node:path";
import { z } from "zod";
import {
  BOM,
  QuoteConfirmationSchema,
  SupplierCandidate
} from "./schemas.js";

// Sentinels in a supplier's step list: run the mock-data fill / RFQ-notes fill at
// exactly that point in the navigation (e.g. fill address on the order page BEFORE
// opening the quote dialog, then paste the RFQ into the expanded instructions box).
const FILL_MOCK = "__FILL_MOCK__";
const FILL_NOTES = "__FILL_NOTES__";

// Truthful verification: did our RFQ draft text actually land in an on-page field?
const ParkVerifySchema = z.object({
  hasNotesBox: z.boolean(),
  draftPresent: z.boolean(),
  mockFieldsFilled: z.boolean()
});
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
import { getMockApplicant } from "./mockApplicant.js";

// ---------------------------------------------------------------------------
// PARK, don't send. We open the supplier's own on-site quote form (McMaster
// "Get a Quote", Swagelok quote notes), paste the generated RFQ draft text into
// the notes/message box, set the quantity, and STOP. The request sits in the
// portal for a human to review and submit. Nothing is ever submitted or emailed
// from here — that RFQ-send path was scrapped.
// ---------------------------------------------------------------------------

export type PortalQuoteResult = {
  item: string;
  supplier: string;
  partNumber: string | null;
  productUrl: string;
  transport: "portal";
  parked: boolean;
  ok: boolean;
  quoteStatus?: string;
  quoteConfirmation?: string | null;
  quotedPrice?: string | null;
  quotedLeadTime?: string | null;
  draftParked?: boolean;
  hasNotesBox?: boolean;
  mockFieldsFilled?: boolean;
  screenshotPath?: string | null;
  error?: string;
  parkedAt: string;
};

function stagehandPage(stagehand: Stagehand) {
  return stagehand.context.pages()[0]!;
}

/** Load the RFQ draft text already written by draftRfqsFromBom for this item. */
function readDraftTextForItem(outputDir: string, item: string): string | null {
  const draftsPath = path.join(outputDir, "rfq_drafts.json");
  if (fs.existsSync(draftsPath)) {
    try {
      const drafts = JSON.parse(fs.readFileSync(draftsPath, "utf-8")) as Array<{
        item: string;
        draftPath?: string;
      }>;
      const match = drafts.find((d) => d.item === item);
      if (match?.draftPath) {
        const abs = path.join(outputDir, match.draftPath);
        if (fs.existsSync(abs)) return fs.readFileSync(abs, "utf-8");
      }
    } catch {
      // fall through to filename heuristic
    }
  }
  const safeName = item.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  const fallback = path.join(outputDir, "rfqs", `${safeName}_rfq.txt`);
  return fs.existsSync(fallback) ? fs.readFileSync(fallback, "utf-8") : null;
}

/** Supplier-specific phrasing for opening the on-site quote form + the notes box. */
function parkInstructions(supplier: SupplierTarget) {
  // openSteps run sequentially — each act() does ONE action, so navigating from
  // a product page to a checkout/contact form must be split into discrete steps.
  if (supplier.name === "McMaster-Carr") {
    return {
      openSteps: [
        "Click the 'Add to Order' button to add this item to the order.",
        "Open the order by clicking the 'Order' link in the top-right header.",
        "In the Delivery address section, if there is an 'Add a delivery address' link or button, click it to open the street address entry fields.",
        // Fill the order's delivery address (Company, Street, City, State, Zip) first.
        FILL_MOCK,
        "Click 'Get a quote' in the order toolbar to open the quote request dialog. Do NOT send the quote.",
        "In the 'Get a quote' dialog, click '+ Additional instructions' to expand the instructions text box.",
        // Now paste the RFQ into the expanded Additional-instructions box.
        FILL_NOTES
      ],
      notes:
        "Type the following request text into the 'Additional instructions' / message box of the Get-a-quote dialog. Do NOT click 'Get a quote', submit, send, or place order:\n%draft%",
      quantity: "If a quantity field is present, set it to %quantity%."
    };
  }
  if (supplier.name === "Swagelok") {
    return {
      openSteps: [
        "Click 'Add to Cart' to add this item to the cart.",
        "Open the cart (click the cart icon or 'View Cart').",
        "Click the button to proceed to checkout or request a quote. Do NOT submit or place the order.",
        "Continue to the contact/shipping information step so the name and address fields and a comments box are visible. Do NOT submit.",
        FILL_MOCK,
        FILL_NOTES
      ],
      notes:
        "Type the following request text into the cart comments, quote notes, or special-instructions field. Do NOT click submit, send, or place order:\n%draft%",
      quantity: "If a quantity field is present, set the requested quantity to %quantity%."
    };
  }
  return {
    openSteps: [
      "Open the request-a-quote, contact, or checkout form on this page so contact/address fields and a notes/comments box are visible. Do NOT submit.",
      FILL_MOCK,
      FILL_NOTES
    ],
    notes:
      "Type the following request text into the quote notes or comments box. Do NOT submit or send:\n%draft%",
    quantity: "If a quantity field is present, set it to %quantity%."
  };
}

/** Fill every matching contact/shipping field on a quote/order form with the
 * clearly-fake mock applicant. One act() per field — a single bundled act only
 * fills one field reliably, so we drive each field individually. Never submits. */
async function fillMockApplicant(
  stagehand: Stagehand,
  page: ReturnType<typeof stagehandPage>
) {
  const m = getMockApplicant();
  const fields: Array<{ instr: string; key: string; value: string }> = [
    { instr: "Type %v% into the Company / Organization field if present.", key: "v", value: m.company },
    { instr: "Type %v% into the Full Name field if present.", key: "v", value: m.fullName },
    { instr: "Type %v% into the First Name field if present.", key: "v", value: m.firstName },
    { instr: "Type %v% into the Last Name field if present.", key: "v", value: m.lastName },
    { instr: "Type %v% into the Email field if present and empty.", key: "v", value: m.email },
    { instr: "Type %v% into the Phone field if present.", key: "v", value: m.phone },
    { instr: "Type %v% into the Address / Address 1 / Street Address field.", key: "v", value: m.address1 },
    { instr: "Type %v% into the Address 2 / suite / line 2 field if present.", key: "v", value: m.address2 },
    { instr: "Type %v% into the City field.", key: "v", value: m.city },
    { instr: "Set the State / Province field to %v% (type it or pick it from the dropdown).", key: "v", value: m.state },
    { instr: "Type %v% into the ZIP / Postal Code field.", key: "v", value: m.zip },
    { instr: "Set the Country field to %v% (type it or pick it from the dropdown) if present.", key: "v", value: m.country }
  ];

  for (const f of fields) {
    try {
      await stagehand.act(f.instr + " Do NOT submit, place the order, or pay.", {
        page,
        variables: { [f.key]: f.value }
      });
    } catch {
      // field not on this form — skip it
    }
  }
}

/** Empty a stale supplier order/cart ONCE per session so the staged quote shows
 * only this run's items (each park run does Add to Order, which would otherwise
 * accumulate). Best-effort; never places or sends anything. */
async function clearSupplierOrder(
  stagehand: Stagehand,
  supplier: SupplierTarget
) {
  // Best-effort, cheap (one open + one delete). McMaster's order is account-level
  // and persists across runs; this keeps the staged quote from accumulating prior
  // lines. Gated by env because the Delete interaction isn't fully reliable and
  // adds a live step — opt in with PROCUREMENT_CLEAR_ORDER=true. Never blocks parking.
  if (supplier.name !== "McMaster-Carr") return;
  if (process.env.PROCUREMENT_CLEAR_ORDER?.trim().toLowerCase() !== "true") return;
  const page = stagehandPage(stagehand);
  try {
    await stagehand.act(
      "Click the 'Order' link in the top-right McMaster-Carr header to open the current order.",
      { page }
    );
    await page.waitForTimeout(1500);
    await stagehand.act(
      "Empty the order: click 'Delete' in the order toolbar to remove all line items, and confirm the deletion if prompted. Do NOT place an order.",
      { page }
    );
    await page.waitForTimeout(1200);
  } catch {
    // best-effort cleanup — never block parking on it
  }
}

async function parkPortalQuoteForCandidate(params: {
  bb: Browserbase;
  stagehand: Stagehand;
  supplier: SupplierTarget;
  item: {
    item: string;
    quantity: number;
    requirements: Record<string, unknown>;
  };
  candidate: SupplierCandidate;
  outputDir: string;
  runId?: string;
}): Promise<PortalQuoteResult> {
  const { stagehand, supplier, item, candidate, outputDir } = params;
  const quoteUrl = resolveSupplierQuoteUrl(
    supplier,
    candidate.partNumber,
    candidate.productUrl
  );
  const page = stagehandPage(stagehand);
  const parkedAt = new Date().toISOString();
  const steps = parkInstructions(supplier);
  const draftText = readDraftTextForItem(outputDir, item.item);

  if (!draftText) {
    return {
      item: item.item,
      supplier: candidate.supplier,
      partNumber: candidate.partNumber,
      productUrl: quoteUrl,
      transport: "portal",
      parked: false,
      ok: false,
      quoteStatus: "failed",
      error: `No RFQ draft text found for "${item.item}" — run procure first`,
      parkedAt
    };
  }

  try {
    await page.goto(quoteUrl);

    // Clear any cookie/consent banner that would block interaction.
    try {
      await stagehand.act(
        "If a cookie consent or privacy banner is visible, accept or dismiss it.",
        { page }
      );
    } catch {
      // no banner — fine
    }

    // Walk the supplier's step list. Plain strings are navigation acts; the
    // FILL_MOCK / FILL_NOTES sentinels run the mock-data and RFQ-text fills at the
    // right moment (address on the order page, RFQ in the expanded instructions).
    for (const step of steps.openSteps) {
      try {
        if (step === FILL_MOCK) {
          await fillMockApplicant(stagehand, page);
        } else if (step === FILL_NOTES) {
          // variables are typed verbatim (same path as the login password fill),
          // so the exact RFQ text lands in the box — the model can't paraphrase it.
          await stagehand.act(steps.notes, {
            page,
            variables: {
              draft: {
                value: draftText,
                description: "RFQ request text to place in the quote notes box"
              }
            }
          });
        } else {
          await stagehand.act(step, { page });
        }
        await page.waitForTimeout(1500);
      } catch {
        // a step may not apply (e.g. no field here) — keep going; verify is the truth
      }
    }

    await stagehand.act(steps.quantity, {
      page,
      variables: {
        quantity: {
          value: String(item.quantity),
          description: "BOM quantity to quote"
        }
      }
    });

    // Truthful check: is there actually a notes box, and did our draft land in it?
    let draftParked = false;
    let hasNotesBox = false;
    let mockFieldsFilled = false;
    try {
      const verify = await stagehand.extract(
        "Inspect the quote/cart/checkout form on this page.\n" +
          "- hasNotesBox: true if an editable notes, comments, message, or special-instructions field exists.\n" +
          "- draftPresent: true ONLY if such a field currently contains text including 'RFQ Request' or 'requesting a quotation'.\n" +
          "- mockFieldsFilled: true if contact/shipping fields (name, email, address, or city) are currently populated with values.",
        ParkVerifySchema,
        { page }
      );
      const parsedVerify = ParkVerifySchema.safeParse(verify);
      if (parsedVerify.success) {
        hasNotesBox = parsedVerify.data.hasNotesBox;
        draftParked = parsedVerify.data.draftPresent;
        mockFieldsFilled = parsedVerify.data.mockFieldsFilled;
      }
    } catch {
      // verification failed; leave flags false (honest default)
    }

    // Proof artifact: a screenshot of the portal with the draft parked in it.
    let screenshotPath: string | null = path.join(
      outputDir,
      `portal_${item.item.toLowerCase().replace(/[^a-z0-9]+/g, "_")}_${supplier.name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")}.png`
    );
    try {
      await page.screenshot({ path: screenshotPath });
    } catch {
      screenshotPath = null;
    }

    const extracted = await stagehand.extract(
      "Without submitting anything, extract any draft quote reference number, quoted price, and lead time visible on the quote form.",
      QuoteConfirmationSchema,
      { page }
    );
    const parsed = QuoteConfirmationSchema.safeParse(extracted);
    const confirmation = parsed.success ? parsed.data : {};

    // Honest status: "parked" = RFQ text verified in a notes box; "form_filled"
    // = mock contact/shipping data populated (even if no notes box); else nothing.
    const quoteStatus = draftParked
      ? "parked"
      : mockFieldsFilled
        ? "form_filled"
        : hasNotesBox
          ? "draft_not_placed"
          : "no_quote_box";
    const accomplished = draftParked || mockFieldsFilled;

    return {
      item: item.item,
      supplier: candidate.supplier,
      partNumber: candidate.partNumber,
      productUrl: quoteUrl,
      transport: "portal",
      parked: accomplished,
      ok: accomplished,
      quoteStatus,
      quoteConfirmation: confirmation.confirmationNumber ?? null,
      quotedPrice: confirmation.quotedPrice ?? null,
      quotedLeadTime: confirmation.quotedLeadTime ?? null,
      draftParked,
      hasNotesBox,
      mockFieldsFilled,
      screenshotPath,
      parkedAt
    };
  } catch (err) {
    return {
      item: item.item,
      supplier: candidate.supplier,
      partNumber: candidate.partNumber,
      productUrl: quoteUrl,
      transport: "portal",
      parked: false,
      ok: false,
      quoteStatus: "failed",
      error: String(err),
      parkedAt
    };
  }
}

export async function parkPortalQuotes(
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
        // Park needs an authenticated cart/quote form. Log in whenever creds
        // exist — even for suppliers whose search step doesn't require login
        // (e.g. Swagelok), so its quote form is reachable.
        const hasCreds = Boolean(
          supplier.usernameEnv &&
            process.env[supplier.usernameEnv]?.trim() &&
            supplier.passwordEnv &&
            process.env[supplier.passwordEnv]?.trim()
        );
        const loginResult = await ensureLoggedIn({
          bb,
          stagehand,
          supplier,
          runId: runId ?? path.basename(outputDir),
          force: hasCreds
        });

        // Only hard-fail when login is mandatory for this supplier. For optional
        // (forced) logins, proceed best-effort even if the login didn't take.
        if (!loginResult.ok && supplier.requiresLogin) {
          results.push({
            item: item.item,
            supplier: candidate.supplier,
            partNumber: candidate.partNumber,
            productUrl: candidate.productUrl,
            transport: "portal",
            parked: false,
            ok: false,
            quoteStatus: "failed",
            error: loginFailureReasonMessage(loginResult.reason),
            parkedAt: new Date().toISOString()
          });
          await stagehand.close();
          continue;
        }

        // First time this supplier's session is up: empty any stale order so the
        // staged quote reflects only this run (runs accumulate Add-to-Order lines).
        await clearSupplierOrder(stagehand, supplier);

        sessions.set(supplier.name, stagehand);
      }

      results.push(
        await parkPortalQuoteForCandidate({
          bb,
          stagehand: stagehand!,
          supplier,
          item,
          candidate,
          outputDir,
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
    parked: true,
    sent: false,
    parkedAt: new Date().toISOString(),
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

    // Parking never sends — sent stays false by design.
    updatedBom.sent = false;
    fs.writeFileSync(bomPath, JSON.stringify(updatedBom, null, 2));
  }

  const summaryPath = path.join(outputDir, "procurement_summary.json");
  if (fs.existsSync(summaryPath)) {
    const summary = JSON.parse(fs.readFileSync(summaryPath, "utf-8"));
    summary.portalQuotes = payload;
    summary.parked = payload.ok;
    summary.sent = false;
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
  }

  return payload;
}
