"""Vercel compatibility API for NetCoop's read-only cloud viewer."""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import json


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def limitations():
    return [
        "Vercel cloud mode cannot inspect a visitor's Windows interfaces, Wi-Fi radio, ARP cache, hardware sensors, or router.",
        "Run the local NetCoop collector for live Windows measurements, or connect an approved read-only edge collector.",
        "Cloud mode never changes network configuration, bandwidth policy, or user access.",
    ]


def payload(path):
    overview = {"captured_at": now(), "hostname": "Vercel cloud viewer", "interfaces": [], "neighbors": [], "neighbor_count": 0, "interface_warning": "Local Windows network inventory is available only from a NetCoop collector running on the monitored computer.", "wifi": {"readings": [], "distinct_aps": 0, "locations": [], "last_scan": None}}
    if path == "/api/health":
        return {"ok": True, "mode": "cloud-viewer", "telemetry_records": 0, "cisco_configured": False, "steering": "not configured", "limitations": limitations()}
    if path == "/api/capabilities":
        return {"build_capabilities": ["cloud_dashboard_viewer", "local_collector_required_for_live_data", "json_export_ui"], "safety": "Cloud viewer is read-only; local collection and network changes are unavailable."}
    if path == "/api/telemetry":
        return {"records": 0, "devices": [], "states": [], "samples": [], "service_health": {"devices": [], "method": "No cloud telemetry source is connected.", "note": "Connect an approved collector before evaluating service health."}, "cisco": {"configured": False, "connected": False, "last_refresh": None, "error": None}, "steering": {"connected": False, "reason": "Traffic steering is not configured."}}
    if path == "/api/tasks": return []
    if path == "/api/network/overview": return overview
    if path == "/api/network/live": return {"interval_seconds": 1, "history": [], "error": "Live device statistics require the local Windows NetCoop collector.", "limitations": limitations()}
    if path == "/api/alerts": return {"generated_at": now(), "status": "unavailable", "alerts": [], "confidence_trace": {"checked_signals": [], "checked_count": 0, "coverage": 0.0, "method": "No approved cloud telemetry source is connected.", "limitations": limitations()}}
    if path == "/api/reports": return {"reports": [], "retention": "Cloud viewer has no configured persistent report store."}
    if path == "/api/downloads/recent": return {"downloads": [], "retention": "Cloud viewer has no configured persistent download-history store."}
    if path == "/api/v2/health": return {"ok": True, "protocol": "NCP/1.0", "runtime": "Vercel cloud viewer; local collector required for live data."}
    return {"error": "Cloud endpoint is unavailable in viewer mode.", "limitations": limitations()}, 404


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def send_json(self, value, status=200):
        raw = json.dumps(value).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        value = payload(self.path.split("?", 1)[0])
        self.send_json(*value) if isinstance(value, tuple) else self.send_json(value)
    def do_POST(self):
        self.send_json({"error": "This action is available only in the local NetCoop collector. Cloud viewer mode is read-only.", "limitations": limitations()}, 501)
