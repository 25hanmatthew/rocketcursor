import type { SampleRow } from "../types";

function splitCsvLine(line: string): string[] {
  const values: string[] = [];
  let current = "";
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];
    if (char === '"' && quoted && next === '"') {
      current += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      values.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  values.push(current);
  return values;
}

function parseValue(value: string): string | number | null {
  if (value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : value;
}

export function parseSamplesCsv(csv: string): SampleRow[] {
  const lines = csv.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return [];

  const headers = splitCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = splitCsvLine(line);
    const row: Record<string, string | number | null> = {};
    headers.forEach((header, index) => {
      row[header] = parseValue(values[index] ?? "");
    });
    return {
      ...row,
      component: String(row.component ?? ""),
      kind: String(row.kind ?? ""),
      time: Number(row.time ?? 0)
    };
  });
}
