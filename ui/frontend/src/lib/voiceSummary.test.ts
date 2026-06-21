import { describe, expect, it } from "vitest";
import { extractChangeExtraction, extractionToRequirements } from "./voiceSummary";

describe("voiceSummary extraction", () => {
  it("parses an object with summary + key_changes", () => {
    const e = extractChangeExtraction(
      `{"summary":"Shrink the LOX tank","key_changes":[{"category":"geometry","description":"Smaller LOX tank","value":"20%"}]}`
    );
    expect(e.summary).toBe("Shrink the LOX tank");
    expect(e.key_changes).toHaveLength(1);
    expect(e.key_changes[0].category).toBe("geometry");
  });

  it("accepts a bare array (legacy) with empty summary", () => {
    const e = extractChangeExtraction(`[{"category":"constraint","description":"Hold pressure","value":null}]`);
    expect(e.summary).toBe("");
    expect(e.key_changes[0].category).toBe("constraint");
  });

  it("renders an extraction to readable requirements text", () => {
    const text = extractionToRequirements({
      summary: "Reduce mass while holding thrust.",
      key_changes: [
        { category: "geometry", description: "Smaller LOX tank", value: "20%" },
        { category: "constraint", description: "Keep thrust target", value: null },
      ],
    });
    expect(text).toContain("Reduce mass while holding thrust.");
    expect(text).toContain("[geometry] Smaller LOX tank (value: 20%)");
    expect(text).toContain("[constraint] Keep thrust target");
  });

  it("falls back to summary-only when there are no changes", () => {
    expect(extractionToRequirements({ summary: "Looks good as is.", key_changes: [] })).toBe("Looks good as is.");
  });
});
