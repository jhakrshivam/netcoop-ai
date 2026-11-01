"""Reproducible evaluation; labels are read separately from agent input."""
from __future__ import annotations
import json, time
from pathlib import Path
from .orchestrator import InvestigationOrchestrator
from .scenarios import SCENARIOS, make_scenario

LABELS = {"normal_network":"normal_network","link_congestion":"congestion","weak_wifi":"weak_wireless_signal","interface_fault":"interface_fault","dns_failure":"dns_dhcp_failure","dhcp_failure":"dns_dhcp_failure","device_cpu_overload":"device_overload","upstream_failure":"upstream_issue","compound_fault":"weak_wireless_signal","conflicting_evidence":None,"ambiguous_low_evidence":None,"interoperability_failure":None}
def evaluate() -> dict:
    outcomes=[]; begin=time.perf_counter()
    for name in SCENARIOS:
        report=InvestigationOrchestrator().run(make_scenario(name),"EVAL-"+name.upper())
        expected=LABELS[name]; actual=report["suspected_root_cause"]
        correct=(actual==expected) if expected else (actual is None)
        outcomes.append({"scenario":name,"expected":expected,"actual":actual,"abstained":actual is None,"correct":correct,"latency_ms":round((time.perf_counter()-begin)*1000,2)})
    nonamb=[x for x in outcomes if LABELS[x["scenario"]] is not None]; accuracy=sum(x["correct"] for x in nonamb)/max(1,len(nonamb)); abst=[x for x in outcomes if LABELS[x["scenario"]] is None]
    return {"scenarios":outcomes,"metrics":{"non_ambiguous_accuracy":round(accuracy,3),"abstention_correctness":round(sum(x["correct"] for x in abst)/max(1,len(abst)),3),"execution_latency_ms":round((time.perf_counter()-begin)*1000,2),"note":"Synthetic development fixtures only. Blind evaluation, ECE, ablation, and coverage are not yet verified."}}
