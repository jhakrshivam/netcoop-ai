"""Strict, dependency-free NCP/1.0 envelopes and in-memory message bus."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib, json, time, uuid
from typing import Any

PROTOCOL_VERSION = "NCP/1.0"
SCHEMA_VERSION = "1.0"
MESSAGE_TYPES = {"TASK_REQUEST", "FINDING", "EVIDENCE_QUERY", "CONFLICT_NOTICE", "DIAGNOSIS", "ERROR", "HEARTBEAT", "AGENT_STATUS"}

class ProtocolError(ValueError):
    """Structured protocol validation error."""
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code
    def as_dict(self): return {"code": self.code, "message": str(self)}

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def canonical_payload(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(value).encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class NCPMessage:
    protocol_version: str
    message_id: str
    correlation_id: str
    sender: str
    recipient_or_topic: str
    message_type: str
    timestamp_utc: str
    schema_version: str
    payload: dict[str, Any]
    ttl_s: int
    payload_sha256: str

    @classmethod
    def create(cls, sender: str, recipient_or_topic: str, message_type: str, payload: dict[str, Any], correlation_id: str | None = None, ttl_s: int = 60) -> "NCPMessage":
        return cls(PROTOCOL_VERSION, str(uuid.uuid4()), correlation_id or str(uuid.uuid4()), sender, recipient_or_topic, message_type, utc_now(), SCHEMA_VERSION, payload, ttl_s, digest(payload))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "NCPMessage":
        required = {"protocol_version", "message_id", "correlation_id", "sender", "recipient_or_topic", "message_type", "timestamp_utc", "schema_version", "payload", "ttl_s", "payload_sha256"}
        missing = required - set(raw)
        if missing: raise ProtocolError("MISSING_FIELDS", "Missing required fields: " + ", ".join(sorted(missing)))
        extra = set(raw) - required
        if extra: raise ProtocolError("UNKNOWN_FIELDS", "Unsupported fields: " + ", ".join(sorted(extra)))
        try: msg = cls(**raw)
        except TypeError as exc: raise ProtocolError("INVALID_ENVELOPE", str(exc)) from exc
        msg.validate(); return msg

    def to_dict(self) -> dict[str, Any]: return asdict(self)
    def validate(self, now: datetime | None = None) -> None:
        if self.protocol_version != PROTOCOL_VERSION: raise ProtocolError("UNSUPPORTED_PROTOCOL", f"Expected {PROTOCOL_VERSION}")
        if self.schema_version != SCHEMA_VERSION: raise ProtocolError("UNSUPPORTED_SCHEMA", f"Expected schema {SCHEMA_VERSION}")
        if self.message_type not in MESSAGE_TYPES: raise ProtocolError("UNSUPPORTED_TYPE", self.message_type)
        if not self.sender or not self.recipient_or_topic or not isinstance(self.payload, dict): raise ProtocolError("INVALID_ENVELOPE", "sender, recipient_or_topic, and object payload are required")
        if not isinstance(self.ttl_s, int) or not 1 <= self.ttl_s <= 3600: raise ProtocolError("INVALID_TTL", "ttl_s must be 1..3600")
        try: uuid.UUID(self.message_id); uuid.UUID(self.correlation_id)
        except (ValueError, TypeError) as exc: raise ProtocolError("INVALID_ID", "message_id and correlation_id must be UUIDs") from exc
        try: stamp = datetime.fromisoformat(self.timestamp_utc.replace("Z", "+00:00"))
        except ValueError as exc: raise ProtocolError("INVALID_TIMESTAMP", "timestamp_utc must be ISO-8601") from exc
        if stamp.tzinfo is None: raise ProtocolError("INVALID_TIMESTAMP", "timestamp_utc must include timezone")
        if stamp > (now or datetime.now(timezone.utc)).astimezone(timezone.utc): raise ProtocolError("INVALID_TIMESTAMP", "timestamp_utc may not be in the future")
        if (now or datetime.now(timezone.utc)).astimezone(timezone.utc) > stamp.astimezone(timezone.utc) + __import__('datetime').timedelta(seconds=self.ttl_s): raise ProtocolError("EXPIRED", "message TTL has expired")
        if self.payload_sha256 != digest(self.payload): raise ProtocolError("INTEGRITY_FAILURE", "payload_sha256 does not match payload")

@dataclass
class AgentCard:
    agent_id: str
    capabilities: list[str]
    input_schema: str = "telemetry/v1"
    output_schema: str = "finding/v1"
    reliability: float = 0.8
    limitations: list[str] = field(default_factory=list)
    status: str = "healthy"
    last_heartbeat: str = field(default_factory=utc_now)

class MessageBus:
    """Validated, replayable transport. No diagnostic agent imports another agent."""
    def __init__(self): self.messages: list[dict[str, Any]] = []; self._ids: set[str] = set(); self.agents: dict[str, AgentCard] = {}
    def register(self, card: AgentCard) -> None:
        if not 0 <= card.reliability <= 1: raise ProtocolError("INVALID_AGENT", "reliability must be 0..1")
        self.agents[card.agent_id] = card
    def publish(self, message: NCPMessage | dict[str, Any]) -> NCPMessage:
        msg = message if isinstance(message, NCPMessage) else NCPMessage.from_dict(message)
        msg.validate()
        if msg.message_id in self._ids: raise ProtocolError("DUPLICATE_MESSAGE", msg.message_id)
        self._ids.add(msg.message_id); self.messages.append(msg.to_dict()); return msg
    def replay(self, correlation_id: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["correlation_id"] == correlation_id]
    def discover(self, capability: str | None = None) -> list[dict[str, Any]]:
        cards = self.agents.values() if capability is None else (x for x in self.agents.values() if capability in x.capabilities)
        return [asdict(card) for card in cards]

def adapt_ncmp_1_0(old: dict[str, Any]) -> NCPMessage:
    """Explicit compatibility adapter for the repository's legacy ncmp/1.0 trace."""
    if old.get("protocol") != "ncmp/1.0": raise ProtocolError("UNSUPPORTED_PROTOCOL", "Legacy adapter accepts ncmp/1.0 only")
    types = {"finding":"FINDING", "report":"DIAGNOSIS", "conflict_notice":"CONFLICT_NOTICE", "probe_request":"EVIDENCE_QUERY", "probe_response":"FINDING"}
    return NCPMessage.create(str(old.get("sender") or "legacy"), str(old.get("recipient") or "legacy-topic"), types.get(old.get("type"), "ERROR"), dict(old.get("payload") or {}), correlation_id=str(old.get("incident_id") or uuid.uuid4()))
