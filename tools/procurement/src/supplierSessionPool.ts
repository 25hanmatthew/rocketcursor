import { Browserbase } from "@browserbasehq/sdk";
import { Stagehand } from "@browserbasehq/stagehand";
import { SupplierTarget } from "./supplierTargets.js";
import { createStagehandSession } from "./stagehandSession.js";
import {
  ensureLoggedInWithRetry,
  LoginResult,
  verifyStillLoggedIn
} from "./supplierAuth.js";

type PooledSession = {
  stagehand: Stagehand;
};

/**
 * One browser session per supplier for the whole procurement run.
 * Login is attempted once up-front (with retries). If it fails, that supplier
 * is blocked for all materials — no anonymous extraction pretending to work.
 */
export class SupplierSessionPool {
  private sessions = new Map<string, PooledSession>();
  private blocked = new Map<string, LoginResult>();

  isBlocked(supplierName: string): boolean {
    return this.blocked.has(supplierName);
  }

  getBlockedResult(supplierName: string): LoginResult | undefined {
    return this.blocked.get(supplierName);
  }

  /** Log in required suppliers once before any material extraction. */
  async prewarm(
    bb: Browserbase,
    suppliers: SupplierTarget[],
    runId?: string
  ): Promise<void> {
    for (const supplier of suppliers) {
      await this.acquire(bb, supplier, runId);
    }
  }

  async acquire(
    bb: Browserbase,
    supplier: SupplierTarget,
    runId?: string
  ): Promise<{ stagehand?: Stagehand; loginResult?: LoginResult }> {
    const blocked = this.blocked.get(supplier.name);
    if (blocked) {
      return { loginResult: blocked };
    }

    const existing = this.sessions.get(supplier.name);
    if (existing) {
      if (
        !supplier.requiresLogin ||
        (await verifyStillLoggedIn(existing.stagehand, supplier))
      ) {
        return { stagehand: existing.stagehand };
      }

      const relogin = await ensureLoggedInWithRetry({
        bb,
        stagehand: existing.stagehand,
        supplier,
        runId
      });
      if (relogin.ok) {
        return { stagehand: existing.stagehand, loginResult: relogin };
      }

      this.blocked.set(supplier.name, relogin);
      await existing.stagehand.close();
      this.sessions.delete(supplier.name);
      return { loginResult: relogin };
    }

    const stagehand = await createStagehandSession(supplier);
    const loginResult = await ensureLoggedInWithRetry({
      bb,
      stagehand,
      supplier,
      runId
    });

    if (!loginResult.ok && supplier.requiresLogin) {
      this.blocked.set(supplier.name, loginResult);
      await stagehand.close();
      return { loginResult };
    }

    this.sessions.set(supplier.name, { stagehand });
    return { stagehand, loginResult };
  }

  has(supplierName: string): boolean {
    return this.sessions.has(supplierName);
  }

  /** Block a supplier for the rest of the run and tear down any live session. */
  markBlocked(supplier: SupplierTarget, loginResult: LoginResult): void {
    if (this.blocked.has(supplier.name)) {
      return;
    }
    this.blocked.set(supplier.name, loginResult);
    const existing = this.sessions.get(supplier.name);
    if (existing) {
      void existing.stagehand.close();
      this.sessions.delete(supplier.name);
    }
  }

  async closeAll(): Promise<void> {
    const closers = [...this.sessions.values()].map(({ stagehand }) =>
      stagehand.close()
    );
    await Promise.allSettled(closers);
    this.sessions.clear();
    this.blocked.clear();
  }
}
