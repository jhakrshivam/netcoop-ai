"""NetCoop AI: evidence-only local dashboard API.

No sample telemetry or topology is bundled. Records are accepted only from a
user-supplied CSV or a configured integration adapter.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone
from demo_scenarios import make_rows as demo_rows
from netcoop.orchestrator import InvestigationOrchestrator
from netcoop.scenarios import SCENARIOS
from netcoop.evaluate import evaluate as evaluate_v2
import csv, io, json, math, os, re, sqlite3, ssl, threading, time, uuid, urllib.parse, urllib.request, urllib.error, subprocess, ctypes, ctypes.wintypes as wt, ipaddress, socket, struct, platform, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent
DB = ROOT / "netcoop.db"
LOCK = threading.Lock()
LIVE_LOCK = threading.Lock()
LIVE_HISTORY = []
CLOCK_BASELINE = None
NET_BASELINE = {}
DB_STATUS = {'available':False,'sampled_at':None,'reason':'Waiting for first database health sample.'}
DB_STATUS_LOCK = threading.Lock()
GATEWAY_QUALITY = {'available':False,'sampled_at':None,'reason':'Waiting for first local gateway quality sample.','history':[]}
GATEWAY_QUALITY_LOCK = threading.Lock()
CISCO_LAST = {"connected": False, "last_refresh": None, "error": None}
CPU_TEMP_STATE = {"value_c": None, "sensor": None, "sampled_at": None, "available": False, "reason": "No CPU temperature sensor has been read yet."}
CPU_TEMP_LOCK = threading.Lock()
PROBE_RESULTS = {}
PROBE_LOCK = threading.Lock()
REQUIRED = {"timestamp", "device_id", "metric", "value", "unit", "source"}
STATUS_METRICS = {"device_status", "server_status", "dns_status", "dhcp_status", "database_status"}
ALIASES = {"latency":"latency_ms", "rtt":"latency_ms", "cpu":"cpu_pct", "cpu_percent":"cpu_pct", "memory":"mem_pct", "memory_pct":"mem_pct", "utilization":"link_utilization_pct", "utilization_pct":"link_utilization_pct", "loss":"packet_loss_pct", "retries":"retransmission_pct", "egress_drops":"queue_drops", "oper_status":"device_status"}

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try: return super().__exit__(exc_type, exc_value, traceback)
        finally: self.close()

def connect():
    c = sqlite3.connect(DB, timeout=20, factory=ClosingConnection)
    c.row_factory = sqlite3.Row
    return c

def task_action_report_id(task_id):
    with connect() as c: rows=c.execute("SELECT id,report FROM action_reports WHERE action='/api/tasks' ORDER BY created DESC").fetchall()
    for row in rows:
        try:
            report=json.loads(row['report'])
            if report.get('result',{}).get('id')==task_id:return row['id']
        except (TypeError,json.JSONDecodeError): pass
    return None

def init_db():
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, request TEXT, name TEXT, status TEXT, created REAL, result TEXT, events TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS action_reports (id TEXT PRIMARY KEY, action TEXT NOT NULL, created REAL NOT NULL, report TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS telemetry (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, device_id TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, source TEXT NOT NULL, parent_device_id TEXT, path_id TEXT)")
        c.execute("CREATE INDEX IF NOT EXISTS telemetry_lookup ON telemetry(device_id, metric, timestamp)")
        c.execute("CREATE TABLE IF NOT EXISTS wifi_scans (id TEXT PRIMARY KEY, location TEXT NOT NULL, scanned_at TEXT NOT NULL, interface TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS wifi_readings (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id TEXT NOT NULL, ssid TEXT NOT NULL, bssid TEXT NOT NULL, rssi_dbm INTEGER NOT NULL, signal_quality INTEGER NOT NULL, frequency_khz INTEGER NOT NULL)")
        c.execute("CREATE INDEX IF NOT EXISTS wifi_scan_lookup ON wifi_readings(scan_id)")
        c.execute("CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, created REAL NOT NULL, status TEXT NOT NULL, report TEXT NOT NULL)")
        # Additive management records. Existing telemetry and reports are never altered.
        c.execute("CREATE TABLE IF NOT EXISTS managed_routers (id TEXT PRIMARY KEY, name TEXT NOT NULL, server_id TEXT NOT NULL, created REAL NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS managed_devices (id TEXT PRIMARY KEY, router_id TEXT NOT NULL, name TEXT NOT NULL, created REAL NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS router_assessments (id TEXT PRIMARY KEY, router_id TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL, details TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS verification_attempts (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL, method TEXT NOT NULL, reason TEXT, created REAL NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS support_tickets (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS export_history (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, filename TEXT NOT NULL, size_bytes INTEGER NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS download_history (id TEXT PRIMARY KEY, filename TEXT NOT NULL, source_url TEXT NOT NULL, created REAL NOT NULL)")
        c.execute("CREATE INDEX IF NOT EXISTS ticket_status_lookup ON support_tickets(status, created DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS download_history_created ON download_history(created DESC)")
init_db()

def database_status_snapshot():
    """Small local SQLite health snapshot, safe to refresh automatically."""
    sampled=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    try:
        with connect() as c:
            telemetry=c.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]
            tasks=c.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
            actions=c.execute('SELECT COUNT(*) FROM action_reports').fetchone()[0]
            integrity=c.execute('PRAGMA quick_check').fetchone()[0]
        return {'available':integrity=='ok','sampled_at':sampled,'database_file':DB.name,'database_size_bytes':DB.stat().st_size if DB.exists() else 0,'telemetry_records':telemetry,'investigations':tasks,'operation_reports':actions,'integrity_check':integrity,'reason':None if integrity=='ok' else 'SQLite quick check did not return ok.'}
    except Exception as exc:
        return {'available':False,'sampled_at':sampled,'reason':f'Database status unavailable: {type(exc).__name__}.'}

def database_status_sampler():
    while True:
        snapshot=database_status_snapshot()
        with DB_STATUS_LOCK: DB_STATUS.update(snapshot)
        time.sleep(15)

def local_interfaces():
    if os.name!='nt': return [], 'Local interface discovery is implemented for Windows only.'
    script=r'''
$rows=[System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object {
  $p=$_.GetIPProperties();
  $v=@($p.UnicastAddresses | Where-Object {$_.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork} | ForEach-Object {@{address=$_.Address.IPAddressToString; prefix=$_.PrefixLength}});
  $g=@($p.GatewayAddresses | ForEach-Object {$_.Address.IPAddressToString} | Where-Object {$_ -ne '0.0.0.0'});
  $d=@($p.DnsAddresses | ForEach-Object {$_.IPAddressToString});
  if($_.OperationalStatus -eq 'Up' -and $_.NetworkInterfaceType -ne 'Loopback' -and ($v.Count -gt 0 -or $g.Count -gt 0)){
    [pscustomobject]@{name=$_.Name;description=$_.Description;type=$_.NetworkInterfaceType.ToString();status=$_.OperationalStatus.ToString();speed_mbps=[math]::Round($_.Speed/1000000,1);mac=$_.GetPhysicalAddress().ToString();interface_index=$p.GetIPv4Properties().Index;ipv4=$v;gateways=$g;dns=$d}
  }
}; ConvertTo-Json -InputObject @($rows) -Compress -Depth 5
'''
    try:
        p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if p.returncode: return [], 'Windows did not provide interface details.'
        data=json.loads(p.stdout or '[]'); return data if isinstance(data,list) else [data], None
    except Exception as e: return [], f'Interface query unavailable: {type(e).__name__}.'

class _MibRow(ctypes.Structure):
    _fields_=[('interface_index',wt.DWORD),('physical_length',wt.DWORD),('physical_address',ctypes.c_ubyte*8),('address',wt.DWORD),('row_type',wt.DWORD)]
class _MibTable(ctypes.Structure):
    _fields_=[('count',wt.DWORD),('rows',_MibRow*1)]

def local_neighbors(interfaces):
    if os.name!='nt': return [], 'Neighbor cache is available only on Windows in this build.'
    try:
        iphlp=ctypes.WinDLL('iphlpapi.dll',use_last_error=True); size=wt.ULONG(0)
        rc=iphlp.GetIpNetTable(None,ctypes.byref(size),False)
        if rc not in (0,122) or not size.value: return [], 'Windows did not provide the ARP neighbor cache.'
        buf=ctypes.create_string_buffer(size.value); rc=iphlp.GetIpNetTable(buf,ctypes.byref(size),False)
        if rc: return [], 'Windows did not provide the ARP neighbor cache.'
        table=ctypes.cast(buf,ctypes.POINTER(_MibTable)).contents
        rows=(_MibRow*table.count).from_address(ctypes.addressof(table)+_MibTable.rows.offset)
        aliases={int(x['interface_index']):x['name'] for x in interfaces if x.get('interface_index') is not None}
        broadcasts=set()
        for interface in interfaces:
            for address in interface.get('ipv4',[]):
                try: broadcasts.add(str(ipaddress.ip_interface(f"{address['address']}/{address['prefix']}").network.broadcast_address))
                except (ValueError,KeyError,TypeError): pass
        result=[]
        for row in rows:
            if row.interface_index not in aliases or row.row_type not in (3,4): continue
            addr=ipaddress.ip_address(socket.inet_ntoa(struct.pack('<I',row.address)))
            if addr.is_multicast or addr.is_unspecified or addr.is_loopback or addr.is_link_local or addr.is_reserved or str(addr) in broadcasts: continue
            mac=':'.join(f'{row.physical_address[i]:02X}' for i in range(min(int(row.physical_length),8)))
            result.append({'ip':str(addr),'interface':aliases[row.interface_index],'mac':mac or None,'cache_type':'dynamic' if row.row_type==3 else 'static','verified_reachable':False})
        return sorted(result,key=lambda x:(x['interface'],ipaddress.ip_address(x['ip']))),None
    except Exception as e: return [],f'Neighbor cache unavailable: {type(e).__name__}.'

def _wlan_signal_scan_api():
    if os.name!='nt': raise RuntimeError('Wi-Fi radio scanning is available only on Windows.')
    class _Guid(ctypes.Structure): _fields_=[('a',wt.DWORD),('b',wt.WORD),('c',wt.WORD),('d',ctypes.c_ubyte*8)]
    class _Interface(ctypes.Structure): _fields_=[('guid',_Guid),('description',wt.WCHAR*256),('state',ctypes.c_int)]
    class _InterfaceList(ctypes.Structure): _fields_=[('count',wt.DWORD),('index',wt.DWORD),('items',_Interface*1)]
    class _Ssid(ctypes.Structure): _fields_=[('length',wt.ULONG),('value',ctypes.c_ubyte*32)]
    class _Bss(ctypes.Structure): _fields_=[('ssid',_Ssid),('bss_type',ctypes.c_int),('bssid',ctypes.c_ubyte*6),('phy_type',ctypes.c_int),('phy_id',wt.ULONG),('rssi',wt.LONG),('quality',wt.ULONG),('in_domain',ctypes.c_ubyte),('beacon_period',wt.WORD),('timestamp',ctypes.c_ulonglong),('host_timestamp',ctypes.c_ulonglong),('capability',wt.WORD),('center_frequency_khz',wt.ULONG),('rate_set_length',wt.ULONG),('rates',wt.WORD*126),('ie_offset',wt.ULONG),('ie_size',wt.ULONG)]
    class _BssList(ctypes.Structure): _fields_=[('total_size',wt.DWORD),('count',wt.DWORD),('items',_Bss*1)]
    api=ctypes.WinDLL('wlanapi.dll',use_last_error=True); handle=wt.HANDLE(); version=wt.DWORD(); allocations=[]
    try:
        rc=api.WlanOpenHandle(2,None,ctypes.byref(version),ctypes.byref(handle))
        if rc: raise RuntimeError(f'Windows WLAN API denied access (code {rc}).')
        ptr=ctypes.POINTER(_InterfaceList)(); rc=api.WlanEnumInterfaces(handle,None,ctypes.byref(ptr))
        if rc: raise RuntimeError(f'Wi-Fi interface query failed (code {rc}).')
        allocations.append(ptr); listing=ptr.contents
        interfaces=(_Interface*listing.count).from_address(ctypes.addressof(listing)+_InterfaceList.items.offset)
        targets=[x for x in interfaces if x.state==1]
        if not targets: raise RuntimeError('No connected Wi-Fi interface is available for a signal survey.')
        for iface in targets:
            rc=api.WlanScan(handle,ctypes.byref(iface.guid),None,None,None)
            if rc: raise RuntimeError(f'Wi-Fi scan could not start (code {rc}).')
        time.sleep(2.0)
        readings=[]; labels=[]
        for iface in targets:
            labels.append(iface.description)
            bptr=ctypes.POINTER(_BssList)(); rc=api.WlanGetNetworkBssList(handle,ctypes.byref(iface.guid),None,3,False,None,ctypes.byref(bptr))
            if rc: continue
            allocations.append(bptr); bl=bptr.contents
            entries=(_Bss*bl.count).from_address(ctypes.addressof(bl)+_BssList.items.offset)
            for entry in entries:
                ssid=bytes(entry.ssid.value[:min(32,entry.ssid.length)]).decode('utf-8','replace') or '(hidden network)'
                bssid=':'.join(f'{b:02X}' for b in entry.bssid)
                readings.append({'ssid':ssid,'bssid':bssid,'rssi_dbm':int(entry.rssi),'signal_quality':int(entry.quality),'frequency_khz':int(entry.center_frequency_khz)})
        unique={x['bssid']:x for x in readings}
        return sorted(unique.values(),key=lambda x:(-x['rssi_dbm'],x['ssid'],x['bssid'])),', '.join(labels)
    finally:
        try:
            free=api.WlanFreeMemory
            for ptr in allocations: free(ptr)
            if handle: api.WlanCloseHandle(handle,None)
        except Exception: pass

def wlan_signal_scan():
    """Survey nearby Wi-Fi beacons using the Windows-supported netsh view.

    The older ctypes WLAN path remains available above, but certain drivers can
    hold that API call. Netsh gives the dashboard a bounded scan path instead.
    """
    if os.name!='nt': raise RuntimeError('Wi-Fi radio scanning is available only on Windows.')
    try:
        result=subprocess.run(['netsh','wlan','show','networks','mode=bssid'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired: raise RuntimeError('Windows Wi-Fi survey timed out. Check that the WLAN AutoConfig service and Wi-Fi adapter are running.')
    if result.returncode: raise RuntimeError('Windows could not query nearby Wi-Fi networks.')
    readings=[]; ssid=None; bssid=None; quality=None; interface='Windows WLAN survey'
    for raw in result.stdout.splitlines():
        line=raw.strip()
        found=re.match(r'^SSID\s+\d+\s*:\s*(.*)$',line,re.I)
        if found:
            ssid=found.group(1).strip() or '(hidden network)'; bssid=None; quality=None; continue
        found=re.match(r'^BSSID\s+\d+\s*:\s*([0-9A-F:-]{11,})$',line,re.I)
        if found:
            bssid=found.group(1).replace('-',':').upper(); quality=None; continue
        found=re.match(r'^Signal\s*:\s*(\d{1,3})%$',line,re.I)
        if found and ssid and bssid:
            quality=max(0,min(100,int(found.group(1))))
            readings.append({'ssid':ssid,'bssid':bssid,'rssi_dbm':round(quality/2-100),'signal_quality':quality,'frequency_khz':0})
    unique={row['bssid']:row for row in readings}
    if not unique: raise RuntimeError('Windows found no nearby Wi-Fi access points. Turn on Wi-Fi, move closer to the hotspot, then rescan.')
    return sorted(unique.values(),key=lambda x:(-x['rssi_dbm'],x['ssid'],x['bssid'])),interface

def network_overview(location=None):
    interfaces,error=local_interfaces(); neighbors,nerr=local_neighbors(interfaces)
    gateways={g for interface in interfaces for g in interface.get('gateways',[])}
    with PROBE_LOCK: probes=dict(PROBE_RESULTS)
    for neighbor in neighbors:
        neighbor['is_default_gateway']=neighbor['ip'] in gateways
        neighbor['probe_result']=probes.get(neighbor['ip'])
    with connect() as c:
        if location: scan=c.execute('SELECT * FROM wifi_scans WHERE location=? ORDER BY scanned_at DESC LIMIT 1',(location,)).fetchone()
        else: scan=c.execute('SELECT * FROM wifi_scans ORDER BY scanned_at DESC LIMIT 1').fetchone()
        locations=[dict(x) for x in c.execute('SELECT location,MAX(scanned_at) AS scanned_at FROM wifi_scans GROUP BY location ORDER BY MAX(scanned_at) DESC')]
        readings=[]
        if scan: readings=[dict(x) for x in c.execute('SELECT ssid,bssid,rssi_dbm,signal_quality,frequency_khz FROM wifi_readings WHERE scan_id=? ORDER BY rssi_dbm DESC',(scan['id'],))]
    return {'hostname':socket.gethostname(),'captured_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'interfaces':interfaces,'interface_warning':error,'neighbors':neighbors,'neighbor_count':len(neighbors),'neighbor_warning':nerr,'wifi':{'last_scan':dict(scan) if scan else None,'locations':locations,'readings':readings,'interface':scan['interface'] if scan else None,'best_rssi_dbm':max((r['rssi_dbm'] for r in readings),default=None),'distinct_aps':len(readings),'method':'Windows WLAN BSS scan; RSSI measured at this device location'}}

def _powershell_json(script, timeout=8):
    """Read-only Windows inventory command with a bounded, structured result."""
    if os.name!='nt': return {'available':False,'reason':'Windows inventory is unavailable on this host.'}
    try:
        proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if proc.returncode: return {'available':False,'reason':'Windows did not return this inventory section.'}
        result=json.loads(proc.stdout or '[]')
        return result
    except Exception as exc:
        return {'available':False,'reason':f'{type(exc).__name__} while reading local inventory.'}

def system_hardware_software_report():
    """Organized local-only inventory. No keys, passwords, installed-app list, or private files are collected."""
    captured=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    hardware=_powershell_json(r'''
$cpu=Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
$mem=Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
$bios=Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate
$disks=Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID,Size,FreeSpace,FileSystem
[pscustomobject]@{cpu=@($cpu);memory=$mem;bios=$bios;storage=@($disks)} | ConvertTo-Json -Compress -Depth 4
''')
    interfaces,interface_warning=local_interfaces()
    live=collect_live_sample()
    software={'application':{'name':'NetCoop AI','version':'local evidence-only build','python_version':sys.version.split()[0]},'operating_system':{'platform':platform.platform(),'release':platform.release(),'machine':platform.machine()},'runtime':{'process_id':os.getpid(),'database':'SQLite local workspace','server_bind':'127.0.0.1:8000'},'limitations':['Installed applications, product keys, passwords, browser data, and personal files are intentionally not collected.']}
    return {'report_type':'system_hardware_software_inventory','captured_at':captured,'scope':'Local computer only; read-only inventory.','hardware':hardware,'software':software,'network':{'interfaces':interfaces,'interface_warning':interface_warning,'live_sample':live,'overview':network_overview()},'limitations':['Hardware values are Windows-reported and may be unavailable on some devices.','This report does not establish health of routers, access points, remote servers, or the Internet.']}

def realtime_network_report():
    with LIVE_LOCK: history=list(LIVE_HISTORY[-180:])
    latest=history[-1] if history else None
    with DB_STATUS_LOCK: database=dict(DB_STATUS)
    with GATEWAY_QUALITY_LOCK: gateway_quality=dict(GATEWAY_QUALITY)
    return {'report_type':'realtime_local_network_report','captured_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'sample_interval_seconds':1,'window_seconds':180,'latest':latest,'history':history,'database_status':database,'local_gateway_quality':gateway_quality,'network_overview':network_overview(),'limitations':['This reports the computer running NetCoop and its active adapters only.','Adapter byte rates are local counters, not an Internet speed test or network-wide packet-loss measurement.']}

def local_throughput_scan():
    """Summarize measured local adapter rates without generating test traffic."""
    with LIVE_LOCK: history=list(LIVE_HISTORY[-60:])
    valid=[sample for sample in history if not sample.get('error')]
    latest=valid[-1] if valid else None
    def totals(sample):
        interfaces=sample.get('interfaces',[]) if sample else []
        return (round(sum(float(item.get('rx_mbps') or 0) for item in interfaces),3),round(sum(float(item.get('tx_mbps') or 0) for item in interfaces),3))
    current_rx,current_tx=totals(latest)
    peak_rx=max((totals(item)[0] for item in valid),default=0.0); peak_tx=max((totals(item)[1] for item in valid),default=0.0)
    return {'report_type':'local_adapter_throughput_scan','captured_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'measured' if latest else 'waiting_for_samples','current_receive_mbps':current_rx,'current_send_mbps':current_tx,'peak_receive_mbps':peak_rx,'peak_send_mbps':peak_tx,'sample_count':len(valid),'sample_window_seconds':min(60,len(valid)),'source':'Windows local adapter byte-counter changes','limitations':['This is a passive local adapter-throughput measurement. It does not contact an external speed-test server.','It is not an Internet speed result, Wi-Fi capacity measurement, or total network bandwidth.']}

def local_alerts_snapshot():
    """Deterministic read-only local alert monitor with traceable rule coverage."""
    with LIVE_LOCK: latest=LIVE_HISTORY[-1] if LIVE_HISTORY else None
    alerts=[]; checked=[]
    if latest and not latest.get('error'):
        cpu=latest.get('cpu_pct'); memory=latest.get('memory_pct')
        if cpu is not None:
            checked.append('cpu_pct')
            if cpu>=90: alerts.append({'id':'local-cpu-high','severity':'critical','title':'High local CPU use','detail':f'CPU measured {cpu:.1f}%, crossing the 90% local alert threshold.','source':'Windows local sample','signals':['cpu_pct']})
        if memory is not None:
            checked.append('memory_pct')
            if memory>=90: alerts.append({'id':'local-memory-high','severity':'warning','title':'High local memory use','detail':f'Memory measured {memory:.1f}%, crossing the 90% local alert threshold.','source':'Windows local sample','signals':['memory_pct']})
    with connect() as c: telemetry=[dict(row) for row in c.execute('SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 5000')]
    anomalies=[state for state in metric_states(telemetry) if state.get('state')=='anomaly']
    for state in anomalies[:8]:
        checked.append(f"{state.get('device_id')}/{state.get('metric')}")
        alerts.append({'id':f"telemetry-{state.get('device_id')}-{state.get('metric')}",'severity':'warning','title':'Telemetry deviation','detail':f"{state.get('device_id')} / {state.get('metric')} is outside its empirical baseline.",'source':'Imported telemetry baseline','signals':[state.get('metric')],'device_id':state.get('device_id')})
    coverage=round(min(1.0,len(checked)/2),2) if latest else 0.0
    return {'generated_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'alert' if alerts else 'normal','alerts':alerts,'confidence_trace':{'checked_signals':checked,'checked_count':len(checked),'coverage':coverage,'method':'Deterministic threshold and empirical-baseline rules. Coverage reflects available local CPU/memory signals, not root-cause probability.','limitations':['No router, AP, or Internet-wide health is inferred from local PC counters.','No network configuration was changed.']}}

def mitigation_dry_run_plan():
    """Produce recommendations only; never mutate OS, Wi-Fi, router, or controller state."""
    with LIVE_LOCK: latest=LIVE_HISTORY[-1] if LIVE_HISTORY else None
    actions=[{'priority':'collect','action':'Run a Wi-Fi spot survey at the affected location and compare RSSI/BSSIDs.','requires_operator':True}, {'priority':'collect','action':'Import authorized latency, packet-loss, jitter, and interface-counter telemetry for the affected path.','requires_operator':True}, {'priority':'review','action':'If loss/jitter is confirmed, review channel utilization, AP association, link errors, queue drops, and upstream capacity before changing any configuration.','requires_operator':True}]
    return {'report_type':'network_quality_mitigation_dry_run','status':'recommendations_only','created_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'observed_local_sample':latest,'recommended_actions':actions,'changes_applied':[],'safety_gate':'No operating-system, Wi-Fi, router, controller, QoS, DNS, or route setting was changed. Apply any change only through an authorized network administrator with rollback and measurement verification.','limitations':['NetCoop has no authorized controller write integration.','A local PC cannot safely determine a network-wide change that will reduce jitter or packet loss.']}

def probe_cached_peers():
    if os.name != 'nt': return {'status':'unavailable','summary':'Cached peer checks are available on Windows only.','checked_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'observations':[],'limitations':['No devices were probed.']}
    overview=network_overview(); candidates=[]; seen=set()
    for row in overview.get('neighbors',[]):
        try: address=ipaddress.ip_address(row['ip'])
        except ValueError: continue
        if address.is_private and row['ip'] not in seen:
            candidates.append(row);seen.add(row['ip'])
    for interface in overview.get('interfaces',[]):
        for gateway in interface.get('gateways',[]):
            try: address=ipaddress.ip_address(gateway)
            except ValueError: continue
            if address.is_private and gateway not in seen:
                candidates.append({'ip':gateway,'interface':interface['name'],'mac':None,'cache_type':'OS-reported default gateway','is_default_gateway':True});seen.add(gateway)
    candidates=candidates[:128]
    checked=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    def probe(row):
        try:
            proc=subprocess.run(['ping.exe','-n','1','-w','700',row['ip']],capture_output=True,text=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            output=proc.stdout or ''
            match=re.search(r'time[=<]\s*(\d+)\s*ms',output,re.I)
            return {**row,'probe_result':{'status':'reachable' if proc.returncode==0 else 'no_reply','latency_ms':int(match.group(1)) if match else (1 if proc.returncode==0 else None),'checked_at':checked,'method':'single ICMP echo; a no-reply result may mean ICMP is blocked'}}
        except Exception as exc:
            return {**row,'probe_result':{'status':'check_error','latency_ms':None,'checked_at':checked,'method':type(exc).__name__}}
    results=[]
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures=[pool.submit(probe,row) for row in candidates]
        for future in as_completed(futures): results.append(future.result())
    results.sort(key=lambda x:ipaddress.ip_address(x['ip']))
    with PROBE_LOCK:
        for row in results: PROBE_RESULTS[row['ip']]=row['probe_result']
    reachable=sum(x['probe_result']['status']=='reachable' for x in results)
    report={'status':'completed' if results else 'insufficient_evidence','summary':f'Checked {len(results)} private IPv4 addresses already present in the Windows neighbor cache; {reachable} replied to one ICMP echo.','checked_at':checked,'source':'Windows neighbor cache plus one bounded ICMP echo per cached private IPv4 address','observations':results,'limitations':['ICMP no-reply does not prove a device is offline; firewalls may block echo requests.','Only current OS-reported default gateways and private addresses already in the local neighbor cache were checked; no subnet sweep was performed.','Device identity and health beyond IP/MAC/interface were not inferred.']}
    return report

def local_gateway_quality_sample():
    """One ICMP echo to the OS-reported private gateway; never scans a subnet."""
    sampled=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    interfaces,error=local_interfaces()
    gateways=[]
    for interface in interfaces:
        for gateway in interface.get('gateways',[]):
            try:
                if ipaddress.ip_address(gateway).is_private: gateways.append(gateway)
            except ValueError: pass
    if os.name!='nt' or not gateways:
        return {'available':False,'sampled_at':sampled,'reason':'No Windows-reported private default gateway is available for a bounded local probe.','history':[]}
    gateway=gateways[0]
    try:
        proc=subprocess.run(['ping.exe','-n','1','-w','700',gateway],capture_output=True,text=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        match=re.search(r'time[=<]\s*(\d+)\s*ms',proc.stdout or '',re.I)
        observation={'sampled_at':sampled,'gateway':gateway,'status':'reachable' if proc.returncode==0 else 'no_reply','latency_ms':int(match.group(1)) if match else (1 if proc.returncode==0 else None)}
    except Exception as exc:
        observation={'sampled_at':sampled,'gateway':gateway,'status':'probe_error','latency_ms':None,'reason':type(exc).__name__}
    with GATEWAY_QUALITY_LOCK:
        history=list(GATEWAY_QUALITY.get('history',[])); history.append(observation); history=history[-12:]
    replied=[x['latency_ms'] for x in history if x.get('status')=='reachable' and x.get('latency_ms') is not None]
    loss=round(100*(len(history)-len(replied))/len(history),1) if history else None
    jitter=round(max(replied)-min(replied),1) if len(replied)>=2 else None
    return {'available':bool(history),'sampled_at':sampled,'gateway':gateway,'latest':observation,'samples':len(history),'local_gateway_loss_pct':loss,'local_gateway_jitter_ms':jitter,'history':history,'method':'One ICMP echo to a Windows-reported private default gateway every 10 seconds; no subnet sweep.','limitations':['ICMP no-reply can be caused by a firewall and does not prove packet loss.','This only reflects the local hop to the default gateway, not Internet or campus-wide packet loss/jitter.']}

def gateway_quality_sampler():
    while True:
        snapshot=local_gateway_quality_sample()
        with GATEWAY_QUALITY_LOCK: GATEWAY_QUALITY.update(snapshot)
        time.sleep(10)

def _system_load():
    if os.name!='nt': raise RuntimeError('Local system counters are available only on Windows.')
    class _MemoryStatus(ctypes.Structure):
        _fields_=[('length',wt.DWORD),('memory_load',wt.DWORD),('total_phys',ctypes.c_ulonglong),('avail_phys',ctypes.c_ulonglong),('total_page',ctypes.c_ulonglong),('avail_page',ctypes.c_ulonglong),('total_virtual',ctypes.c_ulonglong),('avail_virtual',ctypes.c_ulonglong),('avail_extended',ctypes.c_ulonglong)]
    idle=ctypes.c_ulonglong(); kernel=ctypes.c_ulonglong(); user=ctypes.c_ulonglong()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
        raise OSError('Windows CPU counters are unavailable.')
    ticks=(idle.value,kernel.value,user.value)
    previous=CLOCK_BASELINE
    globals()['CLOCK_BASELINE']=ticks
    cpu=None
    if previous:
        total=sum(ticks[i]-previous[i] for i in (1,2)); idle_delta=ticks[0]-previous[0]
        if total>0: cpu=round(max(0,min(100,(total-idle_delta)*100/total)),1)
    mem=_MemoryStatus(); mem.length=ctypes.sizeof(mem)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
        raise OSError('Windows memory counters are unavailable.')
    total=int(mem.total_phys); used=total-int(mem.avail_phys)
    return cpu,round(used*100/total,1) if total else None,used,total

def _interface_counters():
    script=r'''
$rows=[System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | Where-Object {$_.OperationalStatus -eq 'Up' -and $_.NetworkInterfaceType -ne 'Loopback'} | ForEach-Object {
  try {$s=$_.GetIPv4Statistics(); [pscustomobject]@{name=$_.Name;description=$_.Description;speed_mbps=[math]::Round($_.Speed/1000000,1);mac=$_.GetPhysicalAddress().ToString();received_bytes=[double]$s.BytesReceived;sent_bytes=[double]$s.BytesSent}} catch {}
}; ConvertTo-Json -InputObject @($rows) -Compress -Depth 4
'''
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=6,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode: raise RuntimeError('Windows did not provide interface byte counters.')
    data=json.loads(p.stdout or '[]'); return data if isinstance(data,list) else [data]

def read_cpu_temperature():
    # Return CPU-specific hardware readings only; never substitute a guessed value.
    if os.name != 'nt': return {"value_c":None,"sensor":None,"sampled_at":None,"available":False,"reason":"CPU temperature reading is available only from a local Windows hardware sensor provider."}
    script=r'''
$rows=@()
foreach($ns in @('root/LibreHardwareMonitor','root/OpenHardwareMonitor')) {
  try {
    $sensors=Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop | Where-Object {$_.SensorType -eq 'Temperature' -and ($_.Name -match '(?i)CPU.*(Package|Core)|Tctl|Tdie|Core #[0-9]+')}
    foreach($sensor in $sensors){$rows+=@{name=[string]$sensor.Name;value_c=[double]$sensor.Value;provider=$ns}}
  } catch {}
}
$rows | ConvertTo-Json -Compress -Depth 3
'''
    try:
        proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        candidates=json.loads(proc.stdout or '[]') if proc.returncode==0 else []
        if isinstance(candidates,dict): candidates=[candidates]
        candidates=[x for x in candidates if isinstance(x,dict) and isinstance(x.get('value_c'),(int,float)) and -10<=float(x['value_c'])<=150]
        if candidates:
            packages=[x for x in candidates if re.search(r'package|tctl|tdie',x.get('name',''),re.I)]
            selected=packages[0] if packages else max(candidates,key=lambda x:float(x['value_c']))
            return {"value_c":round(float(selected['value_c']),1),"sensor":selected.get('name'),"provider":selected.get('provider'),"sampled_at":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),"available":True,"reason":None}
        return {"value_c":None,"sensor":None,"provider":None,"sampled_at":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),"available":False,"reason":"Windows exposes no CPU temperature sensor. Install and run a compatible hardware monitor (LibreHardwareMonitor/OpenHardwareMonitor) to enable this reading."}
    except Exception as exc:
        return {"value_c":None,"sensor":None,"provider":None,"sampled_at":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),"available":False,"reason":f"CPU temperature sensor query unavailable ({type(exc).__name__})."}

def cpu_temperature_sampler():
    while True:
        reading=read_cpu_temperature()
        with CPU_TEMP_LOCK: CPU_TEMP_STATE.update(reading)
        time.sleep(30)

def collect_live_sample():
    global NET_BASELINE
    stamp=time.time(); now=datetime.fromtimestamp(stamp,timezone.utc).isoformat().replace('+00:00','Z')
    cpu,memory,used,total=_system_load(); raw=_interface_counters(); interfaces=[]; next_base={}
    for row in raw:
        name=str(row.get('name') or ''); rx=int(row.get('received_bytes') or 0); tx=int(row.get('sent_bytes') or 0); old=NET_BASELINE.get(name)
        rx_mbps=tx_mbps=0.0
        if old and stamp>old['time'] and rx>=old['rx'] and tx>=old['tx']:
            elapsed=stamp-old['time']; rx_mbps=round((rx-old['rx'])*8/elapsed/1_000_000,3); tx_mbps=round((tx-old['tx'])*8/elapsed/1_000_000,3)
        next_base[name]={'time':stamp,'rx':rx,'tx':tx}
        interfaces.append({'name':name,'description':row.get('description',''),'speed_mbps':float(row.get('speed_mbps') or 0),'mac':row.get('mac') or None,'rx_mbps':rx_mbps,'tx_mbps':tx_mbps,'received_bytes':rx,'sent_bytes':tx})
    NET_BASELINE=next_base
    with CPU_TEMP_LOCK: temperature=dict(CPU_TEMP_STATE)
    with DB_STATUS_LOCK: database=dict(DB_STATUS)
    with GATEWAY_QUALITY_LOCK: gateway_quality=dict(GATEWAY_QUALITY)
    sample={'timestamp':now,'cpu_pct':cpu,'cpu_temp_c':temperature['value_c'],'cpu_temp_sensor':temperature['sensor'],'cpu_temp_sampled_at':temperature['sampled_at'],'cpu_temp_available':temperature['available'],'cpu_temp_unavailable_reason':temperature['reason'],'memory_pct':memory,'memory_used_bytes':used,'memory_total_bytes':total,'interfaces':interfaces,'database':database,'gateway_quality':gateway_quality,'source':'Windows system times, GlobalMemoryStatusEx, .NET NetworkInterface IPv4 counters; CPU temperature only when reported by a compatible hardware sensor provider'}
    with LIVE_LOCK:
        LIVE_HISTORY.append(sample)
        del LIVE_HISTORY[:-600]
    return sample

def live_sampler():
    while True:
        try: collect_live_sample()
        except Exception as e:
            with LIVE_LOCK:
                LIVE_HISTORY.append({'timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'error':str(e),'interfaces':[]})
                del LIVE_HISTORY[:-600]
        time.sleep(1)

def cisco_config():
    return (os.environ.get('NETCOOP_CISCO_BASE_URL','').strip().rstrip('/'), os.environ.get('NETCOOP_CISCO_USERNAME',''), os.environ.get('NETCOOP_CISCO_PASSWORD',''))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Redirect refused', headers, fp)

def cisco_fetch():
    base,user,password=cisco_config()
    if not base or not user or not password: raise RuntimeError('Set NETCOOP_CISCO_BASE_URL, NETCOOP_CISCO_USERNAME, and NETCOOP_CISCO_PASSWORD on the server.')
    p=urllib.parse.urlparse(base)
    if p.scheme!='https' or not p.hostname: raise RuntimeError('Cisco Manager URL must use HTTPS with a valid hostname.')
    opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    def request(path,body=None,token=None):
        data=json.dumps(body).encode() if body is not None else None
        headers={'Accept':'application/json','Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        req=urllib.request.Request(base+path,data=data,headers=headers,method='POST' if data is not None else 'GET')
        with opener.open(req,timeout=12) as response: return response.read().decode('utf-8')
    auth=json.loads(request('/jwt/login',{'username':user,'password':password,'duration':300}))
    token=auth.get('token')
    if not token: raise RuntimeError('Cisco Manager login returned no access token.')
    # This endpoint returns live hardware state, CPU and memory. It is read-only.
    raw=json.loads(request('/dataservice/device/hardwarehealth/detail',token=token))
    items=raw if isinstance(raw,list) else raw.get('data',[])
    records=[]; now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    for item in items:
        device=str(item.get('system-ip') or item.get('local-system-ip') or item.get('host-name') or '').strip()
        if not device: continue
        stamp=item.get('lastupdated'); ts=now
        if stamp:
            try: ts=datetime.fromtimestamp(float(stamp)/1000,timezone.utc).isoformat().replace('+00:00','Z')
            except (ValueError,OverflowError,OSError): pass
        for field,metric in [('cpuLoadDisplay','cpu_pct'),('memUsageDisplay','mem_pct')]:
            try: records.append((ts,device,metric,float(item[field]),'percent','Cisco Catalyst SD-WAN Manager',None,None))
            except (KeyError,ValueError,TypeError): pass
        hw=str(item.get('hardwareState','')).lower()
        reach=str(item.get('reachability','')).lower()
        status='down' if hw in ('error','down','critical') or reach in ('unreachable','down') else 'degraded' if hw in ('warning','degraded') else 'up' if hw in ('normal','up','') and reach in ('reachable','up','') else None
        if status: records.append((ts,device,'device_status',status,'state','Cisco Catalyst SD-WAN Manager',None,None))
    if not records: raise RuntimeError('Cisco Manager responded, but no supported health values were returned. Check API role and device inventory.')
    with LOCK,connect() as c:
        c.executemany('INSERT INTO telemetry(timestamp,device_id,metric,value,unit,source,parent_device_id,path_id) VALUES(?,?,?,?,?,?,?,?)',records)
    CISCO_LAST.update(connected=True,last_refresh=now,error=None)
    return len(records)

def percentile(values, p):
    s=sorted(values)
    if not s:return None
    x=(len(s)-1)*p; lo=int(x); hi=min(lo+1,len(s)-1)
    return s[lo]+(s[hi]-s[lo])*(x-lo)

def metric_states(samples):
    groups={}
    for r in samples: groups.setdefault((r['device_id'],r['metric'],r['unit']),[]).append(r)
    out=[]
    for (dev,metric,unit), rows in groups.items():
        rows.sort(key=lambda r:r['timestamp'])
        vals=[r['value'] for r in rows]
        latest=rows[-1]; prior=vals[:-1]
        state={"device_id":dev,"metric":metric,"value":latest['value'],"unit":unit,"timestamp":latest['timestamp'],"source":latest['source'],"observations":len(vals),"baseline_method":"empirical median and median absolute deviation","state":"unknown","baseline":None,"score":None}
        if metric in STATUS_METRICS:
            value=str(latest['value']).lower()
            state['state']='normal' if value in ('up','ok','healthy','success','passed') else 'anomaly' if value in ('down','degraded','failed','failure','error','critical','warning') else 'unknown'; state['baseline_method']='reported categorical status'; out.append(state); continue
        if len(prior)>=20:
            med=percentile(prior,.5); mad=percentile([abs(x-med) for x in prior],.5)
            scale=1.4826*mad
            state['baseline']={"median":med,"mad":mad,"sample_count":len(prior)}
            if scale>0:
                z=0.67448975*(latest['value']-med)/mad
                state['score']=round(z,2)
                state['state']='anomaly' if abs(z)>3.5 else 'normal'
            else:
                spread=percentile(prior,.75)-percentile(prior,.25)
                if spread>0:
                    z=0.67448975*(latest['value']-med)/(spread/1.349)
                    state['score']=round(z,2); state['state']='anomaly' if abs(z)>3.5 else 'normal'
                elif latest['value']==med:
                    state['score']=0; state['state']='normal'
                else:
                    state['state']='unknown'
        out.append(state)
    return sorted(out,key=lambda x:(x['device_id'],x['metric']))

def diagnostic_report(incident_id, result):
    evidence=result.get('anomalies') or []
    supplied=[]
    for finding in result.get('agent_findings',[]):
        if isinstance(finding.get('observations'),list): supplied.extend(finding['observations'])
    by_device={}
    for item in evidence: by_device.setdefault(item['device_id'],{})[item['metric']]=item
    for item in supplied:
        metric=item.get('metric'); value=item.get('value')
        if metric in STATUS_METRICS and str(value).lower() in ('down','failed','failure','error','critical'):
            by_device.setdefault(item['device_id'],{})[metric]=item
        if metric=='connection_pool_usage_pct' and isinstance(value,(int,float)) and value>=95:
            by_device.setdefault(item['device_id'],{})[metric]=item
    for item in evidence:
        if item['metric']=='connection_pool_usage_pct' and isinstance(item.get('value'),(int,float)) and item['value']>=95:
            by_device.setdefault(item['device_id'],{})[item['metric']]=item
    candidates=[]
    def add(name, expected, observations, action):
        matched=[x for x in observations if x]
        if not matched:return
        belief=min(1.0,len(matched)/max(1,len(expected)))
        candidates.append({'cause':name,'belief':belief,'evidence':matched,'action':action})
    actions={
        'link_congestion':'Inspect the affected link utilization, queue-drop counters, and adjacent-path capacity.',
        'weak_wifi_signal':'Measure RSSI/SNR at the affected location and inspect AP placement and retransmissions.',
        'interface_fault':'Inspect the affected interface, cabling, error counters, and link transitions.',
        'device_overload':'Check the device CPU and memory history and correlate load with affected interfaces.',
        'upstream_issue':'Compare the shared parent and upstream links with the affected downstream segments.',
        'server_downtime':'Verify the server service and process state at the reported timestamp.',
        'dns_failure':'Test the configured resolver and compare name resolution with direct IP connectivity.',
        'dhcp_failure':'Inspect DHCP lease allocation, server availability, and address-pool exhaustion.',
        'database_failure':'Check database availability, connection logs, and recent query failures.',
        'connection_pool_exhaustion':'Inspect active versus maximum connections, long-running queries, and pool wait time.'}
    for device, metrics in by_device.items():
        add('link_congestion',['link_utilization_pct','queue_drops','latency_ms'],[metrics.get('link_utilization_pct'),metrics.get('queue_drops'),metrics.get('latency_ms') or metrics.get('jitter_ms')],actions['link_congestion'])
        add('weak_wifi_signal',['rssi_dbm','retransmission_pct'],[metrics.get('rssi_dbm'),metrics.get('retransmission_pct')],actions['weak_wifi_signal'])
        add('interface_fault',['interface_errors','packet_loss_pct'],[metrics.get('interface_errors'),metrics.get('packet_loss_pct')],actions['interface_fault'])
        add('device_overload',['cpu_pct','mem_pct','latency_ms'],[metrics.get('cpu_pct') or metrics.get('mem_pct'),metrics.get('latency_ms') or metrics.get('packet_loss_pct')],actions['device_overload'])
        categorical={'server_status':'server_downtime','dns_status':'dns_failure','dhcp_status':'dhcp_failure','database_status':'database_failure'}
        for metric,cause in categorical.items():
            item=metrics.get(metric)
            if item and str(item['value']).lower() in ('down','failed','failure','error','critical'):
                add(cause,[metric],[item],actions[cause])
        pool=metrics.get('connection_pool_usage_pct')
        if pool and isinstance(pool.get('value'),(int,float)) and pool['value']>=95:
            add('connection_pool_exhaustion',['connection_pool_usage_pct'],[pool],actions['connection_pool_exhaustion'])
    diagnostic_evidence=[]
    for candidate in candidates:
        for item in candidate['evidence']:
            if item not in diagnostic_evidence: diagnostic_evidence.append(item)
    if not candidates and evidence:
        primary='unknown'
    elif candidates:
        candidates.sort(key=lambda x:(x['belief'],len(x['evidence'])),reverse=True)
        primary=candidates[0]['cause']
    else:
        primary=None
    alternatives=[x for x in candidates if x['cause']!=primary]
    agreement=1.0 if not alternatives else candidates[0]['belief']/sum(x['belief'] for x in candidates)
    belief=candidates[0]['belief'] if candidates else 0.0
    confidence=round(min(0.90,belief*agreement*0.85),2) if candidates else None
    margin=belief-(alternatives[0]['belief'] if alternatives else 0.0)
    category='High' if confidence is not None and confidence>=0.80 and margin>=0.15 else 'Medium' if confidence is not None and confidence>=0.55 else 'Low' if confidence is not None and confidence>=0.35 else 'Unknown'
    if not candidates: status='insufficient_evidence' if evidence or result.get('status')=='insufficient_evidence' else 'no_fault_found'
    elif confidence<0.35: status='insufficient_evidence'
    elif confidence<0.55: status='tentative'
    else: status='diagnosed'
    if primary=='unknown' or primary is None:
        cause='No specific root cause established from the available evidence.' if evidence else 'No fault found in the available measurements.'
        next_steps=['Collect additional, timestamped telemetry from the affected devices and path.'] if evidence else ['Continue monitoring; no fault was observed in the supplied measurements.']
    else:
        cause=primary.replace('_',' ').capitalize()
        next_steps=[candidates[0]['action']]
    sources=sorted({str(x.get('source','')) for x in evidence if x.get('source')})
    if not evidence and not diagnostic_evidence: limitations=['No measurements supported a root-cause assessment.']
    else: limitations=['Confidence is a rule-based support estimate, not a calibrated probability.','Only imported or connected telemetry is assessed; missing devices and path segments remain unknown.']
    shown=diagnostic_evidence or evidence
    conflicts=[{'between':[primary,x['cause']],'K':round(1-agreement,3),'resolved_by':'correlation-agent rule ranking; alternative retained'} for x in alternatives]
    return {'incident_id':incident_id,'status':status,'suspected_root_cause':cause,'root_cause_code':primary or 'unknown','confidence':confidence,'confidence_category':category,'confidence_breakdown':{'belief_top':round(belief,3),'coverage':round(belief,3),'agreement':round(agreement,3),'method':'supporting evidence rule score; uncalibrated'},'affected_devices':sorted({x['device_id'] for x in shown}),'supporting_evidence':[{'device_id':x['device_id'],'metric':x['metric'],'value':x['value'],'unit':x['unit'],'timestamp':x['timestamp'],'source':x['source'],'interpretation':f"{x['metric']} is outside its empirical baseline or crossed a documented rule"} for x in shown],'alternative_causes':[{'cause':x['cause'],'belief':round(x['belief'],3)} for x in alternatives],'conflicts':conflicts,'recommended_actions':next_steps,'evidence_sources':sorted({f['agent'] for f in result.get('agent_findings',[]) if f.get('status')=='ok'}),'limitations':limitations}

def service_health_summary(rows):
    latest={}
    for row in rows:
        key=(row['device_id'],row['metric'])
        if key not in latest or row['timestamp']>latest[key]['timestamp']: latest[key]=row
    states={(x['device_id'],x['metric']):x for x in metric_states(rows)}
    metrics=('server_status','dns_status','database_status','connection_pool_usage_pct','cpu_pct','mem_pct','latency_ms','packet_loss_pct')
    devices=sorted({d for d,m in latest if m in metrics}); out=[]
    for device in devices:
        parts=[]
        for metric in metrics:
            row=latest.get((device,metric))
            if not row: continue
            value=row['value']; score=None
            if metric.endswith('_status'):
                status=str(value).lower(); score=100 if status in ('up','ok','healthy','success','passed') else 0 if status in ('down','failed','failure','error','critical') else 50 if status in ('degraded','warning') else None
            elif metric=='connection_pool_usage_pct': score=100 if value<70 else 80 if value<85 else 50 if value<95 else 0
            elif metric in ('cpu_pct','mem_pct'): score=100 if value<=80 else 60 if value<=90 else 20
            elif metric in ('latency_ms','packet_loss_pct'):
                state=states.get((device,metric),{}).get('state'); score=100 if state=='normal' else 20 if state=='anomaly' else None
            if score is not None: parts.append({'metric':metric,'score':score,'value':value,'unit':row['unit'],'timestamp':row['timestamp'],'source':row['source']})
        coverage=len(parts)/len(metrics); raw=sum(x['score'] for x in parts)/len(parts) if parts else None
        score=round(raw*coverage) if raw is not None else None
        out.append({'device_id':device,'score':score,'out_of':100,'coverage':round(coverage,2),'observed_components':len(parts),'expected_components':len(metrics),'components':parts,'method':'mean of available component rules multiplied by measurement coverage; uncalibrated'})
    return {'devices':out,'method':'evidence-coverage-adjusted rule score; uncalibrated','note':'Missing telemetry lowers coverage and the score. The score is not an SLA or a statistical health probability.'}

def validate_report(report):
    required={'incident_id','status','suspected_root_cause','confidence','affected_devices','supporting_evidence','alternative_causes','recommended_actions','evidence_sources','limitations'}
    missing=required-set(report)
    if missing: raise ValueError('Report missing required fields: '+', '.join(sorted(missing)))
    if not isinstance(report['affected_devices'],list) or not isinstance(report['supporting_evidence'],list) or not isinstance(report['recommended_actions'],list):
        raise ValueError('Report collections have invalid types.')
    if report['confidence'] is not None and not 0<=report['confidence']<=1: raise ValueError('Report confidence must be between 0 and 1.')
    return True

def validate_message(message):
    required={'protocol','message_id','incident_id','task_id','type','sender','recipient','payload'}
    if not required.issubset(message): raise ValueError('Inter-agent message is missing required envelope fields.')
    if message['protocol']!='ncmp/1.0' or message['type'] not in {'finding','report','conflict_notice','probe_request','probe_response'}: raise ValueError('Unsupported inter-agent protocol or message type.')
    if not isinstance(message['payload'],dict): raise ValueError('Inter-agent message payload must be a JSON object.')
    return True

def task_result(request, samples=None):
    if samples is None:
        with connect() as c: rows=[dict(r) for r in c.execute('SELECT * FROM telemetry ORDER BY timestamp ASC')]
    else: rows=sorted(samples,key=lambda r:r['timestamp'])
    events=[]; now=time.strftime('%H:%M:%S')
    def event(name,tool,detail,status='completed'):
        events.append({"name":name,"tool":tool,"detail":detail,"status":status,"time":time.strftime('%H:%M:%S')})
    event('Task received','Request validator','Request accepted; read-only analysis requested.')
    event('Task interpreted','Request classifier','Analysis will use the explicitly supplied synthetic fixture; no live network data is read.' if samples is not None else 'Analysis will use telemetry currently stored by this workspace. No live device commands are issued.')
    if not rows:
        event('Telemetry query','Local telemetry store','No telemetry records are available; no measurement tool could return a result.','no_data')
        event('Evidence check','Evidence validator','Insufficient evidence. Import timestamped measurements before diagnosing.','insufficient')
        result={"status":"insufficient_evidence","title":"No telemetry connected","summary":"No network measurements have been imported or retrieved from a live source. The system has taken no action.","evidence":[],"recommendation":"Connect an approved telemetry source or import real measurements with timestamps, device IDs, metric values, and units.","mode":"No telemetry available","confidence":"Not assessed","anomalies":[],"coverage":0}
        return result,events
    event('Telemetry query','In-memory synthetic fixture' if samples is not None else 'Local telemetry store',f"Retrieved {len(rows)} observation(s) from the {'explicitly labeled synthetic fixture' if samples is not None else 'stored workspace telemetry'}, across {len(set(r['device_id'] for r in rows))} device(s).")
    states=metric_states(rows); anomalies=[x for x in states if x['state']=='anomaly']; unknown=[x for x in states if x['state']=='unknown']; normals=[x for x in states if x['state']=='normal']
    perf_names={'latency_ms','jitter_ms','packet_loss_pct','throughput_mbps','bandwidth_mbps','link_utilization_pct','rssi_dbm','snr_db','retransmission_pct','dns_failure_pct'}
    health_names={'cpu_pct','mem_pct','queue_drops','interface_errors','device_status','server_status','dns_status','dhcp_status','database_status','connection_pool_usage_pct','connection_pool_active','connection_pool_max','database_query_latency_ms'}
    perf=[x for x in states if x['metric'] in perf_names]
    health=[x for x in states if x['metric'] in health_names]
    observed_devices=sorted({r['device_id'] for r in rows})
    parents=sorted({(r['device_id'],r['parent_device_id']) for r in rows if r['parent_device_id']})
    connectivity={"observed_devices":observed_devices,"observed_parent_edges":[{"child":a,"parent":b} for a,b in parents],"anomalous_devices":sorted({x['device_id'] for x in anomalies})}
    findings=[{"agent":"performance_agent","status":"ok" if perf else "no_data","observations":perf},
              {"agent":"infrastructure_health_agent","status":"ok" if health else "no_data","observations":health},
              {"agent":"connectivity_agent","status":"ok" if parents else "degraded","observations":connectivity}]
    messages=[]
    for i,finding in enumerate(findings):
        message={"protocol":"ncmp/1.0","message_id":str(uuid.uuid4()),"incident_id":"local-analysis","task_id":"telemetry-review","type":"finding","sender":finding['agent'],"recipient":"correlation_agent","payload":finding}
        messages.append(message)
        event(f"Finding received: {finding['agent']}",finding['agent'],f"Returned {len(finding['observations']) if isinstance(finding['observations'],list) else len(finding['observations'].get('observed_devices',[]))} evidence item(s); status {finding['status']}.")
    event('Evidence correlation','correlation_agent',f"Compared {len(perf)} performance, {len(health)} infrastructure and {len(parents)} supplied topology relationship(s). Cause is not assigned without corroborating evidence.")
    messages.append({"protocol":"ncmp/1.0","message_id":str(uuid.uuid4()),"incident_id":"local-analysis","task_id":"telemetry-review","type":"report","sender":"correlation_agent","recipient":"reporting_agent","payload":{"anomaly_count":len(anomalies),"unclassified_count":len(unknown),"root_cause":"not_assessed","steering":"not_configured"}})
    if anomalies:
        event('Baseline comparison','Robust baseline analyzer',f"{len(anomalies)} metric(s) are outside their empirical baseline; {len(unknown)} metric group(s) lack enough historical data.")
        event('Response policy','Policy gate','Anomaly recorded. Automatic path steering is unavailable until an authorized controller adapter and explicit operating limits are configured. No route was changed.','blocked')
        result={"status":"anomaly_detected","title":"Telemetry deviation detected","summary":f"{len(anomalies)} metric(s) deviated from an empirical baseline. This does not by itself establish a root cause.","evidence":anomalies,"recommendation":"Inspect the affected device and related path. Automatic traffic steering requires a connected controller, verified alternate-path capacity, and operator-defined limits.","mode":"Imported telemetry","confidence":"Cause not established","anomalies":anomalies,"coverage":len(normals)+len(anomalies),"agent_findings":findings,"message_log":messages}
    elif unknown and not normals:
        event('Evidence check','Evidence validator','Historical readings are insufficient to establish a baseline; no action taken.','insufficient')
        result={"status":"insufficient_evidence","title":"Baseline not established","summary":"At least 20 historical readings per device and metric are required before the latest reading can be classified.","evidence":states,"recommendation":"Continue collecting timestamped telemetry. No route or device settings were changed.","mode":"Imported telemetry","confidence":"Not assessed","anomalies":[],"coverage":0,"agent_findings":findings,"message_log":messages}
    else:
        event('Baseline comparison','Robust baseline analyzer',f"No deviations found in {len(normals)} metric group(s). {len(unknown)} group(s) remain unclassified.")
        event('Response policy','Policy gate','No anomaly detected. No remediation or route change was requested.')
        result={"status":"no_fault_found","title":"No action required","summary":"No deviation was detected in metrics with sufficient history. Metrics without a baseline remain unknown.","evidence":normals,"recommendation":"Continue monitoring. Collect more history for metrics still marked unknown.","mode":"Imported telemetry","confidence":"No fault identified","anomalies":[],"coverage":len(normals),"agent_findings":findings,"message_log":messages}
    event('Result verified','Output validator','Result contains only measurements from the supplied dataset and computed baseline comparisons.')
    if samples is not None: result['mode']='Explicit synthetic fixture; not live network data'
    return result,events

def run_task(tid, request):
    try:
        result,events=task_result(request)
        report=diagnostic_report('INC-'+tid[:8].upper(),result); validate_report(report); result['json_report']=report
        # Correlation and recommendation/reporting are explicit fifth-stage agents, with their own bounded inputs and outputs.
        result.setdefault('agent_findings',[]).extend([
            {'agent':'fault_correlation_agent','status':'ok' if report['root_cause_code']!='unknown' else 'insufficient_evidence','observations':{'root_cause_code':report['root_cause_code'],'confidence_category':report['confidence_category'],'affected_devices':report['affected_devices'],'summary':f"Compared {len(report['supporting_evidence'])} evidence item(s); retained {len(report['alternative_causes'])} alternative cause(s)."}},
            {'agent':'recommendation_reporting_agent','status':'ok','observations':{'validated_fields':len(report),'action_count':len(report['recommended_actions']),'summary':f"Validated the structured report and prepared {len(report['recommended_actions'])} recommended action(s)."}}
        ])
        events.append({'name':'Fault correlation agent','tool':'fault_correlation_agent','detail':f"Selected {report['root_cause_code']} using {len(report['supporting_evidence'])} evidence item(s); confidence is {report['confidence_category'].lower()} and uncalibrated.",'status':'completed','time':time.strftime('%H:%M:%S')})
        events.append({'name':'Recommendation and reporting agent','tool':'recommendation_reporting_agent','detail':f"Validated {len(report)} report fields and prepared {len(report['recommended_actions'])} recommendation(s).",'status':'completed','time':time.strftime('%H:%M:%S')})
        if result.get('message_log'):
            for message in result['message_log']:
                if message.get('sender')=='correlation_agent' and message.get('type')=='report':
                    message['payload']={'root_cause_code':report['root_cause_code'],'status':report['status'],'confidence':report['confidence'],'alternatives':report['alternative_causes']}
            if report['alternative_causes']:
                messages=result['message_log']; findings={f['agent']:f for f in result.get('agent_findings',[])}
                incident=report['incident_id']
                messages.append({'protocol':'ncmp/1.0','message_id':str(uuid.uuid4()),'incident_id':incident,'task_id':tid,'type':'conflict_notice','sender':'correlation_agent','recipient':'performance_agent','payload':{'ranked_causes':[report['root_cause_code']]+[x['cause'] for x in report['alternative_causes']],'agreement':report['confidence_breakdown']['agreement']}})
                for agent in ('performance_agent','infrastructure_health_agent'):
                    finding=findings.get(agent,{'status':'no_data','observations':[]})
                    messages.append({'protocol':'ncmp/1.0','message_id':str(uuid.uuid4()),'incident_id':incident,'task_id':tid,'type':'probe_request','sender':'correlation_agent','recipient':agent,'payload':{'request':'Recheck the competing hypotheses against your assigned evidence slice. No new device poll is issued.'}})
                    messages.append({'protocol':'ncmp/1.0','message_id':str(uuid.uuid4()),'incident_id':incident,'task_id':tid,'type':'probe_response','sender':agent,'recipient':'correlation_agent','payload':{'status':finding.get('status'),'observations':finding.get('observations',[]),'new_measurement_collected':False}})
                events.append({'name':'Conflict round completed','tool':'ncmp/1.0 probe exchange','detail':'The performance and infrastructure agents rechecked their assigned snapshot; existing evidence was reused, no new device poll occurred, and competing causes remain visible.','status':'completed','time':time.strftime('%H:%M:%S')})
            result['message_log'].append({'protocol':'ncmp/1.0','message_id':str(uuid.uuid4()),'incident_id':report['incident_id'],'task_id':tid,'type':'finding','sender':'fault_correlation_agent','recipient':'recommendation_reporting_agent','payload':{'root_cause_code':report['root_cause_code'],'confidence':report['confidence'],'alternative_causes':report['alternative_causes'],'evidence_count':len(report['supporting_evidence'])}})
            result['message_log'].append({'protocol':'ncmp/1.0','message_id':str(uuid.uuid4()),'incident_id':report['incident_id'],'task_id':tid,'type':'report','sender':'recommendation_reporting_agent','recipient':'user_interface','payload':report})
            for message in result['message_log']: validate_message(message)
        events.append({'name':'Root causes compared','tool':'fault_correlation_agent','detail':f"Selected {report['root_cause_code']} with {report['confidence_category'].lower()} rule-based confidence; alternatives and missing evidence retained.",'status':'completed','time':time.strftime('%H:%M:%S')})
        events.append({'name':'JSON report validated','tool':'report_validator','detail':'Required report fields and confidence range were checked.','status':'completed','time':time.strftime('%H:%M:%S')})
        status='Completed'
        with LOCK, connect() as c: c.execute('UPDATE tasks SET status=?,result=?,events=? WHERE id=?',(status,json.dumps(result),json.dumps(events),tid))
    except Exception as e:
        result={"status":"error","title":"Analysis failed","summary":"The stored telemetry could not be analyzed.","evidence":[],"recommendation":"Review the imported records and try again.","error":str(e)}
        with LOCK, connect() as c: c.execute('UPDATE tasks SET status=?,result=?,events=? WHERE id=?',('Failed',json.dumps(result),'[]',tid))

def request_role(headers):
    """Local demo role, enforced by the server for management endpoints.

    This is not a replacement for authentication on a shared deployment.
    """
    return 'admin' if headers.get('X-NetCoop-Role', '').lower() == 'admin' else 'user'

def assess_router(router_id):
    with connect() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM telemetry WHERE device_id=? OR parent_device_id=? ORDER BY timestamp DESC LIMIT 5000',(router_id,router_id))]
    latest={}
    for row in rows:
        latest.setdefault(row['metric'],row)
    loss=float(latest.get('packet_loss_pct',{}).get('value',0))
    latency=float(latest.get('latency_ms',{}).get('value',0))
    spikes=sum(1 for state in metric_states(rows) if state.get('state')=='anomaly')
    status='Healthy'
    if loss>5 or latency>150 or spikes>=5: status='Critical'
    elif loss>=1 or latency>=50 or spikes>=2: status='Degraded'
    if not rows: status='Unknown'; summary=f'{router_id}: Unknown — no supplied telemetry.'
    else: summary=f'{router_id}: {status}, {loss:.1f}% loss, {latency:.0f} ms latency, and {spikes} deviation(s) in supplied history.'
    details={'packet_loss_pct':loss,'latency_ms':latency,'spikes':spikes,'sample_count':len(rows),'source':'supplied telemetry only'}
    return {'router_id':router_id,'status':status,'summary':summary,'details':details}

PPT_MESSAGE_TYPES=(
    ('task_request','A user starts a diagnosis through the task request API.'),
    ('finding','A specialist returns validated observations and support.'),
    ('probe_request','Correlation asks agents to recheck competing evidence.'),
    ('probe_response','An agent returns its recheck; no new device poll is implied.'),
    ('conflict_notice','Correlation preserves disagreement and its resolution.'),
    ('error','A validation or adapter failure is named instead of silently ignored.'),
    ('report','The reporting role returns the structured diagnosis.'),
)
PPT_VALIDATION_CODES=('E_MALFORMED','E_MISSING_FIELD','E_UNIT_MISMATCH','E_SCHEMA_VERSION','E_STALE_DATA','E_AGENT_TIMEOUT')

def interoperability_catalog():
    return {'protocol':'ncmp/1.0','message_types':[{'type':kind,'meaning':meaning} for kind,meaning in PPT_MESSAGE_TYPES], 'required_measurement_fields':['metric','value','unit','source','timestamp','device_id'], 'named_validation_outcomes':list(PPT_VALIDATION_CODES), 'gateway_behavior':'Foreign fields are normalized through the validated import/adapter path; units are retained or the row is rejected.', 'limitations':['The current agent transport is in-process and deterministic. It is not a distributed HTTP agent network.']}

def result_parameter_criteria(report):
    names=('incident_id','status','suspected_root_cause','root_cause_code','confidence','confidence_category','confidence_breakdown','affected_devices','supporting_evidence','alternative_causes','conflicts','recommended_actions','evidence_sources','limitations')
    return {'parameters':[{'name':name,'present':name in report,'value':report.get(name)} for name in names], 'confidence_inputs':['belief_top','coverage','agreement','method'], 'event_criteria':['validated intake','specialist findings','conflict notice when needed','one bounded probe round when needed','correlation','report validation']}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT/'web'),**kw)
    def log_message(self,*a): pass
    def send_json(self,obj,status=200):
        if self.command=='POST' and urllib.parse.urlparse(self.path).path.startswith('/api/') and '/action-reports/' not in self.path:
            action_id=str(uuid.uuid4()); action=urllib.parse.urlparse(self.path).path
            safe_keys=('ok','id','name','status','imported','rejected','row_errors','source','scan_id','location','readings','best_rssi_dbm','connected','last_refresh','error','probed','reachable','summary','checked_at','report','observations')
            result_fields={key:obj[key] for key in safe_keys if isinstance(obj,dict) and key in obj}
            summary=(obj.get('error') or obj.get('summary')) if isinstance(obj,dict) else None
            if not summary and isinstance(obj,dict) and 'imported' in obj: summary=f"Imported {obj['imported']} telemetry row(s); rejected {obj.get('rejected',0)}."
            if not summary and isinstance(obj,dict) and 'report' in obj: summary=obj['report'].get('summary') or f"{action} completed and returned an evidence report."
            if not summary and isinstance(obj,dict) and 'readings' in obj: summary=f"Wi-Fi survey completed with {obj['readings']} access-point reading(s) at {obj.get('location','the selected spot')}."
            if not summary: summary=f'{action} returned HTTP {status}.'
            report={'action_id':action_id,'action':action,'created_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'outcome':'failed' if status>=400 else 'accepted' if status==202 else 'completed','http_status':status,'summary':str(summary),'result':result_fields,'limitations':['This action record logs the API operation and returned summary; it is not a diagnosis unless a linked diagnostic task report is also present.']}
            if not report['summary'] or report['summary']=='None': report['summary']=f'{action} returned HTTP {status}.'
            with connect() as c:c.execute('INSERT INTO action_reports VALUES(?,?,?,?)',(action_id,action,time.time(),json.dumps(report)))
            if isinstance(obj,dict): obj={**obj,'action_report_id':action_id}
        raw=json.dumps(obj).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)
    def send_download(self,obj,filename):
        raw=json.dumps(obj,indent=2,ensure_ascii=False).encode('utf-8'); self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Disposition',f'attachment; filename="{filename}"'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)
    def body_json(self):
        n=int(self.headers.get('Content-Length',0)); return json.loads(self.rfile.read(min(n,5_000_000)) or b'{}')
    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/api/capabilities':
            return self.send_json({'build_capabilities':['operation_json_reports','system_hardware_software_inventory','realtime_network_report','quality_mitigation_dry_run','auto_refreshed_database_status','local_gateway_quality_sampling'],'safety':'Read-only collection and recommendation-only mitigation.'})
        if path=='/api/v2/health':
            return self.send_json({'ok':True,'protocol':'NCP/1.0','runtime':'thread-worker fallback; see docs/phase-0-gate.md','pydantic_v2':False})
        if path=='/api/v2/agents':
            return self.send_json(InvestigationOrchestrator().bus.discover())
        if path=='/api/v2/scenarios':
            return self.send_json({'scenarios':list(SCENARIOS),'source':'synthetic fixtures only — not live telemetry'})
        if path=='/api/v2/evaluation':
            return self.send_json(evaluate_v2())
        if path=='/api/v2/topology':
            with connect() as c: rows=[dict(r) for r in c.execute('SELECT DISTINCT device_id,parent_device_id,path_id FROM telemetry WHERE parent_device_id IS NOT NULL')]
            return self.send_json({'edges':[{'child':r['device_id'],'parent':r['parent_device_id'],'path_id':r['path_id']} for r in rows],'limitations':['Only imported parent relationships are shown.']})
        if path=='/api/reports':
            with connect() as c: rows=[dict(r) for r in c.execute('SELECT id,action,created,report FROM action_reports ORDER BY created DESC LIMIT 250')]
            reports=[]
            for row in rows:
                item=json.loads(row.pop('report')); reports.append({'action_id':row['id'],'action':row['action'],'created_at':datetime.fromtimestamp(row['created'],timezone.utc).isoformat().replace('+00:00','Z'),'outcome':item.get('outcome'),'summary':item.get('summary'),'download':f"/api/action-reports/{row['id']}.json"})
            return self.send_json({'reports':reports,'retention':'The current local build retains reports in SQLite until the user clears/replaces its local workspace data.'})
        if path=='/api/downloads/recent':
            with connect() as c: rows=[dict(row) for row in c.execute('SELECT id,filename,source_url,created FROM download_history ORDER BY created DESC LIMIT 25')]
            for row in rows: row['created_at']=datetime.fromtimestamp(row.pop('created'),timezone.utc).isoformat().replace('+00:00','Z')
            return self.send_json({'downloads':rows,'retention':'Download history is stored locally in SQLite on this computer.'})
        if path=='/api/alerts':
            return self.send_json(local_alerts_snapshot())
        if path.startswith('/api/v2/incidents/'):
            incident_id=path.rsplit('/',1)[-1]
            with connect() as c: row=c.execute('SELECT report FROM incidents WHERE id=?',(incident_id,)).fetchone()
            return self.send_json(json.loads(row['report']) if row else {'error':'Incident not found'},200 if row else 404)
        if path=='/api/health':
            with connect() as c: n=c.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]
            return self.send_json({"ok":True,"mode":"evidence-only","telemetry_records":n,"cisco_configured":all(cisco_config()),"steering":"not configured"})
        if path=='/api/interoperability/catalog':
            return self.send_json(interoperability_catalog())
        if path=='/api/topology':
            with connect() as c:
                routers=[dict(r) for r in c.execute('SELECT id,name,server_id FROM managed_routers ORDER BY name')]
                devices=[dict(r) for r in c.execute('SELECT id,router_id,name FROM managed_devices ORDER BY name')]
                imported=[dict(r) for r in c.execute('SELECT DISTINCT device_id,parent_device_id FROM telemetry WHERE parent_device_id IS NOT NULL')]
            return self.send_json({'server_id':'SERVER_LAPTOP_01','routers':routers,'devices':devices,'imported_edges':[{'child':r['device_id'],'parent':r['parent_device_id']} for r in imported],'limitations':['Managed topology is empty until an authorized administrator adds routers. Imported edges are shown exactly as supplied.']})
        if path.startswith('/api/routers/'):
            pieces=path.split('/')
            if len(pieces)>=5:
                router_id=urllib.parse.unquote(pieces[3])
                if pieces[4]=='assessment': return self.send_json(assess_router(router_id))
                if pieces[4]=='telemetry':
                    query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query); start=(query.get('from') or [''])[0]; end=(query.get('to') or [''])[0]
                    sql='SELECT * FROM telemetry WHERE (device_id=? OR parent_device_id=?)'; params=[router_id,router_id]
                    if start: sql+=' AND timestamp>=?'; params.append(start)
                    if end: sql+=' AND timestamp<=?'; params.append(end)
                    sql+=' ORDER BY timestamp ASC LIMIT 5000'
                    with connect() as c: rows=[dict(r) for r in c.execute(sql,params)]
                    return self.send_json({'router_id':router_id,'samples':rows,'limitations':['Only supplied telemetry is returned.']})
        if path=='/api/tickets':
            role=request_role(self.headers)
            with connect() as c:
                rows=[dict(r) for r in c.execute('SELECT id,user_id,title,category,message,status,created,updated FROM support_tickets ORDER BY updated DESC')]
            if role!='admin': rows=[]
            return self.send_json({'tickets':rows,'role':role,'limitations':['Ticket administration is limited to the local demo admin role.']})
        if path=='/api/exports/recent':
            with connect() as c: rows=[dict(r) for r in c.execute('SELECT id,filename,size_bytes,created FROM export_history ORDER BY created DESC LIMIT 10')]
            return self.send_json({'exports':rows})
        if path=='/api/network/overview':
            query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self.send_json(network_overview((query.get('location') or [None])[0]))
        if path=='/api/network/live':
            with LIVE_LOCK: history=list(LIVE_HISTORY[-180:])
            return self.send_json({'interval_seconds':1,'history':history,'latest':history[-1] if history else None,'window_seconds':180,'retention_minutes':10})
        if path=='/api/telemetry':
            with connect() as c: rows=[dict(r) for r in c.execute('SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 5000')]
            states=metric_states(rows)
            devices={}
            for r in rows:
                d=devices.setdefault(r['device_id'],{"device_id":r['device_id'],"parent_device_id":r['parent_device_id'],"path_id":r['path_id'],"metrics":{},"latest_timestamp":r['timestamp']})
                if r['metric'] not in d['metrics']: d['metrics'][r['metric']]={"value":r['value'],"unit":r['unit'],"timestamp":r['timestamp'],"source":r['source']}
            with connect() as c: count=c.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]
            configured=all(cisco_config())
            return self.send_json({"records":count,"devices":list(devices.values()),"states":states,"samples":list(reversed(rows)),"service_health":service_health_summary(rows),"cisco":{"configured":configured,"connected":CISCO_LAST['connected'],"last_refresh":CISCO_LAST['last_refresh'],"error":CISCO_LAST['error']},"steering":{"connected":False,"reason":"Traffic steering is not configured. Cisco hardware-health integration is read-only."}})
        if path=='/api/tasks':
            with connect() as c: rows=[dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY created DESC')]
            for x in rows:
                x['created']=time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(x['created'])); x['result']=json.loads(x['result']) if x['result'] else None; x['events']=json.loads(x['events'] or '[]'); x['action_report_id']=task_action_report_id(x['id'])
            return self.send_json(rows)
        if path.startswith('/api/action-reports/'):
            action_id=path[len('/api/action-reports/'):].removesuffix('.json')
            with connect() as c: row=c.execute('SELECT report FROM action_reports WHERE id=?',(action_id,)).fetchone()
            if row is None:return self.send_json({'error':'Action report not found.'},404)
            return self.send_download(json.loads(row['report']),f'action-{action_id}.json')
        if path.startswith('/api/tasks/'):
            tid=path[len('/api/tasks/'):].split('/',1)[0]
            with connect() as c: row=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if row is None:return self.send_json({"error":"Task not found"},404)
            x=dict(row); x['created']=time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(x['created'])); x['result']=json.loads(x['result']) if x['result'] else None; x['events']=json.loads(x['events'] or '[]'); x['action_report_id']=task_action_report_id(tid)
            if path.endswith('/activity.json'):
                result=x['result'] or {}
                return self.send_download({'task_id':tid,'request':x['request'],'status':x['status'],'events':x['events'],'agent_findings':result.get('agent_findings',[]),'agent_messages':result.get('message_log',[]),'diagnostic_report':result.get('json_report'),'limitations':['Local deterministic workflow; no live network commands are issued by an investigation.']},f"{tid}-activity.json")
            if path.endswith('/report.json'):
                report=(x['result'] or {}).get('json_report')
                if not report:return self.send_json({'error':'No structured JSON report is available for this task.'},404)
                return self.send_download(report,f"{report['incident_id']}.json")
            if path.endswith('/criteria.json'):
                report=(x['result'] or {}).get('json_report') or {}
                return self.send_download({'task_id':tid,'result_parameters':result_parameter_criteria(report),'event_based_diagnosis':{'events':x['events'],'message_log':(x['result'] or {}).get('message_log',[])},'interoperability_protocol':interoperability_catalog(),'limitations':['This trace records supplied evidence and deterministic workflow events. It does not prove a root cause beyond the structured report confidence.']},f"{tid}-criteria.json")
            return self.send_json(x)
        return super().do_GET()
    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/api/telemetry/import':
            n=int(self.headers.get('Content-Length',0))
            if n>10_000_000:return self.send_json({"error":"CSV exceeds 10 MB."},413)
            raw=self.rfile.read(n).decode('utf-8-sig')
            try:
                reader=csv.DictReader(io.StringIO(raw)); fields={x.strip() for x in (reader.fieldnames or [])}
                missing=REQUIRED-fields
                if missing:return self.send_json({"error":"Missing required columns: "+', '.join(sorted(missing))},400)
                parsed=[]; errors=[]
                for lineno,row in enumerate(reader,2):
                    try:
                        ts=(row.get('timestamp') or '').strip(); parsed_ts=datetime.fromisoformat(ts.replace('Z','+00:00'))
                        if parsed_ts.tzinfo is None: raise ValueError('timestamp must include a timezone (for example Z or +05:30)')
                        ts=parsed_ts.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
                        device=(row.get('device_id') or '').strip(); metric=(row.get('metric') or '').strip().lower(); metric=ALIASES.get(metric,metric)
                        rawvalue=(row.get('value') or '').strip(); value=rawvalue.lower() if metric in STATUS_METRICS else float(rawvalue)
                        if not device or not metric or (metric in STATUS_METRICS and value not in ('up','down','degraded','ok','failed','failure','error','critical','warning','healthy','success','passed')) or (metric not in STATUS_METRICS and not math.isfinite(value)): raise ValueError('invalid device, metric, or value')
                        if metric.endswith('_pct') and metric not in ('packet_loss_pct',) and (not isinstance(value,(int,float)) or not 0<=value<=100): raise ValueError(f'{metric} must be between 0 and 100 percent')
                        if metric in ('packet_loss_pct','retransmission_pct') and not 0<=value<=100: raise ValueError(f'{metric} must be between 0 and 100 percent')
                        if metric in ('queue_drops','interface_errors','connection_pool_active','connection_pool_max') and value<0: raise ValueError(f'{metric} cannot be negative')
                        unit=(row.get('unit') or '').strip()
                        if not unit: raise ValueError('unit is required')
                        source=(row.get('source') or '').strip()
                        if not source: raise ValueError('source is required')
                        parsed.append((ts,device,metric,value,unit,source,(row.get('parent_device_id') or '').strip() or None,(row.get('path_id') or '').strip() or None))
                    except Exception as e: errors.append(f"row {lineno}: {e}")
                    if len(parsed)>200_000:return self.send_json({"error":"CSV exceeds the 200,000 observation limit."},413)
                if not parsed:return self.send_json({"error":"No valid observations found.","row_errors":errors[:25]},400)
                with LOCK,connect() as c:
                    existing={(r['device_id'],r['metric']):r['unit'] for r in c.execute('SELECT device_id,metric,MAX(unit) AS unit FROM telemetry GROUP BY device_id,metric')}
                    consistent=[]
                    for record in parsed:
                        key=(record[1],record[2]); expected=existing.get(key)
                        if expected and expected!=record[4]: errors.append(f"unit mismatch for {key[0]}/{key[1]}: stored {expected}, received {record[4]}")
                        else: consistent.append(record); existing[key]=record[4]
                    if not consistent:return self.send_json({"error":"No rows had units consistent with existing device/metric history.","row_errors":errors[:25]},400)
                    c.executemany('INSERT INTO telemetry(timestamp,device_id,metric,value,unit,source,parent_device_id,path_id) VALUES(?,?,?,?,?,?,?,?)',consistent)
                return self.send_json({"imported":len(consistent),"rejected":len(errors),"row_errors":errors[:25],"source":"CSV import"},201)
            except Exception as e:return self.send_json({"error":f"CSV could not be parsed: {e}"},400)
        try: body=self.body_json()
        except Exception:return self.send_json({"error":"Invalid JSON request"},400)
        if path=='/api/system/report':
            return self.send_json({'ok':True,'summary':'Generated organized local hardware, software, and network inventory.','report':system_hardware_software_report()})
        if path=='/api/network/realtime-report':
            return self.send_json({'ok':True,'summary':'Generated a real-time local network report from current samples.','report':realtime_network_report()})
        if path=='/api/network/throughput-scan':
            scan=local_throughput_scan()
            return self.send_json({'ok':True,'summary':'Captured a passive local adapter-throughput scan. No external speed-test traffic was generated.','report':scan})
        if path=='/api/network/mitigation-plan':
            return self.send_json({'ok':True,'summary':'Generated a safe jitter/packet-loss mitigation dry-run. No settings were changed.','report':mitigation_dry_run_plan()})
        if path=='/api/downloads/register':
            filename=str(body.get('filename') or '').strip()[:180]; source_url=str(body.get('source_url') or '').strip()[:500]
            if not filename or not source_url.startswith('/api/'):
                return self.send_json({'error':'filename and a local API source_url are required.'},400)
            download_id=str(uuid.uuid4())
            with connect() as c:c.execute('INSERT INTO download_history VALUES(?,?,?,?)',(download_id,filename,source_url,time.time()))
            return self.send_json({'ok':True,'id':download_id,'summary':f'Recorded download of {filename}.'},201)
        if path=='/api/v2/diagnosis':
            rows=body.get('telemetry')
            if not isinstance(rows,list): return self.send_json({'error':'telemetry must be an array of observations'},400)
            try:
                report=InvestigationOrchestrator(timeout_s=3).run(rows,body.get('incident_id'))
                with connect() as c:c.execute('INSERT OR REPLACE INTO incidents VALUES(?,?,?,?)',(report['incident_id'],time.time(),report['status'],json.dumps(report)))
                return self.send_json(report,201)
            except Exception as exc: return self.send_json({'error':'Diagnosis request was rejected.','detail':type(exc).__name__},400)
        if path=='/api/demo/run':
            scenario=str(body.get('scenario') or '').strip().lower()
            try: rows=demo_rows(scenario)
            except ValueError:return self.send_json({'error':'Choose a documented demo scenario.'},400)
            tid=str(uuid.uuid4()); request=f"Synthetic demo scenario: {scenario} (not live network data)"
            result,events=task_result(request,samples=rows); incident='DEMO-'+scenario.upper()
            report=diagnostic_report(incident,result)
            try: validate_report(report)
            except Exception as e:return self.send_json({'error':f'Demo report validation failed: {e}'},500)
            result['json_report']=report; result['demo_data']='SYNTHETIC ONLY - NOT LIVE NETWORK DATA'
            result.setdefault('agent_findings',[]).extend([
                {'agent':'fault_correlation_agent','status':'ok' if report['root_cause_code']!='unknown' else 'insufficient_evidence','observations':{'root_cause_code':report['root_cause_code'],'confidence_category':report['confidence_category'],'affected_devices':report['affected_devices'],'summary':f"Compared {len(report['supporting_evidence'])} evidence item(s); retained {len(report['alternative_causes'])} alternative cause(s)."}},
                {'agent':'recommendation_reporting_agent','status':'ok','observations':{'validated_fields':len(report),'action_count':len(report['recommended_actions']),'summary':f"Validated the structured report and prepared {len(report['recommended_actions'])} recommended action(s)."}}
            ])
            events.append({'name':'Fault correlation agent','tool':'fault_correlation_agent','detail':f"Selected {report['root_cause_code']} from the explicitly synthetic evidence with {report['confidence_category'].lower()}, uncalibrated confidence.",'status':'completed','time':time.strftime('%H:%M:%S')})
            events.append({'name':'Recommendation and reporting agent','tool':'recommendation_reporting_agent','detail':f"Validated the JSON report and prepared {len(report['recommended_actions'])} recommendation(s).",'status':'completed','time':time.strftime('%H:%M:%S')})
            events.append({'name':'Demo JSON report validated','tool':'report_validator','detail':'Synthetic fixture results are explicitly labeled and were not inserted into live telemetry.','status':'completed','time':time.strftime('%H:%M:%S')})
            if result.get('message_log'):
                for message in result['message_log']:
                    message['incident_id']=incident; message['task_id']=tid
                result['message_log'].append({'protocol':'ncmp/1.0','message_id':str(uuid.uuid4()),'incident_id':incident,'task_id':tid,'type':'finding','sender':'fault_correlation_agent','recipient':'recommendation_reporting_agent','payload':{'root_cause_code':report['root_cause_code'],'confidence':report['confidence'],'alternative_causes':report['alternative_causes'],'evidence_count':len(report['supporting_evidence'])}})
                result['message_log'].append({'protocol':'ncmp/1.0','message_id':str(uuid.uuid4()),'incident_id':incident,'task_id':tid,'type':'report','sender':'recommendation_reporting_agent','recipient':'user_interface','payload':report})
                for message in result['message_log']: validate_message(message)
            with connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(tid,request,f'DEMO: {scenario}', 'Completed',time.time(),json.dumps(result),json.dumps(events)))
            return self.send_json({'id':tid,'status':'Completed','name':f'DEMO: {scenario}','result':result,'events':events},201)
        if path=='/api/tasks':
            request=(body.get('request') or '').strip()
            if not request:return self.send_json({"error":"Describe the network issue to inspect."},400)
            if len(request)>1200:return self.send_json({"error":"Request too long (maximum 1,200 characters)."},400)
            tid=str(uuid.uuid4()); now=time.time()
            with connect() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(tid,request,request[:46], 'Running',now,None,'[]'))
            threading.Thread(target=run_task,args=(tid,request),daemon=True).start()
            return self.send_json({"id":tid,"status":"Running"},201)
        if path=='/api/telemetry/clear':
            with LOCK,connect() as c:c.execute('DELETE FROM telemetry')
            return self.send_json({"ok":True})
        if path=='/api/cisco/refresh':
            try: count=cisco_fetch(); return self.send_json({"ok":True,"imported":count,"connected":True,"last_refresh":CISCO_LAST['last_refresh']})
            except Exception as e:
                CISCO_LAST.update(connected=False,error=str(e))
                return self.send_json({"error":"Cisco read-only refresh failed: "+str(e)},502)
        if path=='/api/network/probe':
            report=probe_cached_peers(); report['action_id']=str(uuid.uuid4())
            with PROBE_LOCK: count=len(report['observations']); reachable=sum(x['probe_result']['status']=='reachable' for x in report['observations'])
            return self.send_json({'ok':True,'probed':count,'reachable':reachable,'report':report},200)
        if path=='/api/network/scan':
            try: body=self.body_json()
            except Exception: body={}
            location=(str(body.get('location') or 'Current device location').strip()[:80] or 'Current device location')
            try:
                readings,interface=wlan_signal_scan(); scan_id=str(uuid.uuid4()); scanned=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
                with LOCK,connect() as c:
                    c.execute('INSERT INTO wifi_scans(id,location,scanned_at,interface) VALUES(?,?,?,?)',(scan_id,location,scanned,interface))
                    c.executemany('INSERT INTO wifi_readings(scan_id,ssid,bssid,rssi_dbm,signal_quality,frequency_khz) VALUES(?,?,?,?,?,?)',[(scan_id,x['ssid'],x['bssid'],x['rssi_dbm'],x['signal_quality'],x['frequency_khz']) for x in readings])
                return self.send_json({'ok':True,'scan_id':scan_id,'location':location,'scanned_at':scanned,'readings':len(readings),'best_rssi_dbm':max((x['rssi_dbm'] for x in readings),default=None),'observations':readings})
            except Exception as e:return self.send_json({'error':f'Wi-Fi survey failed: {e}'},503)
        if path=='/api/tickets':
            title=str(body.get('title') or '').strip()[:140]; category=str(body.get('category') or '').strip()[:80]; message=str(body.get('message') or '').strip()[:4000]
            if not title or not category or not message:return self.send_json({'error':'title, category, and message are required.'},400)
            ticket_id='TKT-'+uuid.uuid4().hex[:8].upper(); now=time.time(); user_id=str(body.get('user_id') or 'local-user')[:80]
            with connect() as c:c.execute('INSERT INTO support_tickets VALUES(?,?,?,?,?,?,?,?)',(ticket_id,user_id,title,category,message,'open',now,now))
            return self.send_json({'ok':True,'id':ticket_id,'status':'open','summary':f'Ticket {ticket_id} was created.'},201)
        if path=='/api/export':
            filename=re.sub(r'[^A-Za-z0-9._-]','_',str(body.get('filename') or 'netcoop-export.json'))[:120]
            payload=body.get('payload') if isinstance(body.get('payload'),dict) else {'generated_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'note':'Local NetCoop export.'}
            raw=json.dumps(payload,indent=2).encode(); export_id=str(uuid.uuid4()); now=time.time()
            with connect() as c:c.execute('INSERT INTO export_history VALUES(?,?,?,?,?,?)',(export_id,str(body.get('user_id') or 'local-user')[:80],filename,len(raw),now,raw.decode()))
            return self.send_json({'ok':True,'id':export_id,'filename':filename,'size_bytes':len(raw),'summary':f'Export {filename} was recorded.'},201)
        if path=='/api/verify' or re.fullmatch(r'/api/verify/[^/]+/retry',path):
            if request_role(self.headers)!='admin':return self.send_json({'error':'Admin role is required for verification controls.'},403)
            previous_id=path.split('/')[3] if path!='/api/verify' and len(path.split('/'))>3 else None
            attempt=1
            if previous_id:
                with connect() as c: previous=c.execute('SELECT attempt FROM verification_attempts WHERE id=?',(previous_id,)).fetchone()
                if not previous:return self.send_json({'error':'Verification record not found.'},404)
                attempt=int(previous['attempt'])+1
            if attempt>3:return self.send_json({'error':'Retry limit reached (3). Choose an alternative method.'},409)
            outcome=str(body.get('outcome') or 'pending').lower(); method=str(body.get('method') or 'manual_check')[:100]
            status='FinalResult' if outcome=='success' else 'Alternative' if outcome=='alternative' else 'Retry' if outcome=='failure' else 'Pending'
            vid='VRF-'+uuid.uuid4().hex[:8].upper()
            with connect() as c:c.execute('INSERT INTO verification_attempts VALUES(?,?,?,?,?,?,?)',(vid,str(body.get('user_id') or 'local-admin')[:80],status,attempt,method,str(body.get('reason') or '')[:1000],time.time()))
            return self.send_json({'ok':True,'id':vid,'status':status,'attempt':attempt,'summary':f'Verification {vid} is {status}.'},201)
        if path=='/api/tasks/clear':
            with LOCK,connect() as c:c.execute('DELETE FROM tasks')
            return self.send_json({"ok":True})
        return self.send_json({"error":"Not found"},404)

    def do_PATCH(self):
        path=urllib.parse.urlparse(self.path).path
        if not path.startswith('/api/tickets/'):
            return self.send_json({'error':'Not found'},404)
        if request_role(self.headers)!='admin':
            return self.send_json({'error':'Admin role is required to update tickets.'},403)
        try: body=self.body_json()
        except Exception: return self.send_json({'error':'Invalid JSON request'},400)
        status=str(body.get('status') or '').lower()
        if status not in {'open','in-progress','closed'}: return self.send_json({'error':'status must be open, in-progress, or closed.'},400)
        ticket_id=path.rsplit('/',1)[-1]
        with connect() as c:
            existing=c.execute('SELECT id FROM support_tickets WHERE id=?',(ticket_id,)).fetchone()
            if not existing:return self.send_json({'error':'Ticket not found.'},404)
            c.execute('UPDATE support_tickets SET status=?,updated=? WHERE id=?',(status,time.time(),ticket_id))
        return self.send_json({'ok':True,'id':ticket_id,'status':status,'summary':f'Ticket {ticket_id} is now {status}.'})

if __name__=='__main__':
    print('NetCoop AI evidence-only dashboard at http://localhost:8000')
    threading.Thread(target=live_sampler,daemon=True).start()
    threading.Thread(target=cpu_temperature_sampler,daemon=True).start()
    threading.Thread(target=database_status_sampler,daemon=True).start()
    threading.Thread(target=gateway_quality_sampler,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',8000),Handler).serve_forever()
