import { describe, expect, it } from "vitest";
import { chatSubmissionTarget, loadedIterationForSession } from "./App";

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
});
