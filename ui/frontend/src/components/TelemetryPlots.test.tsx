import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { TelemetryPlots, telemetryPlotSpecsForRows, telemetrySeries } from "./TelemetryPlots";
import type { SampleRow } from "../types";

const PA_PER_PSI = 6894.757293168;

function row(fields: Partial<SampleRow>): SampleRow {
  return {
    component: "component",
    kind: "Node",
    time: 0,
    ...fields
  };
}

describe("TelemetryPlots", () => {
  it("selects pressure, temperature, and mass-flow plots when present", () => {
    const rows = [
      row({ time: 0, P: 100 * PA_PER_PSI, T: 293.15, mdot: 0.1 }),
      row({ time: 1, P: 120 * PA_PER_PSI, T: 303.15, mdot: 0.2 })
    ];

    expect(telemetryPlotSpecsForRows(rows).map((spec) => spec.field)).toEqual(["P", "T", "mdot"]);
  });

  it("converts pressure to psi and temperature to Fahrenheit", () => {
    const rows = [
      row({ time: 0, P: 100 * PA_PER_PSI, T: 293.15 }),
      row({ time: 1, P: 200 * PA_PER_PSI, T: 303.15 })
    ];
    const [pressureSpec, temperatureSpec] = telemetryPlotSpecsForRows(rows);

    expect(telemetrySeries(rows, pressureSpec).map((point) => point.value)).toEqual([100, 200]);
    expect(telemetrySeries(rows, temperatureSpec).map((point) => point.value)).toEqual([68, 86]);
  });

  it("uses oxidizer and fuel mass flow for engine rows when plain mdot is absent", () => {
    const rows = [
      row({ kind: "Engine", time: 0, mdot_ox: 0.4, mdot_fu: 0.2 }),
      row({ kind: "Engine", time: 1, mdot_ox: 0.5, mdot_fu: 0.25 })
    ];

    expect(telemetryPlotSpecsForRows(rows).map((spec) => spec.field)).toEqual(["mdot_ox", "mdot_fu"]);
  });

  it("omits missing fields without crashing", () => {
    const html = renderToStaticMarkup(
      <TelemetryPlots
        rows={[row({ time: 0, P: 100 * PA_PER_PSI }), row({ time: 1, P: 110 * PA_PER_PSI })]}
        currentSample={row({ time: 0.5, P: 105 * PA_PER_PSI })}
        time={0.5}
      />
    );

    expect(html).toContain("Pressure vs time");
    expect(html).not.toContain("Temperature vs time");
    expect(html).not.toContain("Mass flow vs time");
  });

  it("renders current values and a current-time cursor", () => {
    const html = renderToStaticMarkup(
      <TelemetryPlots
        rows={[
          row({ time: 0, P: 100 * PA_PER_PSI, T: 293.15, mdot: 0.1 }),
          row({ time: 1, P: 120 * PA_PER_PSI, T: 303.15, mdot: 0.2 })
        ]}
        currentSample={row({ time: 0.5, P: 110 * PA_PER_PSI, T: 298.15, mdot: 0.15 })}
        time={0.5}
      />
    );

    expect(html).toContain("110");
    expect(html).toContain("77");
    expect(html).toContain("0.15");
    expect(html).toContain("class=\"telemetry-cursor\"");
  });
});
