function envInt(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** Max catalog/search URLs to extract per supplier per material (default 4). Use 2 for faster smoke runs. */
export const MAX_URLS_PER_SUPPLIER = envInt("PROCUREMENT_MAX_URLS", 4);

/** Max product pages to drill from a listing (default 2). Use 1 for faster smoke runs. */
export const MAX_DRILLDOWN_PRODUCTS = envInt("PROCUREMENT_MAX_DRILLDOWN", 2);

/** Browserbase web search result count (default 8). */
export const SEARCH_RESULT_LIMIT = envInt("PROCUREMENT_SEARCH_RESULTS", 8);

/** Catalog seed URLs mixed into search (default 2). */
export const MAX_SEED_URLS = envInt("PROCUREMENT_MAX_SEEDS", 2);

/** When true, search matching suppliers for a material in parallel (default true). */
export function supplierSearchParallel(): boolean {
  const value = process.env.PROCUREMENT_PARALLEL_SUPPLIERS?.trim().toLowerCase();
  return value !== "false" && value !== "0";
}

/** Retries for flaky supplier login before blocking the supplier for the run (default 2). */
export const SUPPLIER_LOGIN_RETRIES = envInt("SUPPLIER_LOGIN_RETRIES", 2);
