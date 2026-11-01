"""Append-only JSONL message log for Phase 1 validation/replay groundwork."""
from __future__ import annotations

from pathlib import Path
from .messages import NCPMessage


class MessageLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, message: NCPMessage) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(message.model_dump_json() + "\n")

    def read_all(self) -> list[NCPMessage]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as stream:
            return [NCPMessage.model_validate_json(line) for line in stream if line.strip()]
