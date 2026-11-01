"""Independent evidence handlers. They share NCP messages, not implementation imports."""
from __future__ import annotations
from collections import defaultdict
from .protocol import AgentCard

def card(agent_id, capability, reliability=.8, limitations=()):
    return AgentCard(agent_id, [capability], reliability=reliability, limitations=list(limitations))

def _latest(rows):
    result={}
    for row in rows:
        key=(row["device_id"],row["metric"])
        if key not in result or row["timestamp"]>result[key]["timestamp"]: result[key]=row
    return result

def normalizer_agent(rows, quality):
    return {"agent":"normalizer", "status":"ok" if rows else "no_data", "hypotheses":{}, "evidence":[], "data_quality":quality, "limitations":["Only provided telemetry was normalized."]}

def performance_agent(rows, quality):
    latest=_latest(rows); evidence=[]; support=defaultdict(float)
    for (_, metric), row in latest.items():
        val=row["value"]
        if metric=="link_utilization_pct" and val>=90: support["congestion"]+=.75; evidence.append(row)
        if metric in ("latency_ms","jitter_ms") and val>=120: support["congestion"]+=.45; support["upstream_issue"]+=.25; evidence.append(row)
        if metric=="packet_loss_pct" and val>=5: support["interface_fault"]+=.5; support["congestion"]+=.25; evidence.append(row)
    return {"agent":"performance", "status":"ok" if evidence else "no_finding", "hypotheses":dict(support), "evidence":evidence, "data_quality":quality, "limitations":["Thresholds are initial rules, not calibrated probabilities."]}

def infrastructure_agent(rows, quality):
    latest=_latest(rows); evidence=[]; support=defaultdict(float)
    for (_,metric),row in latest.items():
        val=row["value"]
        if metric in ("cpu_pct","mem_pct") and val>=90: support["device_overload"]+=.65; evidence.append(row)
        if metric in ("interface_errors","queue_drops") and val>20: support["interface_fault" if metric=="interface_errors" else "congestion"]+=.7; evidence.append(row)
        if metric=="device_status" and str(val).lower() in ("down","failed","error"): support["hardware_failure"]+=.8; evidence.append(row)
    return {"agent":"infrastructure", "status":"ok" if evidence else "no_finding", "hypotheses":dict(support), "evidence":evidence, "data_quality":quality, "limitations":["Hardware health is based on supplied data only."]}

def connectivity_agent(rows, quality):
    latest=_latest(rows); evidence=[]; support=defaultdict(float); children=defaultdict(set)
    for row in rows:
        if row.get("parent_device_id"): children[row["parent_device_id"]].add(row["device_id"])
    for (_, metric), row in latest.items():
        if metric=="device_status" and str(row["value"]).lower() in ("down","failed","error"): support["upstream_issue"]+=.55; evidence.append(row)
    blast=sorted({node for group in children.values() for node in group})
    return {"agent":"connectivity", "status":"ok" if rows else "no_data", "hypotheses":dict(support), "evidence":evidence, "blast_radius":blast, "data_quality":quality, "limitations":["Topology is derived only from supplied parent_device_id edges."]}

def wireless_agent(rows, quality):
    latest=_latest(rows); evidence=[]; support=0
    for (_,metric),row in latest.items():
        if metric=="rssi_dbm" and row["value"] <= -75: support+=.7; evidence.append(row)
        if metric in ("retransmission_pct","channel_utilization_pct") and row["value"] >= 40: support+=.45; evidence.append(row)
    return {"agent":"wireless", "status":"ok" if evidence else "no_finding", "hypotheses":{"weak_wireless_signal":min(1,support)} if support else {}, "evidence":evidence, "data_quality":quality, "limitations":["Signal applies only to surveyed/client-reported locations."]}

def service_agent(rows, quality):
    latest=_latest(rows); evidence=[]; support=defaultdict(float)
    for (_,metric),row in latest.items():
        if str(row["value"]).lower() in ("down","failed","error"):
            cause={"dns_status":"dns_dhcp_failure","dhcp_status":"dns_dhcp_failure"}.get(metric)
            if cause: support[cause]+=.9; evidence.append(row)
    return {"agent":"service", "status":"ok" if evidence else "no_finding", "hypotheses":dict(support), "evidence":evidence, "data_quality":quality, "limitations":["DNS/DHCP needs explicit supplied status measurements."]}

HANDLERS = {"normalizer":normalizer_agent,"performance":performance_agent,"infrastructure":infrastructure_agent,"connectivity":connectivity_agent,"wireless":wireless_agent,"service":service_agent}
CARDS = [card("normalizer","normalize",.95),card("performance","performance-analysis",.82),card("infrastructure","infrastructure-analysis",.82),card("connectivity","topology-analysis",.8),card("wireless","wireless-analysis",.78),card("service","service-analysis",.8)]
