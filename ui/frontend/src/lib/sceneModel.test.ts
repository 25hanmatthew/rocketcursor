import { describe, expect, it } from "vitest";
import { buildDiagram } from "./diagram";
import { buildSceneModel } from "./sceneModel";
import type { NetworkConfig } from "../types";

/* A minimal pressure-fed LOX/kerosene stack: GN2 bottle pressurises two tanks
   that feed an engine, mirroring loop/design_seeds/pressure_fed_lox_kerosene. */
const ROCKET: NetworkConfig = {
  nodes: [
    { id: 0, type: "Node", x: 0, y: 0, params: { fluid: "Nitrogen", V: 18, name: "gn2_tank" } },
    { id: 1, type: "Tank", x: -220, y: 220, params: { V_total_L: 20, fluid_liq: "Oxygen", name: "lox_tank" } },
    { id: 2, type: "Tank", x: 220, y: 220, params: { V_total_L: 16, fluid_liq: "n-Dodecane", name: "kerosene_tank" } },
    { id: 3, type: "Engine", x: 0, y: 440, params: { name: "engine", fuel: "RP-1", oxidizer: "LOX" } }
  ],
  connections: [
    { type: "Regulator", start_id: 0, end_id: 1, params: { name: "lox_press" } },
    { type: "Regulator", start_id: 0, end_id: 2, params: { name: "fuel_press" } },
    { type: "Connection", start_id: 1, end_id: 3, params: { name: "ox_feed" } },
    { type: "Connection", start_id: 2, end_id: 3, params: { name: "fuel_feed" } }
  ]
};

describe("buildSceneModel", () => {
  const scene = buildSceneModel(buildDiagram(ROCKET))!;

  it("returns null for an empty diagram", () => {
    expect(buildSceneModel(null)).toBeNull();
    expect(buildSceneModel({ nodes: [], connections: [], bounds: { minX: 0, minY: 0, width: 0, height: 0 } })).toBeNull();
  });

  it("detects a rocket-like network", () => {
    expect(scene.rocketLike).toBe(true);
  });

  it("classifies fluids by source node", () => {
    const byName = Object.fromEntries(scene.nodes.map((n) => [n.name, n.fluid]));
    expect(byName.lox_tank).toBe("oxidizer");
    expect(byName.kerosene_tank).toBe("fuel");
    expect(byName.gn2_tank).toBe("pressurant");
    const oxFeed = scene.connections.find((c) => c.name === "ox_feed");
    expect(oxFeed?.fluid).toBe("oxidizer");
  });

  it("stacks the engine below the pressurant for rocket-like flow", () => {
    const engine = scene.nodes.find((n) => n.type === "Engine")!;
    const bottle = scene.nodes.find((n) => n.name === "gn2_tank")!;
    expect(engine.position.y).toBeLessThan(bottle.position.y);
  });

  it("flags regulators as valve-like and feeds as not", () => {
    const reg = scene.connections.find((c) => c.name === "lox_press");
    const feed = scene.connections.find((c) => c.name === "ox_feed");
    expect(reg?.valveLike).toBe(true);
    expect(feed?.valveLike).toBe(false);
  });

  it("keeps tank geometry within clamped bounds", () => {
    for (const node of scene.nodes) {
      expect(node.radius).toBeGreaterThan(0);
      expect(node.radius).toBeLessThan(1.5);
      expect(node.height).toBeLessThan(4);
    }
  });
});
