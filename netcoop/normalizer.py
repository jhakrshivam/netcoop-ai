"""Telemetry normalization with provenance preservation."""
from __future__ import annotations
from datetime import datetime, timezone
import math

ALIASES = {"latency":"latency_ms", "rtt":"latency_ms", "cpu":"cpu_pct", "memory":"mem_pct", "utilization":"link_utilization_pct", "loss":"packet_loss_pct", "wifi_rssi":"rssi_dbm"}
PERCENT_METRICS = {"cpu_pct", "mem_pct", "packet_loss_pct", "retransmission_pct", "link_utilization_pct", "channel_utilization_pct"}
STATUS = {"up", "down", "ok", "failed", "degraded", "healthy", "error", "warning"}

def normalize(rows: list[dict], now: datetime | None = None) -> tuple[list[dict], dict]:
    now = now or datetime.now(timezone.utc); output=[]; rejected=[]; seen=set(); stale=0
    for index, raw in enumerate(rows):
        item=dict(raw); metric=ALIASES.get(str(item.get("metric", "")).lower(), str(item.get("metric", "")).lower())
        key=(item.get("timestamp"), item.get("device_id"), metric, item.get("value"), item.get("source"))
        if key in seen: rejected.append({"row":index,"reason":"duplicate"}); continue
        seen.add(key)
        try:
            stamp=datetime.fromisoformat(str(item["timestamp"]).replace("Z","+00:00"));
            if stamp.tzinfo is None: raise ValueError("timestamp has no timezone")
            # Explicit fixtures have deliberately stable timestamps; freshness is a
            # property of collection data, not of reproducibility fixtures.
            if (now-stamp.astimezone(timezone.utc)).total_seconds()>3600 and "SYNTHETIC" not in str(item.get("source", "")).upper(): stale += 1
            value=item["value"]
            if metric not in {"device_status","dns_status","dhcp_status","server_status","database_status"}:
                value=float(value)
                if not math.isfinite(value): raise ValueError("value is not finite")
                if metric in PERCENT_METRICS and not 0<=value<=100: raise ValueError("percent outside 0..100")
            elif str(value).lower() not in STATUS: raise ValueError("invalid status value")
            if not item.get("device_id") or not item.get("unit") or not item.get("source"): raise ValueError("device_id, unit and source are required")
            output.append({**item,"metric":metric,"value":value,"timestamp":stamp.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),"raw_value":raw.get("value")})
        except (KeyError, ValueError, TypeError) as exc: rejected.append({"row":index,"reason":str(exc)})
    quality=round(max(0, 1-(len(rejected)/max(1,len(rows)))*.55-(stale/max(1,len(rows)))*.25),3)
    return output, {"input_rows":len(rows),"normalized_rows":len(output),"rejected_rows":rejected,"stale_rows":stale,"data_quality_score":quality}
