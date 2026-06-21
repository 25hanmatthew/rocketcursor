import dotenv from "dotenv";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Browserbase } from "@browserbasehq/sdk";
import { BOMSchema } from "./schemas.js";
import { buildProcurementGaps } from "./procurementGaps.js";
import { parkPortalQuotes } from "./submitQuoteRequest.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
dotenv.config({ path: path.join(repoRoot, ".env"), quiet: true, override: true });
dotenv.config({ path: path.join(process.cwd(), ".env"), quiet: true, override: true });

async function main() {
  const outputDir = process.argv[2];

  if (!outputDir) {
    throw new Error("Usage: npm run park-quotes -- <output_dir>");
  }

  // No approval gate: parking only places the draft text in the supplier's
  // quote box for human review — it never submits or sends anything.

  if (!process.env.BROWSERBASE_API_KEY) {
    throw new Error("Missing BROWSERBASE_API_KEY");
  }

  const resolvedDir = path.resolve(outputDir);
  const bomPath = path.join(resolvedDir, "bom.json");
  if (!fs.existsSync(bomPath)) {
    throw new Error(`Missing bom.json in ${resolvedDir}`);
  }

  const bom = BOMSchema.parse(JSON.parse(fs.readFileSync(bomPath, "utf-8")));
  fs.writeFileSync(
    path.join(resolvedDir, "procurement_gaps.json"),
    JSON.stringify(buildProcurementGaps(bom), null, 2)
  );

  const bb = new Browserbase({
    apiKey: process.env.BROWSERBASE_API_KEY
  });

  const result = await parkPortalQuotes(
    bb,
    bom,
    resolvedDir,
    path.basename(resolvedDir)
  );

  console.log(JSON.stringify(result, null, 2));

  if (!result.ok) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
