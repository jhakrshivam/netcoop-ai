"""Separate-process BYO-agent conformance example (stdin/stdout JSON)."""
from __future__ import annotations
import json, sys
from .protocol import AgentCard, NCPMessage, ProtocolError

CARD=AgentCard("external-latency-agent",["performance-analysis"],reliability=.72,limitations=["Example process; analyzes supplied latency only."])
def respond(raw):
 try:
  message=NCPMessage.from_dict(raw)
  if message.message_type!="TASK_REQUEST": raise ProtocolError("INVALID_REQUEST","TASK_REQUEST required")
  rows=message.payload.get("telemetry",[]); evidence=[x for x in rows if x.get("metric") in ("latency_ms","jitter_ms") and isinstance(x.get("value"),(int,float)) and x["value"]>=120]
  return NCPMessage.create(CARD.agent_id,message.sender,"FINDING",{"agent":CARD.agent_id,"status":"ok","hypotheses":{"congestion":.6} if evidence else {},"evidence":evidence},message.correlation_id).to_dict()
 except ProtocolError as exc: return NCPMessage.create(CARD.agent_id,"requester","ERROR",exc.as_dict()).to_dict()
for line in sys.stdin:
 try: print(json.dumps(respond(json.loads(line))))
 except json.JSONDecodeError: print(json.dumps(NCPMessage.create(CARD.agent_id,"requester","ERROR",{"code":"MALFORMED_JSON"}).to_dict()))
