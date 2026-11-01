# NCP conformance

Run `C:\Users\Kumar Shivam\AppData\Local\Python\bin\python.exe -m unittest tests.test_ncp_core -v`.

The suite covers required envelope fields, message integrity, duplicate protection, legacy adaptation, finding exchange, and insufficient-evidence handling. The external agent example uses one JSON message per stdin line and one NCP response per stdout line; use `TASK_REQUEST` with a `telemetry` payload.
