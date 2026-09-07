---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 0
total_count: 2
last_updated: 2026-09-07T00:11:56.699Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01 | stub | schemas/guards/money-guard.stub.test.ts |  | D-07 TypeScript float-in-money guard stub, deliberately skipped (describe.skip) -- becomes real in Phase 4 when TS first handles money | open |  | 2026-09-07T00:11:56.525Z |  |
| 2 | 01 | stub | schemas/guards/money-guard.stub.sql |  | D-07 SQL float-in-money guard stub, query commented out -- becomes real in Phase 4 when Prisma first declares a monetary column | open |  | 2026-09-07T00:11:56.699Z |  |

````json
[
  {
    "id": 1,
    "kind": "stub",
    "phase": "01",
    "file": "schemas/guards/money-guard.stub.test.ts",
    "line": null,
    "description": "D-07 TypeScript float-in-money guard stub, deliberately skipped (describe.skip) -- becomes real in Phase 4 when TS first handles money",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-07T00:11:56.525Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "stub",
    "phase": "01",
    "file": "schemas/guards/money-guard.stub.sql",
    "line": null,
    "description": "D-07 SQL float-in-money guard stub, query commented out -- becomes real in Phase 4 when Prisma first declares a monetary column",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-07T00:11:56.699Z",
    "resolved_at": null
  }
]
````
