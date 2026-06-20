import { describe, expect, it } from "vitest";
import { parseSamplesCsv } from "./csv";
import { interpolateSample, nearestSample, numericValue, rowsByComponent, timeRange } from "./telemetry";

describe("telemetry helpers", () => {
  it("parses csv and finds nearest component samples", () => {
    const rows = parseSamplesCsv("component,kind,time,mdot\nvent,Connection,0,1\nvent,Connection,1,3\n");
    const grouped = rowsByComponent(rows);
    expect(nearestSample(grouped.vent, 0.8)?.mdot).toBe(3);
    expect(timeRange(rows)).toEqual({ min: 0, max: 1 });
  });

  it("interpolates numeric sample fields at exact and in-between times", () => {
    const rows = parseSamplesCsv(
      "component,kind,time,fill_level,m_l\nkerosene_tank,Tank,0,1,10\nkerosene_tank,Tank,2,0.5,5\n"
    );

    expect(numericValue(interpolateSample(rows, 0), "fill_level")).toBe(1);
    expect(numericValue(interpolateSample(rows, 1), "fill_level")).toBe(0.75);
    expect(numericValue(interpolateSample(rows, 1), "m_l")).toBe(7.5);
  });

  it("clamps interpolation outside available sample time", () => {
    const rows = parseSamplesCsv(
      "component,kind,time,fill_level\nkerosene_tank,Tank,5,0.8\nkerosene_tank,Tank,10,0.4\n"
    );

    expect(numericValue(interpolateSample(rows, 0), "fill_level")).toBe(0.8);
    expect(numericValue(interpolateSample(rows, 20), "fill_level")).toBe(0.4);
  });

  it("lets missing fill levels fall back to zero at render call sites", () => {
    const rows = parseSamplesCsv("component,kind,time,P\nempty,Tank,0,100\nempty,Tank,1,200\n");
    expect(numericValue(interpolateSample(rows, 0.5), "fill_level") ?? 0).toBe(0);
  });

  it("keeps physical fill nearly constant when exported tank liquid mass is constant", () => {
    const rows = parseSamplesCsv(
      "component,kind,time,fill_level,m_l\nkerosene_tank_500psi,Tank,0,0.8063287557694353,9.7\nkerosene_tank_500psi,Tank,20,0.8063867909773668,9.7\n"
    );

    const mid = interpolateSample(rows, 10);
    expect(numericValue(mid, "fill_level")).toBeCloseTo(0.806357773373401, 12);
    expect(numericValue(mid, "m_l")).toBe(9.7);
  });
});
