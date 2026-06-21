const BLOCKED_MISSING_REQUIREMENTS = new Set([
  "extraction_failed",
  "search_failed",
  "skipped_url",
  "no_products_found",
  "login_failed",
  "login_challenge"
]);

export type ScoredRequirements = {
  matched_requirements: string[];
  missing_requirements: string[];
  failed_requirements: string[];
  confidence: number;
};

export function isViableProcurementCandidate(candidate: {
  missing_requirements?: string[];
}): boolean {
  return !(candidate.missing_requirements ?? []).some((req) =>
    BLOCKED_MISSING_REQUIREMENTS.has(req)
  );
}

export function isRfqEligibleCandidate(candidate: {
  missing_requirements?: string[];
  failed_requirements?: string[];
  partNumber?: string | null;
}): boolean {
  if (!isViableProcurementCandidate(candidate)) return false;
  if (!candidate.partNumber) return false;
  if ((candidate.failed_requirements ?? []).length > 0) return false;
  if ((candidate.missing_requirements ?? []).length > 0) return false;
  return true;
}

function candidateRankBoost(
  candidate: {
    productName?: string;
    partNumber?: string | null;
    notes?: string;
    matched_requirements?: string[];
    failed_requirements?: string[];
  },
  material?: { item: string }
): number {
  if (!material?.item.toLowerCase().includes("valve")) return 0;

  const itemLower = material.item.toLowerCase();
  const name = `${candidate.productName ?? ""} ${candidate.notes ?? ""}`.toLowerCase();
  const part = String(candidate.partNumber ?? "").toUpperCase();

  let boost = 0;

  if (name.includes("ball valve") || /SS-4\d.*GS|SS-43|SS-45/.test(part)) {
    boost += 0.2;
  }
  if (
    name.includes("needle") ||
    name.includes("metering") ||
    name.includes("regulating stem")
  ) {
    boost -= 0.15;
  }
  if (itemLower.includes("feed") && name.includes("ball")) {
    boost += 0.1;
  }
  if ((candidate.matched_requirements ?? []).includes("minimum_cda_m2")) {
    boost += 0.08;
  }
  boost -= (candidate.failed_requirements?.length ?? 0) * 0.08;

  return boost;
}

export function rankProcurementCandidates<
  T extends {
    confidence: number;
    missing_requirements?: string[];
    productName?: string;
    partNumber?: string | null;
    notes?: string;
    matched_requirements?: string[];
    failed_requirements?: string[];
  }
>(candidates: T[], material?: { item: string }): T[] {
  const viable = candidates.filter(isViableProcurementCandidate);
  const ranked = (viable.length > 0 ? viable : candidates).sort((a, b) => {
    const scoreA = a.confidence + candidateRankBoost(a, material);
    const scoreB = b.confidence + candidateRankBoost(b, material);
    return scoreB - scoreA;
  });
  return ranked.slice(0, 8);
}

export function dedupeProcurementCandidates<
  T extends {
    supplier: string;
    partNumber: string | null;
    productUrl: string;
    confidence: number;
  }
>(candidates: T[]): T[] {
  const byKey = new Map<string, T>();

  for (const candidate of candidates) {
    const key = candidate.partNumber
      ? `${candidate.supplier}:${candidate.partNumber}`
      : `${candidate.supplier}:${candidate.productUrl}`;

    const existing = byKey.get(key);
    if (!existing || candidate.confidence > existing.confidence) {
      byKey.set(key, candidate);
    }
  }

  return [...byKey.values()];
}

function includesIgnoreCase(values: string[], target: string): boolean {
  return values.some((value) =>
    value.toLowerCase().includes(target.toLowerCase())
  );
}

export function scoreCandidateAgainstRequirements(
  candidate: any,
  material: any
): ScoredRequirements {
  const req = material.requirements || {};

  const matched: string[] = [];
  const missing: string[] = [];
  const failed: string[] = [];

  const requiredPressure =
    req.minimum_pressure_rating_pa ?? req.pressure_rating_pa ?? null;

  if (requiredPressure) {
    if (!candidate.pressure_rating_pa) {
      missing.push("pressure_rating_pa");
    } else if (candidate.pressure_rating_pa >= requiredPressure) {
      matched.push("pressure_rating_pa");
    } else {
      failed.push("pressure_rating_pa");
    }
  }

  if (req.minimum_volume_l) {
    if (!candidate.volume_l) {
      missing.push("volume_l");
    } else if (candidate.volume_l >= req.minimum_volume_l) {
      matched.push("volume_l");
    } else {
      failed.push("volume_l");
    }
  }

  if (req.minimum_cda_m2) {
    if (!candidate.minimum_cda_m2) {
      missing.push("minimum_cda_m2");
    } else if (candidate.minimum_cda_m2 >= req.minimum_cda_m2) {
      matched.push("minimum_cda_m2");
    } else {
      failed.push("minimum_cda_m2");
    }
  }

  if (req.fluid) {
    const compat = candidate.fluid_compatibility || [];
    if (!compat.length) {
      missing.push("fluid_compatibility");
    } else if (includesIgnoreCase(compat, req.fluid)) {
      matched.push("fluid_compatibility");
    } else {
      failed.push("fluid_compatibility");
    }
  }

  if (Array.isArray(req.compatible_with) && req.compatible_with.length > 0) {
    const compat = candidate.fluid_compatibility || [];

    for (const requiredFluid of req.compatible_with) {
      if (!compat.length) {
        missing.push(`compatible_with:${requiredFluid}`);
      } else if (includesIgnoreCase(compat, requiredFluid)) {
        matched.push(`compatible_with:${requiredFluid}`);
      } else {
        failed.push(`compatible_with:${requiredFluid}`);
      }
    }
  }

  if (req.oxygen_clean === true) {
    if (candidate.oxygen_clean === true) {
      matched.push("oxygen_clean");
    } else if (candidate.oxygen_clean === false) {
      failed.push("oxygen_clean");
    } else {
      missing.push("oxygen_clean");
    }
  }

  if (req.cryogenic_compatible === true) {
    if (candidate.cryogenic_compatible === true) {
      matched.push("cryogenic_compatible");
    } else if (candidate.cryogenic_compatible === false) {
      failed.push("cryogenic_compatible");
    } else {
      missing.push("cryogenic_compatible");
    }
  }

  const totalChecks = matched.length + missing.length + failed.length || 1;

  const rawConfidence =
    matched.length / totalChecks -
    failed.length * 0.25 -
    missing.length * 0.1;

  return {
    matched_requirements: matched,
    missing_requirements: missing,
    failed_requirements: failed,
    confidence: Math.max(0, Math.min(1, rawConfidence))
  };
}
