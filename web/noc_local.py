"""
REGTeches NOC Local  v1.0.0
Replaces noc_agent.py + noc_sysmon.py — one script does both jobs.

  • Runs a background HTTP agent so the NOC dashboard can read this
    PC's CPU, RAM, disks, processes, and execute power actions.
  • Shows a small desktop widget with live bars — click it to open
    the full 6-tab detail window.
  • ONE psutil collection loop feeds both — zero duplication.

─────────────────────────────────────────────────────────────────
QUICK START
─────────────────────────────────────────────────────────────────
1.  pip install psutil
2.  python noc_local.py
    First run creates noc_agent_settings.json and prints your API key.
3.  In the NOC dashboard edit this PC's card:
      Tag:      noc-agent
      API Key:  (key printed in step 2)
      Port:     9182
    Tick  📊 Enable System Info  and save.
4.  Click the 📊 Info button on the card — done.

─────────────────────────────────────────────────────────────────
WINDOWS — AUTO-START ON LOGIN  (no admin needed)
─────────────────────────────────────────────────────────────────
  Win+R  →  shell:startup
  Create a shortcut pointing to:
    pythonw  C:\\full\\path\\to\\noc_local.py

─────────────────────────────────────────────────────────────────
HTTP ENDPOINTS
─────────────────────────────────────────────────────────────────
  GET  /health              no key needed
  GET  /info?key=KEY        full system info JSON
  POST /power?key=KEY       body: {"action": "reboot|shutdown|
                                    cancel|lock|sleep|hibernate|logoff"}
─────────────────────────────────────────────────────────────────
"""

import os
import sys
import json
import time
import platform
import threading
import secrets
import socket
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import tkinter as tk
from tkinter import ttk

try:
    import psutil
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
    import psutil

# ── Version / identity ────────────────────────────────────────────────────────
VERSION    = "1.0.0"
AUTHOR     = "Ronald Goodchild"
COPYRIGHT  = "(c) 2026 REGTeches / Bay Area Tech"

# ── Settings file (shared with old noc_agent.py — backward compatible) ────────
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "noc_agent_settings.json")

_DEFAULT_CFG = {
    "api_key":   "",       # auto-generated on first run
    "port":      9182,
    "host":      "0.0.0.0",
    "top_procs": 25,
    "allow_ips": [],       # empty = allow all
}

def _load_cfg():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            cfg = {**_DEFAULT_CFG, **saved}
            if not cfg.get("api_key"):
                cfg["api_key"] = secrets.token_hex(20)
                _save_cfg(cfg)
            return cfg
        except Exception:
            pass
    cfg = dict(_DEFAULT_CFG)
    cfg["api_key"] = secrets.token_hex(20)
    _save_cfg(cfg)
    return cfg

def _save_cfg(cfg):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

CFG = _load_cfg()

# ── UI refresh interval ───────────────────────────────────────────────────────
UI_REFRESH_MS  = 2000   # widget redraws every 2 s
DATA_COLLECT_S = 1.5    # collector thread runs every 1.5 s

# ── Colour palette (matches NOC dashboard dark theme) ────────────────────────
BG      = "#0a0f1a"
CARD    = "#0f172a"
CARD2   = "#0d1629"
BORDER  = "#1e293b"
HDR     = "#060a14"
TEXT    = "#e2e8f0"
DIM     = "#94a3b8"
ACCENT  = "#3b82f6"
GREEN   = "#22c55e"
RED     = "#ef4444"
YELLOW  = "#eab308"
ORANGE  = "#f97316"

F_UI    = ("Segoe UI",  9)
F_BOLD  = ("Segoe UI",  9, "bold")
F_HEAD  = ("Segoe UI", 10, "bold")
F_TITLE = ("Segoe UI", 11, "bold")
F_MONO  = ("Consolas",  9)
F_SMALL = ("Consolas",  8)
F_SB    = ("Consolas",  8, "bold")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Data collection  (one loop feeds HTTP + widget)
# ══════════════════════════════════════════════════════════════════════════════

def _cpu_name():
    try:
        if platform.system() == "Windows":
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        with open("/proc/cpuinfo") as f:
            for ln in f:
                if "model name" in ln:
                    return ln.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "CPU"


def _gb(b):
    return round(b / (1024 ** 3), 2)


def collect():
    """Gather all psutil metrics into a single dict."""
    d = {"type": "noc-agent", "agent_version": VERSION}

    # CPU
    d["cpu_pct"]        = psutil.cpu_percent(interval=None)
    d["cpu_per_core"]   = psutil.cpu_percent(percpu=True)
    freq = psutil.cpu_freq()
    d["cpu_name"]       = _cpu_name()
    d["cpu_cores_phys"] = psutil.cpu_count(logical=False) or 0
    d["cpu_cores_logi"] = psutil.cpu_count(logical=True)  or 0
    d["cpu_freq_mhz"]   = round(freq.current) if freq else 0
    d["cpu_freq_max"]   = round(freq.max)      if freq else 0
    temps = []
    try:
        for chip, ee in (psutil.sensors_temperatures() or {}).items():
            for e in ee:
                if (e.current or 0) > 0:
                    temps.append({
                        "label": f"{chip}/{e.label or 'core'}",
                        "cur":   round(e.current, 1),
                        "high":  round(e.high or 95, 1),
                    })
    except (AttributeError, NotImplementedError):
        pass
    d["cpu_temps"] = temps

    # Memory
    m  = psutil.virtual_memory()
    sw = psutil.swap_memory()
    d["ram_pct"]      = m.percent
    d["ram_total_gb"] = _gb(m.total)
    d["ram_used_gb"]  = _gb(m.used)
    d["ram_free_gb"]  = _gb(m.available)
    d["ram_cached_gb"]= _gb(getattr(m, "cached", 0))
    d["swap_pct"]     = sw.percent
    d["swap_total_gb"]= _gb(sw.total)
    d["swap_used_gb"] = _gb(sw.used)

    # Disks
    vols = []
    for part in psutil.disk_partitions(all=False):
        if platform.system() == "Windows" and (
            "cdrom" in (part.opts or "") or part.fstype == ""
        ):
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
            vols.append({
                "label":    part.mountpoint,
                "device":   part.device,
                "fstype":   part.fstype,
                "used_pct": round(u.percent, 1),
                "total_gb": _gb(u.total),
                "used_gb":  _gb(u.used),
                "free_gb":  _gb(u.free),
            })
        except (PermissionError, OSError):
            pass
    d["volumes"] = vols
    try:
        io = psutil.disk_io_counters()
        d["disk_read_gb"]  = _gb(io.read_bytes)
        d["disk_write_gb"] = _gb(io.write_bytes)
    except Exception:
        pass

    # Processes
    pl = []
    try:
        for p in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent",
             "status", "memory_info", "username"]
        ):
            try:
                mi = p.info.get("memory_info")
                pl.append({
                    "pid":     p.info["pid"],
                    "name":    (p.info["name"] or "?")[:40],
                    "cpu_pct": round(p.info.get("cpu_percent") or 0, 1),
                    "mem_pct": round(p.info.get("memory_percent") or 0, 2),
                    "status":  p.info.get("status") or "",
                    "mem_mb":  round(mi.rss / (1024**2), 1) if mi else 0,
                    "user":    (p.info.get("username") or "")[:30],
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass
    pl.sort(key=lambda x: x["cpu_pct"], reverse=True)
    d["processes"]  = pl[:CFG["top_procs"]]
    d["proc_count"] = len(psutil.pids())

    # Network
    ifaces = []
    try:
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                fn = getattr(a.family, "name", str(a.family))
                if "INET" in fn and "INET6" not in fn:
                    ifaces.append({
                        "name": name,
                        "ipv4": a.address,
                        "mask": a.netmask or "",
                    })
    except Exception:
        pass
    d["net_ifaces"] = ifaces
    try:
        nio = psutil.net_io_counters()
        d["net_sent_gb"] = _gb(nio.bytes_sent)
        d["net_recv_gb"] = _gb(nio.bytes_recv)
    except Exception:
        pass

    # System
    boot = datetime.fromtimestamp(psutil.boot_time())
    up   = datetime.now() - boot
    hh, r = divmod(up.seconds, 3600)
    mm, _ = divmod(r, 60)
    d["hostname"]    = platform.node()
    d["os"]          = f"{platform.system()} {platform.release()}"
    d["os_version"]  = platform.version()[:80]
    d["arch"]        = platform.machine()
    d["uptime_days"] = round(up.days + up.seconds / 86400, 2)
    d["uptime_str"]  = f"{up.days}d {hh}h {mm}m"
    d["boot_time"]   = boot.strftime("%Y-%m-%d %H:%M:%S")
    d["timestamp"]   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        d["users"] = len(psutil.users())
    except Exception:
        d["users"] = 0
    try:
        d["load_avg"] = list(psutil.getloadavg())
    except (AttributeError, OSError):
        d["load_avg"] = None
    try:
        bat = psutil.sensors_battery()
        if bat:
            d["battery_pct"]     = round(bat.percent, 1)
            d["battery_plugged"] = bat.power_plugged
            d["battery_secs"]    = bat.secsleft
    except (AttributeError, NotImplementedError):
        pass

    return d


class Collector(threading.Thread):
    """Single background thread — collects data once, shared by HTTP + widget."""

    def __init__(self):
        super().__init__(daemon=True)
        self._lock  = threading.Lock()
        self._data  = {}
        self._alive = True
        # warm-up so first reading is non-zero
        psutil.cpu_percent(interval=0.5)
        psutil.cpu_percent(percpu=True, interval=None)

    def snap(self):
        with self._lock:
            return dict(self._data)

    def stop(self):
        self._alive = False

    def run(self):
        while self._alive:
            try:
                d = collect()
                with self._lock:
                    self._data = d
            except Exception:
                pass
            time.sleep(DATA_COLLECT_S)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — HTTP agent server
# ══════════════════════════════════════════════════════════════════════════════

class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler — reads from shared Collector, no extra psutil."""

    collector = None   # injected by AgentServer before serving

    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._json(code, {"error": msg})

    def _html(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        allow = CFG.get("allow_ips") or []
        return not allow or self.client_address[0] in allow

    def _key_ok(self, params):
        return (params.get("key") or [""])[0] == CFG["api_key"]

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if not self._allowed():
            self._err(403, "IP not in allowlist"); return
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path.rstrip("/")

        if path in ("", "/"):
            self._html(200, self._landing_page())
            return

        if path == "/health":
            self._json(200, {"ok": True, "hostname": platform.node(),
                              "agent": VERSION})
            return

        if path == "/status":
            # Quick human-readable status page (no key needed)
            self._html(200, self._status_page())
            return

        if path == "/info":
            if not self._key_ok(params):
                self._err(401, "Invalid or missing API key"); return
            data = _Handler.collector.snap() if _Handler.collector else {}
            self._json(200, data or {"error": "Data not ready yet, retry in 2s"})
            return

        self._err(404, "Unknown path. Try / or /health or /status")

    # ── HTML page builders ────────────────────────────────────────────────────
    def _bar_html(self, pct, color):
        pct = max(0, min(float(pct), 100))
        return (
            f'<div style="background:#1e293b;border-radius:4px;height:18px;'
            f'overflow:hidden;margin:4px 0;position:relative;">'
            f'<div style="background:{color};width:{pct:.1f}%;height:100%;"></div>'
            f'<span style="position:absolute;inset:0;display:flex;align-items:center;'
            f'justify-content:center;font-size:11px;font-weight:700;color:#e2e8f0;">'
            f'{pct:.1f}%</span></div>'
        )

    def _pct_color(self, p):
        if p < 60: return "#22c55e"
        if p < 80: return "#eab308"
        return "#ef4444"

    def _landing_page(self):
        d = (_Handler.collector.snap() if _Handler.collector else {}) or {}
        host    = d.get("hostname", platform.node())
        os_str  = d.get("os", f"{platform.system()} {platform.release()}")
        uptime  = d.get("uptime_str", "—")
        cpu     = d.get("cpu_pct", 0)
        ram     = d.get("ram_pct", 0)
        vols    = d.get("volumes", [])
        port    = CFG["port"]
        ts      = d.get("timestamp", "—")

        # Build disk rows
        disk_rows = ""
        for v in vols:
            disk_rows += (
                f'<tr><td style="color:#94a3b8;padding:4px 8px;">'
                f'{v["label"]}</td>'
                f'<td style="padding:4px 8px;">'
                f'{self._bar_html(v["used_pct"], self._pct_color(v["used_pct"]))}</td>'
                f'<td style="color:#94a3b8;padding:4px 8px;white-space:nowrap;">'
                f'{v["free_gb"]} GB free / {v["total_gb"]} GB</td></tr>'
            )

        return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>REGTeches NOC Local — {host}</title>
<style>
* {{margin:0;padding:0;box-sizing:border-box;}}
body {{font-family:'Segoe UI',sans-serif;background:#0a0f1a;color:#e2e8f0;padding:24px;}}
h1   {{color:#3b82f6;font-size:1.3rem;letter-spacing:1px;}}
h2   {{color:#3b82f6;font-size:0.9rem;margin:20px 0 8px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #1e293b;padding-bottom:4px;}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:16px 20px;margin-bottom:16px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:16px;}}
.stat{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;}}
.stat-val{{font-size:1.4rem;font-weight:700;}}
.stat-lbl{{font-size:0.65rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-top:3px;}}
table{{width:100%;border-collapse:collapse;font-size:0.82rem;}}
td,th{{padding:5px 8px;text-align:left;}}
th{{color:#94a3b8;font-size:0.7rem;text-transform:uppercase;}}
code{{background:#1e293b;padding:2px 8px;border-radius:4px;font-family:Consolas,monospace;color:#38bdf8;font-size:0.82rem;}}
a    {{color:#3b82f6;text-decoration:none;}}
a:hover{{text-decoration:underline;}}
.ok  {{color:#22c55e;}} .dim {{color:#94a3b8;}}
footer{{margin-top:24px;font-size:0.7rem;color:#475569;text-align:center;}}
</style>
</head><body>

<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">
  <span style="font-size:2rem;">📡</span>
  <div>
    <h1>REGTeches NOC Local &nbsp;<span style="font-size:0.75rem;color:#475569;">v{VERSION}</span></h1>
    <div style="color:#94a3b8;font-size:0.8rem;">{host} &nbsp;·&nbsp; {os_str}</div>
  </div>
  <div style="margin-left:auto;font-size:0.75rem;color:#475569;">
    Auto-refreshes every 10s &nbsp;·&nbsp; {ts}
  </div>
</div>

<div class="grid">
  <div class="stat">
    <div class="stat-val" style="color:{self._pct_color(cpu)};">{cpu:.1f}%</div>
    <div class="stat-lbl">CPU Usage</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:{self._pct_color(ram)};">{ram:.1f}%</div>
    <div class="stat-lbl">RAM Used</div>
  </div>
  <div class="stat">
    <div class="stat-val ok">{uptime}</div>
    <div class="stat-lbl">Uptime</div>
  </div>
  <div class="stat">
    <div class="stat-val ok">Online</div>
    <div class="stat-lbl">Agent Status</div>
  </div>
</div>

<div class="card">
  <h2>CPU &amp; RAM</h2>
  <table><tr><td style="width:80px;color:#94a3b8;">CPU</td>
    <td>{self._bar_html(cpu, self._pct_color(cpu))}</td></tr>
  <tr><td style="color:#94a3b8;">RAM</td>
    <td>{self._bar_html(ram, self._pct_color(ram))}</td></tr>
  </table>
</div>

<div class="card">
  <h2>Storage</h2>
  <table><thead><tr><th>Drive</th><th>Usage</th><th>Space</th></tr></thead>
  <tbody>{disk_rows or '<tr><td colspan="3" class="dim">No disk data yet</td></tr>'}</tbody>
  </table>
</div>

<div class="card">
  <h2>API Endpoints</h2>
  <table>
    <tr><td style="width:100px;color:#94a3b8;">GET</td>
        <td><a href="/health"><code>/health</code></a></td>
        <td class="dim">Status check — no key needed</td></tr>
    <tr><td style="color:#94a3b8;">GET</td>
        <td><a href="/status"><code>/status</code></a></td>
        <td class="dim">This page</td></tr>
    <tr><td style="color:#94a3b8;">GET</td>
        <td><code>/info?key=YOUR_KEY</code></td>
        <td class="dim">Full JSON system data</td></tr>
    <tr><td style="color:#94a3b8;">POST</td>
        <td><code>/power?key=YOUR_KEY</code></td>
        <td class="dim">Power control (reboot / shutdown / lock…)</td></tr>
  </table>
</div>

<div class="card">
  <h2>NOC Dashboard Setup</h2>
  <table>
    <tr><td style="width:120px;color:#94a3b8;">Tag</td>
        <td><code>noc-agent</code></td></tr>
    <tr><td style="color:#94a3b8;">API Key</td>
        <td><code>{CFG["api_key"][:8]}…</code>
            <span class="dim"> (see console or noc_agent_settings.json)</span></td></tr>
    <tr><td style="color:#94a3b8;">Port</td>
        <td><code>{port}</code></td></tr>
  </table>
</div>

<footer>{COPYRIGHT} &nbsp;·&nbsp; {AUTHOR} &nbsp;·&nbsp; noc_local.py v{VERSION}</footer>
</body></html>"""

    def _status_page(self):
        """Alias for landing page — same content."""
        return self._landing_page()

    def do_POST(self):
        if not self._allowed():
            self._err(403, "IP not in allowlist"); return
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path.rstrip("/")
        if not self._key_ok(params):
            self._err(401, "Invalid or missing API key"); return
        if path == "/power":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            self._power(body.get("action", "").lower())
            return
        self._err(404, "Unknown POST endpoint")

    def _power(self, action):
        sys = platform.system()
        try:
            if action == "reboot":
                if sys == "Windows":
                    subprocess.Popen(["shutdown","/r","/t","10",
                                      "/c","Remote reboot — REGTeches NOC"])
                else:
                    subprocess.Popen(["shutdown","-r","+1"])
                self._json(200, {"ok":True,"msg":"Reboot in 10s — shutdown /a to cancel"})

            elif action == "shutdown":
                if sys == "Windows":
                    subprocess.Popen(["shutdown","/s","/t","10",
                                      "/c","Remote shutdown — REGTeches NOC"])
                else:
                    subprocess.Popen(["shutdown","-h","+1"])
                self._json(200, {"ok":True,"msg":"Shutdown in 10s — shutdown /a to cancel"})

            elif action == "cancel":
                subprocess.Popen(["shutdown","/a"] if sys=="Windows"
                                  else ["shutdown","-c"])
                self._json(200, {"ok":True,"msg":"Pending shutdown/reboot cancelled"})

            elif action == "lock":
                if sys == "Windows":
                    subprocess.Popen(["rundll32.exe","user32.dll,LockWorkStation"])
                else:
                    for cmd in (["gnome-screensaver-command","--lock"],
                                ["loginctl","lock-session"],
                                ["xdg-screensaver","lock"]):
                        try: subprocess.Popen(cmd); break
                        except FileNotFoundError: pass
                self._json(200, {"ok":True,"msg":"Screen locked"})

            elif action == "sleep":
                if sys == "Windows":
                    subprocess.Popen(["rundll32.exe",
                                      "powrprof.dll,SetSuspendState","0,1,0"])
                else:
                    subprocess.Popen(["systemctl","suspend"])
                self._json(200, {"ok":True,"msg":"Sleep command sent"})

            elif action == "hibernate":
                if sys == "Windows":
                    subprocess.Popen(["shutdown","/h"])
                else:
                    subprocess.Popen(["systemctl","hibernate"])
                self._json(200, {"ok":True,"msg":"Hibernate command sent"})

            elif action == "logoff":
                if sys == "Windows":
                    subprocess.Popen(["shutdown","/l"])
                    self._json(200, {"ok":True,"msg":"Log off command sent"})
                else:
                    self._err(400,"Logoff not supported on Linux")
            else:
                self._err(400, f"Unknown action '{action}'. "
                               "Use: reboot shutdown cancel lock sleep "
                               "hibernate logoff")
        except Exception as e:
            self._err(500, str(e))


class AgentServer(threading.Thread):
    """Wraps HTTPServer so it runs in a daemon thread."""

    def __init__(self, collector: Collector):
        super().__init__(daemon=True)
        _Handler.collector = collector
        self._server = HTTPServer((CFG["host"], CFG["port"]), _Handler)

    def run(self):
        self._server.serve_forever()

    def stop(self):
        self._server.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Desktop widget + detail window  (tkinter)
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def _pct_clr(p):
    if p < 60: return GREEN
    if p < 80: return YELLOW
    return RED


def _make_scroll_frame(parent):
    outer  = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
    vsb    = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    inner  = tk.Frame(canvas, bg=BG)
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)

    def _scroll(ev):
        canvas.yview_scroll(-1 if (ev.num == 4 or ev.delta > 0) else 1, "units")

    canvas.bind("<MouseWheel>", _scroll)
    canvas.bind("<Button-4>",   _scroll)
    canvas.bind("<Button-5>",   _scroll)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    return inner


class Bar(tk.Canvas):
    def __init__(self, parent, w=220, h=16, bg=CARD, **kw):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, **kw)
        self._bw = w   # NOTE: never use _w/_h — those are tkinter internals
        self._bh = h

    def draw(self, pct: float, clr=None):
        self.delete("all")
        self.create_rectangle(0, 0, self._bw, self._bh, fill=BORDER, outline="")
        pct = max(0.0, min(float(pct), 100.0))
        if pct > 0:
            self.create_rectangle(0, 0, max(2, int(self._bw * pct / 100)),
                                  self._bh, fill=(clr or _pct_clr(pct)), outline="")
        self.create_text(self._bw // 2, self._bh // 2,
                         text=f"{pct:.1f}%", fill=TEXT, font=F_SB)


# ── Compact floating widget ───────────────────────────────────────────────────
class Widget(tk.Tk):
    """Small always-on-top window — shows live CPU/MEM/DISK, opens details."""

    def __init__(self, on_details):
        super().__init__()
        self._on_details = on_details
        self.title("REGTeches NOC Local")
        self.configure(bg=CARD)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"+{sw - 320}+{sh - 265}")
        self._build()
        self.bind("<Double-Button-1>", lambda e: self._on_details())

    def _build(self):
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")

        hdr = tk.Frame(self, bg=HDR)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  REGTeches NOC Local",
                 bg=HDR, fg=ACCENT, font=F_BOLD, pady=6).pack(side="left")
        tk.Label(hdr, text=f"v{VERSION}  ", bg=HDR, fg=DIM,
                 font=F_SMALL).pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=CARD, padx=12, pady=10)
        body.pack(fill="x")
        self._b_cpu  = self._bar_row(body, "CPU ")
        self._b_mem  = self._bar_row(body, "MEM ")
        self._b_disk = self._bar_row(body, "DISK")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        self._status = tk.Label(self, text="Starting…",
                                bg=CARD, fg=DIM, font=F_SMALL, pady=4)
        self._status.pack(fill="x", padx=12)

        bf = tk.Frame(self, bg=CARD, pady=8)
        bf.pack(fill="x", padx=12)
        btn = tk.Label(bf, text="  Open Full System Details  >>",
                       bg=ACCENT, fg=TEXT, font=F_BOLD,
                       cursor="hand2", pady=7)
        btn.pack(fill="x")
        btn.bind("<Button-1>",        lambda e: self._on_details())
        btn.bind("<Double-Button-1>", lambda e: self._on_details())

    def _bar_row(self, parent, label):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg=CARD, fg=DIM,
                 font=F_SMALL, width=5, anchor="w").pack(side="left")
        bar = Bar(row, w=205, h=16, bg=CARD)
        bar.pack(side="left", padx=(4, 0))
        return bar

    def update_stats(self, cpu, mem, disk, host, port):
        self._b_cpu.draw(cpu)
        self._b_mem.draw(mem)
        self._b_disk.draw(disk)
        ts = datetime.now().strftime("%H:%M:%S")
        self._status.config(
            text=f"  {host}  |  :{port}  |  {ts}")


# ── Full detail window ────────────────────────────────────────────────────────
class DetailWin(tk.Toplevel):
    """Six-tab full system info window."""

    def __init__(self, master):
        super().__init__(master)
        self.title("REGTeches NOC Local  --  Full Details")
        self.configure(bg=BG)
        self.geometry("990x720")
        self.minsize(720, 520)
        self._sort_cpu = True
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 990) // 2
        y = (self.winfo_screenheight() - 720) // 2
        self.geometry(f"990x720+{x}+{y}")
        self._apply_styles()
        self._build()

    def _apply_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook", background=BG,
                    borderwidth=0, tabmargins=[0, 0, 0, 0])
        s.configure("TNotebook.Tab", background=CARD, foreground=DIM,
                    padding=[14, 7], font=F_UI, borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", BORDER), ("active", CARD2)],
              foreground=[("selected", TEXT),   ("active", TEXT)])
        s.configure("Treeview", background=CARD, foreground=TEXT,
                    fieldbackground=CARD, rowheight=26,
                    font=F_MONO, borderwidth=0, relief="flat")
        s.configure("Treeview.Heading", background=BORDER, foreground=TEXT,
                    font=F_BOLD, relief="flat", borderwidth=0)
        s.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", TEXT)])
        s.configure("Vertical.TScrollbar", background=BORDER,
                    troughcolor=BG, arrowcolor=DIM, borderwidth=0)

    def _build(self):
        hdr = tk.Frame(self, bg=HDR)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  REGTeches NOC Local  --  System Details",
                 bg=HDR, fg=ACCENT, font=F_TITLE, padx=14, pady=8).pack(side="left")
        self._hdr_info = tk.Label(hdr, text="", bg=HDR, fg=DIM,
                                  font=F_UI, padx=14)
        self._hdr_info.pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self._t_cpu  = self._tab("  CPU")
        self._t_mem  = self._tab("  Memory")
        self._t_disk = self._tab("  Disks")
        self._t_proc = self._tab("  Processes")
        self._t_net  = self._tab("  Network")
        self._t_sys  = self._tab("  System")
        self._build_proc_tab()

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", side="bottom")
        self._footer = tk.Label(self, text="", bg=HDR, fg=DIM,
                                font=F_SMALL, pady=4)
        self._footer.pack(side="bottom", fill="x")
        self.bind("<Escape>", lambda e: self.destroy())

    def _tab(self, title):
        f = tk.Frame(self.nb, bg=BG)
        self.nb.add(f, text=title)
        return _make_scroll_frame(f)

    # ── section helpers ───────────────────────────────────────────────────────
    def _sec(self, p, title):
        f = tk.Frame(p, bg=BG)
        f.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(f, text=title, bg=BG, fg=ACCENT, font=F_HEAD).pack(side="left")
        tk.Frame(f, bg=BORDER, height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=7)

    def _kv(self, p, key, val, vc=None):
        row = tk.Frame(p, bg=CARD)
        row.pack(fill="x", padx=16, pady=1)
        tk.Label(row, text=key, bg=CARD, fg=DIM, font=F_UI,
                 width=24, anchor="w").pack(side="left", padx=(10, 0), pady=4)
        tk.Label(row, text=str(val), bg=CARD, fg=vc or TEXT,
                 font=F_MONO).pack(side="left", padx=4)

    def _bar_row(self, p, label, pct, detail="", bw=340):
        row = tk.Frame(p, bg=CARD)
        row.pack(fill="x", padx=16, pady=2)
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=F_UI,
                 width=22, anchor="w").pack(side="left", padx=(10, 4), pady=6)
        b = Bar(row, w=bw, h=18, bg=CARD)
        b.draw(pct)
        b.pack(side="left")
        if detail:
            tk.Label(row, text=detail, bg=CARD, fg=DIM,
                     font=F_SMALL).pack(side="left", padx=6)

    def _clr(self, tab):
        for w in tab.winfo_children():
            w.destroy()

    # ── CPU tab ───────────────────────────────────────────────────────────────
    def _show_cpu(self, d):
        self._clr(self._t_cpu)
        info = d.get("cpu_info") or d   # accept both old & new format
        self._sec(self._t_cpu, "Overview")
        self._bar_row(self._t_cpu, "Overall CPU Usage", d.get("cpu_pct", 0))
        self._kv(self._t_cpu, "Processor",
                 d.get("cpu_name") or info.get("name", "?"))
        self._kv(self._t_cpu, "Physical Cores",
                 d.get("cpu_cores_phys") or info.get("phys", "?"))
        self._kv(self._t_cpu, "Logical Cores",
                 d.get("cpu_cores_logi") or info.get("logi", "?"))
        fcur = d.get("cpu_freq_mhz", 0)
        if fcur:
            self._kv(self._t_cpu, "Current Freq", f"{fcur:,} MHz")
        fmax = d.get("cpu_freq_max", 0)
        if fmax:
            self._kv(self._t_cpu, "Max Freq",     f"{fmax:,} MHz")

        cores = d.get("cpu_per_core", [])
        if cores:
            self._sec(self._t_cpu, f"Per-Core  ({len(cores)} cores)")
            grid = tk.Frame(self._t_cpu, bg=BG)
            grid.pack(fill="x", padx=16, pady=4)
            for i, cp in enumerate(cores):
                col = i % 2
                cell = tk.Frame(grid, bg=CARD)
                cell.grid(row=i // 2, column=col,
                          padx=4, pady=2, sticky="ew")
                grid.columnconfigure(col, weight=1)
                tk.Label(cell, text=f"Core {i:2d}", bg=CARD, fg=DIM,
                         font=F_SMALL, width=7, anchor="w").pack(
                    side="left", padx=(8, 4), pady=4)
                b = Bar(cell, w=160, h=14, bg=CARD)
                b.draw(cp)
                b.pack(side="left")

        temps = d.get("cpu_temps", [])
        if temps:
            self._sec(self._t_cpu, "Temperatures")
            for t in temps:
                c = GREEN if t["cur"] < 60 else (YELLOW if t["cur"] < 80 else RED)
                self._kv(self._t_cpu, t["label"],
                         f"{t['cur']:.1f}C  (max {t['high']:.0f}C)", c)

    # ── Memory tab ────────────────────────────────────────────────────────────
    def _show_mem(self, d):
        self._clr(self._t_mem)
        self._sec(self._t_mem, "RAM")
        self._bar_row(self._t_mem, "RAM Used", d.get("ram_pct", 0),
                      f"{d.get('ram_used_gb','?')} GB / {d.get('ram_total_gb','?')} GB")
        self._kv(self._t_mem, "Total",     f"{d.get('ram_total_gb','?')} GB")
        self._kv(self._t_mem, "Used",      f"{d.get('ram_used_gb','?')} GB",
                 RED if (d.get("ram_pct", 0) > 85) else TEXT)
        self._kv(self._t_mem, "Available", f"{d.get('ram_free_gb','?')} GB", GREEN)
        if d.get("ram_cached_gb"):
            self._kv(self._t_mem, "Cached", f"{d['ram_cached_gb']} GB")

        self._sec(self._t_mem, "Swap / Page File")
        if (d.get("swap_total_gb") or 0) > 0:
            self._bar_row(self._t_mem, "Swap Used", d.get("swap_pct", 0),
                          f"{d.get('swap_used_gb','?')} GB / "
                          f"{d.get('swap_total_gb','?')} GB")
        else:
            self._kv(self._t_mem, "Swap", "Not configured / 0 bytes")

    # ── Disks tab ─────────────────────────────────────────────────────────────
    def _show_disks(self, d):
        self._clr(self._t_disk)
        for v in d.get("volumes", []):
            self._sec(self._t_disk,
                      f"  {v['device']}   >>   {v['label']}")
            self._bar_row(self._t_disk, "Used Space", v["used_pct"],
                          f"{v['used_gb']} GB  /  {v['total_gb']} GB  "
                          f"({v['free_gb']} GB free)")
            self._kv(self._t_disk, "File System", v.get("fstype", "?"))
            self._kv(self._t_disk, "Total",
                     f"{v['total_gb']} GB")
            self._kv(self._t_disk, "Used",
                     f"{v['used_gb']} GB",
                     RED if v["used_pct"] > 85 else TEXT)
            self._kv(self._t_disk, "Free",
                     f"{v['free_gb']} GB", GREEN)

        if d.get("disk_read_gb") is not None:
            self._sec(self._t_disk, "Disk I/O  (since boot)")
            self._kv(self._t_disk, "Total Read",
                     f"{d['disk_read_gb']} GB")
            self._kv(self._t_disk, "Total Written",
                     f"{d['disk_write_gb']} GB")

    # ── Processes tab ─────────────────────────────────────────────────────────
    def _build_proc_tab(self):
        hdr = tk.Frame(self._t_proc, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(hdr, text="Top Processes", bg=BG, fg=ACCENT,
                 font=F_HEAD).pack(side="left")
        self._proc_lbl = tk.Label(hdr, text="", bg=BG, fg=DIM, font=F_SMALL)
        self._proc_lbl.pack(side="right")

        sf = tk.Frame(self._t_proc, bg=BG)
        sf.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(sf, text="Sort:", bg=BG, fg=DIM, font=F_SMALL).pack(side="left")
        self._sb_c = tk.Label(sf, text=" CPU% ", bg=ACCENT, fg=TEXT,
                              font=F_SB, cursor="hand2", padx=4, pady=2)
        self._sb_c.pack(side="left", padx=4)
        self._sb_c.bind("<Button-1>", lambda e: self._sort("cpu"))
        self._sb_m = tk.Label(sf, text=" MEM% ", bg=BORDER, fg=DIM,
                              font=F_SB, cursor="hand2", padx=4, pady=2)
        self._sb_m.pack(side="left")
        self._sb_m.bind("<Button-1>", lambda e: self._sort("mem"))

        tf = tk.Frame(self._t_proc, bg=BG)
        tf.pack(fill="both", expand=True, padx=16, pady=4)
        cols = ("pid", "name", "cpu", "mem", "rss", "status", "user")
        self._tree = ttk.Treeview(tf, columns=cols, show="headings", height=22)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        for cid, head, w, anc in [
            ("pid",    "PID",     60,  "e"),
            ("name",   "Process", 210, "w"),
            ("cpu",    "CPU %",    70, "e"),
            ("mem",    "MEM %",    70, "e"),
            ("rss",    "Memory",   90, "e"),
            ("status", "Status",   80, "w"),
            ("user",   "User",    130, "w"),
        ]:
            self._tree.heading(cid, text=head,
                               command=lambda c=cid: self._tree_col(c))
            self._tree.column(cid, width=w, anchor=anc, stretch=False)
        self._tree.tag_configure("even",    background=CARD)
        self._tree.tag_configure("odd",     background=CARD2)
        self._tree.tag_configure("hi_cpu",  foreground=RED)
        self._tree.tag_configure("med_cpu", foreground=YELLOW)
        self._tree.tag_configure("hi_mem",  foreground=ORANGE)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        menu = tk.Menu(self._tree, tearoff=0, bg=CARD, fg=TEXT,
                       activebackground=ACCENT)
        menu.add_command(label="Copy PID",  command=self._cp_pid)
        menu.add_command(label="Copy Name", command=self._cp_name)
        if platform.system() == "Windows":
            menu.add_separator()
            menu.add_command(label="Open Task Manager",
                             command=lambda: os.startfile("taskmgr"))
        self._tree.bind("<Button-3>",
                        lambda e: (self._tree.selection_set(
                            self._tree.identify_row(e.y)),
                            menu.post(e.x_root, e.y_root)))
        self._proc_data = []

    def _sort(self, by):
        self._sort_cpu = (by == "cpu")
        self._sb_c.config(bg=ACCENT if self._sort_cpu else BORDER,
                          fg=TEXT   if self._sort_cpu else DIM)
        self._sb_m.config(bg=ACCENT if not self._sort_cpu else BORDER,
                          fg=TEXT   if not self._sort_cpu else DIM)
        self._refresh_tree()

    def _tree_col(self, col):
        self._sort("cpu" if col == "cpu" else "mem")

    def _refresh_tree(self):
        key = "cpu_pct" if self._sort_cpu else "mem_pct"
        procs = sorted(self._proc_data, key=lambda x: x.get(key, 0), reverse=True)
        self._tree.delete(*self._tree.get_children())
        for i, p in enumerate(procs):
            tags = ["even" if i % 2 == 0 else "odd"]
            cpu = p.get("cpu_pct", 0)
            if cpu > 50:   tags.append("hi_cpu")
            elif cpu > 20: tags.append("med_cpu")
            if p.get("mem_pct", 0) > 20: tags.append("hi_mem")
            self._tree.insert("", "end", iid=str(p.get("pid", i)),
                              tags=tags, values=(
                                  p.get("pid", ""),
                                  p.get("name", "?"),
                                  f"{cpu:.1f}%",
                                  f"{p.get('mem_pct',0):.1f}%",
                                  _fmt_bytes(p.get("mem_mb", 0) * 1024**2).strip(),
                                  p.get("status", ""),
                                  p.get("user", ""),
                              ))

    def _cp_pid(self):
        s = self._tree.selection()
        if s:
            self.clipboard_clear()
            self.clipboard_append(self._tree.item(s[0], "values")[0])

    def _cp_name(self):
        s = self._tree.selection()
        if s:
            self.clipboard_clear()
            self.clipboard_append(self._tree.item(s[0], "values")[1])

    def _show_proc(self, d):
        self._proc_data = d.get("processes", [])
        n = d.get("proc_count", 0)
        self._proc_lbl.config(
            text=f"Showing {len(self._proc_data)} of {n} total")
        self._refresh_tree()

    # ── Network tab ───────────────────────────────────────────────────────────
    def _show_net(self, d):
        self._clr(self._t_net)
        self._sec(self._t_net, "Network Interfaces")
        for iface in d.get("net_ifaces", []):
            self._kv(self._t_net, f"{iface['name']}  IPv4", iface["ipv4"])
            if iface.get("mask"):
                self._kv(self._t_net, f"{iface['name']}  Netmask", iface["mask"])
        nio = d.get("net_io") or d
        sent = d.get("net_sent_gb")
        recv = d.get("net_recv_gb")
        if sent is not None:
            self._sec(self._t_net, "I/O Statistics  (since boot)")
            self._kv(self._t_net, "Bytes Sent",     f"{sent} GB")
            self._kv(self._t_net, "Bytes Received", f"{recv} GB")

    # ── System tab ────────────────────────────────────────────────────────────
    def _show_sys(self, d):
        self._clr(self._t_sys)
        self._sec(self._t_sys, "Machine")
        self._kv(self._t_sys, "Hostname",  d.get("hostname", "?"))
        self._kv(self._t_sys, "OS",        d.get("os",       "?"))
        self._kv(self._t_sys, "Version",   d.get("os_version","?"))
        self._kv(self._t_sys, "Architecture", d.get("arch",  "?"))

        self._sec(self._t_sys, "Uptime")
        self._kv(self._t_sys, "Uptime",    d.get("uptime_str","?"), GREEN)
        self._kv(self._t_sys, "Boot Time", d.get("boot_time", "?"))
        self._kv(self._t_sys, "Users In",  str(d.get("users", 0)))

        load = d.get("load_avg")
        if load:
            self._sec(self._t_sys, "Load Average  (Linux)")
            self._kv(self._t_sys, " 1 min", f"{load[0]:.2f}")
            self._kv(self._t_sys, " 5 min", f"{load[1]:.2f}")
            self._kv(self._t_sys, "15 min", f"{load[2]:.2f}")

        bat_pct = d.get("battery_pct")
        if bat_pct is not None:
            self._sec(self._t_sys, "Battery")
            clr = GREEN if bat_pct > 40 else (YELLOW if bat_pct > 20 else RED)
            plug = d.get("battery_plugged", False)
            self._bar_row(self._t_sys, "Charge", bat_pct,
                          "Charging" if plug else "On battery", bw=280)
            if not plug:
                secs = d.get("battery_secs", 0) or 0
                if secs > 0:
                    hh, r = divmod(int(secs), 3600)
                    mm, _ = divmod(r, 60)
                    self._kv(self._t_sys, "Time Remaining",
                             f"{hh}h {mm}m", clr)

        self._sec(self._t_sys, "About")
        self._kv(self._t_sys, "Script",    "noc_local.py")
        self._kv(self._t_sys, "Version",   VERSION)
        self._kv(self._t_sys, "HTTP port", str(CFG["port"]))
        self._kv(self._t_sys, "Author",    AUTHOR)
        self._kv(self._t_sys, "Copyright", COPYRIGHT)

    # ── Master refresh (called on the main tkinter thread) ────────────────────
    def refresh(self, data: dict):
        if not data:
            return
        self._hdr_info.config(
            text=f"  {data.get('hostname','?')}  |  "
                 f"{data.get('os','')}  ")

        tab = self.nb.index(self.nb.select())
        self._show_proc(data)          # process tree is cheap to update
        if tab == 0:   self._show_cpu(data)
        elif tab == 1: self._show_mem(data)
        elif tab == 2: self._show_disks(data)
        elif tab == 4: self._show_net(data)
        elif tab == 5: self._show_sys(data)

        self.nb.bind("<<NotebookTabChanged>>",
                     lambda e: self._on_tab(data))
        ts = datetime.now().strftime("%H:%M:%S")
        self._footer.config(
            text=f"  {COPYRIGHT}  |  {AUTHOR}  |  v{VERSION}  "
                 f"|  HTTP :{CFG['port']}  |  {ts}  ")

    def _on_tab(self, data):
        t = self.nb.index(self.nb.select())
        if t == 0:   self._show_cpu(data)
        elif t == 1: self._show_mem(data)
        elif t == 2: self._show_disks(data)
        elif t == 4: self._show_net(data)
        elif t == 5: self._show_sys(data)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — App controller  (ties everything together)
# ══════════════════════════════════════════════════════════════════════════════

class App:
    def __init__(self):
        self.collector  = Collector()
        self.collector.start()

        self.http       = AgentServer(self.collector)
        self.http.start()

        self.detail_win = None
        self.widget     = Widget(self._open_detail)
        self._tick()    # start the UI refresh loop

    def _open_detail(self):
        try:
            if self.detail_win and self.detail_win.winfo_exists():
                self.detail_win.lift()
                self.detail_win.focus_force()
                return
        except tk.TclError:
            pass
        self.detail_win = DetailWin(self.widget)
        data = self.collector.snap()
        if data:
            self.detail_win.refresh(data)

    def _tick(self):
        data = self.collector.snap()
        if data:
            cpu   = data.get("cpu_pct", 0)
            mem   = data.get("ram_pct", 0)
            vols  = data.get("volumes", [])
            disk  = (sum(v["used_pct"] for v in vols) / len(vols)) if vols else 0
            host  = data.get("hostname", "localhost")
            try:
                self.widget.update_stats(cpu, mem, disk, host, CFG["port"])
            except tk.TclError:
                pass
            try:
                if self.detail_win and self.detail_win.winfo_exists():
                    self.detail_win.refresh(data)
            except tk.TclError:
                self.detail_win = None
        self.widget.after(UI_REFRESH_MS, self._tick)

    def run(self):
        try:
            self.widget.mainloop()
        finally:
            self.collector.stop()
            self.http.stop()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # Crisp rendering on Windows HiDPI screens
    if platform.system() == "Windows":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    # Resolve display IP for the startup banner
    try:
        display_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        display_ip = "127.0.0.1"

    print("=" * 58)
    print(f"  REGTeches NOC Local  v{VERSION}")
    print("=" * 58)
    print(f"  Host    : {platform.node()}  ({display_ip})")
    print(f"  HTTP    : http://{display_ip}:{CFG['port']}")
    print()
    print(f"  API KEY : {CFG['api_key']}")
    print()
    print("  NOC Dashboard setup:")
    print(f"    Tag     : noc-agent")
    print(f"    API Key : (key above)")
    print(f"    Port    : {CFG['port']}")
    print()
    print("  Endpoints:")
    print(f"    http://{display_ip}:{CFG['port']}/health")
    print(f"    http://{display_ip}:{CFG['port']}/info?key=...")
    print()
    print("  Desktop widget is opening...")
    print("=" * 58)

    App().run()


if __name__ == "__main__":
    main()
