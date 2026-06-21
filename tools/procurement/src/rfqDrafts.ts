import fs from "node:fs";
import path from "node:path";
import { isRfqEligibleCandidate } from "./scoring.js";
import {
  getSupplierTarget,
  supplierSupportsPortalQuote
} from "./supplierTargets.js";

export function draftRfqsFromBom(bom: any, outputDir: string) {
  const rfqDir = path.join(outputDir, "rfqs");
  fs.mkdirSync(rfqDir, { recursive: true });

  const drafts = [];

  for (const item of bom.items) {
    const best = (item.candidates ?? []).find(isRfqEligibleCandidate);
    if (!best) continue;

    const body = `
Subject: RFQ Request — ${item.item}

Hello,

We are requesting a quotation for the following component:

Item: ${item.item}
Quantity: ${item.quantity}
Candidate product: ${best.productName}
Part number: ${best.partNumber ?? "not listed"}
Supplier: ${best.supplier}
Product URL: ${best.productUrl}

Required specifications:
${JSON.stringify(item.requirements, null, 2)}

Extracted candidate specifications:
Pressure rating: ${best.pressure_rating_pa ?? "not found"} Pa
Volume: ${best.volume_l ?? "not found"} L
Minimum CdA: ${best.minimum_cda_m2 ?? "not found"} m^2
Fluid compatibility: ${(best.fluid_compatibility ?? []).join(", ") || "not found"}
Oxygen clean: ${best.oxygen_clean ?? "not found"}
Cryogenic compatible: ${best.cryogenic_compatible ?? "not found"}

Requirement check:
Matched: ${(best.matched_requirements ?? []).join(", ") || "none"}
Missing: ${(best.missing_requirements ?? []).join(", ") || "none"}
Failed: ${(best.failed_requirements ?? []).join(", ") || "none"}

Please include:
- Unit pricing
- Lead time
- Datasheet
- Pressure rating documentation
- Fluid compatibility documentation
- Cleaning/compliance documentation where applicable
- Any minimum order quantity
- Shipping options

Note: This RFQ draft was generated automatically from a simulation-derived BOM and requires engineering review before purchase or use.

Best,
Engineering Team
`.trim();

    const safeName = item.item.toLowerCase().replace(/[^a-z0-9]+/g, "_");
    const draftRelativePath = path.join("rfqs", `${safeName}_rfq.txt`);
    const draftAbsolutePath = path.join(outputDir, draftRelativePath);

    fs.writeFileSync(draftAbsolutePath, body);

    const supplierTarget = getSupplierTarget(best.supplier);
    const transport =
      supplierTarget && supplierSupportsPortalQuote(supplierTarget)
        ? "portal"
        : "email";

    drafts.push({
      item: item.item,
      supplier: best.supplier,
      partNumber: best.partNumber ?? null,
      productUrl: best.productUrl,
      draftPath: draftRelativePath,
      approvalRequired: true,
      sent: false,
      transport
    });
  }

  const rfqDraftsPath = path.join(outputDir, "rfq_drafts.json");
  fs.writeFileSync(rfqDraftsPath, JSON.stringify(drafts, null, 2));

  return drafts;
}