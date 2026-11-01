"""Offline, explicitly synthetic demonstration. Does not modify netcoop.db."""
import argparse
import json

from server import diagnostic_report, task_result, validate_report
from demo_scenarios import make_rows


def main():
    parser = argparse.ArgumentParser(description="Run an offline synthetic NetCoop diagnosis")
    parser.add_argument("scenario", choices=["normal", "link_congestion", "weak_wifi", "interface_fault", "dns_failure", "dhcp_failure", "server_downtime", "database_failure", "connection_pool_exhaustion", "missing"])
    args = parser.parse_args()
    rows = make_rows(args.scenario)
    result, events = task_result(f"Synthetic demo: {args.scenario}", samples=rows)
    report = diagnostic_report(f"DEMO-{args.scenario.upper()}", result)
    validate_report(report)
    result.setdefault("agent_findings", []).extend([
        {"agent":"fault_correlation_agent","status":"ok" if report["root_cause_code"] != "unknown" else "insufficient_evidence","observations":{"root_cause_code":report["root_cause_code"],"summary":f"Compared {len(report['supporting_evidence'])} evidence item(s)."}},
        {"agent":"recommendation_reporting_agent","status":"ok","observations":{"validated_fields":len(report),"summary":f"Validated report and prepared {len(report['recommended_actions'])} action(s)."}}
    ])
    print(json.dumps({"demo_data": "SYNTHETIC - NOT LIVE NETWORK DATA", "scenario": args.scenario, "agent_findings": result.get("agent_findings", []), "agent_trace": result.get("message_log", []), "report": report}, indent=2))


if __name__ == "__main__":
    main()
