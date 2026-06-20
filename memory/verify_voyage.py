"""End-to-end check: Voyage embed → Redis write → KNN search."""

from memory.core import Memory

mem = Memory()
mem.write_failure(
    "external",
    "test1",
    {
        "failure_mode": "turbopump bearing seizure",
        "system_config": "LOX turbopump",
        "operating_conditions": "startup transient, high RPM",
        "root_cause": "inadequate lubrication at cold start",
        "corrective_action": "added pre-chill lube cycle",
    },
)
results = mem.search_failures("pump bearing failure during ignition")
print(results)
if results and "test1" in results[0]["id"]:
    print("PASS — Voyage → Redis → KNN path is live")
else:
    print("FAIL — expected failure:external:test1 as top hit")
