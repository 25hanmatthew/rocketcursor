export type MaterialCategory = "tank" | "valve" | "general";

export type SupplierTarget = {
  name: string;
  domain: string;
  /** Browserbase search uses site:{searchDomain} when set, else domain */
  searchDomain?: string;
  searchHints: string[];
  categories: MaterialCategory[];
  needsBrowser: boolean;
  useVerifiedProxy: boolean;
  /** Whether logged-in extraction is required for pricing */
  requiresLogin: boolean;
  /** Page to open before login (homepage for panel flows) */
  loginUrl?: string;
  /** panel = click header Login to open side drawer; page = form is on loginUrl */
  loginFlow?: "page" | "panel";
  /** Env var names — resolved at runtime, never store secrets here */
  usernameEnv?: string;
  passwordEnv?: string;
  contextEnv?: string;
  /** When set, RFQs can be submitted via the supplier's on-site quote portal */
  supportsPortalQuote?: boolean;
  quoteUrlTemplate?: string;
};

export const SUPPLIERS: SupplierTarget[] = [
  {
    name: "McMaster-Carr",
    domain: "mcmaster.com",
    searchHints: ["catalog", "buy", "part number"],
    categories: ["tank", "valve", "general"],
    needsBrowser: true,
    // Verified/stealth proxy requires Browserbase Enterprise — use standard session + context instead
    useVerifiedProxy: false,
    requiresLogin: true,
    loginUrl: "https://www.mcmaster.com/",
    loginFlow: "panel",
    usernameEnv: "MCMASTER_USERNAME",
    passwordEnv: "MCMASTER_PASSWORD",
    contextEnv: "BROWSERBASE_CONTEXT_MCMASTER",
    supportsPortalQuote: true
  },
  {
    name: "Swagelok",
    domain: "swagelok.com",
    searchDomain: "products.swagelok.com",
    searchHints: [
      "ball valve",
      "needle valve",
      "pressure regulator",
      "tube fitting"
    ],
    categories: ["valve", "general"],
    needsBrowser: true,
    useVerifiedProxy: false,
    requiresLogin: false,
    loginUrl: "https://www.swagelok.com/en/login",
    usernameEnv: "SWAGELOK_USERNAME",
    passwordEnv: "SWAGELOK_PASSWORD",
    contextEnv: "BROWSERBASE_CONTEXT_SWAGELOK",
    supportsPortalQuote: true,
    quoteUrlTemplate: "https://products.swagelok.com/en/c/2-way-straight-pattern/p/{partNumber}"
  },
  {
    name: "Parker",
    domain: "parker.com",
    searchHints: ["ball valve", "needle valve", "fitting"],
    categories: ["valve", "general"],
    needsBrowser: true,
    useVerifiedProxy: false,
    requiresLogin: false
  }
];

export function getSupplierTarget(name: string): SupplierTarget | undefined {
  return SUPPLIERS.find((supplier) => supplier.name === name);
}

export function supplierSupportsPortalQuote(supplier: SupplierTarget): boolean {
  return Boolean(supplier.supportsPortalQuote ?? supplier.quoteUrlTemplate);
}

export function resolveSupplierQuoteUrl(
  supplier: SupplierTarget,
  partNumber: string | null | undefined,
  productUrl: string
): string {
  if (supplier.quoteUrlTemplate && partNumber) {
    return supplier.quoteUrlTemplate.replace("{partNumber}", partNumber);
  }
  return productUrl;
}
