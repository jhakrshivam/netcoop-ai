# NetCoop AI network operations dashboard

A local dashboard for importing and inspecting real telemetry. It ships with no sample campus readings, device statuses, or inferred links.

## Run locally

Requires Python 3.11–3.14. Install dependencies first so the NCP models,
temperature collector, and tests are available on a new system.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
python server.py
```

Open `http://127.0.0.1:8000`. If the browser remains on the loading screen,
stop the server with `Ctrl+C`, start it again with `python server.py`, and do a
hard refresh with `Ctrl+F5`. The server must remain open while using the site.

For the portable Windows launcher, use:

```powershell
.\netcoop.cmd serve
```

SQLite stores imported readings and investigations in `netcoop.db`. It is local
runtime data and is deliberately excluded from the GitHub/deployment package.

## GitHub and free-hosting handoff

Upload the source package as a new GitHub repository, then let the host install
`requirements.txt` and start `python server.py`. This build binds to
`127.0.0.1` by design, so it works as a local desktop dashboard. A public host
needs a separate authenticated HTTPS deployment and a production server wrapper;
do not expose this local development server directly to the Internet.

Before uploading, never include `.venv/`, `netcoop.db`, `work/`, `.pytest_cache/`,
or credentials. Copy `config.yaml` as the starting configuration and place
controller credentials only in deployment environment variables.

The server binds to `127.0.0.1`, so only this computer can open it. Sharing the dashboard with other people requires an authenticated HTTPS deployment; do not expose the current local server directly to a LAN or the Internet.

## Portable startup and JSON operation reports

Use `./netcoop.cmd serve` from the extracted project folder. The portable launcher resolves its own location, validates the server with `GET /api/health` before opening a browser, and replaces only an older NetCoop process from the same project when an update is detected. See [START_HERE.md](START_HERE.md) and the [portable handoff chart](outputs/PORTABLE_DEPLOYMENT_REQUIREMENTS.md).

Every user-triggered POST operation produces a persistent JSON action report in SQLite and returns `action_report_id`; download it at `GET /api/action-reports/{action_report_id}.json`. Recent report metadata is available from `GET /api/reports`.

Additional local, read-only reporting operations:

- `POST /api/system/report` — organized hardware, software, local network, and limitations report.
- `POST /api/network/realtime-report` — current local adapter samples and up to three minutes of live history.
- `POST /api/network/mitigation-plan` — a dry-run jitter/loss investigation and mitigation plan. It never changes Windows, Wi-Fi, routes, QoS, DNS, or network devices.

The live sampler refreshes the following local status automatically: CPU/memory and adapter traffic every second, CPU temperature every 30 seconds when an actual compatible sensor is available, SQLite database status/record counts every 15 seconds, and a single ICMP echo to the Windows-reported private default gateway every 10 seconds. Gateway ICMP no-replies and latency spread are labeled **local gateway quality**; they are not assumed to be Internet/campus-wide loss or jitter. See [hackathon traceability](outputs/HACKATHON_REQUIREMENT_TRACEABILITY.md).

The dashboard’s **System JSON report**, **Live network JSON**, and **Quality dry-run** controls call these operations and expose their action-report download link.

## Temperature collector: demo mode and real hardware setup

For a presentation without a sensor, use the explicit demo mode below. It produces a random walk solely for demonstration and every reading is marked `kind: "simulated"`, `source: "demo"`, and `SIMULATED` in its detail. It is not a temperature measurement and must not be presented as one.

```powershell
& 'C:\Users\Kumar Shivam\AppData\Local\Python\bin\python.exe' -m netcoop.collectors.temperature --demo
```

For genuine Windows hardware data, install and run [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) as Administrator, then enable **Options > Remote Web Server > Run**. Confirm that `http://localhost:8085/data.json` opens on the same laptop, then run:

```powershell
& 'C:\Users\Kumar Shivam\AppData\Local\Python\bin\python.exe' -m netcoop.collectors.temperature
```

The collector first uses a CPU-specific temperature sensor exposed by the hardware monitor. If one is unavailable, it reports an estimated thermal-stress index with `temp_c: null`; it never converts an estimate into degrees Celsius. Stop the hardware monitor after use if you do not want its local web endpoint running.

## NCP/1.0 development core

The preserved dashboard/API remains the default interface. Additive NCP/1.0 components live in `netcoop/` and do not replace the legacy `ncmp/1.0` activity trace. Use the verified local interpreter:

```powershell
& 'C:\Users\Kumar Shivam\AppData\Local\Python\bin\python.exe' -m netcoop.cli run --scenario link_congestion
& 'C:\Users\Kumar Shivam\AppData\Local\Python\bin\python.exe' -m netcoop.cli evaluate
& 'C:\Users\Kumar Shivam\AppData\Local\Python\bin\python.exe' -m unittest tests.test_ncp_core -v
```

`/api/v2/health`, `/api/v2/agents`, `/api/v2/scenarios`, `/api/v2/topology`, `/api/v2/evaluation`, `POST /api/v2/diagnosis`, and `GET /api/v2/incidents/{id}` are additive endpoints. They accept supplied telemetry only; scenarios are explicitly synthetic. See [the phase-0 environment gate](docs/phase-0-gate.md), [implementation inventory](docs/implementation_inventory.md), and [NCP protocol](docs/protocol.md) for verified limitations.

## Import telemetry

Choose **CSV format** in the dashboard to download a header-only template. Required columns:

```csv
timestamp,device_id,metric,value,unit,source,parent_device_id,path_id
```

Timestamps must include a timezone. Each measurement must include its source and unit. `parent_device_id` and `path_id` are optional and displayed only when supplied. Aliases such as `latency` -> `latency_ms`, `cpu` -> `cpu_pct`, and `utilization` -> `link_utilization_pct` are normalized. Values are not silently converted. A device/metric cannot be imported with a different unit from existing history.

CSV import is a local ingest path, not a live collector.

## Local network overview and Wi-Fi spot survey

The main screen now reads the Windows network-interface inventory, the local ARP neighbor cache, and—when requested—the WLAN BSS scan API. It shows active adapters, assigned IPv4/prefix, gateway, adapter-reported link rate, and cached neighbor IPs. Cached neighbors now show observed MAC, interface, gateway role, and optional one-echo reachability results. **Check cached peers** checks Windows-reported private default gateways and addresses already in the Windows neighbor cache, with one ICMP echo each; it never sweeps the subnet. ICMP no-reply is inconclusive because a firewall may block it.

Choose **Signal coverage**, put the computer at the physical point you want to inspect, enter a spot label, and click **Scan Wi-Fi here**. The scan records BSSID-level RSSI in dBm and the Windows driver quality percentage. It is a location-labeled measurement from this computer, not an automatic room locator. The dashboard reports the strongest AP and each overlapping AP separately. RSSI values in dBm are not added together because clients associate to an AP and arithmetic summation would misstate usable signal. To compare areas, move the computer and scan with another spot label.

**Live device stats** samples Windows CPU time, physical memory, and each active local adapter's cumulative IPv4 bytes approximately every second. It derives receive/send throughput from counter changes and returns a lightweight 3-minute graph window from a 10-minute in-memory history. The curves smooth only the display between actual samples. CPU temperature is shown only when a CPU-specific sensor is exposed through LibreHardwareMonitor/OpenHardwareMonitor; otherwise the page says unavailable instead of estimating it. These are measurements for the computer running the dashboard, not per-client, AP, ISP, or controller statistics. Low traffic means this computer is currently transferring little data; it is not an Internet speed test. The in-memory history resets when the server restarts.

Interface and ARP details are queried from Windows when the overview refreshes. Wi-Fi survey history is stored in the local SQLite database. No scan data is sent to Cisco or another service.

## Optional Cisco Catalyst SD-WAN Manager health reader

If you already operate Cisco Catalyst SD-WAN Manager, the dashboard can read device hardware health (reported state, CPU and memory). Set these **server-side** environment variables before starting the server:

```powershell
$env:NETCOOP_CISCO_BASE_URL = 'https://your-manager.example:8443'
$env:NETCOOP_CISCO_USERNAME = 'read-only-api-user'
$env:NETCOOP_CISCO_PASSWORD = 'set-this-outside-the-repository'
python server.py
```

Use a read-only account with the needed device monitoring role and a certificate trusted by the machine running NetCoop. TLS certificate verification is enforced; the app refuses HTTP and redirects. When the dashboard is open, it polls the Manager's hardware-health detail endpoint every 60 seconds; **Refresh Cisco health** triggers an immediate read. Credentials are sent only to the configured Manager and are never returned to the browser or written to SQLite. The connection uses Cisco's JWT login endpoint. This connector is read-only and has not been validated against your specific Manager release or account. It reads reported device state, CPU, and memory; interface performance collection and controller policy changes are not enabled by this connector.

Do not paste credentials into the web page, commit them, or use a high-privilege account.

## Detection and response behavior

- At least 20 prior observations are required for a per-device, per-metric baseline.
- The detector compares the latest value with the historical median and median absolute deviation, marking a deviation above modified score 3.5. This rule has not been benchmarked or calibrated for your network. Insufficient history remains **Unknown**.
- Normal measurements do not trigger action.
- Deviations create an investigation record; they do not establish root cause by themselves.
- No route, hardware setting, or production traffic is changed. Automatic steering is **not configured**. Enabling it requires the actual controller and version, observed alternate-path capacity and health, operator-defined safety limits, and post-change verification.
- File size alone, including a 200 GB transfer, is not a congestion signal. Safe shifting requires observed flow/path load, alternate-path headroom, and live controller confirmation.

The investigation workflow has deterministic performance, infrastructure-health, and connectivity analysis roles. They receive separate evidence slices and send structured `ncmp/1.0` findings to correlation; the report view exposes this message trace. These are local rule-based roles, not independent LLM services. The current correlator reports deviations and supplied topology scope but does not assert a root cause without a validated evidence rule.

## Features

- Telemetry CSV import with timestamp/unit validation and rejected-row reporting
- Trend graph of imported measurements
- Per-device latest metrics and reported health
- Local interface, gateway, MAC, DNS, neighbor cache, and explicit cached-peer reachability view
- Topology view from supplied parent relationships only
- Normal / anomaly / unknown classification with history requirements
- Investigation history stored in SQLite
- One-second local CPU, memory, and adapter traffic sampling with a rolling graph; CPU temperature only when a compatible CPU-specific sensor is exposed

## API

- `GET /api/health`
- `GET /api/telemetry`
- `GET /api/network/live` (one-second Windows CPU, memory, temperature-if-exposed, and adapter snapshots; 3-minute response window)
- `POST /api/network/probe` (one ICMP echo to each Windows-reported private gateway and cached private peer; no subnet sweep)
- `GET /api/action-reports/{id}.json` (JSON result for each POST operation)
- `GET /api/network/overview`
- `POST /api/network/scan` (Windows WLAN spot survey)
- `POST /api/telemetry/import` (`text/csv` body)
- `POST /api/telemetry/clear`
- `POST /api/cisco/refresh` (only if server-side Cisco settings are present)
- `GET /api/tasks` and `GET /api/tasks/{id}`
- `POST /api/tasks` (`{"request":"..."}`)
- `POST /api/tasks/clear`

## Limitations

There is no automatic route controller in this build. The local Windows adapter, CPU/memory counters, adapter byte counters, ARP cache, and WLAN BSS scan are live reads; the Cisco reader polls hardware health only when configured and the dashboard is open, and does not provide link utilization or latency. There is no live SNMP, gNMI, or Prometheus connection unless explicitly configured. Root-cause accuracy and detector calibration have not been evaluated. Align the schema and thresholds with your actual network and policy before operational use.

## Agent workflow, health score, and reports

The **Analyze telemetry** workflow uses five distinct local agents: performance, infrastructure health, connectivity, fault correlation, and recommendation/reporting. Agents exchange structured `ncmp/1.0` messages with documented units and meanings in [docs/agent-protocol.md](docs/agent-protocol.md). If findings conflict, the workflow records a recheck exchange against the same captured evidence; it does not claim a fresh device poll.

Each investigation exposes a downloadable JSON report at `GET /api/tasks/{id}/report.json`, validated against [schemas/report.schema.json](schemas/report.schema.json). The adjacent `GET /api/tasks/{id}/activity.json` downloads every workflow event, five agent outputs, inter-agent message, and final report. Every POST operation returns an action-report ID and can be downloaded from `GET /api/action-reports/{id}.json`; those records follow [schemas/action-report.schema.json](schemas/action-report.schema.json). Reports contain the incident ID, status, suspected root cause (or insufficient evidence), rule-based confidence, affected devices, supporting evidence, alternative causes, actions, evidence sources, limitations, and conflict details. This is a rule-based starting point; confidence and diagnostic accuracy have not been calibrated on a real network.

The dashboard's **Service health score** is a coverage-adjusted heuristic out of 100 using reported server/DNS/database state, connection-pool use, CPU, memory, latency, and packet loss. It is labeled uncalibrated. Missing measurements reduce coverage and are not fabricated or silently treated as healthy. “Connection pool exhaustion,” DNS, database, and server-down findings require the relevant source metrics/statuses to be supplied; local PC counters cannot reveal remote service health.

The six-step demo guide covers fault context, agents, architecture, demonstration, implementation choices, and results/limits. Its one-click scenario is an explicit synthetic fixture, visibly labeled and stored only as an investigation, never imported into the live telemetry table. Available fixtures and tests are documented in [tests/README.md](tests/README.md). Run `python demo.py connection_pool_exhaustion` for a terminal JSON example.

## Additional API

- `POST /api/demo/run` with `{"scenario":"link_congestion"}` creates a clearly labeled synthetic investigation without adding telemetry.
- `GET /api/tasks/{id}/report.json` downloads the schema-conformant diagnostic report.
- `GET /api/tasks/{id}/activity.json` downloads the task events, five agent outputs, inter-agent messages, and diagnostic report as a full activity trace.
- Every POST operation receives a downloadable action JSON link in the dashboard notification; action records are also stored locally.

Router/modem attribution requires those devices and their relationships to be supplied by an authorized telemetry/controller integration. The existing Cisco reader is hardware-health read-only; it does not change routes or expose full per-hop diagnosis. Team access requires a separate authenticated HTTPS deployment; this local server binds only to loopback.
