"""
REGTeches NOC Agent  v1.0.0
Lightweight system-info agent — runs on any Windows or Linux PC.
Exposes psutil data over HTTP so the NOC dashboard can display
CPU, RAM, disks, processes, and network info for that machine.

─────────────────────────────────────────────────────────────────
QUICK START
─────────────────────────────────────────────────────────────────
1.  pip install psutil
2.  python noc_agent.py
    → first run auto-generates noc_agent_settings.json with a
      random API key and prints the key to the console.
3.  In the NOC dashboard, edit the PC server card:
      • Add tag:  noc-agent
      • API Key:  (paste the key printed by step 2)
      • Port:     9182  (or whatever you set in settings)
    Enable the 📊 System Info toggle and save.
4.  Click 📊 Info on the card — done.

─────────────────────────────────────────────────────────────────
WINDOWS: AUTO-START ON LOGIN (no admin needed)
─────────────────────────────────────────────────────────────────
Create a shortcut to:
  pythonw  C:\\path\\to\\noc_agent.py
and drop it in:
  shell:startup   (Win+R → shell:startup)

─────────────────────────────────────────────────────────────────
WINDOWS: RUN AS A SERVICE (requires NSSM)
─────────────────────────────────────────────────────────────────
nssm install NOCAgent  python  C:\\path\\to\\noc_agent.py
nssm start NOCAgent

─────────────────────────────────────────────────────────────────
LINUX: SYSTEMD SERVICE
─────────────────────────────────────────────────────────────────
[Unit]  Description=REGTeches NOC Agent
[Service]
  ExecStart=/usr/bin/python3 /opt/noc_agent/noc_agent.py
  Restart=always
[Install]  WantedBy=multi-user.target

─────────────────────────────────────────────────────────────────
API ENDPOINTS  (no Flask needed — pure stdlib + psutil)
─────────────────────────────────────────────────────────────────
GET /health                    → {"ok": true}  (no key needed)
GET /info?key=YOUR_KEY         → full system info JSON
"""

import os
import sys
import json
import time
import platform
import threading
import secrets
import socket
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    import psutil
except ImportError:
    import subprocess
    print("Installing psutil...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
    import psutil

# ── Config ────────────────────────────────────────────────────────────────────
AGENT_VERSION = "1.0.0"
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "noc_agent_settings.json")

DEFAULT_SETTINGS = {
    "api_key":      "",          # auto-generated on first run
    "port":         9182,
    "host":         "0.0.0.0",
    "top_procs":    25,
    "allow_ips":    [],          # empty = allow all; e.g. ["192.168.1.1","192.168.1.5"]
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            cfg = {**DEFAULT_SETTINGS, **stored}
            # auto-generate key if missing or blank
            if not cfg.get("api_key"):
                cfg["api_key"] = secrets.token_hex(20)
                save_settings(cfg)
            return cfg
        except Exception:
            pass
    # First run — generate and save
    cfg = dict(DEFAULT_SETTINGS)
    cfg["api_key"] = secrets.token_hex(20)
    save_settings(cfg)
    return cfg


def save_settings(cfg):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


CFG = load_settings()


# ── psutil helpers ────────────────────────────────────────────────────────────
def _get_cpu_name():
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


def _fmt_gb(b):
    return round(b / (1024 ** 3), 2)


def collect_info():
    """Return a dict of system metrics compatible with the NOC dashboard."""
    d = {"type": "noc-agent", "agent_version": AGENT_VERSION}

    # ── CPU ──────────────────────────────────────────────────────────────────
    d["cpu_pct"]       = psutil.cpu_percent(interval=0.3)
    d["cpu_per_core"]  = psutil.cpu_percent(percpu=True)
    freq = psutil.cpu_freq()
    d["cpu_name"]      = _get_cpu_name()
    d["cpu_cores_phys"]= psutil.cpu_count(logical=False) or 0
    d["cpu_cores_logi"]= psutil.cpu_count(logical=True)  or 0
    d["cpu_freq_mhz"]  = round(freq.current) if freq else 0
    d["cpu_freq_max"]  = round(freq.max)      if freq else 0

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

    # ── Memory ───────────────────────────────────────────────────────────────
    m  = psutil.virtual_memory()
    sw = psutil.swap_memory()
    d["ram_pct"]     = m.percent
    d["ram_total_gb"]= _fmt_gb(m.total)
    d["ram_used_gb"] = _fmt_gb(m.used)
    d["ram_free_gb"] = _fmt_gb(m.available)
    d["ram_cached_gb"]  = _fmt_gb(getattr(m, "cached",  0))
    d["swap_pct"]    = sw.percent
    d["swap_total_gb"]= _fmt_gb(sw.total)
    d["swap_used_gb"] = _fmt_gb(sw.used)

    # ── Disks ────────────────────────────────────────────────────────────────
    volumes = []
    for part in psutil.disk_partitions(all=False):
        if platform.system() == "Windows" and (
            "cdrom" in (part.opts or "") or part.fstype == ""
        ):
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
            volumes.append({
                "label":    part.mountpoint,
                "device":   part.device,
                "fstype":   part.fstype,
                "used_pct": round(u.percent, 1),
                "total_gb": _fmt_gb(u.total),
                "used_gb":  _fmt_gb(u.used),
                "free_gb":  _fmt_gb(u.free),
            })
        except (PermissionError, OSError):
            pass
    d["volumes"] = volumes

    try:
        io = psutil.disk_io_counters()
        d["disk_read_gb"]  = _fmt_gb(io.read_bytes)
        d["disk_write_gb"] = _fmt_gb(io.write_bytes)
    except Exception:
        pass

    # ── Processes ─────────────────────────────────────────────────────────────
    procs = []
    try:
        for p in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent",
             "status", "memory_info", "username"]
        ):
            try:
                mi = p.info.get("memory_info")
                procs.append({
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
    procs.sort(key=lambda x: x["cpu_pct"], reverse=True)
    d["processes"]   = procs[:CFG["top_procs"]]
    d["proc_count"]  = len(psutil.pids())

    # ── Network ──────────────────────────────────────────────────────────────
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
        d["net_sent_gb"] = _fmt_gb(nio.bytes_sent)
        d["net_recv_gb"] = _fmt_gb(nio.bytes_recv)
    except Exception:
        pass

    # ── System ───────────────────────────────────────────────────────────────
    boot = datetime.fromtimestamp(psutil.boot_time())
    up   = datetime.now() - boot
    hh, r = divmod(up.seconds, 3600)
    mm, _ = divmod(r, 60)
    d["hostname"]   = platform.node()
    d["os"]         = f"{platform.system()} {platform.release()}"
    d["os_version"] = platform.version()[:80]
    d["arch"]       = platform.machine()
    d["uptime_days"]= round(up.days + up.seconds / 86400, 2)
    d["uptime_str"] = f"{up.days}d {hh}h {mm}m"
    d["boot_time"]  = boot.strftime("%Y-%m-%d %H:%M:%S")
    d["timestamp"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
            d["battery_pct"]    = round(bat.percent, 1)
            d["battery_plugged"]= bat.power_plugged
            d["battery_secs"]   = bat.secsleft
    except (AttributeError, NotImplementedError):
        pass

    return d


# ── HTTP Request Handler ──────────────────────────────────────────────────────
class AgentHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass   # suppress default access log spam

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _send_json(self, code, obj):
        try:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type",   "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass  # client closed the connection — harmless

    def _send_html(self, code, html):
        try:
            body = html.encode()
            self.send_response(code)
            self.send_header("Content-Type",   "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def _send_error(self, code, msg):
        self._send_json(code, {"error": msg})

    def _check_allowed(self):
        if not CFG.get("allow_ips"):
            return True
        return self.client_address[0] in CFG["allow_ips"]

    def _check_key(self, params):
        return (params.get("key") or [""])[0] == CFG["api_key"]

    # ── GET ───────────────────────────────────────────────────────────────────
    def do_GET(self):
        if not self._check_allowed():
            self._send_error(403, "IP not in allowlist")
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path.rstrip("/")

        # Root and status — show HTML landing page
        if path in ("", "/", "/status"):
            self._send_html(200, self._landing_page())
            return

        # Favicon — return empty 204 to stop browser error spam
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if path == "/health":
            self._send_json(200, {
                "ok":       True,
                "hostname": platform.node(),
                "agent":    AGENT_VERSION,
            })
            return

        if path == "/info":
            if not self._check_key(params):
                self._send_error(401, "Invalid or missing API key")
                return
            try:
                data = collect_info()
                self._send_json(200, data)
            except Exception as e:
                self._send_error(500, str(e))
            return

        self._send_error(404, "Unknown path. Try / or /health or /info?key=KEY")

    # ── Landing page ──────────────────────────────────────────────────────────
    def _bar(self, pct):
        c = "#22c55e" if pct < 60 else ("#eab308" if pct < 80 else "#ef4444")
        return (
            f'<div style="background:#1e293b;border-radius:4px;height:18px;'
            f'overflow:hidden;position:relative;margin:4px 0;">'
            f'<div style="background:{c};width:{pct:.1f}%;height:100%;"></div>'
            f'<span style="position:absolute;inset:0;display:flex;align-items:center;'
            f'justify-content:center;font-size:11px;font-weight:700;color:#e2e8f0;">'
            f'{pct:.1f}%</span></div>'
        )

    def _landing_page(self):
        try:
            d = collect_info()
        except Exception:
            d = {}
        host   = d.get("hostname", platform.node())
        os_str = d.get("os", f"{platform.system()} {platform.release()}")
        uptime = d.get("uptime_str", "—")
        cpu    = d.get("cpu_pct", 0)
        ram    = d.get("ram_pct", 0)
        ts     = d.get("timestamp", "—")
        port   = CFG["port"]

        disk_rows = ""
        for v in d.get("volumes", []):
            c = "#22c55e" if v["used_pct"] < 60 else ("#eab308" if v["used_pct"] < 80 else "#ef4444")
            disk_rows += (
                f'<tr><td style="color:#94a3b8;padding:4px 8px;">{v["label"]}</td>'
                f'<td style="padding:4px 8px;">{self._bar(v["used_pct"])}</td>'
                f'<td style="color:#94a3b8;padding:4px 8px;white-space:nowrap;">'
                f'{v["free_gb"]} GB free / {v["total_gb"]} GB</td></tr>'
            )

        cpu_c = "#22c55e" if cpu < 60 else ("#eab308" if cpu < 80 else "#ef4444")
        ram_c = "#22c55e" if ram < 60 else ("#eab308" if ram < 80 else "#ef4444")

        return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>REGTeches NOC Agent — {host}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Segoe UI',sans-serif;background:#0a0f1a;color:#e2e8f0;padding:24px;}}
h1  {{color:#3b82f6;font-size:1.3rem;letter-spacing:1px;}}
h2  {{color:#3b82f6;font-size:0.85rem;margin:20px 0 8px;text-transform:uppercase;
      letter-spacing:1px;border-bottom:1px solid #1e293b;padding-bottom:4px;}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:10px;
       padding:16px 20px;margin-bottom:16px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
       gap:12px;margin-bottom:16px;}}
.stat{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
       padding:12px;text-align:center;}}
.sv  {{font-size:1.3rem;font-weight:700;}}
.sl  {{font-size:0.65rem;color:#94a3b8;text-transform:uppercase;
       letter-spacing:.05em;margin-top:3px;}}
table{{width:100%;border-collapse:collapse;font-size:0.82rem;}}
td,th{{padding:5px 8px;text-align:left;}}
th   {{color:#94a3b8;font-size:0.7rem;text-transform:uppercase;}}
code {{background:#1e293b;padding:2px 8px;border-radius:4px;
       font-family:Consolas,monospace;color:#38bdf8;font-size:0.82rem;}}
a    {{color:#3b82f6;text-decoration:none;}}
a:hover{{text-decoration:underline;}}
.dim {{color:#94a3b8;}}
footer{{margin-top:24px;font-size:0.7rem;color:#475569;text-align:center;}}
</style></head><body>

<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">
  <span style="font-size:2rem;">📡</span>
  <div>
    <h1>REGTeches NOC Agent &nbsp;<span style="font-size:0.75rem;color:#475569;">v{AGENT_VERSION}</span></h1>
    <div class="dim" style="font-size:0.8rem;">{host} &nbsp;·&nbsp; {os_str}</div>
  </div>
  <div style="margin-left:auto;font-size:0.75rem;color:#475569;">
    Auto-refreshes every 10s &nbsp;·&nbsp; {ts}
  </div>
</div>

<div class="grid">
  <div class="stat"><div class="sv" style="color:{cpu_c};">{cpu:.1f}%</div>
    <div class="sl">CPU Usage</div></div>
  <div class="stat"><div class="sv" style="color:{ram_c};">{ram:.1f}%</div>
    <div class="sl">RAM Used</div></div>
  <div class="stat"><div class="sv" style="color:#22c55e;">{uptime}</div>
    <div class="sl">Uptime</div></div>
  <div class="stat"><div class="sv" style="color:#22c55e;">Online</div>
    <div class="sl">Agent Status</div></div>
</div>

<div class="card">
  <h2>CPU &amp; RAM</h2>
  <table>
    <tr><td style="width:80px;" class="dim">CPU</td><td>{self._bar(cpu)}</td></tr>
    <tr><td class="dim">RAM</td><td>{self._bar(ram)}</td></tr>
  </table>
</div>

<div class="card">
  <h2>Storage</h2>
  <table><thead><tr><th>Drive</th><th>Usage</th><th>Space</th></tr></thead>
  <tbody>{disk_rows or '<tr><td colspan="3" class="dim" style="padding:8px;">Collecting data…</td></tr>'}</tbody>
  </table>
</div>

<div class="card">
  <h2>API Endpoints</h2>
  <table>
    <tr><td style="width:80px;" class="dim">GET</td>
        <td><a href="/health"><code>/health</code></a></td>
        <td class="dim">Status check — no key needed</td></tr>
    <tr><td class="dim">GET</td>
        <td><a href="/status"><code>/status</code></a></td>
        <td class="dim">This page</td></tr>
    <tr><td class="dim">GET</td>
        <td><code>/info?key=YOUR_KEY</code></td>
        <td class="dim">Full JSON system data</td></tr>
    <tr><td class="dim">POST</td>
        <td><code>/power?key=YOUR_KEY</code></td>
        <td class="dim">Power control (reboot / shutdown / lock…)</td></tr>
  </table>
</div>

<div class="card">
  <h2>NOC Dashboard Setup</h2>
  <table>
    <tr><td style="width:120px;" class="dim">Tag</td>
        <td><code>noc-agent</code></td></tr>
    <tr><td class="dim">API Key</td>
        <td><code>{CFG["api_key"][:8]}…</code>
            <span class="dim"> (see console or noc_agent_settings.json)</span></td></tr>
    <tr><td class="dim">Port</td>
        <td><code>{port}</code></td></tr>
  </table>
</div>

<footer>(c) 2026 REGTeches / Bay Area Tech &nbsp;·&nbsp; Ronald Goodchild
        &nbsp;·&nbsp; noc_agent.py v{AGENT_VERSION}</footer>
</body></html>"""

    def do_POST(self):
        if not self._check_allowed():
            self._send_error(403, "IP not in allowlist")
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path.rstrip("/")

        if not self._check_key(params):
            self._send_error(401, "Invalid or missing API key")
            return

        if path == "/power":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length) or b"{}") if length else {}
            action = body.get("action", "").lower()
            self._do_power(action)
            return

        self._send_error(404, "Unknown POST endpoint")

    def _do_power(self, action):
        """Execute a power action on the local machine."""
        import subprocess as _sp
        sys_name = platform.system()
        try:
            if action == "reboot":
                if sys_name == "Windows":
                    _sp.Popen(["shutdown", "/r", "/t", "10",
                               "/c", "Remote reboot by REGTeches NOC"])
                else:
                    _sp.Popen(["shutdown", "-r", "+1",
                               "Remote reboot by REGTeches NOC"])
                self._send_json(200, {"ok": True, "action": "reboot",
                                      "msg": "Reboot in 10s — shutdown /a to cancel"})

            elif action == "shutdown":
                if sys_name == "Windows":
                    _sp.Popen(["shutdown", "/s", "/t", "10",
                               "/c", "Remote shutdown by REGTeches NOC"])
                else:
                    _sp.Popen(["shutdown", "-h", "+1",
                               "Remote shutdown by REGTeches NOC"])
                self._send_json(200, {"ok": True, "action": "shutdown",
                                      "msg": "Shutdown in 10s — shutdown /a to cancel"})

            elif action == "cancel":
                if sys_name == "Windows":
                    _sp.Popen(["shutdown", "/a"])
                else:
                    _sp.Popen(["shutdown", "-c"])
                self._send_json(200, {"ok": True, "action": "cancel",
                                      "msg": "Pending shutdown/reboot cancelled"})

            elif action == "lock":
                if sys_name == "Windows":
                    _sp.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
                    self._send_json(200, {"ok": True, "action": "lock",
                                          "msg": "Screen locked"})
                else:
                    # Try common Linux screen lockers
                    for cmd in (["gnome-screensaver-command", "--lock"],
                                ["loginctl", "lock-session"],
                                ["xdg-screensaver", "lock"]):
                        try:
                            _sp.Popen(cmd)
                            break
                        except FileNotFoundError:
                            continue
                    self._send_json(200, {"ok": True, "action": "lock",
                                          "msg": "Lock command sent"})

            elif action == "sleep":
                if sys_name == "Windows":
                    _sp.Popen(["rundll32.exe",
                               "powrprof.dll,SetSuspendState", "0,1,0"])
                else:
                    _sp.Popen(["systemctl", "suspend"])
                self._send_json(200, {"ok": True, "action": "sleep",
                                      "msg": "Sleep command sent"})

            elif action == "hibernate":
                if sys_name == "Windows":
                    _sp.Popen(["shutdown", "/h"])
                else:
                    _sp.Popen(["systemctl", "hibernate"])
                self._send_json(200, {"ok": True, "action": "hibernate",
                                      "msg": "Hibernate command sent"})

            elif action == "logoff":
                if sys_name == "Windows":
                    _sp.Popen(["shutdown", "/l"])
                    self._send_json(200, {"ok": True, "action": "logoff",
                                          "msg": "Log off command sent"})
                else:
                    self._send_json(400, {"error": "Logoff not supported on Linux"})

            else:
                self._send_error(400, f"Unknown action '{action}'. "
                                      "Use: reboot, shutdown, cancel, lock, sleep, "
                                      "hibernate, logoff")
        except Exception as e:
            self._send_error(500, str(e))

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    host = CFG["host"]
    port = CFG["port"]

    # Resolve display hostname
    try:
        display_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        display_ip = "127.0.0.1"

    server = HTTPServer((host, port), AgentHandler)

    # Warm up cpu_percent so first reading is non-zero
    psutil.cpu_percent(interval=0.5)

    print("=" * 60)
    print(f"  REGTeches NOC Agent  v{AGENT_VERSION}")
    print("=" * 60)
    print(f"  Host:    {platform.node()}  ({display_ip})")
    print(f"  OS:      {platform.system()} {platform.release()}")
    print(f"  Listening on  http://{display_ip}:{port}")
    print()
    print(f"  API KEY:  {CFG['api_key']}")
    print()
    print("  NOC Dashboard setup:")
    print(f"    Tag:      noc-agent")
    print(f"    API Key:  (copy the key above)")
    print(f"    URL:      http://{display_ip}:{port}")
    print()
    print("  Endpoints:")
    print(f"    http://{display_ip}:{port}/health")
    print(f"    http://{display_ip}:{port}/info?key={CFG['api_key']}")
    print()
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgent stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
