"""Fault-tolerant bounded worker orchestration and explainable correlation."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import math, uuid
from .agents import CARDS, HANDLERS
from .normalizer import normalize
from .protocol import MessageBus, NCPMessage, ProtocolError

PRIOR = {"congestion":.15,"weak_wireless_signal":.12,"interface_fault":.12,"device_overload":.12,"dns_dhcp_failure":.1,"upstream_issue":.1,"hardware_failure":.08,"normal_network":.21}
ACTIONS = {"congestion":"Inspect capacity, queues, and alternative path headroom.","weak_wireless_signal":"Survey RSSI/SNR at affected locations and inspect AP/channel load.","interface_fault":"Inspect cable, interface errors, and link transitions.","device_overload":"Check CPU, memory, process load, and affected interfaces.","dns_dhcp_failure":"Inspect resolver/DHCP status and lease allocation.","upstream_issue":"Compare shared parent and upstream paths.","hardware_failure":"Verify device health and maintenance logs."}

class InvestigationOrchestrator:
    def __init__(self, timeout_s=3, max_workers=6):
        self.timeout_s=timeout_s; self.max_workers=max_workers; self.bus=MessageBus()
        for card in CARDS: self.bus.register(card)
    def run(self, telemetry: list[dict], incident_id: str | None=None, disabled_agents=()) -> dict:
        incident_id=incident_id or "INC-"+uuid.uuid4().hex[:10].upper(); correlation_id=str(uuid.uuid4()); trace=[]; lifecycle=["CREATED","VALIDATING","NORMALIZING","INVESTIGATING"]
        rows, quality=normalize(telemetry)
        self.bus.publish(NCPMessage.create("orchestrator","normalizer","TASK_REQUEST",{"rows":len(telemetry)},correlation_id))
        findings=[]; missing=[]
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="netcoop-agent") as pool:
            futures={pool.submit(fn, rows, quality):name for name,fn in HANDLERS.items() if name not in disabled_agents and name!="normalizer"}
            missing.extend(disabled_agents)
            for future in as_completed(futures, timeout=self.timeout_s*max(1,len(futures))):
                name=futures[future]
                try: finding=future.result(timeout=self.timeout_s); findings.append(finding)
                except Exception as exc: missing.append(name); finding={"agent":name,"status":"failed","error":type(exc).__name__,"hypotheses":{},"evidence":[],"data_quality":quality}
                message=NCPMessage.create(name,"correlation","FINDING",finding,correlation_id); self.bus.publish(message); trace.append(message.to_dict())
        lifecycle.append("CORRELATING")
        scores={key:math.log(value) for key,value in PRIOR.items()}; provenance={}; conflicts=[]
        for finding in findings:
            rel=next((c.reliability for c in CARDS if c.agent_id==finding["agent"]),.7); q=quality["data_quality_score"]
            for cause,support in finding.get("hypotheses",{}).items():
                evidence_keys={(x.get("device_id"),x.get("metric"),x.get("timestamp")) for x in finding.get("evidence",[])}
                unique=len(evidence_keys-provenance.setdefault(cause,set())); provenance[cause].update(evidence_keys)
                scores[cause]=scores.get(cause,math.log(.02))+rel*q*min(1,support)*(1 if unique else .35)
        # Temperature is configurable in a production configuration store. 0.5 is
        # the current explicit synthetic-development setting, never a calibration claim.
        ranked=sorted(scores.items(),key=lambda x:x[1],reverse=True); high,second=ranked[0],ranked[1]; temperature=.5; exp=[math.exp((x[1]-high[1])/temperature) for x in ranked]; posterior=1/sum(exp)
        if second[1] > high[1]-.25:
            conflicts.append({"between":[high[0],second[0]],"outcome":"preserved","method":"insufficient score separation"})
            note=NCPMessage.create("correlation","agents","CONFLICT_NOTICE",conflicts[-1],correlation_id); self.bus.publish(note); trace.append(note.to_dict())
            query=NCPMessage.create("correlation","agents","EVIDENCE_QUERY",{"competing":conflicts[-1]["between"],"request":"additional independent measurements"},correlation_id); self.bus.publish(query); trace.append(query.to_dict())
        lifecycle.append("RESOLVING_CONFLICTS")
        diversity=min(1,len({f["agent"] for f in findings if f.get("evidence")})/4); confidence=round(max(0,min(1,posterior*quality["data_quality_score"]*(.65+.35*diversity)-.15*len(conflicts))),3)
        # Below 0.25 we deliberately abstain. This is a policy threshold, not a
        # calibration claim; unresolved conflicts remain penalized above.
        abstain=not rows or quality["data_quality_score"]<.45 or confidence<.25 or (high[0]=="normal_network" and any(f.get("evidence") for f in findings))
        status="INSUFFICIENT_EVIDENCE" if abstain else "DEGRADED" if missing else "DIAGNOSIS_READY"; lifecycle.append(status)
        evidence=[item for finding in findings for item in finding.get("evidence",[])]
        report={"incident_id":incident_id,"status":status,"suspected_root_cause":None if abstain else high[0],"confidence":None if abstain else confidence,"affected_devices":sorted({x.get("device_id") for x in evidence if x.get("device_id")}),"supporting_evidence":evidence,"alternative_causes":[{"cause":c,"score":round(s,3)} for c,s in ranked[1:4]],"recommended_actions":[] if abstain else [ACTIONS.get(high[0],"Collect corroborating telemetry.")],"evidence_sources":sorted({f["agent"] for f in findings if f.get("evidence")}),"limitations":["Synthetic inputs remain explicitly labeled." if any("SYNTHETIC" in str(x.get("source","")) for x in rows) else "Only supplied telemetry was assessed.",*(["Missing or failed agents: "+", ".join(missing)] if missing else [])],"confidence_breakdown":{"posterior":round(posterior,3),"data_quality":quality["data_quality_score"],"evidence_diversity":round(diversity,3),"temperature":temperature,"unresolved_conflicts":len(conflicts),"method":"configured priors + reliability-weighted evidence; not calibrated"},"hypothesis_ranking":[{"cause":c,"score":round(s,3)} for c,s in ranked],"causal_chain":[],"blast_radius":next((f.get("blast_radius",[]) for f in findings if f["agent"]=="connectivity"),[]),"data_quality_summary":quality,"agent_timeline":[{"agent":f["agent"],"status":f["status"]} for f in findings],"conflicts_resolved":conflicts,"what_would_change_my_mind":"Independent, recent topology and path measurements that materially support another hypothesis."}
        diagnosis=NCPMessage.create("correlation","reporting","DIAGNOSIS",report,correlation_id); self.bus.publish(diagnosis); trace.append(diagnosis.to_dict()); report["message_trace"]=trace; report["lifecycle"]=lifecycle
        return report
