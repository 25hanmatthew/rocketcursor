import { describe, expect, it } from "vitest";
import { buildDiagram } from "./diagram";
import type { NetworkConfig } from "../types";

describe("buildDiagram", () => {
  it("uses explicit node coordinates", () => {
    const diagram = buildDiagram({
      nodes: [
        { id: 0, type: "Node", x: -10, y: 5, params: { name: "tank" } },
        { id: 1, type: "Ambient", x: 100, y: 5, params: { name: "atm" } }
      ],
      connections: [{ type: "Connection", start_id: 0, end_id: 1, params: { name: "vent" } }]
    });
    expect(diagram.nodes[0].x).toBe(-10);
    expect(diagram.connections[0].name).toBe("vent");
  });

  it("auto-lays out configs without coordinates", () => {
    const config: NetworkConfig = {
      nodes: [
        { id: 0, type: "Node", params: { name: "a" } },
        { id: 1, type: "Node", params: { name: "b" } }
      ],
      connections: [{ type: "Line", start_id: 0, end_id: 1, params: { name: "pipe" } }]
    };
    const diagram = buildDiagram(config);
    expect(diagram.nodes[1].x).toBeGreaterThan(diagram.nodes[0].x);
  });
});
