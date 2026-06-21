import { Browserbase } from "@browserbasehq/sdk";
import { Stagehand } from "@browserbasehq/stagehand";
import { z } from "zod";
import { SUPPLIERS, SupplierTarget } from "./supplierTargets.js";
import { SupplierCandidateSchema } from "./schemas.js";
import {
  dedupeProcurementCandidates,
  rankProcurementCandidates,
  scoreCandidateAgainstRequirements
} from "./scoring.js";
import { materialCategory, materialSearchTerms } from "./materialUtils.js";
import { enrichExtractedCandidate, mcmasterProductUrl } from "./enrichment.js";
import {
  loadCachedCandidates,
  saveCacheableCandidates
} from "./candidateCache.js";
import {
  getSwagelokSeedUrls,
  isSwagelokCatalogListing,
  scoreProcurementUrl,
  swagelokProductUrl
} from "./swagelokCatalog.js";
import {
  getMcMasterSeedUrls,
  isMcMasterCatalogListing
} from "./mcmasterCatalog.js";
import {
  ensureLoggedInWithRetry,
  loginFailureReasonMessage,
  LoginResult,
  verifyStillLoggedIn
} from "./supplierAuth.js";
import { SupplierSessionPool } from "./supplierSessionPool.js";
import {
  MAX_DRILLDOWN_PRODUCTS,
  MAX_SEED_URLS,
  MAX_URLS_PER_SUPPLIER,
  SEARCH_RESULT_LIMIT,
  supplierSearchParallel
} from "./procurementLimits.js";

import { createStagehandSession } from "./stagehandSession.js";

export { createStagehandSession } from "./stagehandSession.js";
export { SupplierSessionPool } from "./supplierSessionPool.js";

const ExtractedCandidateListSchema = z.object({
  candidates: z.array(
    z.object({
      productName: z.string().nullable().optional(),
      partNumber: z.string().nullable().optional(),
      productUrl: z.string().nullable().optional(),
      price: z.string().nullable().optional(),
      leadTime: z.string().nullable().optional(),

      pressure_rating_pa: z.number().nullable().optional(),
      volume_l: z.number().nullable().optional(),
      minimum_cda_m2: z.number().nullable().optional(),
      cv_max: z.number().nullable().optional(),
      fluid_compatibility: z.array(z.string()).optional(),
      oxygen_clean: z.boolean().nullable().optional(),
      cryogenic_compatible: z.boolean().nullable().optional(),

      notes: z.string().optional()
    })
  )
});

const ListingPartSchema = z.object({
  candidates: z.array(
    z.object({
      partNumber: z.string(),
      productName: z.string().nullable().optional()
    })
  )
});

function paToBar(pa?: number): number | null {
  if (!pa) return null;
  return Math.ceil(pa / 100000);
}

export function isUnextractableUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return true;
  }

  const lower = parsed.href.toLowerCase();
  const path = parsed.pathname.toLowerCase();

  return (
    path.endsWith(".pdf") ||
    lower.includes(".ashx") ||
    path.includes("/downloads/") ||
    path.includes("/download/") ||
    path.includes("/-/media/") ||
    path.includes("/media/distributor-media/")
  );
}

function supplierMatchesMaterial(supplier: SupplierTarget, item: string): boolean {
  return supplier.categories.includes(materialCategory(item));
}

function buildSupplierQuery(material: any, supplier: SupplierTarget): string {
  const req = material.requirements || {};
  const pressurePa = req.minimum_pressure_rating_pa ?? req.pressure_rating_pa;
  const pressureBar = paToBar(pressurePa);

  const searchDomain = supplier.searchDomain ?? supplier.domain;

  const pieces = [
    `site:${searchDomain}`,
    material.item,
    ...materialSearchTerms(material.item),
    req.fluid ? String(req.fluid) : "",
    Array.isArray(req.compatible_with) ? req.compatible_with.join(" ") : "",
    req.oxygen_clean ? `"SC-11" "oxygen clean"` : "",
    req.cryogenic_compatible ? `"cryogenic"` : "",
    req.minimum_volume_l ? `"${req.minimum_volume_l} L"` : "",
    pressureBar ? `"${pressureBar} bar"` : "",
    req.minimum_cda_m2 ? `"Cv"` : "",
    ...supplier.searchHints,
    "part number"
  ];

  return pieces.filter(Boolean).join(" ");
}

type UrlCandidate = {
  url: string;
  title?: string | null;
  source: "search" | "catalog";
};

function collectSupplierUrls(
  material: any,
  supplier: SupplierTarget,
  searchResults: any
): UrlCandidate[] {
  const merged = new Map<string, UrlCandidate>();

  if (supplier.name === "Swagelok") {
    for (const seed of getSwagelokSeedUrls(material).slice(0, MAX_SEED_URLS)) {
      merged.set(seed.url, {
        url: seed.url,
        title: seed.title,
        source: "catalog"
      });
    }
  }

  if (supplier.name === "McMaster-Carr") {
    for (const seed of getMcMasterSeedUrls(material)) {
      merged.set(seed.url, {
        url: seed.url,
        title: seed.title,
        source: "catalog"
      });
    }
  }

  for (const result of searchResults.results ?? []) {
    if (!result.url || isUnextractableUrl(result.url)) continue;
    if (!merged.has(result.url)) {
      merged.set(result.url, {
        url: result.url,
        title: result.title,
        source: "search"
      });
    }
  }

  return [...merged.values()]
    .sort((a, b) => scoreProcurementUrl(b.url) - scoreProcurementUrl(a.url))
    .slice(0, MAX_URLS_PER_SUPPLIER);
}

function rankListingParts(parts: { partNumber: string; productName?: string | null }[], material: any) {
  const req = material.requirements || {};

  return [...parts].sort((a, b) => {
    const score = (part: { partNumber: string }) => {
      let value = 0;
      const upper = part.partNumber.toUpperCase();
      if (req.oxygen_clean && upper.includes("-SC11")) value += 100;
      if (req.oxygen_clean && upper.includes("SC11")) value += 100;
      if (upper.includes("-SC10")) value -= 50;
      if (material.item.toLowerCase().includes("ball") && upper.includes("SS-4")) {
        value += 20;
      }
      return value;
    };
    return score(b) - score(a);
  });
}

async function extractWithStagehand(
  stagehand: Stagehand,
  url: string,
  material: any,
  supplier: SupplierTarget
) {
  const page = stagehand.context.pages()[0]!;
  await page.goto(url);

  const instruction =
    `You are extracting procurement candidates for an engineering bill of materials.\n\n` +
    `Supplier: ${supplier.name}\n` +
    `Material requirement:\n${JSON.stringify(material, null, 2)}\n\n` +
    `Extract only real purchasable product candidates from this page. ` +
    `Do not invent part numbers, prices, pressure ratings, compatibility, or lead times. ` +
    `If a field is not visible, return null or an empty array. ` +
    `Convert pressure ratings to pascals when possible. ` +
    `Convert volumes to liters when possible. ` +
    `Extract cv_max when the page lists Cv or flow coefficient. ` +
    `For oxygen-clean or cryogenic compatibility, only return true if the page explicitly says so.`;

  const result = await stagehand.extract(instruction, ExtractedCandidateListSchema);

  const parsed = ExtractedCandidateListSchema.safeParse(result);
  if (!parsed.success) {
    return [];
  }

  return parsed.data.candidates ?? [];
}

async function extractListingPartNumbers(
  stagehand: Stagehand,
  url: string,
  material: any,
  supplier: SupplierTarget
) {
  const page = stagehand.context.pages()[0]!;
  await page.goto(url);

  const instruction =
    `You are reading a ${supplier.name} catalog listing page with product tables.\n\n` +
    `Material requirement:\n${JSON.stringify(material, null, 2)}\n\n` +
    `Extract purchasable part numbers from visible product tables on this page. ` +
    `Return up to 12 distinct part numbers that could match the requirement. ` +
    `Do not invent part numbers.`;

  const result = await stagehand.extract(instruction, ListingPartSchema);
  const parsed = ListingPartSchema.safeParse(result);
  if (!parsed.success) {
    return [];
  }

  const seen = new Set<string>();
  return (parsed.data.candidates ?? []).filter((row) => {
    const partNumber = row.partNumber.trim();
    if (!partNumber || seen.has(partNumber)) return false;
    seen.add(partNumber);
    return true;
  });
}

async function extractFromUrl(
  stagehand: Stagehand,
  urlCandidate: UrlCandidate,
  material: any,
  supplier: SupplierTarget
) {
  if (
    isSwagelokCatalogListing(urlCandidate.url) ||
    isMcMasterCatalogListing(urlCandidate.url)
  ) {
    const listingParts = await extractListingPartNumbers(
      stagehand,
      urlCandidate.url,
      material,
      supplier
    );

    if (listingParts.length === 0) {
      return extractWithStagehand(
        stagehand,
        urlCandidate.url,
        material,
        supplier
      );
    }

    const drillTargets = rankListingParts(listingParts, material).slice(
      0,
      MAX_DRILLDOWN_PRODUCTS
    );

    const drilled: any[] = [];
    for (const part of drillTargets) {
      const productUrl =
        supplier.name === "McMaster-Carr"
          ? mcmasterProductUrl(part.partNumber)
          : swagelokProductUrl(part.partNumber);
      const extracted = await extractWithStagehand(
        stagehand,
        productUrl,
        material,
        supplier
      );
      drilled.push(...extracted);
    }
    return drilled;
  }

  return extractWithStagehand(stagehand, urlCandidate.url, material, supplier);
}

function buildFailureCandidate(
  material: any,
  supplier: SupplierTarget,
  result: { url: string; title?: string | null },
  reason: string,
  missingRequirement: string,
  confidence: number
) {
  return SupplierCandidateSchema.parse({
    item: material.item,
    supplier: supplier.name,
    productName: result.title || "Extraction failed",
    partNumber: null,
    productUrl: result.url,
    price: null,
    leadTime: null,
    pressure_rating_pa: null,
    volume_l: null,
    minimum_cda_m2: null,
    fluid_compatibility: [],
    oxygen_clean: null,
    cryogenic_compatible: null,
    matched_requirements: [],
    missing_requirements: [missingRequirement],
    failed_requirements: [],
    confidence,
    notes: reason
  });
}

function buildScoredCandidate(
  material: any,
  supplier: SupplierTarget,
  raw: Record<string, unknown>,
  fallback: { url: string; title?: string | null }
) {
  const enriched = enrichExtractedCandidate(
    {
      ...raw,
      productUrl: raw.productUrl ?? fallback.url
    },
    material,
    supplier.name
  );

  const scored = scoreCandidateAgainstRequirements(enriched, material);

  return SupplierCandidateSchema.parse({
    item: material.item,
    supplier: supplier.name,
    productName:
      (enriched.productName as string | undefined) ??
      fallback.title ??
      "Unknown product",
    partNumber: (enriched.partNumber as string | null | undefined) ?? null,
    productUrl: (enriched.productUrl as string | undefined) ?? fallback.url,
    price: (enriched.price as string | null | undefined) ?? null,
    leadTime: (enriched.leadTime as string | null | undefined) ?? null,
    pressure_rating_pa:
      (enriched.pressure_rating_pa as number | null | undefined) ?? null,
    volume_l: (enriched.volume_l as number | null | undefined) ?? null,
    minimum_cda_m2:
      (enriched.minimum_cda_m2 as number | null | undefined) ?? null,
    fluid_compatibility:
      (enriched.fluid_compatibility as string[] | undefined) ?? [],
    oxygen_clean: (enriched.oxygen_clean as boolean | null | undefined) ?? null,
    cryogenic_compatible:
      (enriched.cryogenic_compatible as boolean | null | undefined) ?? null,
    matched_requirements: scored.matched_requirements,
    missing_requirements: scored.missing_requirements,
    failed_requirements: scored.failed_requirements,
    confidence: scored.confidence,
    notes: (enriched.notes as string | undefined) ?? ""
  });
}

function loginFailureCandidate(
  material: any,
  supplier: SupplierTarget,
  loginNote: string,
  missingRequirement = "login_failed"
) {
  return buildFailureCandidate(
    material,
    supplier,
    {
      url: supplier.loginUrl ?? `https://${supplier.domain}`,
      title: `${supplier.name} login required`
    },
    loginNote,
    missingRequirement,
    0
  );
}

function loginFailureFromResult(
  material: any,
  supplier: SupplierTarget,
  loginResult: { reason?: LoginResult["reason"]; detail?: string }
) {
  const missingRequirement =
    loginResult.reason === "login_challenge_requires_interactive" ||
    loginResult.reason === "login_challenge_timeout"
      ? "login_challenge"
      : "login_failed";
  return loginFailureCandidate(
    material,
    supplier,
    loginFailureReasonMessage(loginResult.reason, loginResult.detail),
    missingRequirement
  );
}

async function acquireSupplierSession(
  bb: Browserbase,
  supplier: SupplierTarget,
  material: any,
  pool?: SupplierSessionPool
): Promise<{ stagehand: Stagehand | null; loginFailed: boolean; loginNote?: string; missingRequirement?: string }> {
  if (pool?.isBlocked(supplier.name)) {
    const blocked = pool.getBlockedResult(supplier.name)!;
    return {
      stagehand: null,
      loginFailed: true,
      loginNote: loginFailureReasonMessage(blocked.reason, blocked.detail),
      missingRequirement:
        blocked.reason === "login_challenge_requires_interactive" ||
        blocked.reason === "login_challenge_timeout"
          ? "login_challenge"
          : "login_failed"
    };
  }

  if (pool) {
    const acquired = await pool.acquire(bb, supplier, material.item);
    if (acquired.loginResult && !acquired.loginResult.ok && supplier.requiresLogin) {
      return {
        stagehand: null,
        loginFailed: true,
        loginNote: loginFailureReasonMessage(
          acquired.loginResult.reason,
          acquired.loginResult.detail
        ),
        missingRequirement:
          acquired.loginResult.reason === "login_challenge_requires_interactive" ||
          acquired.loginResult.reason === "login_challenge_timeout"
            ? "login_challenge"
            : "login_failed"
      };
    }
    if (!acquired.stagehand) {
      return {
        stagehand: null,
        loginFailed: true,
        loginNote: `${supplier.name} session unavailable`,
        missingRequirement: "login_failed"
      };
    }
    return { stagehand: acquired.stagehand, loginFailed: false };
  }

  const stagehand = await createStagehandSession(supplier);
  const loginResult = await ensureLoggedInWithRetry({
    bb,
    stagehand,
    supplier,
    runId: material.item
  });

  if (!loginResult.ok && supplier.requiresLogin) {
    await stagehand.close();
    return {
      stagehand: null,
      loginFailed: true,
      loginNote: loginFailureReasonMessage(loginResult.reason, loginResult.detail),
      missingRequirement:
        loginResult.reason === "login_challenge_requires_interactive" ||
        loginResult.reason === "login_challenge_timeout"
          ? "login_challenge"
          : "login_failed"
    };
  }

  return { stagehand, loginFailed: false };
}

async function requireAuthenticatedSession(
  bb: Browserbase,
  material: any,
  supplier: SupplierTarget,
  pool?: SupplierSessionPool
): Promise<
  | { ok: true; stagehand: Stagehand; ownsSession: boolean }
  | { ok: false; candidates: any[] }
> {
  const session = await acquireSupplierSession(bb, supplier, material, pool);
  if (session.loginFailed) {
    return {
      ok: false,
      candidates: [
        loginFailureCandidate(
          material,
          supplier,
          session.loginNote ?? "Supplier login failed",
          session.missingRequirement ?? "login_failed"
        )
      ]
    };
  }

  const stagehand = session.stagehand!;
  const stillLoggedIn = await verifyStillLoggedIn(stagehand, supplier);
  if (!stillLoggedIn) {
    const loginResult: LoginResult = {
      ok: false,
      reason: "login_failed",
      detail: `${supplier.name} session is not authenticated — logged-in pricing required`
    };
    pool?.markBlocked(supplier, loginResult);
    return {
      ok: false,
      candidates: [loginFailureFromResult(material, supplier, loginResult)]
    };
  }

  return { ok: true, stagehand, ownsSession: !pool };
}

async function searchOneSupplier(
  bb: Browserbase,
  material: any,
  supplier: SupplierTarget,
  pool?: SupplierSessionPool
): Promise<any[]> {
  if (supplier.requiresLogin && pool?.isBlocked(supplier.name)) {
    return [
      loginFailureFromResult(
        material,
        supplier,
        pool.getBlockedResult(supplier.name)!
      )
    ];
  }

  if (!supplier.requiresLogin) {
    const cached = loadCachedCandidates(material, supplier.name);
    if (cached) {
      return cached;
    }
  }

  let stagehand: Stagehand | null = null;
  let ownsSession = !pool;

  if (supplier.requiresLogin) {
    const auth = await requireAuthenticatedSession(bb, material, supplier, pool);
    if (!auth.ok) {
      return auth.candidates;
    }
    stagehand = auth.stagehand;
    ownsSession = auth.ownsSession;
  }

  const query = buildSupplierQuery(material, supplier);

  let searchResults: any = { results: [] };
  try {
    searchResults = await bb.search.web({
      query,
      numResults: SEARCH_RESULT_LIMIT
    });
  } catch (err) {
    return [
      buildFailureCandidate(
        material,
        supplier,
        { url: `https://${supplier.domain}`, title: "Search failed" },
        `Browserbase search failed for ${supplier.name}: ${String(err)}`,
        "search_failed",
        0
      )
    ];
  }

  const urlCandidates = collectSupplierUrls(material, supplier, searchResults);

  if (urlCandidates.length === 0) {
    return [
      buildFailureCandidate(
        material,
        supplier,
        { url: `https://${supplier.domain}`, title: "No extractable pages" },
        `Search returned only PDF/media URLs for ${supplier.name}`,
        "skipped_url",
        0
      )
    ];
  }

  const supplierCandidates: any[] = [];

  try {
    if (!supplier.requiresLogin) {
      const session = await acquireSupplierSession(bb, supplier, material, pool);
      if (session.loginFailed) {
        return [
          loginFailureCandidate(
            material,
            supplier,
            session.loginNote ?? "Supplier login failed",
            session.missingRequirement ?? "login_failed"
          )
        ];
      }
      stagehand = session.stagehand!;
    }

    if (!stagehand) {
      return [
        buildFailureCandidate(
          material,
          supplier,
          { url: `https://${supplier.domain}`, title: "Session unavailable" },
          `No browser session for ${supplier.name}`,
          "extraction_failed",
          0
        )
      ];
    }

    for (const urlCandidate of urlCandidates) {
      let extractedCandidates: any[] = [];

      try {
        extractedCandidates = await extractFromUrl(
          stagehand,
          urlCandidate,
          material,
          supplier
        );
      } catch (err) {
        supplierCandidates.push(
          buildFailureCandidate(
            material,
            supplier,
            urlCandidate,
            `Extraction failed: ${String(err)}`,
            "extraction_failed",
            0.05
          )
        );
        continue;
      }

      if (extractedCandidates.length === 0) {
        supplierCandidates.push(
          buildFailureCandidate(
            material,
            supplier,
            urlCandidate,
            `No purchasable products extracted from ${urlCandidate.url}`,
            "no_products_found",
            0.02
          )
        );
        continue;
      }

      for (const raw of extractedCandidates) {
        supplierCandidates.push(
          buildScoredCandidate(material, supplier, raw, urlCandidate)
        );
      }
    }
  } finally {
    if (ownsSession && stagehand) {
      await stagehand.close();
    }
  }

  if (!supplier.requiresLogin) {
    saveCacheableCandidates(material, supplier.name, supplierCandidates);
  }
  return supplierCandidates;
}

export function suppliersRequiringLogin(materials: { item: string }[]) {
  const names = new Set<string>();
  for (const material of materials) {
    for (const supplier of SUPPLIERS) {
      if (supplier.requiresLogin && supplierMatchesMaterial(supplier, material.item)) {
        names.add(supplier.name);
      }
    }
  }
  return SUPPLIERS.filter((s) => names.has(s.name));
}

export async function searchSuppliersForMaterial(
  bb: Browserbase,
  material: any,
  pool?: SupplierSessionPool
) {
  const matchingSuppliers = SUPPLIERS.filter((supplier) =>
    supplierMatchesMaterial(supplier, material.item)
  );

  let batches: any[][];
  if (supplierSearchParallel()) {
    batches = await Promise.all(
      matchingSuppliers.map((supplier) =>
        searchOneSupplier(bb, material, supplier, pool)
      )
    );
  } else {
    batches = [];
    for (const supplier of matchingSuppliers) {
      batches.push(await searchOneSupplier(bb, material, supplier, pool));
    }
  }

  const allCandidates = batches.flat();

  return rankProcurementCandidates(
    dedupeProcurementCandidates(allCandidates),
    material
  );
}
