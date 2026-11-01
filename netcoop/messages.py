"""Phase 1 Pydantic v2 NCP/1.0 message models only."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import ProtocolConfig


class MessageType(str, Enum):
    TELEMETRY_SNAPSHOT = "TELEMETRY_SNAPSHOT"
    TASK_REQUEST = "TASK_REQUEST"
    FINDING = "FINDING"
    EVIDENCE_QUERY = "EVIDENCE_QUERY"
    CONFLICT_NOTICE = "CONFLICT_NOTICE"
    DIAGNOSIS = "DIAGNOSIS"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    AGENT_STATUS = "AGENT_STATUS"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def payload_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class NCPMessage(BaseModel):
    """Validated protocol envelope used at every Phase 1 boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    protocol_version: str = "NCP/1.0"
    message_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID = Field(default_factory=uuid4)
    sender: str = Field(min_length=1, max_length=160)
    recipient_or_topic: str = Field(min_length=1, max_length=160)
    message_type: MessageType
    timestamp_utc: datetime = Field(default_factory=utc_now)
    schema_version: str = "1.0"
    payload: dict[str, Any]
    ttl_s: int = Field(default=60, ge=1, le=3600)
    payload_sha256: str | None = None

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_utc_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc must include a UTC offset")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_protocol_and_integrity(self) -> "NCPMessage":
        if self.protocol_version != "NCP/1.0":
            raise ValueError("protocol_version must be NCP/1.0")
        if self.schema_version != "1.0":
            raise ValueError("schema_version must be 1.0")
        expected = payload_sha256(self.payload)
        if self.payload_sha256 is not None and self.payload_sha256 != expected:
            raise ValueError("payload_sha256 does not match payload")
        object.__setattr__(self, "payload_sha256", expected)
        return self

    @classmethod
    def create(cls, message_type: MessageType, *, sender: str = "phase1-test", recipient_or_topic: str = "phase1-topic", payload: dict[str, Any] | None = None, correlation_id: UUID | None = None, config: ProtocolConfig | None = None) -> "NCPMessage":
        settings = config or ProtocolConfig()
        return cls(sender=sender, recipient_or_topic=recipient_or_topic, message_type=message_type, payload=payload or {}, correlation_id=correlation_id or uuid4(), ttl_s=settings.message_ttl_s, protocol_version=settings.protocol_version, schema_version=settings.schema_version)
