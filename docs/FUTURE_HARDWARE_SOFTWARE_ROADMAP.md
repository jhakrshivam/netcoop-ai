# NetCoop AI: future hardware and software roadmap

This document is a build plan, not a claim that the current local dashboard
already owns or controls the listed equipment. The current program is a
read-only Windows dashboard: it observes the host computer, imports supplied
telemetry, stores evidence locally, and generates JSON reports. It does not
change a router, switch, access point, bandwidth policy, or user access.

## Current demonstration machine

- One Windows 11 laptop or desktop with Python 3.11 through 3.14, 8 GB RAM,
  and an active Ethernet or Wi-Fi connection is sufficient for the present
  project.
- Optional: LibreHardwareMonitor can expose a real CPU temperature sensor.
  If no compatible sensor is exposed, NetCoop labels temperature unavailable;
  it must not display an estimate as degrees Celsius.

## Best staged hardware build

### Stage 1: hackathon demonstrator

| Item | Suggested class | Role in NetCoop |
|---|---|---|
| Dashboard machine | Existing Windows laptop, 8 GB+ RAM | Runs the current local UI and demonstration. |
| Edge collector | Raspberry Pi 5 with 8 GB RAM, active cooling, reliable SSD, wired Ethernet | Small always-on collector for approved read-only polling and store-and-forward JSON. |
| Power | UPS sized for the laptop/collector/router/AP | Prevents false outage events during short power cuts. |
| Test network | A spare router, a managed switch, and one or two APs | Safe place to demonstrate faults without touching a campus/production network. |

The Raspberry Pi 5 is a practical collector because it has Gigabit Ethernet
and can use PoE+ with the appropriate HAT. Use a wired connection for the
collector rather than treating its Wi-Fi RSSI as infrastructure telemetry.

### Stage 2: campus or lab pilot

| Item | Minimum capability | What becomes possible |
|---|---|---|
| Edge server | x86 mini PC (Intel N100/Core i5 class), 16 GB RAM, 512 GB NVMe, two Ethernet ports preferred | Containerized collectors, local database, dashboard, and alert relay. |
| Managed PoE switch | SNMPv3, LLDP, per-port counters, VLANs, PoE budget reporting | Real interface utilization, errors, discards, AP uplink status, and topology evidence. |
| Managed Wi-Fi AP/controller | Documented read-only API or SNMPv3; client count, channel, radio load, retry and RSSI data | Actual AP/radio telemetry rather than a laptop-only BSS snapshot. |
| Router/firewall | Read-only telemetry/API support, flow/latency/loss counters, audit log | WAN status and route/path evidence; changes remain operator-approved. |
| Environmental sensors | UPS telemetry plus temperature/humidity probe for each rack/room | Separates power or room heat events from network faults. |

Use a separate management VLAN and a least-privilege read-only monitoring
account. Do not place controller credentials in a browser, JSON report, Git
repository, or source ZIP.

### Stage 3: resilient production architecture

- Two small x86 servers or VMs: one primary collector/dashboard and one
  standby/reporting node. Put the database on backed-up encrypted storage.
- A separate management network, firewall rules that permit only collector to
  device telemetry ports, and audited administrator access.
- Hardware-backed time synchronization (NTP/PTP from an approved source) so
  events from switches, APs, routers, UPS devices, and collectors correlate
  correctly.
- A VPN or zero-trust access gateway for remote operators; never publish this
  development HTTP server directly to the Internet.

## Software additions, in order

1. **Collector service**: run a signed Python service or container on the edge
   device. It polls only approved sources, timestamps each reading, preserves
   units/source/device ID, queues during outages, and posts to NetCoop.
2. **Telemetry integrations**: SNMPv3 for switches/APs/UPS devices, controller
   APIs for authorized Wi-Fi/router platforms, and syslog ingestion. Each
   adapter should declare the collection interval, permission scope, and
   limitations.
3. **Metrics platform**: Prometheus plus the official SNMP exporter for
   read-only metric collection; Grafana for historical dashboards; a retained
   database such as PostgreSQL/TimescaleDB when SQLite is no longer enough.
4. **Asset/topology source**: NetBox or an approved CMDB/IPAM system for
   authorized inventory, rack, VLAN, IP, and cable data. Imported topology
   should remain source-tagged and never be guessed from client scans.
5. **Event pipeline**: MQTT or a durable message broker, alert routing, and a
   ticket connector. Every alert must retain the raw measurements, rule,
   threshold, coverage, and confidence trace that produced it.
6. **Identity and secrets**: SSO/OIDC roles, separate read-only service
   accounts, secret vault, TLS, signed backups, audit logs, and retention
   rules.
7. **Controlled remediation (last)**: use a human approval workflow that shows
   proposed QoS/VLAN/rate-limit changes, target device, rollback, expiry, and
   post-change verification. NetCoop must remain simulation-only until a
   network owner approves a specific controller integration.

## Evidence requirements for an "ultimate" project

Every device reading should include: timestamp with timezone, device identity,
source/adapter, metric, unit, collection method, collection status, raw value,
quality/completeness, and retention policy. Every recommendation should include
the evidence inputs, alternatives, uncertainty, confidence trace, operator,
approval state, action ID, rollback plan, and verification result.

## Recommended demo narrative

1. Show NetCoop observing the Windows laptop and producing a JSON report.
2. Show a Raspberry Pi or x86 collector receiving read-only switch/AP samples.
3. Create a controlled lab fault such as an overloaded AP uplink or a UPS alarm.
4. Show the alert, evidence, confidence trace, proposed action, and JSON
   download.
5. Keep the proposed remediation labelled **Simulated** unless an authorized
   operator explicitly approves a real controller action.
