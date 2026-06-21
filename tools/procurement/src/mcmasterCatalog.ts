import type { MaterialCategory } from "./supplierTargets.js";
import { materialCategory } from "./materialUtils.js";

export const MCMASTER_BASE = "https://www.mcmaster.com";

type McMasterCatalogRule = {
  materialCategories: MaterialCategory[];
  itemKeywords?: string[];
  requirementKeys?: string[];
  paths: { path: string; title: string; priority: number }[];
};

const MCMASTER_CATALOG_RULES: McMasterCatalogRule[] = [
  {
    materialCategories: ["tank"],
    itemKeywords: ["gn2", "nitrogen", "pressurant", "gas"],
    paths: [
      {
        path: "/products/compressed-gas-tanks/",
        title: "Compressed Gas Tanks",
        priority: 100
      },
      {
        path: "/products/cga-gas-tanks/",
        title: "CGA Gas Tanks",
        priority: 95
      }
    ]
  },
  {
    materialCategories: ["tank"],
    itemKeywords: ["lox", "oxygen", "cryo"],
    paths: [
      {
        path: "/products/cga-gas-tanks/",
        title: "CGA Gas Tanks",
        priority: 100
      },
      {
        path: "/products/compressed-gas-tanks/",
        title: "Compressed Gas Tanks",
        priority: 90
      }
    ]
  },
  {
    materialCategories: ["tank"],
    paths: [
      {
        path: "/products/gas-welding-tanks/",
        title: "Gas Welding Tanks",
        priority: 80
      }
    ]
  },
  {
    materialCategories: ["valve"],
    requirementKeys: ["oxygen_clean"],
    paths: [
      {
        path: "/products/valves/for-use-with~oxygen-2/",
        title: "Valves for Oxygen",
        priority: 110
      },
      {
        path: "/products/valves/for-use-with~liquid-oxygen/",
        title: "Valves for Liquid Oxygen",
        priority: 105
      }
    ]
  },
  {
    materialCategories: ["valve"],
    paths: [
      {
        path: "/products/panel-mount-needle-valves/",
        title: "Panel-Mount Needle Valves",
        priority: 85
      },
      {
        path: "/products/ball-valves/",
        title: "Ball Valves",
        priority: 80
      }
    ]
  }
];

export type SeedUrl = {
  url: string;
  title: string;
  source: "catalog";
};

export function getMcMasterSeedUrls(material: {
  item: string;
  requirements?: Record<string, unknown>;
}): SeedUrl[] {
  const category = materialCategory(material.item);
  const itemLower = material.item.toLowerCase();
  const req = material.requirements ?? {};

  const matched: SeedUrl[] = [];

  for (const rule of MCMASTER_CATALOG_RULES) {
    if (!rule.materialCategories.includes(category)) continue;
    if (
      rule.itemKeywords &&
      !rule.itemKeywords.some((kw) => itemLower.includes(kw))
    ) {
      continue;
    }
    if (
      rule.requirementKeys &&
      !rule.requirementKeys.some((key) => req[key] != null && req[key] !== false)
    ) {
      continue;
    }

    for (const entry of rule.paths) {
      matched.push({
        url: `${MCMASTER_BASE}${entry.path}`,
        title: entry.title,
        source: "catalog"
      });
    }
  }

  const seen = new Set<string>();
  return matched
    .filter((entry) => {
      if (seen.has(entry.url)) return false;
      seen.add(entry.url);
      return true;
    })
    .slice(0, 3);
}

export function isMcMasterCatalogListing(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.includes("mcmaster.com")) return false;
    return parsed.pathname.startsWith("/products/") && !isMcMasterPartPage(url);
  } catch {
    return false;
  }
}

export function isMcMasterPartPage(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.includes("mcmaster.com")) return false;
    return /^\/[0-9a-z]{4,}$/i.test(parsed.pathname);
  } catch {
    return false;
  }
}
