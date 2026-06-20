import type {
  DiagramConnection,
  DiagramModel,
  DiagramNode,
  NetworkConfig,
  NetworkConnection,
  NetworkNode
} from "../types";

function componentName(item: NetworkNode | NetworkConnection, fallback: string): string {
  const name = item.params?.name;
  return typeof name === "string" && name.trim() ? name : fallback;
}

function hasCoordinates(nodes: NetworkNode[]): boolean {
  return nodes.every((node) => typeof node.x === "number" && typeof node.y === "number");
}

function autoLayout(config: NetworkConfig): Map<number, { x: number; y: number }> {
  const incoming = new Map<number, number>();
  const outgoing = new Map<number, number[]>();
  for (const node of config.nodes) {
    incoming.set(node.id, 0);
    outgoing.set(node.id, []);
  }
  for (const connection of config.connections) {
    incoming.set(connection.end_id, (incoming.get(connection.end_id) ?? 0) + 1);
    outgoing.get(connection.start_id)?.push(connection.end_id);
  }

  const levels = new Map<number, number>();
  const queue = config.nodes.filter((node) => (incoming.get(node.id) ?? 0) === 0).map((node) => node.id);
  for (const node of config.nodes) levels.set(node.id, 0);

  while (queue.length > 0) {
    const id = queue.shift()!;
    const base = levels.get(id) ?? 0;
    for (const next of outgoing.get(id) ?? []) {
      if ((levels.get(next) ?? 0) <= base) {
        levels.set(next, base + 1);
        queue.push(next);
      }
    }
  }

  const byLevel = new Map<number, number[]>();
  for (const node of config.nodes) {
    const level = levels.get(node.id) ?? 0;
    if (!byLevel.has(level)) byLevel.set(level, []);
    byLevel.get(level)!.push(node.id);
  }

  const positions = new Map<number, { x: number; y: number }>();
  for (const [level, ids] of byLevel.entries()) {
    ids.forEach((id, index) => {
      positions.set(id, {
        x: level * 280,
        y: (index - (ids.length - 1) / 2) * 180
      });
    });
  }
  return positions;
}

export function buildDiagram(config: NetworkConfig): DiagramModel {
  const coordinates = hasCoordinates(config.nodes) ? undefined : autoLayout(config);
  const nodes: DiagramNode[] = config.nodes.map((node) => {
    const position = coordinates?.get(node.id);
    return {
      id: node.id,
      name: componentName(node, `${node.type}_${node.id}`),
      type: node.type,
      x: typeof node.x === "number" ? node.x : position?.x ?? 0,
      y: typeof node.y === "number" ? node.y : position?.y ?? 0,
      params: node.params ?? {}
    };
  });

  const connections: DiagramConnection[] = config.connections.map((connection, index) => ({
    id: `${componentName(connection, `${connection.type}_${index}`)}_${index}`,
    name: componentName(connection, `${connection.type}_${index}`),
    type: connection.type,
    startId: connection.start_id,
    endId: connection.end_id,
    params: connection.params ?? {}
  }));

  const xs = nodes.map((node) => node.x);
  const ys = nodes.map((node) => node.y);
  const minX = Math.min(...xs, 0) - 180;
  const maxX = Math.max(...xs, 0) + 180;
  const minY = Math.min(...ys, 0) - 150;
  const maxY = Math.max(...ys, 0) + 150;

  return {
    nodes,
    connections,
    bounds: {
      minX,
      minY,
      width: Math.max(640, maxX - minX),
      height: Math.max(420, maxY - minY)
    }
  };
}
