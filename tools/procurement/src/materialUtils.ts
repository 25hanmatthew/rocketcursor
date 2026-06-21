import type { MaterialCategory } from "./supplierTargets.js";

export function materialCategory(item: string): MaterialCategory {
  const lower = item.toLowerCase();
  if (lower.includes("tank")) return "tank";
  if (lower.includes("valve")) return "valve";
  return "general";
}

export function materialSearchTerms(item: string): string[] {
  const category = materialCategory(item);
  if (category === "tank") {
    return ["pressure vessel", "gas cylinder", "storage tank"];
  }
  if (category === "valve") {
    return ["ball valve", "needle valve", "shutoff valve"];
  }
  return ["component", "fitting"];
}
