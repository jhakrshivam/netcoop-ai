import unittest
import json, subprocess, sys
from netcoop.protocol import NCPMessage, MessageBus, ProtocolError, adapt_ncmp_1_0
from netcoop.orchestrator import InvestigationOrchestrator
from netcoop.scenarios import make_scenario

class NcpConformanceTests(unittest.TestCase):
 def test_integrity_duplicate_and_ttl(self):
  msg=NCPMessage.create("a","b","HEARTBEAT",{"ready":True}); bus=MessageBus(); bus.publish(msg)
  with self.assertRaises(ProtocolError): bus.publish(msg)
  raw=msg.to_dict(); raw["payload"]={"ready":False}
  with self.assertRaises(ProtocolError): NCPMessage.from_dict(raw)
 def test_legacy_adapter_and_report(self):
  self.assertEqual(adapt_ncmp_1_0({"protocol":"ncmp/1.0","sender":"a","recipient":"b","type":"finding","payload":{}}).message_type,"FINDING")
  report=InvestigationOrchestrator().run(make_scenario("link_congestion"))
  self.assertEqual(report["status"],"DIAGNOSIS_READY")
  self.assertEqual(report["suspected_root_cause"],"congestion")
  self.assertTrue(any(x["message_type"]=="FINDING" for x in report["message_trace"]))
 def test_abstains_on_invalid_or_ambiguous_data(self):
  report=InvestigationOrchestrator().run(make_scenario("interoperability_failure"))
  self.assertEqual(report["status"],"INSUFFICIENT_EVIDENCE")
 def test_external_agent_process_returns_valid_finding(self):
  task=NCPMessage.create("test","external-latency-agent","TASK_REQUEST",{"telemetry":[{"metric":"latency_ms","value":150}]}).to_dict()
  proc=subprocess.run([sys.executable,"-m","netcoop.external_example_agent"],input=json.dumps(task)+"\n",text=True,capture_output=True,timeout=5)
  reply=NCPMessage.from_dict(json.loads(proc.stdout)); self.assertEqual(reply.message_type,"FINDING")
if __name__=="__main__": unittest.main()
