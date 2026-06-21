"""End-to-end check: Voyage embed → Redis write → KNN search.

Writes a throwaway record under a dedicated probe id, confirms the full
embed/index/search path returns it, then deletes it so the live corpus is
left untouched.
"""

from memory.core import Memory

PROBE_ID = "_verify_voyage_probe"
PROBE_KEY = f"failure:external:{PROBE_ID}"
QUERY = "turbopump bearing seizure from inadequate cryogenic lubrication"

mem = Memory()
mem.write_failure(
    "external",
    PROBE_ID,
    {
        "failure_mode": "turbopump bearing seizure",
        "system_config": "LOX turbopump",
        "operating_conditions": "startup transient, high RPM",
        "root_cause": "inadequate lubrication at cold start",
        "corrective_action": "added pre-chill lube cycle",
    },
)
try:
    results = mem.search_failures(QUERY, k=10)
    for r in results:
        print(f"  {r['score']:.4f}  {r['id']}  source_type={r['source_type']}")

    found = next((r for r in results if PROBE_ID in r["id"]), None)
    if found is None:
        print("FAIL — probe record not returned by search; check index/embeddings")
    elif found["source_type"] != "external":
        print(f"FAIL — source_type not populated correctly: {found['source_type']!r}")
    else:
        rank = [r["id"] for r in results].index(found["id"]) + 1
        print(
            f"PASS — Voyage → Redis → KNN path is live "
            f"(probe found at rank {rank}/{len(results)}, source_type populated)"
        )
finally:
    mem.r.delete(PROBE_KEY)
    print(f"cleaned up {PROBE_KEY}")
