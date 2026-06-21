import { describe, expect, it } from "vitest";
import { classifyFluid, isRocketLikeDiagram, visualStateFromSample } from "./pidViewModel";
import type { DiagramModel } from "../types";

describe("pidViewModel", () => {
  it("classifies rocket fluids into display categories", () => {
    expect(classifyFluid("Nitrogen")).toBe("pressurant");
    expect(classifyFluid("He")).toBe("pressurant");
    expect(classifyFluid("n-Dodecane")).toBe("fuel");
    expect(classifyFluid("RP-1")).toBe("fuel");
    expect(classifyFluid("LOX")).toBe("oxidizer");
    expect(classifyFluid("CombustionGas")).toBe("combined");
  });

  it("derives visual flow states from telemetry and status", () => {
    expect(visualStateFromSample({ component: "v", kind: "Connection", time: 0, mdot: 0.2, dP: 20_000, state: 1 })).toBe("flowing");
    expect(visualStateFromSample({ component: "v", kind: "Connection", time: 0, mdot: 0, state: 0 })).toBe("closed");
    expect(visualStateFromSample({ component: "v", kind: "Connection", time: 0, mdot: 0.2, state: 0 })).toBe("blocked");
    expect(visualStateFromSample({ component: "v", kind: "Connection", time: 0, mdot: 0.2, dP: 10, state: 1 })).toBe("lowPressure");
    expect(visualStateFromSample({ component: "v", kind: "Connection", time: 0, mdot: 0.2, state: 1 }, "red")).toBe("warning");
  });

  it("detects pressure-fed rocket diagrams", () => {
    const diagram: DiagramModel = {
      nodes: [
        { id: 1, name: "gn2", type: "Node", x: 0, y: 0, params: { fluid: "Nitrogen" } },
        { id: 2, name: "fuel", type: "Tank", x: 0, y: 0, params: { fluid_liq: "Kerosene", fluid_ullage: "Nitrogen" } },
        { id: 3, name: "lox", type: "Tank", x: 0, y: 0, params: { fluid_liq: "Oxygen", fluid_ullage: "Nitrogen" } },
        { id: 4, name: "engine", type: "Engine", x: 0, y: 0, params: {} }
      ],
      connections: [],
      bounds: { minX: -100, minY: -100, width: 200, height: 200 }
    };

    expect(isRocketLikeDiagram(diagram)).toBe(true);
    expect(isRocketLikeDiagram({ ...diagram, nodes: diagram.nodes.filter((node) => node.type !== "Engine") })).toBe(false);
  });
});

