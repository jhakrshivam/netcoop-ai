"""
Temperature collector for NetCoop-Local (Windows first, Linux/macOS tolerated).

Providers are tried in order. The first one that returns a plausible value wins.
Every reading says where it came from (`source`) and how trustworthy it is (`kind`):

    real         -> measured by a hardware sensor
    estimated    -> NOT degrees C; a 0-100 "thermal stress" index from CPU load/frequency
    simulated    -> demo mode only
    unavailable  -> nothing worked (the reason is in `detail`)

Never show an `estimated` value as degrees C in the UI.

Setup on Windows (one time):
    1. Download LibreHardwareMonitor (free, open source).
    2. Right-click -> Run as administrator.
    3. Menu: Options -> Remote Web Server -> Run   (default port 8085).
    4. Check http://localhost:8085/data.json opens in your browser.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional, Tuple
from uuid import UUID

try:
    import psutil
except ImportError:  # psutil is a project dependency, but never crash on import
    psutil = None

PLAUSIBLE_MIN_C = 5.0
PLAUSIBLE_MAX_C = 110.0
LHM_URL = "http://localhost:8085/data.json"


@dataclass
class TemperatureReading:
    value_c: Optional[float]          # degrees C, only when kind == "real" or "simulated"
    source: str                       # e.g. "librehardwaremonitor", "wmi", "psutil"
    kind: str                         # real | estimated | simulated | unavailable
    detail: str = ""                  # sensor name or reason for failure
    thermal_stress_index: Optional[float] = None  # 0-100, only for kind == "estimated"
    tried: List[str] = field(default_factory=list)  # "provider: why it failed"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------
# Provider 1: psutil (works on Linux only; psutil has no such function on Windows)
# ----------------------------------------------------------------------------
def read_psutil() -> Tuple[Optional[TemperatureReading], str]:
    if psutil is None or not hasattr(psutil, "sensors_temperatures"):
        return None, "psutil.sensors_temperatures not available on this OS"
    try:
        data = psutil.sensors_temperatures()
    except Exception as exc:
        return None, f"psutil error: {exc}"
    if not data:
        return None, "psutil returned no sensors"
    for chip in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
        entries = data.get(chip)
        if entries:
            vals = [e.current for e in entries if _plausible(e.current)]
            if vals:
                return TemperatureReading(max(vals), "psutil", "real", f"chip={chip}"), ""
    return None, "no plausible CPU sensor in psutil data"


# ----------------------------------------------------------------------------
# Provider 2: LibreHardwareMonitor / OpenHardwareMonitor remote web server
# ----------------------------------------------------------------------------
_NUM = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)")
_EXCLUDE = ("gpu", "nvidia", "geforce", "radeon", "nvme", "ssd", "hdd", "battery")
_PRIORITY = ("cpu package", "core max", "core average", "tctl", "tdie", "cpu")


def _walk(node: dict, path: List[str], out: List[Tuple[List[str], float]]) -> None:
    text = str(node.get("Text", ""))
    here = path + [text]
    value = node.get("Value")
    # Temperature values look like "45.0 °C". Match on the trailing "C" so a mangled
    # degree sign (encoding issues) does not break parsing.
    if isinstance(value, str) and value.strip().upper().endswith("C"):
        m = _NUM.match(value)
        if m:
            out.append((here, float(m.group(1).replace(",", "."))))
    for child in node.get("Children") or []:
        if isinstance(child, dict):
            _walk(child, here, out)


def parse_lhm_json(tree: dict) -> Tuple[Optional[float], str]:
    """Pure function (easy to unit-test). Returns (temp_c, sensor_name) or (None, reason)."""
    found: List[Tuple[List[str], float]] = []
    _walk(tree, [], found)
    candidates = []
    for path, val in found:
        # path[0] = root, path[1] = computer name; filter on hardware/sensor names only
        label = " / ".join(path[2:]).lower()
        if any(bad in label for bad in _EXCLUDE):
            continue
        if not _plausible(val):
            continue
        if any(k in label for k in ("cpu", "core", "tctl", "tdie", "package")):
            candidates.append((label, path[-1], val))
    if not candidates:
        return None, "no CPU temperature sensor found in LibreHardwareMonitor data"
    for key in _PRIORITY:
        for label, name, val in candidates:
            if key in name.lower():
                return val, name
    label, name, val = max(candidates, key=lambda c: c[2])
    return val, name


def read_lhm(url: str = LHM_URL, timeout: float = 2.0) -> Tuple[Optional[TemperatureReading], str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            tree = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return None, (
            f"cannot reach {url} ({exc.__class__.__name__}). Start LibreHardwareMonitor "
            "as administrator and enable Options > Remote Web Server > Run"
        )
    val, name = parse_lhm_json(tree)
    if val is None:
        return None, name
    return TemperatureReading(val, "librehardwaremonitor", "real", f"sensor={name}"), ""


# ----------------------------------------------------------------------------
# Provider 3: Windows WMI thermal zone (often needs admin, often unreliable)
# ----------------------------------------------------------------------------
class WmiProvider:
    """Keeps a short history so a value that never changes is rejected as fake."""

    def __init__(self) -> None:
        self.history: deque = deque(maxlen=10)

    def __call__(self) -> Tuple[Optional[TemperatureReading], str]:
        if sys.platform != "win32":
            return None, "WMI is Windows-only"
        cmd = [
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
            "| Select-Object -ExpandProperty CurrentTemperature",
        ]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            return None, f"powershell failed: {exc}"
        if out.returncode != 0 or not out.stdout.strip():
            return None, "WMI thermal zone not exposed (needs admin, or the laptop does not provide it)"
        temps = []
        for line in out.stdout.split():
            try:
                temps.append(int(line) / 10.0 - 273.15)  # tenths of Kelvin -> C
            except ValueError:
                continue
        temps = [t for t in temps if _plausible(t)]
        if not temps:
            return None, "WMI returned no plausible value"
        value = round(max(temps), 1)
        self.history.append(value)
        if len(self.history) >= 10 and len(set(self.history)) == 1:
            return None, "WMI value never changes (likely a fixed placeholder), rejected"
        return TemperatureReading(value, "wmi", "real", "MSAcpi_ThermalZoneTemperature"), ""


# ----------------------------------------------------------------------------
# Provider 4: macOS thermal pressure (level only, not degrees)
# ----------------------------------------------------------------------------
def read_macos() -> Tuple[Optional[TemperatureReading], str]:
    return None, "macOS provider not implemented (Windows is the target platform)"


# ----------------------------------------------------------------------------
# Provider 5: estimated thermal stress (NOT degrees C)
# ----------------------------------------------------------------------------
class StressEstimator:
    def __init__(self, window: int = 30) -> None:
        self.cpu: deque = deque(maxlen=window)

    def __call__(self) -> Tuple[Optional[TemperatureReading], str]:
        if psutil is None:
            return None, "psutil missing"
        self.cpu.append(psutil.cpu_percent(interval=None))
        avg_cpu = sum(self.cpu) / len(self.cpu)
        freq_drop = 0.0
        try:
            f = psutil.cpu_freq()
            if f and f.max:
                freq_drop = max(0.0, 1.0 - f.current / f.max)
        except Exception:
            pass
        # Heavy sustained load plus falling clock speed suggests heat pressure.
        index = round(min(100.0, 0.75 * avg_cpu + 0.25 * 100 * freq_drop), 1)
        return TemperatureReading(
            None, "estimate", "estimated",
            "thermal stress index from CPU load and frequency; this is NOT a temperature",
            thermal_stress_index=index,
        ), ""


# ----------------------------------------------------------------------------
# Collector
# ----------------------------------------------------------------------------
def _plausible(v: float) -> bool:
    return v is not None and PLAUSIBLE_MIN_C <= v <= PLAUSIBLE_MAX_C


class TemperatureCollector:
    def __init__(self, demo_mode: bool = False, lhm_url: str = LHM_URL) -> None:
        self.demo_mode = demo_mode
        self.demo_value = 55.0
        self.providers: List[Tuple[str, Callable]] = [
            ("psutil", read_psutil),
            ("librehardwaremonitor", lambda: read_lhm(lhm_url)),
            ("wmi", WmiProvider()),
            ("macos", read_macos),
        ]
        self.estimator = StressEstimator()

    def read(self) -> TemperatureReading:
        tried: List[str] = []
        for name, fn in self.providers:
            reading, why = fn()
            if reading is not None:
                reading.tried = tried
                return reading
            tried.append(f"{name}: {why}")
        est, _ = self.estimator()
        if est is not None:
            est.tried = tried
            if not self.demo_mode:
                return est
        if self.demo_mode:
            # slow random walk, clearly labelled
            import random
            self.demo_value = min(100.0, max(40.0, self.demo_value + random.uniform(-1.5, 2.0)))
            return TemperatureReading(round(self.demo_value, 1), "demo", "simulated",
                                      "SIMULATED value for demo", tried=tried)
        return TemperatureReading(None, "none", "unavailable", "no provider succeeded", tried=tried)


def temperature_to_message(reading: TemperatureReading, correlation_id: str | UUID):
    """Convert a reading into a validated NCP telemetry snapshot.

    Estimated thermal stress is deliberately represented without a Celsius
    value; unavailable sensors similarly remain ``null`` rather than guessed.
    """
    from netcoop.messages import MessageType, NCPMessage

    if reading.kind not in {"real", "estimated", "simulated", "unavailable"}:
        raise ValueError(f"Unsupported temperature reading kind: {reading.kind}")
    correlation = correlation_id if isinstance(correlation_id, UUID) else UUID(str(correlation_id))
    temp_c = reading.value_c if reading.kind in {"real", "simulated"} else None
    data_quality = {"source": reading.kind, "completeness": 1.0, "missing_fields": []}
    if reading.kind == "unavailable":
        data_quality.update({"completeness": 0.0, "missing_fields": ["temp_c"]})
    payload = {
        "temp_c": temp_c,
        "source": reading.source,
        "kind": reading.kind,
        "thermal_stress_index": reading.thermal_stress_index,
        "detail": reading.detail,
        "data_quality": data_quality,
    }
    return NCPMessage.create(
        MessageType.TELEMETRY_SNAPSHOT,
        sender="temperature_collector",
        recipient_or_topic="telemetry",
        payload=payload,
        correlation_id=correlation,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Read local CPU temperature or run a labeled demo.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="emit clearly labeled simulated readings; never use these as hardware measurements",
    )
    parser.add_argument("--samples", type=int, default=3, help="number of readings to print (default: 3)")
    args = parser.parse_args()

    collector = TemperatureCollector(demo_mode=args.demo)
    if args.demo:
        # A demo must stay synthetic even when a real sensor is available.
        collector.providers = []
        print("DEMO MODE: readings below are SIMULATED, not live hardware temperatures.")
    for _ in range(max(1, args.samples)):
        r = collector.read()
        print(json.dumps(r.to_dict(), indent=2, default=str))
        time.sleep(1)
