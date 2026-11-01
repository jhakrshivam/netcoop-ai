# Run NetCoop on any Windows computer

1. Extract the complete project folder; do not run files from inside the ZIP archive.
2. Install Python **3.11–3.14** and select “Add Python to PATH”. Install the project dependencies once before the first launch.
3. Open PowerShell **in this project folder**.
4. Run `python -m pip install -r requirements.txt`, then `./netcoop.cmd serve`.
5. The launcher waits for `GET /api/health` to succeed before opening `http://127.0.0.1:8000`.

If it reports that Python is missing, set the current-session interpreter explicitly, then run again:

```powershell
$env:NETCOOP_PYTHON = 'C:\Path\To\Python\python.exe'
.\netcoop.cmd serve
```

The launcher is portable: it resolves paths relative to itself and contains no username- or laptop-specific path.
