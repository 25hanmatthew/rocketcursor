import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ChatTranscript,
  chatRequestBody,
  chatSubmissionTarget,
  changesToRequirements,
  createRunStatusChatItem,
  createUserChatItem,
  loadedIterationForSession,
  updateRunStatusChatItem
} from "./App";
import type { ChatHistoryItem, SessionState } from "./types";

describe("chat submission routing", () => {
  it("starts a new design when no design is loaded", () => {
    expect(chatSubmissionTarget(null, null, false)).toEqual({ kind: "new", url: "/api/design-runs" });
    expect(chatSubmissionTarget("abc", null, false)).toEqual({ kind: "new", url: "/api/design-runs" });
  });

  it("uses the revision endpoint when a design from the active session is loaded", () => {
    expect(loadedIterationForSession("abc:3", "abc")).toBe(3);
    expect(chatSubmissionTarget("abc", "abc:3", true)).toEqual({
      kind: "revision",
      url: "/api/design-runs/abc/revisions",
      iteration: 3
    });
  });

  it("does not revise from a stale loaded session key", () => {
    expect(loadedIterationForSession("old:2", "abc")).toBeNull();
    expect(chatSubmissionTarget("abc", "old:2", true)).toEqual({ kind: "new", url: "/api/design-runs" });
  });

  it("keeps request bodies limited to the current message", () => {
    expect(chatRequestBody("design this", { kind: "new", url: "/api/design-runs" })).toEqual({
      message: "design this"
    });
    expect(chatRequestBody("make it smaller", { kind: "revision", url: "/api/design-runs/abc/revisions", iteration: 2 })).toEqual({
      message: "make it smaller",
      iteration: 2
    });
  });
});

describe("voice change formatting", () => {
  it("formats a voice summary and key changes as one revision message", () => {
    const message = changesToRequirements({
      summary: "Make the loaded design smaller while preserving pressure targets.",
      key_changes: [
        {
          category: "geometry",
          description: "Reduce the LOX tank volume",
          value: "20%"
        },
        {
          category: "constraint",
          description: "Keep the same pressure targets",
          value: null
        }
      ]
    });

    expect(message).toContain("Voice summary:");
    expect(message).toContain("Make the loaded design smaller");
    expect(message).toContain("Key design changes:");
    expect(message).toContain("[geometry] Reduce the LOX tank volume (value: 20%)");
    expect(message).toContain("[constraint] Keep the same pressure targets");
  });
});

describe("chat transcript helpers", () => {
  it("creates user and status items without persisting full history", () => {
    const target = { kind: "revision" as const, url: "/api/design-runs/abc/revisions", iteration: 3 };
    const user = createUserChatItem("make it smaller", target, "abc", 1000);
    const status = createRunStatusChatItem("child", target, "abc", 1001);

    expect(user.role).toBe("user");
    expect(user.kind).toBe("revision");
    expect(user.parentSessionId).toBe("abc");
    expect(user.iteration).toBe(3);
    expect(status.text).toContain("Revision started");
    expect(status.sessionId).toBe("child");
  });

  it("updates the status item when a run completes", () => {
    const history: ChatHistoryItem[] = [
      {
        id: "status-child",
        role: "assistant",
        text: "Running",
        kind: "status",
        sessionId: "child",
        status: "running",
        createdAt: 1
      }
    ];
    const state = {
      session_id: "child",
      request: "make it smaller",
      provider: "test",
      model: "test",
      status: "passed",
      stage: "report",
      current_iteration: 1,
      iterations: [],
      passed: true,
      iterations_used: 2,
      report: null
    } satisfies SessionState;

    const updated = updateRunStatusChatItem(history, "child", state);
    expect(updated[0].status).toBe("passed");
    expect(updated[0].text).toBe("Design passed in 2 iteration(s).");
  });

  it("renders user and assistant messages", () => {
    const html = renderToStaticMarkup(
      createElement(ChatTranscript, {
        items: [
          {
            id: "u1",
            role: "user",
            text: "Design a tank",
            kind: "initial",
            createdAt: 1
          },
          {
            id: "s1",
            role: "assistant",
            text: "Design passed in 1 iteration(s).",
            kind: "status",
            status: "passed",
            sessionId: "abc",
            createdAt: 2
          }
        ]
      })
    );

    expect(html).toContain("Design a tank");
    expect(html).toContain("Design passed in 1 iteration(s).");
    expect(html).toContain("status-passed");
  });
});
