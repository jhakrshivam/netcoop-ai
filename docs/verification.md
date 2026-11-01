# Verification results — 2026-10-31

## Passed

```text
python -m py_compile server.py netcoop.py netcoop/*.py
python -m unittest tests.test_ncp_core tests.test_agent_workflow.AgentWorkflowTests -v
Ran 12 tests ... OK
```

The checks include legacy-regression behavior, NCP envelope integrity and duplicate detection, legacy NCMP adaptation, NCP diagnosis/abstention, and a separate-process external agent.

## Blocked

The remaining legacy HTTP tests cannot create a localhost client connection under this execution sandbox: `PermissionError: [WinError 10013]`. This is recorded as environment-blocked, not passed. The Python 3.14.7 runtime also hangs for minimal `asyncio.run`, so the verified implementation uses bounded thread workers instead of claiming asyncio operation.

## Evaluation (actual, synthetic development fixtures)

`netcoop evaluate` completed. Current non-ambiguous root-cause accuracy: **0.222**; ambiguous/interoperability abstention correctness: **0.667**. The 90% and 100% acceptance targets therefore **failed** and must not be claimed. F1, ECE, blind-dataset performance, 20%-missing-field resilience, 50-device latency, and coverage are not yet verified.

## Gate decisions

| Phase | Decision |
|---|---|
| 0 Environment audit | PARTIAL |
| 1 Protocol/message bus | PASS |
| 2 Legacy-role integration | PARTIAL |
| 3 Normalizer/specialists | PARTIAL |
| 4 Orchestration/conflicts | PARTIAL |
| 5 Evaluation/confidence | PARTIAL |
| 6 API/CLI/reports | PARTIAL |
| 7 Dashboard | PARTIAL |
| 8 Persistence/replay | PARTIAL |
| 9 External agent | PARTIAL |
| 10–12 Advanced, production security, complete demonstration | NOT IMPLEMENTED |
