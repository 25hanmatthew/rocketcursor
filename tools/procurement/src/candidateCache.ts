import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { SupplierCandidateSchema, type SupplierCandidate } from "./schemas.js";
import {
  isRfqEligibleCandidate,
  isViableProcurementCandidate
} from "./scoring.js";
import {
  hasDirectProductUrl,
  refreshSupplierCandidate
} from "./enrichment.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const CACHE_DIR = path.join(repoRoot, "results/procurement_cache");
const CACHE_FILE = path.join(CACHE_DIR, "candidates.json");

const MIN_CACHE_CONFIDENCE = 0.25;
const CACHE_VERSION = 3;

type CacheFile = {
  version: typeof CACHE_VERSION;
  entries: CacheEntry[];
};

type CacheEntry = {
  key: string;
  cachedAt: string;
  materialItem: string;
  supplier: string;
  requirementsHash: string;
  candidates: SupplierCandidate[];
};

function cacheDisabled(): boolean {
  return process.env.PROCUREMENT_CACHE === "0";
}

function stableRequirementsHash(requirements: Record<string, unknown>): string {
  return createHash("sha256")
    .update(JSON.stringify(requirements, Object.keys(requirements).sort()))
    .digest("hex")
    .slice(0, 16);
}

export function procurementCacheKey(
  material: { item: string; requirements?: Record<string, unknown> },
  supplier: string
): string {
  const requirements = material.requirements ?? {};
  return `${supplier}:${material.item}:${stableRequirementsHash(requirements)}`;
}

export function isCacheableCandidate(candidate: SupplierCandidate): boolean {
  return (
    isRfqEligibleCandidate(candidate) &&
    hasDirectProductUrl(candidate) &&
    candidate.confidence >= MIN_CACHE_CONFIDENCE &&
    !candidate.missing_requirements.includes("extraction_failed")
  );
}

function readCacheFile(): CacheFile {
  if (!fs.existsSync(CACHE_FILE)) {
    return { version: CACHE_VERSION, entries: [] };
  }

  try {
    const parsed = JSON.parse(fs.readFileSync(CACHE_FILE, "utf-8")) as CacheFile;
    if (parsed.version !== CACHE_VERSION || !Array.isArray(parsed.entries)) {
      return { version: CACHE_VERSION, entries: [] };
    }
    return parsed;
  } catch {
    return { version: CACHE_VERSION, entries: [] };
  }
}

function writeCacheFile(cache: CacheFile) {
  fs.mkdirSync(CACHE_DIR, { recursive: true });
  fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2));
}

export function loadCachedCandidates(
  material: { item: string; requirements?: Record<string, unknown> },
  supplier: string
): SupplierCandidate[] | null {
  if (cacheDisabled()) return null;

  const key = procurementCacheKey(material, supplier);
  const cache = readCacheFile();
  const entry = cache.entries.find((row) => row.key === key);
  if (!entry) return null;

  const candidates = entry.candidates
    .map((candidate) => SupplierCandidateSchema.safeParse(candidate))
    .filter((result) => result.success)
    .map((result) => {
      const refreshed = refreshSupplierCandidate(result.data, material);
      return {
        ...refreshed,
        notes: `[cached ${entry.cachedAt}] ${refreshed.notes}`.trim()
      };
    })
    .filter(isCacheableCandidate);

  return candidates.length > 0 ? candidates : null;
}

export function saveCacheableCandidates(
  material: { item: string; requirements?: Record<string, unknown> },
  supplier: string,
  candidates: SupplierCandidate[]
) {
  if (cacheDisabled()) return;

  const cacheable = candidates
    .map((candidate) => refreshSupplierCandidate(candidate, material))
    .filter(isCacheableCandidate);

  if (cacheable.length === 0) return;

  const key = procurementCacheKey(material, supplier);
  const cache = readCacheFile();
  const requirements = material.requirements ?? {};
  const entry: CacheEntry = {
    key,
    cachedAt: new Date().toISOString(),
    materialItem: material.item,
    supplier,
    requirementsHash: stableRequirementsHash(requirements),
    candidates: cacheable
  };

  const nextEntries = cache.entries.filter((row) => row.key !== key);
  nextEntries.push(entry);
  writeCacheFile({ version: CACHE_VERSION, entries: nextEntries });
}
