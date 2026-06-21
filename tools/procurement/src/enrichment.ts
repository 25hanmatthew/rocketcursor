import { MCMASTER_BASE } from "./mcmasterCatalog.js";
import { swagelokProductUrl } from "./swagelokCatalog.js";
import {
  scoreCandidateAgainstRequirements,
  type ScoredRequirements
} from "./scoring.js";
import { SupplierCandidateSchema, type SupplierCandidate } from "./schemas.js";

const CV_TO_CDA_M2 = 8e-5;
const SCF_TO_LITERS = 28.316846592;

function parseCvFromNotes(notes?: string): number | null {
  if (!notes) return null;
  const match = notes.match(/\bCv(?:\s+Max)?\s*:?\s*(\d+(?:\.\d+)?)/i);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}

function partNumberFromUrl(url?: string | null): string | null {
  if (!url) return null;

  const swagelokMatch = url.match(/\/p\/([^/?#]+)/i);
  if (swagelokMatch) return decodeURIComponent(swagelokMatch[1]);

  try {
    const parsed = new URL(url);
    if (parsed.hostname.includes("mcmaster.com")) {
      const segment = parsed.pathname.replace(/^\//, "");
      if (/^[0-9a-z]{4,}$/i.test(segment)) return segment;
    }
  } catch {
    return null;
  }

  return null;
}

function parseGasCapacityLiters(...texts: Array<string | null | undefined>): number | null {
  const text = texts.filter(Boolean).join(" ");
  if (!text) return null;

  const hpMatch = text.match(/\bHP(\d+)\b/i);
  if (hpMatch) {
    const cuFt = Number(hpMatch[1]);
    if (Number.isFinite(cuFt)) return cuFt * SCF_TO_LITERS;
  }

  const cuFtMatch = text.match(/(\d+(?:\.\d+)?)\s*cu\.?\s*ft\.?\b/i);
  if (cuFtMatch) {
    const cuFt = Number(cuFtMatch[1]);
    if (Number.isFinite(cuFt)) return cuFt * SCF_TO_LITERS;
  }

  return null;
}

function cvToEstimatedCdaM2(cv: number): number {
  return cv * CV_TO_CDA_M2;
}

function inferOxygenClean(partNumber: string, notes: string): boolean | null {
  if (
    partNumber.includes("-SC11") ||
    partNumber.endsWith("SC11") ||
    notes.includes("SC-11")
  ) {
    return true;
  }
  if (partNumber.includes("-SC10") || notes.includes("SC-10")) {
    return false;
  }
  return null;
}

export function mcmasterProductUrl(partNumber: string): string {
  return `${MCMASTER_BASE}/${encodeURIComponent(partNumber)}`;
}

export function normalizeSupplierProductUrl(
  partNumber: string | null | undefined,
  productUrl: string | null | undefined,
  supplier?: string
): string | null {
  if (!partNumber) {
    return productUrl ?? null;
  }

  if (supplier === "McMaster-Carr" || productUrl?.includes("mcmaster.com")) {
    return mcmasterProductUrl(partNumber);
  }

  if (supplier === "Swagelok" || productUrl?.includes("swagelok.com")) {
    if (productUrl && /\/p\//.test(productUrl)) return productUrl;
    return swagelokProductUrl(partNumber);
  }

  return productUrl ?? null;
}

export function hasDirectProductUrl(candidate: {
  partNumber: string | null;
  productUrl: string;
  supplier: string;
}): boolean {
  if (!candidate.partNumber || !candidate.productUrl) return false;

  if (candidate.supplier === "McMaster-Carr") {
    return candidate.productUrl === mcmasterProductUrl(candidate.partNumber);
  }

  if (candidate.supplier === "Swagelok") {
    return (
      candidate.productUrl.includes("/p/") &&
      candidate.productUrl.includes(candidate.partNumber)
    );
  }

  try {
    const parsed = new URL(candidate.productUrl);
    return !parsed.pathname.startsWith("/products/");
  } catch {
    return false;
  }
}

export function enrichExtractedCandidate(
  raw: Record<string, unknown>,
  material: any,
  supplier?: string
) {
  const req = material.requirements || {};
  const enriched: Record<string, unknown> = { ...raw };
  const notes = String(enriched.notes ?? "");
  const productName = String(enriched.productName ?? "");

  if (!enriched.partNumber) {
    enriched.partNumber =
      partNumberFromUrl(enriched.productUrl as string | undefined) ??
      partNumberFromUrl(material._sourceUrl as string | undefined);
  }

  const partNumber = String(enriched.partNumber ?? "");
  if (enriched.oxygen_clean == null && partNumber) {
    const inferred = inferOxygenClean(partNumber, notes);
    if (inferred != null) enriched.oxygen_clean = inferred;
  }

  enriched.productUrl = normalizeSupplierProductUrl(
    (enriched.partNumber as string | null | undefined) ?? null,
    (enriched.productUrl as string | undefined) ?? null,
    supplier
  );

  if (!enriched.volume_l) {
    const parsedVolume = parseGasCapacityLiters(notes, productName);
    if (parsedVolume != null) enriched.volume_l = parsedVolume;
  }

  const cvMax =
    typeof enriched.cv_max === "number"
      ? enriched.cv_max
      : parseCvFromNotes(notes);

  if (cvMax && !enriched.minimum_cda_m2) {
    enriched.minimum_cda_m2 = cvToEstimatedCdaM2(cvMax);
    enriched.cv_max = cvMax;
  }

  const compat = Array.isArray(enriched.fluid_compatibility)
    ? [...(enriched.fluid_compatibility as string[])]
    : [];

  if (req.fluid && compat.length === 0) {
    const fluid = String(req.fluid);
    const oxygenClean = enriched.oxygen_clean === true;

    if (
      oxygenClean &&
      (fluid.toLowerCase() === "oxygen" ||
        partNumber.includes("-SC11") ||
        notes.includes("SC-11"))
    ) {
      enriched.fluid_compatibility = [fluid];
    }
  }

  return enriched;
}

export function refreshSupplierCandidate(
  candidate: SupplierCandidate,
  material: { item: string; requirements?: Record<string, unknown> }
): SupplierCandidate {
  const enriched = enrichExtractedCandidate(
    { ...candidate },
    material,
    candidate.supplier
  );
  const scored: ScoredRequirements = scoreCandidateAgainstRequirements(
    enriched,
    material
  );

  return SupplierCandidateSchema.parse({
    ...candidate,
    productUrl:
      (enriched.productUrl as string | undefined) ?? candidate.productUrl,
    volume_l: (enriched.volume_l as number | null | undefined) ?? candidate.volume_l,
    minimum_cda_m2:
      (enriched.minimum_cda_m2 as number | null | undefined) ??
      candidate.minimum_cda_m2,
    fluid_compatibility:
      (enriched.fluid_compatibility as string[] | undefined) ??
      candidate.fluid_compatibility,
    oxygen_clean:
      (enriched.oxygen_clean as boolean | null | undefined) ??
      candidate.oxygen_clean,
    matched_requirements: scored.matched_requirements,
    missing_requirements: scored.missing_requirements,
    failed_requirements: scored.failed_requirements,
    confidence: scored.confidence
  });
}
