// Flight telemetry: parse flight.csv (the 6DOF result contract) and interpolate
// a single time series by time. Mirrors lib/telemetry.ts but for the flat,
// single-entity flight row shape (no per-component grouping).

export interface FlightRow {
  time: number;
  position_x: number;
  position_y: number;
  position_z: number;
  altitude: number;
  quaternion_w: number;
  quaternion_x: number;
  quaternion_y: number;
  quaternion_z: number;
  velocity_x: number;
  velocity_y: number;
  velocity_z: number;
  mach: number;
  dynamic_pressure: number;
  angle_of_attack: number;
  mass: number;
  thrust: number;
  [key: string]: number;
}

export interface FlightEvents {
  ignition: number | null;
  rail_departure: number | null;
  maximum_dynamic_pressure: number | null;
  burnout: number | null;
  apogee: number | null;
  parachute_deployment: number | null;
  landing: number | null;
}

export function parseFlightCsv(text: string): FlightRow[] {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const header = lines[0].split(",");
  const rows: FlightRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",");
    const row = {} as FlightRow;
    header.forEach((key, j) => {
      row[key] = Number(cols[j]);
    });
    rows.push(row);
  }
  return rows;
}

export function flightTimeRange(rows: FlightRow[]): { min: number; max: number } {
  if (!rows.length) return { min: 0, max: 0 };
  return { min: rows[0].time, max: rows[rows.length - 1].time };
}

// Linear interpolation of every numeric field at `t` (nearest at the ends).
export function interpolateFlight(rows: FlightRow[], t: number): FlightRow | undefined {
  if (!rows.length) return undefined;
  if (t <= rows[0].time) return rows[0];
  if (t >= rows[rows.length - 1].time) return rows[rows.length - 1];
  let lo = 0;
  let hi = rows.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].time <= t) lo = mid;
    else hi = mid;
  }
  const a = rows[lo];
  const b = rows[hi];
  const span = b.time - a.time || 1;
  const f = (t - a.time) / span;
  const out = {} as FlightRow;
  for (const key of Object.keys(a)) {
    out[key] = a[key] + (b[key] - a[key]) * f;
  }
  return out;
}
