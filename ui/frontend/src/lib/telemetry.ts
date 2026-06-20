import type { SampleRow } from "../types";

export function rowsByComponent(rows: SampleRow[]): Record<string, SampleRow[]> {
  return rows.reduce<Record<string, SampleRow[]>>((groups, row) => {
    if (!groups[row.component]) groups[row.component] = [];
    groups[row.component].push(row);
    return groups;
  }, {});
}

export function nearestSample(rows: SampleRow[] | undefined, time: number): SampleRow | undefined {
  if (!rows || rows.length === 0) return undefined;
  let best = rows[0];
  let bestDistance = Math.abs(best.time - time);
  for (const row of rows) {
    const distance = Math.abs(row.time - time);
    if (distance < bestDistance) {
      best = row;
      bestDistance = distance;
    }
  }
  return best;
}

export function interpolateSample(rows: SampleRow[] | undefined, time: number): SampleRow | undefined {
  if (!rows || rows.length === 0) return undefined;
  if (rows.length === 1) return rows[0];

  const ordered = [...rows].sort((a, b) => a.time - b.time);
  if (time <= ordered[0].time) return ordered[0];
  if (time >= ordered[ordered.length - 1].time) return ordered[ordered.length - 1];

  let lower = ordered[0];
  let upper = ordered[ordered.length - 1];
  for (let index = 1; index < ordered.length; index += 1) {
    if (ordered[index].time >= time) {
      lower = ordered[index - 1];
      upper = ordered[index];
      break;
    }
  }

  if (upper.time === lower.time) {
    return nearestSample([lower, upper], time);
  }

  const nearest = nearestSample([lower, upper], time) ?? lower;
  const fraction = (time - lower.time) / (upper.time - lower.time);
  const keys = new Set([...Object.keys(lower), ...Object.keys(upper)]);
  const interpolated: Record<string, string | number | null> = {};

  for (const key of keys) {
    const lowValue = lower[key];
    const highValue = upper[key];
    if (
      typeof lowValue === "number" &&
      Number.isFinite(lowValue) &&
      typeof highValue === "number" &&
      Number.isFinite(highValue)
    ) {
      interpolated[key] = lowValue + (highValue - lowValue) * fraction;
    } else {
      interpolated[key] = nearest[key] ?? null;
    }
  }

  return {
    ...interpolated,
    component: String(interpolated.component ?? nearest.component),
    kind: String(interpolated.kind ?? nearest.kind),
    time
  };
}

export function numericValue(row: SampleRow | undefined, key: string): number | undefined {
  const value = row?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function timeRange(...rowSets: SampleRow[][]): { min: number; max: number } {
  const times = rowSets.flat().map((row) => row.time);
  if (times.length === 0) return { min: 0, max: 0 };
  return { min: Math.min(...times), max: Math.max(...times) };
}
