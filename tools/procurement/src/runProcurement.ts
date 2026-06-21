import dotenv from "dotenv";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Browserbase } from "@browserbasehq/sdk";
import { ProcurementInputSchema, BOMSchema } from "./schemas.js";
import {
  searchSuppliersForMaterial,
  SupplierSessionPool,
  suppliersRequiringLogin
} from "./supplierSearch.js";
import { draftRfqsFromBom } from "./rfqDrafts.js";
import { loginFailureReasonMessage } from "./supplierAuth.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
dotenv.config({ path: path.join(repoRoot, ".env"), quiet: true, override: true });
dotenv.config({ path: path.join(process.cwd(), ".env"), quiet: true, override: true });

async function main() {
  const inputPath = process.argv[2];
  const outputDir = process.argv[3];

  if (!inputPath || !outputDir) {
    throw new Error("Usage: npm run procure -- <input.json> <output_dir>");
  }

  if (!process.env.BROWSERBASE_API_KEY) {
    throw new Error("Missing BROWSERBASE_API_KEY");
  }

  const inputRaw = JSON.parse(fs.readFileSync(inputPath, "utf-8"));
  const input = ProcurementInputSchema.parse(inputRaw);

  const bb = new Browserbase({
    apiKey: process.env.BROWSERBASE_API_KEY
  });

  const pool = new SupplierSessionPool();
  const bomItems = [];

  try {
    const loginSuppliers = suppliersRequiringLogin(input.materials);
    if (loginSuppliers.length > 0) {
      await pool.prewarm(bb, loginSuppliers, input.projectName);
      for (const supplier of loginSuppliers) {
        if (pool.isBlocked(supplier.name)) {
          const blocked = pool.getBlockedResult(supplier.name)!;
          console.warn(
            JSON.stringify({
              event: "supplier_login_blocked",
              supplier: supplier.name,
              reason: blocked.reason,
              detail: blocked.detail ?? null,
              message: loginFailureReasonMessage(blocked.reason, blocked.detail)
            })
          );
        }
      }
    }

    for (const material of input.materials) {
      const candidates = await searchSuppliersForMaterial(bb, material, pool);

      bomItems.push({
        item: material.item,
        quantity: material.quantity,
        requirements: material.requirements,
        candidates
      });
    }
  } finally {
    await pool.closeAll();
  }

  const bom = BOMSchema.parse({
    generatedAt: new Date().toISOString(),
    projectName: input.projectName,
    items: bomItems,
    approvalRequired: true,
    sent: false
  });

  fs.mkdirSync(outputDir, { recursive: true });

  const bomPath = path.join(outputDir, "bom.json");
  fs.writeFileSync(bomPath, JSON.stringify(bom, null, 2));

  const drafts = draftRfqsFromBom(bom, outputDir);

  const summaryPath = path.join(outputDir, "procurement_summary.json");
  fs.writeFileSync(
    summaryPath,
    JSON.stringify(
      {
        ok: true,
        projectName: input.projectName,
        bomPath,
        rfqDrafts: drafts,
        approvalRequired: true,
        sent: false
      },
      null,
      2
    )
  );

  console.log(
    JSON.stringify({
      ok: true,
      bomPath,
      summaryPath,
      approvalRequired: true,
      sent: false
    })
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});