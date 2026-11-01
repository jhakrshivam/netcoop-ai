import pytest

from netcoop.message_log import MessageLog
from netcoop.messages import MessageType, NCPMessage


def test_every_message_type_validates_and_is_logged(tmp_path):
    log = MessageLog(tmp_path / "messages.jsonl")
    messages = [NCPMessage.create(kind, payload={"test": kind.value}) for kind in MessageType]

    for message in messages:
        assert message.model_validate(message.model_dump()).message_type == message.message_type
        assert len(message.payload_sha256) == 64
        log.append(message)

    restored = log.read_all()
    assert [message.message_type for message in restored] == list(MessageType)


def test_payload_tampering_is_rejected():
    message = NCPMessage.create(MessageType.FINDING, payload={"metric": "latency_ms", "value": 50})
    raw = message.model_dump()
    raw["payload"] = {"metric": "latency_ms", "value": 500}
    with pytest.raises(ValueError, match="payload_sha256"):
        NCPMessage.model_validate(raw)
