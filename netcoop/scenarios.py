"""Explicitly synthetic scenarios. Ground truth belongs only in data/labels."""
from datetime import datetime, timedelta, timezone

SCENARIOS = ("normal_network", "link_congestion", "weak_wifi", "interface_fault", "dns_failure", "dhcp_failure", "device_cpu_overload", "upstream_failure", "compound_fault", "conflicting_evidence", "ambiguous_low_evidence", "interoperability_failure")
_SPEC = {
 "normal_network":{"latency_ms":("ms",20),"packet_loss_pct":("percent",0.1)},"link_congestion":{"link_utilization_pct":("percent",96),"queue_drops":("count",150),"latency_ms":("ms",180)},"weak_wifi":{"rssi_dbm":("dBm",-88),"retransmission_pct":("percent",70)},"interface_fault":{"interface_errors":("count",100),"packet_loss_pct":("percent",12)},"dns_failure":{"dns_status":("state","failed")},"dhcp_failure":{"dhcp_status":("state","failed")},"device_cpu_overload":{"cpu_pct":("percent",98),"mem_pct":("percent",94),"latency_ms":("ms",160)},"upstream_failure":{"device_status":("state","down"),"latency_ms":("ms",250)},"compound_fault":{"cpu_pct":("percent",98),"rssi_dbm":("dBm",-90),"retransmission_pct":("percent",80)},"conflicting_evidence":{"link_utilization_pct":("percent",97),"latency_ms":("ms",160),"cpu_pct":("percent",98)},"ambiguous_low_evidence":{"latency_ms":("ms",500)},"interoperability_failure":{"latency":("ms","NaN")}}
def make_scenario(name: str) -> list[dict]:
 if name not in _SPEC: raise ValueError("Unknown scenario")
 start=datetime(2026,1,1,tzinfo=timezone.utc); rows=[]
 for metric,(unit,fault) in _SPEC[name].items():
  baseline = 40 if metric.endswith("pct") else 20 if metric.endswith("ms") else -48 if metric=="rssi_dbm" else 1 if unit=="count" else "ok"
  for i in range(20): rows.append({"timestamp":(start+timedelta(minutes=i)).isoformat().replace("+00:00","Z"),"device_id":"SYNTHETIC-EDGE-1","metric":metric,"value":baseline,"unit":unit,"source":"SYNTHETIC FIXTURE — NOT LIVE","parent_device_id":"SYNTHETIC-DIST-1"})
  rows.append({"timestamp":(start+timedelta(minutes=20)).isoformat().replace("+00:00","Z"),"device_id":"SYNTHETIC-EDGE-1","metric":metric,"value":fault,"unit":unit,"source":"SYNTHETIC FIXTURE — NOT LIVE","parent_device_id":"SYNTHETIC-DIST-1"})
 return rows
