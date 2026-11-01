# NCP/1.0 protocol - Phase 1

This document defines Phase 1 only: configuration, validated message envelopes, and append-only message logging. It does not introduce agent execution, orchestration, diagnosis, remediation, APIs, or UI changes.

## Repository layout

| Path | Responsibility |
|---|---|
| `netcoop/config.py` | Environment-backed protocol version, TTL, and message-log location. |
| `config.yaml` | Checked-in default protocol configuration for deployment tooling. |
| `netcoop/messages.py` | Pydantic v2 `NCPMessage` model and `MessageType` enum. |
| `netcoop/message_log.py` | Append-only JSONL message log and validated replay reader. |
| `tests/test_phase1_messages.py` | Creates and validates one message of every type. |
| `work/message-log.jsonl` | Default runtime log; ignored as generated state. |

## Envelope

Every NCP/1.0 message contains: `protocol_version`, `message_id`, `correlation_id`, `sender`, `recipient_or_topic`, `message_type`, `timestamp_utc`, `schema_version`, `payload`, `ttl_s`, and `payload_sha256`.

Pydantic v2 rejects unknown envelope fields, malformed UUIDs, blank sender/recipient values, non-UTC-aware timestamps, invalid TTLs, unsupported protocol/schema versions, and payload integrity mismatches. The SHA-256 digest is calculated from canonical JSON (`sort_keys=true`, compact separators, UTF-8).

## Message types

`TELEMETRY_SNAPSHOT`, `TASK_REQUEST`, `FINDING`, `EVIDENCE_QUERY`, `CONFLICT_NOTICE`, `DIAGNOSIS`, `ERROR`, `HEARTBEAT`, and `AGENT_STATUS`.

## Configuration

`NETCOOP_MESSAGE_LOG` optionally changes the JSONL log location. `NETCOOP_MESSAGE_TTL_S` optionally changes TTL within 1-3600 seconds. Defaults are `work/message-log.jsonl` and 60 seconds.

## Verification

Run:

```powershell
python -m pytest tests/test_phase1_messages.py -q
```

Phase 1 leaves the existing legacy protocol and all Phase 2+ behavior unchanged.
