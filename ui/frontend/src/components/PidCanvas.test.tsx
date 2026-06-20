import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PidCanvas } from "./PidCanvas";
import type { DiagramModel, SampleRow } from "../types";

const diagram: DiagramModel = {
  nodes: [
    {
      id: 1,
      name: "kerosene_tank",
      type: "Tank",
      x: 0,
      y: 0,
      params: {}
    }
  ],
  connections: [],
  bounds: {
    minX: -120,
    minY: -120,
    width: 240,
    height: 240
  }
};

function tankRow(time: number, fillLevel: number): SampleRow {
  return {
    component: "kerosene_tank",
    kind: "Tank",
    time,
    fill_level: fillLevel
  };
}

describe("PidCanvas tank fill", () => {
  it("renders tank liquid height from interpolated physical fill_level", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={diagram}
        nodeSamples={{ kerosene_tank: [tankRow(0, 1), tankRow(2, 0)] }}
        connectionSamples={{}}
        selectedId={null}
        metric="P"
        time={1}
        phase={0}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain('height="56"');
    expect(html).toContain(">50.0%</text>");
  });

  it("keeps test_1-style tank fill near the exported physical value", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={diagram}
        nodeSamples={{
          kerosene_tank: [tankRow(0, 0.8063287557694353), tankRow(20, 0.8063867909773668)]
        }}
        connectionSamples={{}}
        selectedId={null}
        metric="P"
        time={10}
        phase={0}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain(">80.6%</text>");
  });

  it("renders node pressure in psi and temperature in Fahrenheit", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={diagram}
        nodeSamples={{
          kerosene_tank: [
            {
              ...tankRow(0, 0.8),
              P: 3447378.646584,
              T: 293.15
            }
          ]
        }}
        connectionSamples={{}}
        selectedId={null}
        metric="P"
        time={0}
        phase={0}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain(">Pressure: 500 psi</text>");
    expect(html).toContain(">Temperature: 68 F</text>");
  });

  it("hides part labels by default and shows them when enabled", () => {
    const hiddenHtml = renderToStaticMarkup(
      <PidCanvas
        diagram={diagram}
        nodeSamples={{ kerosene_tank: [tankRow(0, 0.8)] }}
        connectionSamples={{}}
        selectedId={null}
        metric="P"
        time={0}
        phase={0}
        onSelect={() => undefined}
      />
    );
    const shownHtml = renderToStaticMarkup(
      <PidCanvas
        diagram={diagram}
        nodeSamples={{ kerosene_tank: [tankRow(0, 0.8)] }}
        connectionSamples={{}}
        selectedId={null}
        metric="P"
        time={0}
        phase={0}
        showPartLabels
        onSelect={() => undefined}
      />
    );

    expect(hiddenHtml).not.toContain(">kerosene_tank</text>");
    expect(shownHtml).toContain(">kerosene_tank</text>");
  });

  it("renders a flow key and colors tank ullage flow by inferred fluid", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={{
          nodes: [
            {
              id: 1,
              name: "kerosene_tank",
              type: "Tank",
              x: 0,
              y: 0,
              params: {
                fluid_liq: "n-Dodecane",
                fluid_ullage: "Nitrogen"
              }
            },
            {
              id: 2,
              name: "ambient",
              type: "Ambient",
              x: 0,
              y: 180,
              params: {
                fluid: "Air"
              }
            }
          ],
          connections: [
            {
              id: "vent_0",
              name: "vent",
              type: "Connection",
              startId: 1,
              endId: 2,
              params: {
                location: 1
              }
            }
          ],
          bounds: {
            minX: -180,
            minY: -120,
            width: 360,
            height: 420
          }
        }}
        nodeSamples={{
          kerosene_tank: [tankRow(0, 0.8)],
          ambient: [{ component: "ambient", kind: "Ambient", time: 0, P: 101325, T: 293.15 }]
        }}
        connectionSamples={{
          vent: [{ component: "vent", kind: "Connection", time: 0, mdot: 0.1, state: 1 }]
        }}
        selectedId={null}
        metric="P"
        time={0}
        phase={0}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain("Flow key");
    expect(html).toContain(">Nitrogen</span>");
    // Pipes are neutral metal; fluid identity is carried by the flowing particles.
    expect(html).toContain('fill="#2563eb"');
  });

  it("renders series subcomponents instead of a generic series count", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={{
          nodes: [
            { id: 1, name: "tank", type: "Tank", x: 0, y: 0, params: {} },
            { id: 2, name: "engine", type: "Engine", x: 180, y: 0, params: {} }
          ],
          connections: [
            {
              id: "feed_0",
              name: "feed",
              type: "Series",
              startId: 1,
              endId: 2,
              params: {
                connections: [
                  { type: "Line", params: { name: "feed_line" } },
                  { type: "Connection", params: { name: "injector" } }
                ]
              }
            }
          ],
          bounds: { minX: -80, minY: -120, width: 340, height: 240 }
        }}
        nodeSamples={{
          tank: [tankRow(0, 0.8)],
          engine: [{ component: "engine", kind: "Engine", time: 0, P: 101325, T: 293.15, thrust: 0 }]
        }}
        connectionSamples={{
          feed: [{ component: "feed", kind: "Series", time: 0, mdot: 0.1, state: 1 }]
        }}
        selectedId={null}
        metric="P"
        time={0}
        phase={0}
        onSelect={() => undefined}
      />
    );

    expect(html).not.toContain("2 in series");
    expect(html).toContain("<title>feed_line</title>");
    expect(html).toContain("<title>injector</title>");
  });
});
