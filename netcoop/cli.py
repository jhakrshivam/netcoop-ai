from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from .evaluate import evaluate
from .orchestrator import InvestigationOrchestrator
from .scenarios import SCENARIOS, make_scenario

def main():
 p=argparse.ArgumentParser(prog="netcoop"); sub=p.add_subparsers(dest="command",required=True)
 run=sub.add_parser("run"); run.add_argument("--scenario",choices=SCENARIOS); run.add_argument("--file")
 sub.add_parser("evaluate"); sub.add_parser("serve"); agents=sub.add_parser("agents"); agents.add_argument("action",choices=["list"])
 incidents=sub.add_parser("incidents"); incidents.add_argument("action",choices=["list"])
 replay=sub.add_parser("replay"); replay.add_argument("incident_id")
 args=p.parse_args()
 if args.command=="run":
  rows=make_scenario(args.scenario) if args.scenario else json.loads(Path(args.file).read_text())
  print(json.dumps(InvestigationOrchestrator().run(rows),indent=2)); return
 if args.command=="evaluate": print(json.dumps(evaluate(),indent=2)); return
 if args.command=="agents": print(json.dumps(InvestigationOrchestrator().bus.discover(),indent=2))
 if args.command=="incidents":
  db=Path(__file__).resolve().parents[1]/"netcoop.db"
  if not db.exists(): print("[]"); return
  con=sqlite3.connect(db); rows=con.execute("SELECT id,status,created FROM incidents ORDER BY created DESC").fetchall(); con.close(); print(json.dumps([{ "incident_id":x[0],"status":x[1],"created":x[2]} for x in rows],indent=2)); return
 if args.command=="replay":
  db=Path(__file__).resolve().parents[1]/"netcoop.db"; con=sqlite3.connect(db); row=con.execute("SELECT report FROM incidents WHERE id=?",(args.incident_id,)).fetchone(); con.close()
  if not row: raise SystemExit("Incident not found")
  print(json.dumps(json.loads(row[0]),indent=2)); return
 if args.command=="serve":
  from server import Handler, live_sampler, cpu_temperature_sampler, database_status_sampler, gateway_quality_sampler
  from http.server import ThreadingHTTPServer
  import threading
  threading.Thread(target=live_sampler,daemon=True).start(); threading.Thread(target=cpu_temperature_sampler,daemon=True).start(); threading.Thread(target=database_status_sampler,daemon=True).start(); threading.Thread(target=gateway_quality_sampler,daemon=True).start(); print("NetCoop AI at http://127.0.0.1:8000"); ThreadingHTTPServer(("127.0.0.1",8000),Handler).serve_forever()
if __name__=="__main__": main()
