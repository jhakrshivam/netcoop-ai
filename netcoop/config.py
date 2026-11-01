"""Phase 1 protocol configuration; no orchestration or diagnosis settings live here."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class ProtocolConfig:
    protocol_version: str = "NCP/1.0"
    schema_version: str = "1.0"
    message_log_path: Path = Path("work/message-log.jsonl")
    message_ttl_s: int = 60

    @classmethod
    def from_environment(cls) -> "ProtocolConfig":
        log_path = Path(os.getenv("NETCOOP_MESSAGE_LOG", "work/message-log.jsonl"))
        ttl_s = int(os.getenv("NETCOOP_MESSAGE_TTL_S", "60"))
        if not 1 <= ttl_s <= 3600:
            raise ValueError("NETCOOP_MESSAGE_TTL_S must be between 1 and 3600")
        return cls(message_log_path=log_path, message_ttl_s=ttl_s)
