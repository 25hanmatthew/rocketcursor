import type { DiagramModel, DiagramNode, SampleRow } from "../types";

export type VisualFluid = "pressurant" | "fuel" | "oxidizer" | "combined" | "warning" | "inert" | "unknown";
export type FlowVisualState = "flowing" | "closed" | "warning" | "blocked" | "lowPressure" | "idle";

export const FLUID_COLORS: Record<VisualFluid, string> = {
  pressurant: "#67f085",
  fuel: "#ff8a1f",
  oxidizer: "#25b8ff",
  combined: "#f8fbff",
  warning: "#ff4d5d",
  inert: "#8a96a8",
  unknown: "#2dd4bf"
};

const ACTIVE_FLOW_EPSILON = 1e-9;

export function classifyFluid(fluid: string | undefined): VisualFluid {
  const value = (fluid ?? "").toLowerCase();
  if (!value) return "unknown";
  if (/\b(he|helium|gn2|nitrogen|n2|pressurant)\b/.test(value)) return "pressurant";
  if (/\b(lox|oxygen|oxidizer|o2)\b/.test(value)) return "oxidizer";
  if (/\b(rp-?1|kerosene|dodecane|methane|fuel|ch4)\b/.test(value)) return "fuel";
  if (/(combined|mixture|combustion|injector|engine)/.test(value)) return "combined";
  if (/\b(air|ambient|vent)\b/.test(value)) return "inert";
  return "unknown";
}

export function colorForVisualFluid(fluid: VisualFluid): string {
  return FLUID_COLORS[fluid];
}

function stringParam(params: Record<string, unknown>, key: string): string | undefined {
  const value = params[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function nodeFluidName(node: DiagramNode, location?: number, fillLevel = 0): string | undefined {
  if (node.type === "Tank") {
    const liquid = stringParam(node.params, "fluid_liq");
    const ullage = stringParam(node.params, "fluid_ullage");
    if (location !== undefined) return location <= fillLevel ? liquid ?? ullage : ullage ?? liquid;
    return liquid ?? ullage;
  }
  return stringParam(node.params, "fluid");
}

export function isRocketLikeDiagram(diagram: DiagramModel): boolean {
  const hasEngine = diagram.nodes.some((node) => node.type === "Engine");
  const tankFluids = diagram.nodes
    .filter((node) => node.type === "Tank")
    .map((node) => classifyFluid(nodeFluidName(node, 0, 1)));
  const nodeFluids = diagram.nodes.map((node) => classifyFluid(nodeFluidName(node)));
  return (
    hasEngine &&
    tankFluids.includes("fuel") &&
    tankFluids.includes("oxidizer") &&
    nodeFluids.includes("pressurant")
  );
}

function booleanishState(value: SampleRow[string] | undefined): boolean {
  if (typeof value === "number") return value > 0;
  if (typeof value === "string") return !/^(false|0|closed)$/i.test(value.trim());
  return true;
}

export function visualStateFromSample(sample: SampleRow | undefined, status?: string): FlowVisualState {
  if (status === "red" || status === "yellow") return "warning";
  const open = booleanishState(sample?.state);
  const mdotValue = sample?.mdot;
  const dPValue = sample?.dP;
  const mdot = typeof mdotValue === "number" && Number.isFinite(mdotValue) ? mdotValue : 0;
  const dP = typeof dPValue === "number" && Number.isFinite(dPValue) ? Math.abs(dPValue) : undefined;

  if (!open) return Math.abs(mdot) > ACTIVE_FLOW_EPSILON ? "blocked" : "closed";
  if (Math.abs(mdot) <= ACTIVE_FLOW_EPSILON) return "idle";
  if (dP !== undefined && dP < 1_000) return "lowPressure";
  return "flowing";
}
