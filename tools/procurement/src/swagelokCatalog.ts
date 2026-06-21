import type { MaterialCategory } from "./supplierTargets.js";
import { materialCategory } from "./materialUtils.js";

export const SWAGELOK_PRODUCTS_BASE = "https://products.swagelok.com/en";

type SwagelokCatalogRule = {
  materialCategories: MaterialCategory[];
  itemKeywords?: string[];
  path: string;
  title: string;
  priority: number;
};

const SWAGELOK_CATALOG_RULES: SwagelokCatalogRule[] = [
  {
    materialCategories: ["valve"],
    path: "all-products/valves/ball-quarter-turn-plug-valves/c/204?clp=true",
    title: "Ball and Quarter-Turn Plug Valves",
    priority: 100
  },
  {
    materialCategories: ["valve"],
    itemKeywords: ["feed", "shutoff", "ball"],
    path: "all-products/valves/ball-quarter-turn-plug-valves/c/204?clp=true",
    title: "Ball and Quarter-Turn Plug Valves",
    priority: 110
  },
  {
    materialCategories: ["valve"],
    itemKeywords: ["needle"],
    path: "all-products/valves/needle-metering-valves/c/202?clp=true",
    title: "Needle and Metering Valves",
    priority: 90
  },
  {
    materialCategories: ["valve"],
    path: "all-products/valves/needle-metering-valves/c/202?clp=true",
    title: "Needle and Metering Valves",
    priority: 80
  },
  {
    materialCategories: ["valve"],
    path: "all-products/valves/check-valves/c/201?clp=true",
    title: "Check Valves",
    priority: 40
  },
  {
    materialCategories: ["general"],
    path: "all-products/valves/c/200?clp=true",
    title: "All Valves",
    priority: 50
  }
];

export type SeedUrl = {
  url: string;
  title: string;
  source: "catalog";
};

export function getSwagelokSeedUrls(material: { item: string }): SeedUrl[] {
  const category = materialCategory(material.item);
  const itemLower = material.item.toLowerCase();

  const matched = SWAGELOK_CATALOG_RULES.filter((rule) => {
    if (!rule.materialCategories.includes(category)) return false;
    if (rule.itemKeywords && !rule.itemKeywords.some((kw) => itemLower.includes(kw))) {
      return false;
    }
    return true;
  })
    .sort((a, b) => b.priority - a.priority)
    .map((rule) => ({
      url: `${SWAGELOK_PRODUCTS_BASE}/${rule.path}`,
      title: rule.title,
      source: "catalog" as const
    }));

  const seen = new Set<string>();
  return matched.filter((entry) => {
    if (seen.has(entry.url)) return false;
    seen.add(entry.url);
    return true;
  });
}

export function isSwagelokCatalogListing(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.includes("products.swagelok.com")) return false;
    return /\/c\/\d+/.test(parsed.pathname) && !/\/p\//.test(parsed.pathname);
  } catch {
    return false;
  }
}

export function isSwagelokProductPage(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.hostname.includes("products.swagelok.com") && /\/p\//.test(parsed.pathname);
  } catch {
    return false;
  }
}

export function swagelokProductUrl(partNumber: string): string {
  return `${SWAGELOK_PRODUCTS_BASE}/p/${encodeURIComponent(partNumber)}`;
}

export function scoreProcurementUrl(url: string): number {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.toLowerCase();

    if (path.endsWith(".pdf") || path.includes(".ashx")) return -1000;
    if (/\/p\/[^/]+$/i.test(path)) return 100;
    if (/\/c\/\d+/.test(path) && parsed.searchParams.get("clp") === "true") {
      return 60;
    }
    if (/\/c\/\d+/.test(path)) return 50;
    if (parsed.hostname.includes("mcmaster.com")) {
      if (/^\/[0-9a-z]{4,}$/i.test(path)) return 100;
      if (path.includes("/products/valves/for-use-with~")) return 65;
      if (path.startsWith("/products/")) return 55;
      return 20;
    }
    if (parsed.hostname.includes("products.swagelok.com")) return 30;
    return 10;
  } catch {
    return -1000;
  }
}
