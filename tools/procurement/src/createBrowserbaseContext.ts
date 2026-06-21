import dotenv from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Browserbase } from "@browserbasehq/sdk";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
dotenv.config({ path: path.join(repoRoot, ".env"), quiet: true, override: true });
dotenv.config({ path: path.join(process.cwd(), ".env"), quiet: true, override: true });

async function main() {
  const label = process.argv[2] ?? "supplier";

  if (!process.env.BROWSERBASE_API_KEY) {
    throw new Error("Missing BROWSERBASE_API_KEY");
  }

  const bb = new Browserbase({
    apiKey: process.env.BROWSERBASE_API_KEY
  });

  const context = await bb.contexts.create({
    projectId: process.env.BROWSERBASE_PROJECT_ID?.trim() || undefined
  });

  const envName =
    label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") ||
    "supplier";

  console.log(
    JSON.stringify(
      {
        ok: true,
        label,
        contextId: context.id,
        suggestedEnvVar: `BROWSERBASE_CONTEXT_${envName.toUpperCase()}`,
        note: "Paste the context id into .env under the suggested env var name."
      },
      null,
      2
    )
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
