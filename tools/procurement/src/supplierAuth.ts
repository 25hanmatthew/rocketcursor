import { Browserbase } from "@browserbasehq/sdk";
import { Stagehand } from "@browserbasehq/stagehand";
import { z } from "zod";
import { SupplierTarget } from "./supplierTargets.js";
import {
  buildSupplierLoginChallengeMessage,
  POKE_SOURCE,
  postToPoke
} from "./pokeClient.js";
import { SUPPLIER_LOGIN_RETRIES } from "./procurementLimits.js";

const LoginStateSchema = z.object({
  loggedIn: z.boolean(),
  onLoginPage: z.boolean().optional(),
  challengeDetected: z.boolean().optional(),
  challengeType: z.string().nullable().optional(),
  loginError: z.string().nullable().optional(),
  botOrCaptchaDetected: z.boolean().optional()
});

export type LoginResult = {
  ok: boolean;
  reason?:
    | "not_required"
    | "already_logged_in"
    | "login_succeeded"
    | "missing_credentials"
    | "login_failed"
    | "login_challenge_requires_interactive"
    | "login_challenge_timeout";
  detail?: string;
};

function resolveEnv(name?: string): string | undefined {
  if (!name) return undefined;
  const value = process.env[name]?.trim();
  return value || undefined;
}

function isSupplierLoginInteractive(): boolean {
  const value = process.env.SUPPLIER_LOGIN_INTERACTIVE?.trim().toLowerCase();
  return value === "true" || value === "1";
}

function supplierLoginTimeoutMs(): number {
  const raw = process.env.SUPPLIER_LOGIN_TIMEOUT_MS?.trim();
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 180_000;
}

function stagehandPage(stagehand: Stagehand) {
  return stagehand.context.pages()[0]!;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

type ParsedLoginState = {
  loggedIn: boolean;
  onLoginPage: boolean;
  challengeDetected: boolean;
  challengeType: string | null;
  loginError: string | null;
  botOrCaptchaDetected: boolean;
};

function isMcMasterSupplier(supplier?: SupplierTarget): boolean {
  return supplier?.name === "McMaster-Carr";
}

const McMasterLoginStateSchema = z.object({
  loggedIn: z.boolean(),
  onLoginPage: z.boolean(),
  topRightAuthLabel: z.string().nullable().optional(),
  logoutVisible: z.boolean().optional(),
  loginError: z.string().nullable().optional(),
  botOrCaptchaDetected: z.boolean().optional()
});

const MCMASTER_LOGIN_EXTRACT_PROMPT =
  "McMaster-Carr ONLY. Inspect the TOP-RIGHT header/auth area (near Order), not the Browse Catalog menu.\n" +
  "- loggedIn: true ONLY if top-right shows a signed-in account name OR Log Out is available. false if top-right shows Log in.\n" +
  "- onLoginPage: true if the login side panel shows Email and Password fields.\n" +
  "- topRightAuthLabel: exact visible auth label in top-right (Log in, account name, etc.), else null.\n" +
  "- logoutVisible: true if Log Out is visible.\n" +
  "- loginError: visible invalid credentials message, else null.\n" +
  "- botOrCaptchaDetected: true for CAPTCHA, bot checks, or blocked access pages.";

function normalizeMcMasterLoginState(
  data: z.infer<typeof McMasterLoginStateSchema>
): ParsedLoginState {
  let loggedIn = data.loggedIn;
  const topRight = data.topRightAuthLabel?.trim() ?? "";

  if (/^log\s*in$/i.test(topRight)) {
    loggedIn = false;
  } else if (topRight.length > 0) {
    loggedIn = true;
  }

  if (data.logoutVisible && !data.onLoginPage) {
    loggedIn = true;
  }

  return {
    loggedIn,
    onLoginPage: Boolean(data.onLoginPage),
    challengeDetected: false,
    challengeType: null,
    loginError: data.loginError ?? null,
    botOrCaptchaDetected: Boolean(data.botOrCaptchaDetected)
  };
}

async function readMcMasterLoginState(
  stagehand: Stagehand
): Promise<ParsedLoginState> {
  const result = await stagehand.extract(
    MCMASTER_LOGIN_EXTRACT_PROMPT,
    McMasterLoginStateSchema
  );

  const parsed = McMasterLoginStateSchema.safeParse(result);
  if (!parsed.success) {
    return {
      loggedIn: false,
      onLoginPage: false,
      challengeDetected: false,
      challengeType: null,
      loginError: null,
      botOrCaptchaDetected: false
    };
  }

  return normalizeMcMasterLoginState(parsed.data);
}

async function openMcMasterLoginPanel(
  stagehand: Stagehand,
  page: ReturnType<typeof stagehandPage>
) {
  await stagehand.act(
    "Click the Log in link in the top-right corner of the McMaster site header (near Order, not in the Browse Catalog menu)",
    { page }
  );
  await sleep(1_500);
}

async function submitMcMasterLogin(
  stagehand: Stagehand,
  page: ReturnType<typeof stagehandPage>,
  username: string,
  password: string
) {
  const steps = loginActInstructions({
    name: "McMaster-Carr"
  } as SupplierTarget);

  await stagehand.act(steps.username, {
    page,
    variables: { username }
  });

  await stagehand.act(steps.password, {
    page,
    variables: {
      password: {
        value: password,
        description: "Supplier account password"
      }
    }
  });

  await stagehand.act(steps.submit, { page });
}

function loginActInstructions(supplier: SupplierTarget) {
  if (supplier.name === "McMaster-Carr") {
    return {
      openPanel:
        "Click the Log in link in the top-right McMaster-Carr site header to open the login side panel",
      username:
        "Type %username% into the Email field in the open McMaster-Carr login side panel",
      password:
        "Type %password% into the Password field in the McMaster-Carr login side panel",
      submit: "Click the Log In button in the McMaster-Carr login side panel"
    };
  }

  return {
    username: "Type %username% into the email or username field",
    password: "Type %password% into the password field",
    submit: "Click the sign in or log in button"
  };
}

async function openLoginForm(
  stagehand: Stagehand,
  page: ReturnType<typeof stagehandPage>,
  supplier: SupplierTarget
) {
  if (supplier.loginFlow === "panel") {
    if (isMcMasterSupplier(supplier)) {
      const state = await readMcMasterLoginState(stagehand);
      if (state.loggedIn || state.onLoginPage) {
        return;
      }

      if (state.botOrCaptchaDetected) {
        throw new Error("McMaster bot or CAPTCHA check detected before login");
      }

      await openMcMasterLoginPanel(stagehand, page);
      return;
    }

    const steps = loginActInstructions(supplier);
    if (!("openPanel" in steps) || !steps.openPanel) {
      throw new Error(`Missing panel login instructions for ${supplier.name}`);
    }
    await stagehand.act(steps.openPanel, { page });
    await sleep(1_500);
    return;
  }

  // Default page flow: loginUrl should already be loaded and contain the form.
}

async function readLoginState(
  stagehand: Stagehand,
  supplier?: SupplierTarget
): Promise<ParsedLoginState> {
  if (isMcMasterSupplier(supplier)) {
    return readMcMasterLoginState(stagehand);
  }

  const result = await stagehand.extract(
    "Inspect this page and determine login state for a supplier website.\n" +
      "- loggedIn: true only if the user is clearly signed in (account menu, logout, order history, etc.).\n" +
      "- onLoginPage: true if a login/sign-in form or side panel/drawer with email/username and password is visible.\n" +
      "- challengeDetected: true for 2FA, OTP, verification code, or email code prompts.\n" +
      "- botOrCaptchaDetected: true for CAPTCHA, 'verify you are human', bot checks, or blocked access pages.\n" +
      "- loginError: any visible invalid credentials or login error message text, else null.\n" +
      "- challengeType: short label like '2fa', 'captcha', 'email_code', or null.",
    LoginStateSchema
  );

  const parsed = LoginStateSchema.safeParse(result);
  if (!parsed.success) {
    return {
      loggedIn: false,
      onLoginPage: true,
      challengeDetected: false,
      challengeType: null,
      loginError: null,
      botOrCaptchaDetected: false
    };
  }

  return {
    loggedIn: parsed.data.loggedIn,
    onLoginPage: Boolean(parsed.data.onLoginPage),
    challengeDetected: Boolean(parsed.data.challengeDetected),
    challengeType: parsed.data.challengeType ?? null,
    loginError: parsed.data.loginError ?? null,
    botOrCaptchaDetected: Boolean(parsed.data.botOrCaptchaDetected)
  };
}

async function pollLoginState(
  stagehand: Stagehand,
  supplier?: SupplierTarget,
  attempts?: number,
  delayMs = 2000
) {
  const maxAttempts =
    attempts ?? (isSupplierLoginInteractive() ? 4 : 2);
  let state = await readLoginState(stagehand, supplier);
  for (let attempt = 1; attempt < maxAttempts && !state.loggedIn; attempt++) {
    await sleep(delayMs);
    state = await readLoginState(stagehand, supplier);
  }
  return state;
}

function needsInteractiveHandoff(state: {
  challengeDetected: boolean;
  challengeType: string | null;
  botOrCaptchaDetected: boolean;
}) {
  return (
    state.challengeDetected ||
    Boolean(state.challengeType) ||
    state.botOrCaptchaDetected
  );
}

async function getLiveViewUrl(bb: Browserbase, stagehand: Stagehand): Promise<string | null> {
  if (stagehand.browserbaseDebugURL) {
    return stagehand.browserbaseDebugURL;
  }

  const sessionId = stagehand.browserbaseSessionID;
  if (!sessionId) return null;

  try {
    const debug = await bb.sessions.debug(sessionId);
    return debug.debuggerFullscreenUrl || null;
  } catch {
    return null;
  }
}

async function notifyLoginChallenge(params: {
  bb: Browserbase;
  stagehand: Stagehand;
  supplier: SupplierTarget;
  runId?: string;
  detail?: string;
}): Promise<void> {
  const liveViewUrl = await getLiveViewUrl(params.bb, params.stagehand);
  if (!liveViewUrl) {
    throw new Error(
      `Could not obtain Browserbase live view URL for ${params.supplier.name} login challenge`
    );
  }

  const detailLine = params.detail ? `\nReason: ${params.detail}` : "";

  await postToPoke({
    message:
      buildSupplierLoginChallengeMessage({
        supplierName: params.supplier.name,
        liveViewUrl,
        runId: params.runId
      }) + detailLine,
    source: POKE_SOURCE,
    run_id: params.runId,
    user_approved_external_action: true,
    metadata: {
      kind: "supplier_login_challenge",
      supplier: params.supplier.name,
      liveViewUrl,
      detail: params.detail
    }
  });

  console.warn(
    JSON.stringify({
      event: "supplier_login_challenge",
      supplier: params.supplier.name,
      liveViewUrl,
      runId: params.runId ?? null,
      note: "Complete sign-in in the live browser. Run polls every 5s for up to SUPPLIER_LOGIN_TIMEOUT_MS."
    })
  );
}

async function waitForInteractiveCompletion(params: {
  bb: Browserbase;
  stagehand: Stagehand;
  supplier: SupplierTarget;
  runId?: string;
  detail?: string;
}): Promise<LoginResult> {
  try {
    await notifyLoginChallenge(params);
  } catch (err) {
    return {
      ok: false,
      reason: "login_challenge_requires_interactive",
      detail: String(err)
    };
  }

  const deadline = Date.now() + supplierLoginTimeoutMs();
  while (Date.now() < deadline) {
    await sleep(5_000);
    const nextState = await readLoginState(params.stagehand, params.supplier);
    if (nextState.loggedIn) {
      return { ok: true, reason: "login_succeeded" };
    }
  }

  return { ok: false, reason: "login_challenge_timeout" };
}

async function waitForAuthOrChallenge(params: {
  bb: Browserbase;
  stagehand: Stagehand;
  supplier: SupplierTarget;
  runId?: string;
}): Promise<LoginResult> {
  const state = await pollLoginState(params.stagehand, params.supplier);
  if (state.loggedIn) {
    return { ok: true, reason: "login_succeeded" };
  }

  const challengeVisible = needsInteractiveHandoff(state);
  const stuckOnLoginPage = state.onLoginPage && !state.loggedIn;

  if (challengeVisible || (stuckOnLoginPage && isSupplierLoginInteractive())) {
    if (!isSupplierLoginInteractive()) {
      return {
        ok: false,
        reason: "login_challenge_requires_interactive",
        detail:
          state.loginError ??
          state.challengeType ??
          (state.botOrCaptchaDetected
            ? "Bot or CAPTCHA check detected"
            : "Login challenge detected")
      };
    }

    return waitForInteractiveCompletion({
      ...params,
      detail:
        state.loginError ??
        state.challengeType ??
        (state.botOrCaptchaDetected
          ? "Complete CAPTCHA or bot check in the live browser"
          : stuckOnLoginPage
            ? "Login form still visible — complete sign-in manually in the live browser"
            : undefined)
    });
  }

  return {
    ok: false,
    reason: "login_failed",
    detail:
      state.loginError ??
      (state.onLoginPage
        ? "Still on login page after automated sign-in — verify McMaster credentials or enable SUPPLIER_LOGIN_INTERACTIVE=true"
        : "Sign-in did not complete")
  };
}

function supplierLoginRetries(): number {
  return SUPPLIER_LOGIN_RETRIES;
}

function loginFailureIsFinal(reason: LoginResult["reason"]): boolean {
  return (
    reason === "missing_credentials" ||
    reason === "login_challenge_requires_interactive" ||
    reason === "login_challenge_timeout"
  );
}

function shouldRetryLogin(result: LoginResult): boolean {
  if (result.ok || loginFailureIsFinal(result.reason)) {
    return false;
  }
  if (
    result.reason === "login_failed" &&
    result.detail?.includes("Login automation error")
  ) {
    return false;
  }
  return result.reason === "login_failed";
}

export async function verifyStillLoggedIn(
  stagehand: Stagehand,
  supplier: SupplierTarget
): Promise<boolean> {
  if (!supplier.requiresLogin) return true;
  const state = await readLoginState(stagehand, supplier);
  return state.loggedIn;
}

export async function ensureLoggedInWithRetry(params: {
  bb: Browserbase;
  stagehand: Stagehand;
  supplier: SupplierTarget;
  runId?: string;
}): Promise<LoginResult> {
  const attempts = supplierLoginRetries();
  let last: LoginResult = { ok: false, reason: "login_failed" };

  for (let attempt = 1; attempt <= attempts; attempt++) {
    last = await ensureLoggedIn(params);
    if (last.ok) {
      return last;
    }
    if (!shouldRetryLogin(last)) {
      return last;
    }
    if (attempt < attempts) {
      await sleep(2_000);
    }
  }

  return {
    ...last,
    detail:
      (last.detail ? `${last.detail}. ` : "") +
      `Login failed after ${attempts} attempts (supplier auth is flaky — set SUPPLIER_LOGIN_INTERACTIVE=true or retry the run)`
  };
}

export async function ensureLoggedIn(params: {
  bb: Browserbase;
  stagehand: Stagehand;
  supplier: SupplierTarget;
  runId?: string;
}): Promise<LoginResult> {
  const { bb, stagehand, supplier, runId } = params;

  if (!supplier.requiresLogin) {
    return { ok: true, reason: "not_required" };
  }

  const username = resolveEnv(supplier.usernameEnv);
  const password = resolveEnv(supplier.passwordEnv);
  if (!username || !password) {
    return { ok: false, reason: "missing_credentials" };
  }

  if (!supplier.loginUrl) {
    return { ok: false, reason: "login_failed", detail: "Missing loginUrl" };
  }

  const page = stagehandPage(stagehand);
  await page.goto(supplier.loginUrl);
  if (isMcMasterSupplier(supplier)) {
    await page.waitForTimeout(2_000);
  }

  const initialState = await readLoginState(stagehand, supplier);
  if (initialState.loggedIn) {
    return { ok: true, reason: "already_logged_in" };
  }

  const steps = loginActInstructions(supplier);

  try {
    if (isMcMasterSupplier(supplier)) {
      await openLoginForm(stagehand, page, supplier);

      const panelState = await readMcMasterLoginState(stagehand);
      if (panelState.loggedIn) {
        return { ok: true, reason: "already_logged_in" };
      }
      if (!panelState.onLoginPage) {
        return {
          ok: false,
          reason: "login_failed",
          detail:
            "McMaster login panel did not open — top-right Log in link may be missing"
        };
      }

      await submitMcMasterLogin(stagehand, page, username, password);
    } else {
      await openLoginForm(stagehand, page, supplier);

      await stagehand.act(steps.username, {
        page,
        variables: { username }
      });

      await stagehand.act(steps.password, {
        page,
        variables: {
          password: {
            value: password,
            description: "Supplier account password"
          }
        }
      });

      await stagehand.act(steps.submit, { page });
    }
  } catch (err) {
    return {
      ok: false,
      reason: "login_failed",
      detail: `Login automation error: ${String(err)}`
    };
  }

  await sleep(isSupplierLoginInteractive() ? 3_000 : 2_000);
  return waitForAuthOrChallenge({ bb, stagehand, supplier, runId });
}

export function loginFailureReasonMessage(
  reason: LoginResult["reason"],
  detail?: string
): string {
  const base = (() => {
    switch (reason) {
      case "missing_credentials":
        return "Supplier login credentials are not configured in .env";
      case "login_challenge_requires_interactive":
        return "Supplier login requires 2FA/CAPTCHA or manual completion — set SUPPLIER_LOGIN_INTERACTIVE=true and re-run";
      case "login_challenge_timeout":
        return "Timed out waiting for interactive supplier login challenge completion";
      case "login_failed":
        return "Supplier login failed";
      default:
        return "Supplier login failed";
    }
  })();

  return detail ? `${base}: ${detail}` : base;
}
