import { isRfqEligibleCandidate, isViableProcurementCandidate } from "./scoring.js";

export type ProcurementGap = {
  item: string;
  status: "needsReview" | "noMatch";
  reason: string;
  bestPartNumber: string | null;
  bestSupplier: string | null;
  bestProductUrl: string | null;
  confidence: number | null;
  failedRequirements: string[];
  missingRequirements: string[];
  suggestedAction: string;
};

export function buildProcurementGaps(bom: any) {
  const needsReview: ProcurementGap[] = [];
  const noMatch: ProcurementGap[] = [];

  for (const item of bom.items ?? []) {
    const candidates = item.candidates ?? [];
    const best = candidates[0];
    const eligible = candidates.find(isRfqEligibleCandidate);

    if (eligible) continue;

    if (!best || !isViableProcurementCandidate(best)) {
      noMatch.push({
        item: item.item,
        status: "noMatch",
        reason: "No viable candidates with extractable product data",
        bestPartNumber: best?.partNumber ?? null,
        bestSupplier: best?.supplier ?? null,
        bestProductUrl: best?.productUrl ?? null,
        confidence: best?.confidence ?? null,
        failedRequirements: best?.failed_requirements ?? [],
        missingRequirements: best?.missing_requirements ?? [],
        suggestedAction:
          "Expand supplier search, adjust requirements, or procure manually."
      });
      continue;
    }

    const failed = best.failed_requirements ?? [];
    const missing = best.missing_requirements ?? [];
    const reason =
      failed.length > 0
        ? `failed:${failed.join(",")}`
        : missing.length > 0
          ? `missing:${missing.join(",")}`
          : "not eligible for RFQ";

    needsReview.push({
      item: item.item,
      status: "needsReview",
      reason,
      bestPartNumber: best.partNumber ?? null,
      bestSupplier: best.supplier ?? null,
      bestProductUrl: best.productUrl ?? null,
      confidence: best.confidence ?? null,
      failedRequirements: failed,
      missingRequirements: missing,
      suggestedAction:
        failed.includes("cryogenic_compatible")
          ? "Find a cryogenic vendor or relax the cryogenic requirement."
          : missing.includes("login_challenge")
            ? "Set SUPPLIER_LOGIN_INTERACTIVE=true, re-run, and complete 2FA/CAPTCHA via the Poke live-view link."
            : missing.includes("login_failed")
              ? "Configure supplier credentials in .env and verify Browserbase context ids."
          : "Review BOM candidate specs or choose a different part manually."
    });
  }

  return { needsReview, noMatch };
}
