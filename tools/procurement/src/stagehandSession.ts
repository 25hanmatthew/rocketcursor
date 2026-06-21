import { Stagehand } from "@browserbasehq/stagehand";
import { SupplierTarget } from "./supplierTargets.js";

function mcMasterUseVerifiedProxy(): boolean {
  return process.env.MCMASTER_USE_VERIFIED_PROXY?.trim().toLowerCase() === "true";
}

export function stagehandCreateParams(supplier: SupplierTarget) {
  const params: Record<string, unknown> = {};
  const browserSettings: Record<string, unknown> = {};
  const useVerifiedProxy =
    supplier.name === "McMaster-Carr"
      ? mcMasterUseVerifiedProxy()
      : supplier.useVerifiedProxy;

  if (useVerifiedProxy) {
    browserSettings.verified = true;
    browserSettings.os = "mac";
    params.proxies = true;
  } else if (supplier.name === "McMaster-Carr") {
    params.proxies = true;
  }

  const contextId = supplier.contextEnv
    ? process.env[supplier.contextEnv]?.trim()
    : undefined;
  if (contextId) {
    browserSettings.context = { id: contextId, persist: true };
  }

  if (Object.keys(browserSettings).length > 0) {
    params.browserSettings = browserSettings;
  }

  return Object.keys(params).length > 0 ? params : undefined;
}

export async function createStagehandSession(
  supplier: SupplierTarget
): Promise<Stagehand> {
  const stagehand = new Stagehand({
    env: "BROWSERBASE",
    model: "anthropic/claude-sonnet-4-6",
    browserbaseSessionCreateParams: stagehandCreateParams(supplier)
  });
  await stagehand.init();
  return stagehand;
}
