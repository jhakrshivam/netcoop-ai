# Field and unit dictionary

| Field | Unit | Meaning |
|---|---|---|
| `latency_ms`, `jitter_ms` | ms | End-to-end latency/jitter supplied by a collector. |
| `packet_loss_pct`, `cpu_pct`, `mem_pct`, `link_utilization_pct`, `retransmission_pct` | percent | A value constrained to 0–100. |
| `rssi_dbm` | dBm | RSSI at the survey/client location. |
| `interface_errors`, `queue_drops` | count | Non-negative reported counter. |
| `dns_status`, `dhcp_status`, `device_status` | state | Explicit source-reported status; never inferred. |
