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

    expect(html).not.toContain(">PT</text>");
    expect(html).toContain(">P: 500 psi</text>");
    expect(html).toContain(">T: 68 F</text>");
  });

  it("does not render internal particles inside tanks", () => {
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
        phase={0.25}
        onSelect={() => undefined}
      />
    );

    expect(html).not.toContain('class="node-particles"');
  });

  it("renders stable bouncing particles inside non-tank gas nodes", () => {
    const gasDiagram: DiagramModel = {
      nodes: [
        {
          id: 1,
          name: "gn2_node",
          type: "Node",
          x: 0,
          y: 0,
          params: {
            fluid: "Nitrogen",
            P: 2_000_000,
            T: 293.15,
            V: 1
          }
        }
      ],
      connections: [],
      bounds: { minX: -120, minY: -120, width: 240, height: 240 }
    };

    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={gasDiagram}
        nodeSamples={{
          gn2_node: [{ component: "gn2_node", kind: "Node", time: 0, P: 2_000_000, T: 293.15 }]
        }}
        connectionSamples={{}}
        selectedId={null}
        metric="P"
        time={0}
        phase={0.25}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain('class="node-particles"');
    expect(html).toContain('clip-path="url(#node-clip-1)"');
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
    expect(html).toContain(">PRESSURANT</span>");
    expect(html).toContain("fluid-pressurant");
    expect(html).toContain('fill="#67f085"');
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

  it("renders rocket-like diagrams with pressurant, fuel, oxidizer, and combined engine flow styling", () => {
    const rocketDiagram: DiagramModel = {
      nodes: [
        { id: 1, name: "gn2_supply", type: "Node", x: -500, y: 0, params: { fluid: "Nitrogen", P: 20_000_000 } },
        { id: 2, name: "fuel_tank", type: "Tank", x: -120, y: -160, params: { fluid_liq: "n-Dodecane", fluid_ullage: "Nitrogen" } },
        { id: 3, name: "lox_tank", type: "Tank", x: -120, y: 160, params: { fluid_liq: "Oxygen", fluid_ullage: "Nitrogen" } },
        { id: 4, name: "engine", type: "Engine", x: 460, y: 0, params: { fuel: "Kerosene", oxidizer: "LOX" } }
      ],
      connections: [
        { id: "pr_f_0", name: "press_fuel", type: "BangBang", startId: 1, endId: 2, params: { location: 1 } },
        { id: "pr_ox_0", name: "press_ox", type: "BangBang", startId: 1, endId: 3, params: { location: 1 } },
        { id: "fuel_feed_0", name: "fuel_feed", type: "Series", startId: 2, endId: 4, params: { connections: [{ type: "Line", params: { name: "fuel_line", location: 0 } }] } },
        { id: "ox_feed_0", name: "ox_feed", type: "Series", startId: 3, endId: 4, params: { connections: [{ type: "Line", params: { name: "ox_line", location: 0 } }] } }
      ],
      bounds: { minX: -700, minY: -260, width: 1300, height: 560 }
    };

    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={rocketDiagram}
        nodeSamples={{
          gn2_supply: [{ component: "gn2_supply", kind: "Node", time: 0, P: 20_000_000 }],
          fuel_tank: [tankRow(0, 0.8)],
          lox_tank: [{ component: "lox_tank", kind: "Tank", time: 0, fill_level: 0.8 }],
          engine: [{ component: "engine", kind: "Engine", time: 0, P: 2_000_000, T: 310, thrust: 1000 }]
        }}
        connectionSamples={{
          press_fuel: [{ component: "press_fuel", kind: "BangBang", time: 0, mdot: 0.04, dP: 10_000, state: 1 }],
          press_ox: [{ component: "press_ox", kind: "BangBang", time: 0, mdot: 0.04, dP: 10_000, state: 1 }],
          fuel_feed: [{ component: "fuel_feed", kind: "Series", time: 0, mdot: 0.2, dP: 10_000, state: 1 }],
          ox_feed: [{ component: "ox_feed", kind: "Series", time: 0, mdot: 0.25, dP: 10_000, state: 1 }]
        }}
        selectedId={null}
        metric="P"
        time={0}
        phase={0.25}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain("fluid-pressurant");
    expect(html).toContain("fluid-fuel");
    expect(html).toContain("fluid-oxidizer");
    expect(html).toContain("combined-engine-feed");
    expect(html).toContain("combined-flow-particle");
    expect(html).toContain("<title>FCV-F</title>");
    expect(html).toContain("<title>FIL-OX</title>");
  });

  it("keeps the engine and combined feed stable even when instantaneous propellant telemetry is idle", () => {
    const rocketDiagram: DiagramModel = {
      nodes: [
        { id: 1, name: "gn2_supply", type: "Node", x: -500, y: 0, params: { fluid: "Nitrogen", P: 20_000_000 } },
        { id: 2, name: "fuel_tank", type: "Tank", x: -120, y: -160, params: { fluid_liq: "n-Dodecane", fluid_ullage: "Nitrogen" } },
        { id: 3, name: "lox_tank", type: "Tank", x: -120, y: 160, params: { fluid_liq: "Oxygen", fluid_ullage: "Nitrogen" } },
        { id: 4, name: "engine", type: "Engine", x: 460, y: 0, params: { fuel: "Kerosene", oxidizer: "LOX" } }
      ],
      connections: [
        { id: "fuel_feed_0", name: "fuel_feed", type: "Series", startId: 2, endId: 4, params: { connections: [{ type: "Line", params: { name: "fuel_line", location: 0 } }] } },
        { id: "ox_feed_0", name: "ox_feed", type: "Series", startId: 3, endId: 4, params: { connections: [{ type: "Line", params: { name: "ox_line", location: 0 } }] } }
      ],
      bounds: { minX: -700, minY: -260, width: 1300, height: 560 }
    };

    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={rocketDiagram}
        nodeSamples={{
          gn2_supply: [{ component: "gn2_supply", kind: "Node", time: 0, P: 20_000_000 }],
          fuel_tank: [tankRow(0, 0.8)],
          lox_tank: [{ component: "lox_tank", kind: "Tank", time: 0, fill_level: 0.8 }],
          engine: [{ component: "engine", kind: "Engine", time: 0, P: 2_000_000, T: 310, thrust: 0 }]
        }}
        connectionSamples={{
          fuel_feed: [{ component: "fuel_feed", kind: "Series", time: 0, mdot: 0, state: 0 }],
          ox_feed: [{ component: "ox_feed", kind: "Series", time: 0, mdot: 0, state: 0 }]
        }}
        selectedId={null}
        metric="P"
        time={0}
        phase={0.25}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain("combined-engine-feed");
    expect(html).toContain("combined-flow-particle");
    expect(html).toContain("engine-flame");
  });

  it("suppresses flow particles and marks a closed valve on closed connections", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={{
          nodes: [
            { id: 1, name: "tank", type: "Tank", x: 0, y: 0, params: { fluid_liq: "n-Dodecane" } },
            { id: 2, name: "engine", type: "Engine", x: 180, y: 0, params: {} }
          ],
          connections: [{ id: "feed_0", name: "feed", type: "ThrottleValve", startId: 1, endId: 2, params: { name: "main_valve", location: 0 } }],
          bounds: { minX: -80, minY: -120, width: 340, height: 240 }
        }}
        nodeSamples={{
          tank: [tankRow(0, 0.8)],
          engine: [{ component: "engine", kind: "Engine", time: 0, P: 101325, T: 293.15, thrust: 0 }]
        }}
        connectionSamples={{
          feed: [{ component: "feed", kind: "ThrottleValve", time: 0, mdot: 0, state: 0 }]
        }}
        selectedId={null}
        metric="P"
        time={0}
        phase={0}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain("pipe-run is-closed");
    expect(html).toContain("series-component component-valve is-closed");
    expect(html).not.toContain('class="flow-particle"');
  });

  it("keeps pressurant flow steady when controller state is false but mdot is nonzero", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={{
          nodes: [
            { id: 1, name: "gn2", type: "Node", x: -180, y: 0, params: { fluid: "Nitrogen", P: 20_000_000 } },
            { id: 2, name: "fuel_tank", type: "Tank", x: 0, y: 0, params: { fluid_liq: "n-Dodecane", fluid_ullage: "Nitrogen" } }
          ],
          connections: [{ id: "press_0", name: "press", type: "BangBang", startId: 1, endId: 2, params: { location: 1 } }],
          bounds: { minX: -260, minY: -120, width: 520, height: 240 }
        }}
        nodeSamples={{
          gn2: [{ component: "gn2", kind: "Node", time: 0, P: 20_000_000, T: 293.15 }],
          fuel_tank: [tankRow(0, 0.8)]
        }}
        connectionSamples={{
          press: [{ component: "press", kind: "BangBang", time: 0, mdot: 0.04, dP: 10_000, state: "False" }]
        }}
        selectedId={null}
        metric="P"
        time={0}
        phase={0.25}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain("pipe-run is-flowing fluid-pressurant");
    expect(html).not.toContain("pipe-run is-blocked");
    expect(html).not.toContain("component-valve is-closed");
    expect(html).toContain('class="flow-particle"');
  });

  it("renders warning classes for components referenced by nodeStatus", () => {
    const html = renderToStaticMarkup(
      <PidCanvas
        diagram={{
          nodes: [
            { id: 1, name: "tank", type: "Tank", x: 0, y: 0, params: { fluid_liq: "n-Dodecane" } },
            { id: 2, name: "engine", type: "Engine", x: 180, y: 0, params: {} }
          ],
          connections: [{ id: "feed_0", name: "feed", type: "Connection", startId: 1, endId: 2, params: { location: 0 } }],
          bounds: { minX: -80, minY: -120, width: 340, height: 240 }
        }}
        nodeSamples={{
          tank: [tankRow(0, 0.8)],
          engine: [{ component: "engine", kind: "Engine", time: 0, P: 101325, T: 293.15, thrust: 0 }]
        }}
        connectionSamples={{
          feed: [{ component: "feed", kind: "Connection", time: 0, mdot: 0.1, dP: 10_000, state: 1 }]
        }}
        selectedId={null}
        metric="P"
        time={0}
        phase={0}
        nodeStatus={{ tank: "red", feed: "red" }}
        onSelect={() => undefined}
      />
    );

    expect(html).toContain("pipe-run is-warning");
    expect(html).toContain("pid-node is-warning");
    expect(html).toContain("pipe-warning-pulse");
  });
});
