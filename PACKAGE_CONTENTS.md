# NetCoop AI package contents

The release ZIP is intentionally source-only and can be moved to another
Windows computer. It includes the application, local web dashboard, tests,
configuration, requirements, startup scripts, schemas, and documentation.

It deliberately excludes `netcoop.db`, `work/`, Python virtual environments,
test caches, logs, and credentials. These are machine-local runtime artifacts
and should never be deployed or committed.

## First run on another Windows computer

1. Extract the ZIP fully.
2. Open PowerShell in the extracted folder.
3. Run `python -m pip install -r requirements.txt`.
4. Run `./netcoop.cmd serve`.
5. Open `http://127.0.0.1:8000`.

If Python is installed but is not found automatically, use the explicit
current-session override:

```powershell
$env:NETCOOP_PYTHON = 'C:\Path\To\python.exe'
.\netcoop.cmd serve
```

## Included functional scope

- Local read-only Windows interface, gateway, neighbor-cache, CPU, memory,
  and adapter-throughput monitoring.
- Wi-Fi BSS spot-survey snapshots, clearly labelled as snapshots rather than
  continuous telemetry.
- Structured telemetry import, evidence-oriented agent workflow, confidence
  trace, downloadable JSON action reports, and local SQLite storage.
- Alert monitor, passive local throughput scan, and an on-page JSON-download
  history when the dashboard is run from this package.

No feature changes router configuration, controls student Internet access,
redistributes bandwidth, or modifies network traffic. Those actions require a
separately authorized network-controller integration and are outside this
local evidence-only package.
