import { describe, expect, it } from "vitest";
import { extractChangeExtraction } from "./ConversationRecorder";

describe("voice extraction parsing", () => {
  it("parses the summary and key changes object", () => {
    const extraction = extractChangeExtraction(`
      {
        "summary": "Reduce the LOX tank while preserving pressure targets.",
        "key_changes": [
          {
            "category": "geometry",
            "description": "Make the LOX tank smaller",
            "value": "20%"
          }
        ]
      }
    `);

    expect(extraction.summary).toContain("Reduce the LOX tank");
    expect(extraction.key_changes).toHaveLength(1);
    expect(extraction.key_changes[0].description).toBe("Make the LOX tank smaller");
  });

  it("accepts older raw array responses", () => {
    const extraction = extractChangeExtraction(`
      [
        {
          "category": "constraint",
          "description": "Keep the same pressure targets",
          "value": null
        }
      ]
    `);

    expect(extraction.summary).toBe("");
    expect(extraction.key_changes).toHaveLength(1);
    expect(extraction.key_changes[0].category).toBe("constraint");
  });
});
