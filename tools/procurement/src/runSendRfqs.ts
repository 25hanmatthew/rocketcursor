import dotenv from "dotenv";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BOMSchema } from "./schemas.js";
import { buildProcurementGaps } from "./procurementGaps.js";
import { sendRfqsViaPoke } from "./sendRfqsViaPoke.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
dotenv.config({ path: path.join(repoRoot, ".env"), quiet: true, override: true });
dotenv.config({ path: path.join(process.cwd(), ".env"), quiet: true, override: true });

async function main() {
  const outputDir = process.argv[2];

  if (!outputDir) {
    throw new Error("Usage: npm run send-rfqs -- <output_dir>");
  }

  const resolvedDir = path.resolve(outputDir);
  const bomPath = path.join(resolvedDir, "bom.json");

  if (fs.existsSync(bomPath)) {
    const bom = BOMSchema.parse(JSON.parse(fs.readFileSync(bomPath, "utf-8")));
    fs.writeFileSync(
      path.join(resolvedDir, "procurement_gaps.json"),
      JSON.stringify(buildProcurementGaps(bom), null, 2)
    );
  }

  const result = await sendRfqsViaPoke(resolvedDir);
  console.log(JSON.stringify(result, null, 2));

  if (!result.dryRun && "transport" in result && result.transport === "mcp") {
    console.error(
      result.emailSent
        ? `\nEmails sent automatically via the MCP server to ${result.recipientEmail}.`
        : `\nMCP send reported a failure. Check the per-item 'error' fields above and the MCP server logs.`
    );
  } else if (!result.dryRun && "transport" in result) {
    console.error(
      `\nNo MCP_SERVER_URL set, so this only handed off to Poke (manual).\n` +
        `To send automatically, set MCP_SERVER_URL to your MCP /mcp endpoint and re-run.\n` +
        `A ready-to-paste fallback was written to:\n` +
        `  ${path.join(resolvedDir, "poke_mcp_instruction.txt")}`
    );
  }

  if (!result.ok) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
