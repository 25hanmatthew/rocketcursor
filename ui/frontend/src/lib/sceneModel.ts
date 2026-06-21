import type { DiagramConnection, DiagramModel, DiagramNode, NodeType } from "../types";
import { classifyFluid, isRocketLikeDiagram, nodeFluidName, type VisualFluid } from "./pidViewModel";

/* sceneModel: the only irreducible adapter for the 3D twin.

   It turns the already-laid-out 2D DiagramModel (topological levels from
   diagram.ts:autoLayout, or explicit x/y) into 3D world transforms, plus
   per-component geometry sizing derived from design params. It carries NO
   telemetry — Twin3D reads interpolated samples at scrub time and feeds those
   into the meshes. Keep this pure + deterministic so 2D and 3D never disagree
   about where a component lives or what fluid it carries. */

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface SceneNode {
  id: number;
  name: string;
  type: NodeType;
  fluid: VisualFluid;
  position: Vec3;
  /* Geometry sizing (world units), derived from design params so a 50 L tank
     reads bigger than a 5 L bottle. Tanks render as capped cylinders; the
     engine as a bell; other nodes as bottles/spheres. */
  radius: number;
  height: number;
}

export interface SceneConnection {
  id: string;
  name: string;
  type: DiagramConnection["type"];
  fluid: VisualFluid;
  start: Vec3;
  end: Vec3;
  /* A connection is "valve-like" if its type can gate flow — we drop a valve
     marker on it and let its open/closed state drive the visual. */
  valveLike: boolean;
}

export interface SceneModel {
  nodes: SceneNode[];
  connections: SceneConnection[];
  rocketLike: boolean;
  /* Radius of the bounding sphere around the centred model — handy for framing
     the camera so any network fits without manual tuning. */
  extent: number;
}

const VALVE_TYPES = new Set<DiagramConnection["type"]>(["Regulator", "BangBang", "ThrottleValve"]);

/* 2D layout steps are ~280 px between flow levels / ~180 px across a level.
   Divide into a few world units so a typical network spans ~4-8 units. */
const WORLD_SCALE = 1 / 110;

function numericParam(params: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = params[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

/* Approximate tank volume in litres from whatever the design provides
   (volume_L, or V in m^3). Used only for relative sizing, not physics. */
function volumeLitres(node: DiagramNode): number | undefined {
  const litres = numericParam(node.params, "V_total_L", "volume_L", "V_L", "volume_l");
  if (litres !== undefined) return litres;
  const cubicMetres = numericParam(node.params, "V", "volume_m3", "volume");
  return cubicMetres !== undefined ? cubicMetres * 1000 : undefined;
}

function sizeFor(node: DiagramNode): { radius: number; height: number } {
  if (node.type === "Engine") return { radius: 0.42, height: 0.9 };
  if (node.type === "Ambient") return { radius: 0.3, height: 0.3 };
  // Generic source nodes (e.g. a gas pressurant bottle): V semantics are
  // unreliable (litres vs m^3) and a big bottle shouldn't dominate the
  // propellant tanks, so use a modest fixed size.
  if (node.type !== "Tank") return { radius: 0.32, height: 1.0 };
  // Tanks: scale gently off volume around a 20 L baseline, clamped hard since
  // sizing is a visual cue, never load-bearing.
  const litres = volumeLitres(node) ?? 20;
  const scale = Math.max(0.7, Math.min(1.6, Math.cbrt(Math.max(litres, 1) / 20)));
  return { radius: 0.45 * scale, height: 1.7 * scale };
}

const LEVEL_GAP = 2.0; // world units between flow levels in a rocket stack
const SIBLING_GAP = 2.0; // world units between parallel branches at one level

/* Rocket-like layout from topology, not from the (noisily-authored) 2D coords:
   BFS depth from the source nodes places pressurant/sources at the top and the
   engine at the bottom, with parallel branches (ox vs fuel) spread sideways.
   This is robust to whichever axis the 2D layout happened to use for flow. */
function rocketLayout(diagram: DiagramModel): Map<number, Vec3> {
  const incoming = new Map<number, number>();
  const outgoing = new Map<number, number[]>();
  for (const node of diagram.nodes) {
    incoming.set(node.id, 0);
    outgoing.set(node.id, []);
  }
  for (const connection of diagram.connections) {
    incoming.set(connection.endId, (incoming.get(connection.endId) ?? 0) + 1);
    outgoing.get(connection.startId)?.push(connection.endId);
  }

  const depth = new Map<number, number>(diagram.nodes.map((node) => [node.id, 0]));
  const queue = diagram.nodes.filter((node) => (incoming.get(node.id) ?? 0) === 0).map((node) => node.id);
  while (queue.length > 0) {
    const id = queue.shift()!;
    const base = depth.get(id) ?? 0;
    for (const next of outgoing.get(id) ?? []) {
      if ((depth.get(next) ?? 0) <= base) {
        depth.set(next, base + 1);
        queue.push(next);
      }
    }
  }

  // Stable sibling order off the original 2D coords so left/right stays sensible.
  const byDepth = new Map<number, number[]>();
  for (const node of [...diagram.nodes].sort((a, b) => a.x - b.x || a.y - b.y)) {
    const d = depth.get(node.id) ?? 0;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(node.id);
  }

  const positions = new Map<number, Vec3>();
  for (const [d, ids] of byDepth.entries()) {
    ids.forEach((id, index) => {
      positions.set(id, { x: (index - (ids.length - 1) / 2) * SIBLING_GAP, y: -d * LEVEL_GAP, z: 0 });
    });
  }
  return positions;
}

export function buildSceneModel(diagram: DiagramModel | null): SceneModel | null {
  if (!diagram || diagram.nodes.length === 0) return null;
  const rocketLike = isRocketLikeDiagram(diagram);
  const rocketPositions = rocketLike ? rocketLayout(diagram) : null;

  // Rocket-like: topological vertical stack. Generic: stand the flat 2D graph up.
  const placed = diagram.nodes.map((node) => ({
    node,
    position: rocketPositions?.get(node.id) ?? { x: node.x * WORLD_SCALE, y: -node.y * WORLD_SCALE, z: 0 }
  }));

  // Centre the model on its centroid so OrbitControls orbits the middle.
  const cx = placed.reduce((sum, p) => sum + p.position.x, 0) / placed.length;
  const cy = placed.reduce((sum, p) => sum + p.position.y, 0) / placed.length;

  const nodes: SceneNode[] = placed.map(({ node, position }) => {
    const { radius, height } = sizeFor(node);
    return {
      id: node.id,
      name: node.name,
      type: node.type,
      fluid: classifyFluid(nodeFluidName(node, 0, 1)),
      position: { x: position.x - cx, y: position.y - cy, z: position.z },
      radius,
      height
    };
  });

  const byId = new Map(nodes.map((node) => [node.id, node]));
  const connections: SceneConnection[] = diagram.connections
    .map((connection) => {
      const start = byId.get(connection.startId);
      const end = byId.get(connection.endId);
      if (!start || !end) return null;
      // A connection inherits the colour of whatever its source node carries.
      const fluid = start.fluid !== "unknown" ? start.fluid : end.fluid;
      return {
        id: connection.id,
        name: connection.name,
        type: connection.type,
        fluid,
        start: start.position,
        end: end.position,
        valveLike: VALVE_TYPES.has(connection.type)
      } satisfies SceneConnection;
    })
    .filter((value): value is SceneConnection => value !== null);

  const extent = Math.max(
    1.5,
    ...nodes.map((node) => Math.hypot(node.position.x, node.position.y, node.position.z) + node.height)
  );

  return { nodes, connections, rocketLike, extent };
}
