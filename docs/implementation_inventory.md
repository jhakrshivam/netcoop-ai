# Implementation inventory

Audited 2026-10-31 against the supplied archive and the engineering brief. “PASS” means implemented and verified in this workspace; it does not mean production validated.

| Feature | Existing implementation | File | Status | Missing work | Verification |
|---|---|---|---|---|---|
| Local dashboard and navigation | Plain JS/CSS operations dashboard | `web/` | PASS | New v2 dashboard panels not yet added | Existing non-HTTP regression tests pass |
| Windows inventory, Wi-Fi, live CPU/traffic | Local read-only collectors | `server.py` | PARTIAL | Windows-only; not verified in sandbox | Source audit |
| CSV import and SQLite history | CSV validation, unit consistency, task/action storage | `server.py` | PARTIAL | HTTP checks blocked by sandbox loopback policy | 8 non-HTTP legacy tests pass |
| Legacy five-role diagnosis | In-process deterministic NCMP trace | `server.py` | PASS | Not independent workers | 8 legacy workflow tests pass |
| Legacy `ncmp/1.0` | Envelope documentation/schema | `docs/agent-protocol.md`, `schemas/message.schema.json` | PARTIAL | Not NCP/1.0 | Legacy compatibility adapter tested |
| NCP/1.0 | Strict integrity envelope, TTL, replay, discovery | `netcoop/protocol.py`, `docs/schemas/` | PASS | Pydantic v2 model unavailable | 4 NCP conformance tests pass |
| Normalizer | Alias mapping, raw value retention, stale/duplicate/invalid handling | `netcoop/normalizer.py` | PASS | Broader unit conversions | NCP integration tests |
| Specialist agents | Performance, infrastructure, connectivity, wireless, service | `netcoop/agents.py` | PARTIAL | No production models/collectors | NCP investigation test |
| Orchestration/conflict | Bounded parallel workers, findings, conflict notice/query, abstention | `netcoop/orchestrator.py` | PARTIAL | Async process orchestration blocked by runtime; no circuit-breaker persistence | NCP tests |
| Synthetic scenarios | 12 explicit synthetic fixtures | `netcoop/scenarios.py` | PARTIAL | Noise controls and blind corpus incomplete | CLI evaluation runs |
| Evaluation | Per-scenario actual outputs/latency | `netcoop/evaluate.py` | PARTIAL | F1/ECE/ablation/noise metrics incomplete; targets not met | `netcoop evaluate` |
| NCP API | Additive health, agents, scenarios, diagnosis, incidents, topology, evaluation API | `server.py` | PARTIAL | HTTP verification blocked; no FastAPI/WebSocket | Compile check only |
| External agent | StdIO JSON NCP process example | `netcoop/external_example_agent.py` | PARTIAL | No network transport or orchestrator participation yet | Separate-process conformance test passes |
| Security | Input size validation, loopback bind, integrity hashing, read-only policy | `server.py`, `netcoop/protocol.py` | PARTIAL | Auth/RBAC/rate limiting/audit retention incomplete | Source audit |
