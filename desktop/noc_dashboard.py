"""
REGTeches NOC Dashboard
Network Operations Center - Multi-Protocol Node Manager & Monitor
Developed by Ronald Goodchild
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
import subprocess
import webbrowser
import os
import time
import json
import copy
import socket
import struct
import winsound
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from collections import deque
import urllib.request
import urllib.parse
import ssl
import glob as _glob_mod
import shutil

# ─── Configuration ───────────────────────────────────────────────────────────

# When frozen as a PyInstaller EXE, __file__ points to a temp extraction dir.
# Use the directory containing the .exe so configs live next to the executable.
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "noc_config.json")
CONFIG_BACKUP_DIR = APP_DIR  # backups stored alongside the config file
LOG_FILE = os.path.join(APP_DIR, "noc_events.log")
ICON_PNG = os.path.join(APP_DIR, "noc_icon.png")
ICON_ICO = os.path.join(APP_DIR, "noc_icon.ico")
SMS_CONFIG_FILE = os.path.join(APP_DIR, "noc_sms_config.json")

CONNECTION_TYPES = {
    "SMB":    {"port": 445,  "icon": "\U0001F4C1", "desc": "Windows File Share (SMB/CIFS)"},
    "FTP":    {"port": 21,   "icon": "\U0001F4E5", "desc": "FTP File Transfer"},
    "FTPS":   {"port": 990,  "icon": "\U0001F512", "desc": "FTP over SSL/TLS (Implicit)"},
    "RDP":    {"port": 3389, "icon": "\U0001F5A5\uFE0F", "desc": "Remote Desktop Protocol"},
    "SSH":    {"port": 22,   "icon": "\U0001F4DF", "desc": "Secure Shell"},
    "Telnet": {"port": 23,   "icon": "\U0001F4DF", "desc": "Telnet Terminal"},
    "HTTP":   {"port": 80,   "icon": "\U0001F310", "desc": "Web Interface (HTTP)"},
    "HTTPS":  {"port": 443,  "icon": "\U0001F512", "desc": "Web Interface (HTTPS)"},
    "Custom": {"port": 0,    "icon": "\U0001F527", "desc": "Custom Port / Protocol"},
}

APP_VERSION = "2.5.0"
APP_AUTHOR = "Ronald Goodchild"
APP_NAME = "REGTeches NOC Dashboard"

# Common ports to scan
COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 135: "RPC", 139: "NetBIOS", 143: "IMAP",
    443: "HTTPS", 445: "SMB", 993: "IMAPS", 990: "FTPS", 995: "POP3S",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 5900: "VNC",
    5001: "Synology", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
    9090: "WebUI", 32400: "Plex",
}

# Icon picker choices for share add/edit dialog
SHARE_ICONS = [
    ("\U0001F4C1", "Folder"),
    ("\U0001F4C2", "Open Folder"),
    ("\U0001F4BE", "Floppy/Save"),
    ("\U0001F4BF", "CD/DVD"),
    ("\U0001F4BD", "Hard Drive"),
    ("\U0001F4E6", "Package"),
    ("\U0001F4E5", "Download"),
    ("\U0001F4E4", "Upload"),
    ("\U0001F310", "Globe/Web"),
    ("\U0001F512", "Lock"),
    ("\U0001F513", "Unlock"),
    ("\U0001F5A5\uFE0F", "Desktop"),
    ("\U0001F5A8\uFE0F", "Printer"),
    ("\U0001F4F7", "Camera"),
    ("\U0001F3AC", "Media"),
    ("\U0001F3B5", "Music"),
    ("\U0001F4F9", "Video"),
    ("\U0001F4DA", "Library"),
    ("\U0001F4DD", "Notes"),
    ("\U0001F4CA", "Chart"),
    ("\u2601\uFE0F", "Cloud"),
    ("\u2699\uFE0F", "Gear"),
    ("\U0001F527", "Wrench"),
    ("\U0001F6E1\uFE0F", "Shield"),
    ("\U0001F4E7", "Email"),
    ("\U0001F3E0", "Home"),
    ("\U0001F3E2", "Office"),
    ("\U0001F4BB", "Laptop"),
    ("\U0001F5C4\uFE0F", "File Cabinet"),
    ("\U0001F4DC", "Scroll"),
    ("\u2B50", "Star"),
    ("\u26A1", "Lightning"),
    ("\U0001F6A8", "Alert"),
    ("\U0001F504", "Refresh"),
    ("\U0001F50D", "Search"),
    ("\u2764\uFE0F", "Heart"),
]

# Companion projects are looked up in sibling folders (git clone them next to this repo)
# or under REGTECHES_TOOLS_DIR if you keep them somewhere else.
_TOOLS_DIR = os.environ.get("REGTECHES_TOOLS_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tool(*parts):
    return os.path.join(_TOOLS_DIR, *parts)


REGTECHES_TOOLS = [
    ("\U0001F5FA\uFE0F  DriveMapper Pro", _tool("drivemapper-pro", "drivemapper_pro.py")),
    ("\U0001F4BE  BackupPro", _tool("backuppro", "backuppro.py")),
    ("\U0001F6E1\uFE0F  Tech Sentinel Monitor", _tool("tech-sentinel-monitor", "windows", "run.py")),
    ("\U0001F9F0  Technician's Toolkit", _tool("technicians-toolkit", "technicians_toolkit.py")),
    ("\U0001F4E6  AppForge", _tool("appforge", "appforge.py")),
    ("\U0001F4E1  Nmap Studio", _tool("cyberscan", "tools", "nmap_studio.py")),
    ("\U0001F527  REGWinTool", _tool("regwintool", "regwintool.py")),
]

DEFAULT_NODES = [
    {
        "name": "📡 Sample Server",
        "ip": "192.168.1.100",
        "connections": [
            {"type": "SMB", "port": 445},
            {"type": "HTTP", "port": 80},
        ],
        "manage_url": "http://192.168.1.100",
        "manage_label": "Manage Server",
        "tags": ["sample"],
        "shares": [
            {"name": "SharedDocs", "icon": "\U0001F4C1", "label": "Shared Documents"},
            {"name": "Backups", "icon": "\U0001F4BE", "label": "Backup Drive"},
        ],
        "hosts": [
            {"ip": "192.168.1.1", "label": "Gateway Router"},
        ],
    },
]


def _get_connections(node):
    """Get the connections list from a node, with backward compatibility for old type/port format."""
    if "connections" in node and node["connections"]:
        return node["connections"]
    # Fallback: convert old single type/port to connections list
    ctype = node.get("type", "SMB")
    port = node.get("port", CONNECTION_TYPES.get(ctype, {}).get("port", 0))
    return [{"type": ctype, "port": port}]

# ─── Colors ──────────────────────────────────────────────────────────────────

COLORS = {
    "bg": "#0a0f1a",
    "card_bg": "#0f172a",
    "card_border": "#1e293b",
    "card_highlight": "#1e3a5f",
    "text": "#e2e8f0",
    "text_dim": "#94a3b8",
    "text_bright": "#f8fafc",
    "accent": "#3b82f6",
    "accent_dim": "#1d4ed8",
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#eab308",
    "orange": "#f97316",
    "purple": "#a855f7",
    "share_bg": "#1e293b",
    "share_hover": "#2563eb",
    "header_bg": "#060a14",
    "footer_bg": "#000000",
    "input_bg": "#1e293b",
    "btn_danger": "#dc2626",
    "log_bg": "#050810",
    "log_info": "#38bdf8",
    "log_warn": "#fbbf24",
    "log_error": "#f87171",
    "log_success": "#4ade80",
    "sparkline_bg": "#0f172a",
    "sparkline_line": "#3b82f6",
    "sparkline_fill": "#1e3a5f",
    "tag_bg": "#1e293b",
    "tag_fg": "#c4b5fd",
}

PING_INTERVAL = 30
PING_TIMEOUT = 2
PING_HISTORY_SIZE = 20  # number of ping samples to keep per host for sparkline


def _center_dialog(dlg, width, height, parent=None):
    """Center a Toplevel dialog over its parent window."""
    dlg.update_idletasks()
    if parent:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
    else:
        px = dlg.winfo_screenwidth() // 2 - width // 2
        py = dlg.winfo_screenheight() // 2 - height // 2
        pw = 0
        ph = 0
    x = px + (pw - width) // 2
    y = py + (ph - height) // 2
    # Keep on screen
    x = max(0, min(x, dlg.winfo_screenwidth() - width))
    y = max(0, min(y, dlg.winfo_screenheight() - height))
    dlg.geometry(f"{width}x{height}+{x}+{y}")


# ─── Config Persistence ─────────────────────────────────────────────────────

def load_config():
    """Load nodes from JSON config file, falling back to empty list if no file exists."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("nodes", [])
        except (json.JSONDecodeError, IOError):
            pass
    # No config file found — start fresh with empty list
    return []


def save_config(nodes):
    """Save current node list to JSON config file.
    Creates a timestamped backup before overwriting, keeps last 10 backups."""
    # Auto-backup existing config before writing
    if os.path.exists(CONFIG_FILE):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"noc_config_backup_{ts}.json"
            backup_path = os.path.join(CONFIG_BACKUP_DIR, backup_name)
            shutil.copy2(CONFIG_FILE, backup_path)
            # Prune old backups — keep only the last 10
            pattern = os.path.join(CONFIG_BACKUP_DIR, "noc_config_backup_*.json")
            backups = sorted(_glob_mod.glob(pattern))
            while len(backups) > 10:
                try:
                    os.remove(backups.pop(0))
                except OSError:
                    pass
        except Exception:
            pass  # backup failure should not block saving

    data = {"version": 2, "saved": datetime.now().isoformat(), "nodes": nodes}
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        messagebox.showerror("Save Error", f"Could not save config:\n{e}")


# ─── SMS / Text Alert System ─────────────────────────────────────────────────

SMS_CARRIERS = {
    "AT&T":              "txt.att.net",
    "T-Mobile":          "tmomail.net",
    "Verizon":           "vtext.com",
    "Sprint":            "messaging.sprintpcs.com",
    "Xfinity / Comcast": "vtext.com",
    "US Cellular":       "email.uscc.net",
    "Boost Mobile":      "sms.myboostmobile.com",
    "Cricket":           "sms.cricketwireless.net",
    "Metro PCS":         "mymetropcs.com",
    "Google Fi":         "msg.fi.google.com",
    "Mint Mobile":       "tmomail.net",
    "Visible":           "vtext.com",
    "Consumer Cellular": "mailmymobile.net",
    "Straight Talk":     "vtext.com",
}


def load_sms_config():
    """Load SMS alert settings from config file."""
    if os.path.exists(SMS_CONFIG_FILE):
        try:
            with open(SMS_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "enabled": False,
        "recipients": [],       # list of {"phone": "5551234567", "carrier": "AT&T", "label": "Ron"}
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "",        # sender email
        "smtp_pass": "",        # app password
        "alert_offline": True,
        "alert_online": True,
        "cooldown_minutes": 5,  # min time between alerts for same IP
    }


def save_sms_config(cfg):
    """Save SMS alert config to file."""
    try:
        with open(SMS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except IOError:
        pass


def send_sms_alert(sms_cfg, subject, body):
    """Send an SMS text message via email-to-SMS gateway.
    Runs in a thread so it never blocks the GUI."""
    if not sms_cfg.get("enabled") or not sms_cfg.get("recipients"):
        return

    smtp_user = sms_cfg.get("smtp_user", "")
    smtp_pass = sms_cfg.get("smtp_pass", "")
    smtp_server = sms_cfg.get("smtp_server", "smtp.gmail.com")
    smtp_port = sms_cfg.get("smtp_port", 587)

    if not smtp_user or not smtp_pass:
        return

    def _send():
        try:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)

            for recip in sms_cfg.get("recipients", []):
                phone = recip.get("phone", "").strip().replace("-", "").replace(" ", "")
                carrier = recip.get("carrier", "")
                gateway = SMS_CARRIERS.get(carrier)
                if not phone or not gateway:
                    continue
                to_addr = f"{phone}@{gateway}"
                msg = MIMEText(body)
                msg["From"] = smtp_user
                msg["To"] = to_addr
                msg["Subject"] = subject
                server.sendmail(smtp_user, to_addr, msg.as_string())

            server.quit()
        except Exception as e:
            print(f"SMS send error: {e}")

    threading.Thread(target=_send, daemon=True).start()


# ─── Synology DSM API ────────────────────────────────────────────────────────

# Ignore SSL cert errors for self-signed NAS certs
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _synology_api_call(base_url, api, version, method, sid=None, extra_params=None):
    """Call a Synology DSM API endpoint and return parsed JSON."""
    params = {
        "api": api,
        "version": str(version),
        "method": method,
    }
    if sid:
        params["_sid"] = sid
    if extra_params:
        params.update(extra_params)
    url = f"{base_url}/webapi/entry.cgi?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx)
    return json.loads(resp.read().decode("utf-8"))


def synology_login(base_url, username, password):
    """Login to Synology DSM API and return session ID."""
    params = {
        "api": "SYNO.API.Auth",
        "version": "6",
        "method": "login",
        "account": username,
        "passwd": password,
        "format": "sid",
    }
    url = f"{base_url}/webapi/auth.cgi?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx)
    data = json.loads(resp.read().decode("utf-8"))
    if data.get("success"):
        return data["data"]["sid"]
    return None


def synology_logout(base_url, sid):
    """Logout from Synology DSM API."""
    try:
        params = {"api": "SYNO.API.Auth", "version": "6", "method": "logout", "_sid": sid}
        url = f"{base_url}/webapi/auth.cgi?{urllib.parse.urlencode(params)}"
        urllib.request.urlopen(urllib.request.Request(url), timeout=5, context=_ssl_ctx)
    except Exception:
        pass


def synology_system_info(base_url, sid):
    """Get CPU and RAM utilization from Synology DSM."""
    data = _synology_api_call(
        base_url, "SYNO.Core.System.Utilization", 1, "get", sid=sid)
    if data.get("success"):
        return data.get("data", {})
    return None


def synology_storage_info(base_url, sid):
    """Get disk/volume info from Synology DSM."""
    data = _synology_api_call(
        base_url, "SYNO.Storage.CGI.Storage", 1, "load_info", sid=sid)
    if data.get("success"):
        return data.get("data", {})
    return None


def _detect_synology_url(node):
    """Check if a node looks like a Synology NAS and return its API base URL.
    Looks for HTTP/HTTPS connections on ports 5000/5001 (Synology DSM default ports)."""
    ip = node.get("ip", "")
    if not ip:
        return None
    conns = _get_connections(node)
    for conn in conns:
        port = conn.get("port", 0)
        if port == 5001:
            return f"https://{ip}:{port}"
        if port == 5000:
            return f"http://{ip}:{port}"
    # Also check manage_url
    manage_url = node.get("manage_url", "")
    if manage_url and (":5000" in manage_url or ":5001" in manage_url):
        return manage_url.rstrip("/")
    return None


def _get_synology_creds(node):
    """Try to find saved credentials from the node's shares."""
    for share in node.get("shares", []):
        user = share.get("user")
        pwd = share.get("pass", "")
        if user:
            return user, pwd
    return None, None


# ─── ZimaOS / CasaOS API ────────────────────────────────────────────────────

def _detect_zimaos_url(node):
    """Check if a node looks like a ZimaOS/CasaOS device.
    Detects by node name containing 'zima' or 'casa', or by checking the API."""
    ip = node.get("ip", "")
    if not ip:
        return None
    name = node.get("name", "").lower()
    tags = [t.lower() for t in node.get("tags", [])]
    # Detect by name or tags
    if any(keyword in name for keyword in ("zima", "casa")):
        return f"http://{ip}"
    if any(keyword in t for t in tags for keyword in ("zima", "casa")):
        return f"http://{ip}"
    return None


def zimaos_login(base_url, username, password):
    """Login to ZimaOS/CasaOS API and return JWT token.
    Returns (token, None) on success or (None, error_string) on failure."""
    # CasaOS v1 expects form-encoded, v2 expects JSON — try both
    endpoints = ["/v1/users/login", "/v2/users/login"]
    errors = []
    for ep in endpoints:
        url = f"{base_url}{ep}"
        if "/v1/" in ep:
            payload = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        else:
            payload = json.dumps({"username": username, "password": password}).encode("utf-8")
            content_type = "application/json"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", content_type)
        try:
            resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
            data = json.loads(resp.read().decode("utf-8"))
            token = data.get("data", {}).get("token")
            if data.get("success") == 200 or token:
                return token, None
            errors.append(f"{ep}: {data.get('message', json.dumps(data)[:120])}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            # Try to extract message from JSON error body
            msg = body
            try:
                msg = json.loads(body).get("message", body)
            except Exception:
                pass
            errors.append(f"{ep}: HTTP {e.code} — {msg}")
        except Exception as e:
            errors.append(f"{ep}: {type(e).__name__}: {e}")
    combined = " | ".join(errors)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as _f:
            _f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [WARN] ZimaOS login failed — {combined}\n")
    except Exception:
        pass
    return None, combined


def zimaos_get(base_url, endpoint, token):
    """GET a ZimaOS API endpoint with JWT auth."""
    url = f"{base_url}{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    resp = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx)
    return json.loads(resp.read().decode("utf-8"))


# ─── Utility Functions ───────────────────────────────────────────────────────

def ping_host(ip, timeout=PING_TIMEOUT):
    """Ping a host and return True if reachable.
    Strips port suffix (e.g. '192.168.1.87:8006' → '192.168.1.87') since ICMP
    doesn't use ports.
    Checks output for a real reply — Windows ping can return exit code 0 even
    when the gateway replies 'Destination host unreachable'."""
    # Strip port if present (ip:port or [ipv6]:port)
    host = ip.split(":")[0] if ":" in ip and not ip.startswith("[") else ip
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout * 1000), host],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False
        out = (result.stdout or "").upper()
        # IPv4 replies contain "TTL=", IPv6 replies contain "TIME=" without TTL
        # "Destination host unreachable" contains neither pattern
        if "TTL=" in out:
            return True
        if "TIME=" in out and "UNREACHABLE" not in out and "COULD NOT FIND" not in out:
            return True
        return False
    except Exception:
        return False


def scan_port(ip, port, timeout=1):
    """Check if a single port is open on a host."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def send_wol(mac_address):
    """Send a Wake-on-LAN magic packet to a MAC address."""
    # Clean the MAC address
    mac = mac_address.replace(":", "").replace("-", "").replace(".", "")
    if len(mac) != 12:
        raise ValueError(f"Invalid MAC address: {mac_address}")
    # Build magic packet: 6x 0xFF + 16x MAC
    mac_bytes = bytes.fromhex(mac)
    magic = b'\xff' * 6 + mac_bytes * 16
    # Send via UDP broadcast
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(magic, ('<broadcast>', 9))
    sock.close()


def _find_free_drive_letter():
    """Find the first available drive letter (Z: down to D:) not currently in use."""
    import string
    used = set()
    result = subprocess.run(
        ["net", "use"], capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        for p in parts:
            if len(p) == 2 and p[1] == ":" and p[0].isalpha():
                used.add(p[0].upper())
    # Also check drives that exist locally (C:, D:, etc.)
    for letter in string.ascii_uppercase:
        if os.path.exists(f"{letter}:\\"):
            used.add(letter)
    # Search from Z down to D for a free letter
    for letter in reversed(string.ascii_uppercase[3:]):  # D-Z
        if letter not in used:
            return f"{letter}:"
    return None


def open_share(ip, share_name, saved_user=None, saved_pass=None):
    """Browse a network share in Windows Explorer (no drive mapping).
    If saved credentials are provided, authenticate first then open UNC path.
    The Explorer window is temporary — closing it leaves nothing behind."""
    path = f"\\\\{ip}\\{share_name}"

    # If saved credentials exist, authenticate the UNC path (no drive letter)
    if saved_user:
        pwd = saved_pass if saved_pass else ""
        # Delete stale connection first
        subprocess.run(
            ["net", "use", path, "/delete", "/y"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # Authenticate: net use \\server\share /user:name password
        cmd = ["net", "use", path, f"/user:{saved_user}", pwd]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)

        if result.returncode == 0:
            # Authenticated — open in Explorer (browse only, no mapping)
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror("Connection Error",
                                     f"Authenticated but could not open {path}\n\n{e}")
            return
        else:
            err_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            answer = messagebox.askyesno(
                "Authentication Failed",
                f"Could not auto-authenticate to {path}\n\n"
                f"Error: {err_msg}\n\n"
                "Would you like to enter credentials manually?",
            )
            if answer:
                if _prompt_credentials(ip, share_name, path):
                    try:
                        os.startfile(path)
                    except Exception as e:
                        messagebox.showerror("Connection Error",
                                             f"Still could not open {path}\n\n{e}")
            return

    # No saved credentials — just try to open UNC path directly
    try:
        os.startfile(path)
    except Exception:
        if _prompt_credentials(ip, share_name, path):
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror("Connection Error", f"Still could not open {path}\n\n{e}")


def map_share(ip, share_name, saved_user=None, saved_pass=None):
    """Map a network share to a drive letter permanently.
    Uses: net use Z: \\\\server\\share /user:USERNAME PASSWORD"""
    path = f"\\\\{ip}\\{share_name}"
    drive = _find_free_drive_letter()
    if not drive:
        messagebox.showerror("Drive Error",
                             "No free drive letters available (D:-Z: all in use).")
        return

    if saved_user:
        pwd = saved_pass if saved_pass else ""
        cmd = ["net", "use", drive, path, f"/user:{saved_user}", pwd]
    else:
        cmd = ["net", "use", drive, path]

    result = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode == 0:
        messagebox.showinfo("Drive Mapped",
                            f"Successfully mapped:\n\n{path}  →  {drive}")
        try:
            os.startfile(drive + "\\")
        except Exception:
            pass
    else:
        err_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        messagebox.showerror("Map Failed",
                             f"Could not map {path} to {drive}\n\n{err_msg}")


def open_rdp(ip, port=3389):
    """Launch Remote Desktop Connection to a host."""
    try:
        cmd = ["mstsc", f"/v:{ip}:{port}"] if port != 3389 else ["mstsc", f"/v:{ip}"]
        subprocess.Popen(cmd)
    except Exception as e:
        messagebox.showerror("RDP Error", f"Could not launch Remote Desktop:\n{e}")


def open_ftp(ip, port=21):
    """Open FTP location in Explorer."""
    url = f"ftp://{ip}:{port}" if port != 21 else f"ftp://{ip}"
    try:
        os.startfile(url)
    except Exception as e:
        messagebox.showerror("FTP Error", f"Could not open FTP:\n{e}")


def open_telnet(ip, port=23):
    """Open a telnet session."""
    try:
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", f"telnet {ip} {port}"])
    except Exception as e:
        messagebox.showerror("Telnet Error", f"Could not open Telnet:\n{e}")


def open_ssh(ip, port=22):
    """Open an SSH session."""
    try:
        cmd = f"ssh -p {port} {ip}" if port != 22 else f"ssh {ip}"
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", cmd])
    except Exception as e:
        messagebox.showerror("SSH Error", f"Could not open SSH:\n{e}")


def open_ftps(ip, port=990):
    """Open an FTPS connection."""
    url = f"ftps://{ip}:{port}" if port != 990 else f"ftps://{ip}"
    try:
        os.startfile(url)
    except Exception:
        messagebox.showinfo(
            "FTPS Connection",
            f"FTPS is not directly supported by Windows Explorer.\n\n"
            f"Use an FTP client (e.g. FileZilla, WinSCP) to connect to:\n\n"
            f"  Host: {ip}\n  Port: {port}\n  Protocol: FTPS (FTP over TLS/SSL)",
        )


def connect_by_type(ip, conn_type, port):
    """Open a connection based on the server type."""
    if conn_type == "SMB":
        open_share(ip, "")
    elif conn_type == "RDP":
        open_rdp(ip, port)
    elif conn_type == "FTP":
        open_ftp(ip, port)
    elif conn_type == "FTPS":
        open_ftps(ip, port)
    elif conn_type == "Telnet":
        open_telnet(ip, port)
    elif conn_type == "SSH":
        open_ssh(ip, port)
    elif conn_type in ("HTTP", "HTTPS"):
        proto = conn_type.lower()
        port_str = f":{port}" if port not in (80, 443) else ""
        open_url(f"{proto}://{ip}{port_str}")
    else:
        open_url(f"http://{ip}:{port}")


def _prompt_credentials(ip, share_name, unc_path):
    """Show a login dialog and authenticate via 'net use'."""
    dlg = tk.Toplevel()
    dlg.title(f"Connect to {ip}")
    dlg.configure(bg=COLORS["card_bg"])
    _center_dialog(dlg, 370, 220)
    dlg.resizable(False, False)
    dlg.grab_set()
    dlg.focus_force()

    result = {"ok": False}

    tk.Label(
        dlg, text=f"Credentials required for\n{unc_path}",
        font=("Consolas", 9), fg=COLORS["text"], bg=COLORS["card_bg"], justify="center",
    ).pack(pady=(15, 10))

    fields = tk.Frame(dlg, bg=COLORS["card_bg"])
    fields.pack(padx=20, fill="x")

    tk.Label(fields, text="Username:", font=("Consolas", 9),
             fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=0, column=0, sticky="w", pady=3)
    user_entry = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["share_bg"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], width=28)
    user_entry.grid(row=0, column=1, pady=3, padx=(5, 0))
    user_entry.focus_set()

    tk.Label(fields, text="Password:", font=("Consolas", 9),
             fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=1, column=0, sticky="w", pady=3)
    pass_entry = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["share_bg"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], width=28, show="*")
    pass_entry.grid(row=1, column=1, pady=3, padx=(5, 0))

    status_label = tk.Label(dlg, text="", font=("Consolas", 8),
                            fg=COLORS["red"], bg=COLORS["card_bg"])
    status_label.pack(pady=(5, 0))

    def do_connect(event=None):
        username = user_entry.get().strip()
        password = pass_entry.get()
        if not username:
            status_label.configure(text="Username is required.")
            return
        share_path = f"\\\\{ip}\\{share_name}"
        # Delete stale connection, then authenticate UNC path (no drive mapping)
        subprocess.run(["net", "use", share_path, "/delete", "/y"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        cmd = ["net", "use", share_path, f"/user:{username}", password]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode == 0:
            result["ok"] = True
            dlg.destroy()
        else:
            err = proc.stderr.strip() or proc.stdout.strip() or "Authentication failed."
            status_label.configure(text=err[:60])

    btn_frame = tk.Frame(dlg, bg=COLORS["card_bg"])
    btn_frame.pack(pady=10)

    tk.Button(
        btn_frame, text="Connect", font=("Consolas", 9, "bold"),
        bg=COLORS["accent"], fg="white", activebackground=COLORS["accent_dim"],
        relief="flat", padx=15, pady=3, command=do_connect, cursor="hand2",
    ).pack(side="left", padx=5)

    tk.Button(
        btn_frame, text="Cancel", font=("Consolas", 9),
        bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
        padx=15, pady=3, command=dlg.destroy, cursor="hand2",
    ).pack(side="left", padx=5)

    dlg.bind("<Return>", do_connect)
    dlg.wait_window()
    return result["ok"]


def open_url(url):
    """Open a URL in the default browser."""
    try:
        webbrowser.open(url)
    except Exception as e:
        messagebox.showerror("Browser Error", f"Could not open {url}\n\n{e}")


# ─── Event Logger ────────────────────────────────────────────────────────────

class EventLog:
    """Thread-safe event logger with file persistence."""

    LEVELS = {"INFO": "log_info", "WARN": "log_warn", "ERROR": "log_error", "OK": "log_success"}

    def __init__(self, max_entries=500):
        self.entries = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._listeners = []

    def log(self, message, level="INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"ts": ts, "level": level, "msg": message}
        with self._lock:
            self.entries.append(entry)
        # Write to file
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [{level}] {message}\n")
        except IOError:
            pass
        # Notify listeners
        for cb in self._listeners:
            try:
                cb(entry)
            except Exception:
                pass

    def on_entry(self, callback):
        self._listeners.append(callback)

    def get_all(self):
        with self._lock:
            return list(self.entries)


# ─── Add / Edit Server Dialog ───────────────────────────────────────────────

class ServerDialog:
    """Modal dialog for adding or editing a server/node."""

    def __init__(self, parent, title="Add Server", node=None):
        self.result = None
        self.parent = parent
        self.dlg = tk.Toplevel(parent)
        self.dlg.title(title)
        self.dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(self.dlg, 540, 750, parent)
        self.dlg.minsize(540, 500)
        self.dlg.resizable(False, True)
        self.dlg.grab_set()
        self.dlg.focus_force()

        self.shares_list = []
        self.hosts_list = []
        self.connections_list = []

        if node:
            self.shares_list = [dict(s) for s in node.get("shares", [])]
            self.hosts_list = [dict(h) for h in node.get("hosts", [])]
            self.connections_list = [dict(c) for c in _get_connections(node)]
        else:
            self.connections_list = [{"type": "SMB", "port": 445}]

        self._build(node)
        self.dlg.wait_window()

    def _build(self, node):
        # ── Fixed bottom bar with Save / Cancel ──
        bottom_bar = tk.Frame(self.dlg, bg=COLORS["header_bg"], pady=10)
        bottom_bar.pack(side="bottom", fill="x")

        tk.Button(
            bottom_bar, text="\U0001F4BE  Save Server", font=("Consolas", 11, "bold"),
            bg=COLORS["green"], fg="white", activebackground="#16a34a",
            relief="flat", padx=25, pady=6, command=self._save, cursor="hand2",
        ).pack(side="left", padx=(20, 10))

        tk.Button(
            bottom_bar, text="Cancel", font=("Consolas", 10),
            bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
            padx=20, pady=6, command=self.dlg.destroy, cursor="hand2",
        ).pack(side="left", padx=5)

        self.dlg.bind("<Return>", lambda e: self._save())
        self.dlg.bind("<Escape>", lambda e: self.dlg.destroy())

        # ── Scrollable content area ──
        outer = tk.Frame(self.dlg, bg=COLORS["card_bg"])
        outer.pack(fill="both", expand=True)

        scroll_canvas = tk.Canvas(outer, bg=COLORS["card_bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=scroll_canvas.yview)
        scroll_inner = tk.Frame(scroll_canvas, bg=COLORS["card_bg"])

        scroll_inner.bind("<Configure>",
                          lambda e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.create_window((0, 0), window=scroll_inner, anchor="nw",
                                    tags="inner_window")
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scroll_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_canvas_cfg(event):
            scroll_canvas.itemconfig("inner_window", width=event.width)
        scroll_canvas.bind("<Configure>", _on_canvas_cfg)

        def _on_mwheel(event):
            scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        scroll_canvas.bind_all("<MouseWheel>", _on_mwheel)
        self.dlg.bind("<Destroy>", lambda e: scroll_canvas.unbind_all("<MouseWheel>"), add="+")

        container = tk.Frame(scroll_inner, bg=COLORS["card_bg"], padx=20, pady=15)
        container.pack(fill="both", expand=True)

        row = 0

        # Server Name
        row = self._add_field(container, row, "Server Name:", "name_entry")
        # IP / Hostname
        row = self._add_field(container, row, "IP Address / Hostname:", "ip_entry")

        # ── Connection Methods ──
        tk.Label(container, text="Connection Methods:", font=("Consolas", 9, "bold"),
                 fg=COLORS["text"], bg=COLORS["card_bg"]).grid(row=row, column=0, sticky="w", pady=(8, 2))
        row += 1

        conn_frame = tk.Frame(container, bg=COLORS["card_bg"])
        conn_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        row += 1

        self.conn_listbox = tk.Listbox(
            conn_frame, font=("Consolas", 9), bg=COLORS["input_bg"],
            fg=COLORS["text"], selectbackground=COLORS["accent"],
            height=3, width=40,
        )
        self.conn_listbox.pack(side="left", fill="both", expand=True)
        self.conn_listbox.bind("<Double-Button-1>", lambda e: self._edit_connection())

        conn_btn_frame = tk.Frame(conn_frame, bg=COLORS["card_bg"])
        conn_btn_frame.pack(side="right", padx=(8, 0))

        for text, color, cmd in [
            ("+ Add", COLORS["accent"], self._add_connection),
            ("Edit", COLORS["orange"], self._edit_connection),
            ("- Remove", COLORS["btn_danger"], self._remove_connection),
        ]:
            fg = "white"
            tk.Button(
                conn_btn_frame, text=text, font=("Consolas", 8),
                bg=color, fg=fg, relief="flat", cursor="hand2",
                command=cmd, width=8,
            ).pack(pady=2)

        self._refresh_conn_listbox()

        # Management URL
        row = self._add_field(container, row, "Management URL (optional):", "url_entry")

        # Management Label
        row = self._add_field(container, row, "Management Label:", "label_entry")

        # MAC Address (for Wake-on-LAN)
        row = self._add_field(container, row, "MAC Address (for Wake-on-LAN, optional):", "mac_entry")

        # Tags
        tk.Label(container, text="Tags (comma-separated):", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=row, column=0, sticky="w", pady=(8, 2))
        row += 1
        self.tags_entry = tk.Entry(container, font=("Consolas", 10), bg=COLORS["input_bg"],
                                   fg=COLORS["tag_fg"], insertbackground=COLORS["text"], width=45)
        self.tags_entry.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        row += 1

        # Notes
        tk.Label(container, text="Notes (optional):", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=row, column=0, sticky="w", pady=(8, 2))
        row += 1
        self.notes_text = tk.Text(container, font=("Consolas", 9), bg=COLORS["input_bg"],
                                  fg=COLORS["text"], insertbackground=COLORS["text"],
                                  height=2, width=45, wrap="word")
        self.notes_text.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        row += 1

        # ── Shares section ──
        tk.Label(container, text="Shares / Paths:", font=("Consolas", 9, "bold"),
                 fg=COLORS["text"], bg=COLORS["card_bg"]).grid(row=row, column=0, sticky="w", pady=(12, 2))
        row += 1

        shares_frame = tk.Frame(container, bg=COLORS["card_bg"])
        shares_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        row += 1

        self.shares_listbox = tk.Listbox(
            shares_frame, font=("Consolas", 9), bg=COLORS["input_bg"],
            fg=COLORS["text"], selectbackground=COLORS["accent"],
            height=5, width=50,
        )
        self.shares_listbox.pack(side="left", fill="both", expand=True)
        self.shares_listbox.bind("<Double-Button-1>", lambda e: self._edit_share())

        shares_btn_frame = tk.Frame(shares_frame, bg=COLORS["card_bg"])
        shares_btn_frame.pack(side="right", padx=(8, 0))

        for text, color, cmd in [
            ("+ Add", COLORS["accent"], self._add_share),
            ("Edit", COLORS["orange"], self._edit_share),
            ("- Remove", COLORS["btn_danger"], self._remove_share),
            ("\u25B2 Up", COLORS["share_bg"], lambda: self._move_share(-1)),
            ("\u25BC Down", COLORS["share_bg"], lambda: self._move_share(1)),
        ]:
            fg = "white" if color != COLORS["share_bg"] else COLORS["text"]
            tk.Button(
                shares_btn_frame, text=text, font=("Consolas", 8),
                bg=color, fg=fg, relief="flat", cursor="hand2",
                command=cmd, width=8,
            ).pack(pady=2)

        # ── Hosts section ──
        tk.Label(container, text="Sub-Hosts (optional, for clusters):", font=("Consolas", 9, "bold"),
                 fg=COLORS["text"], bg=COLORS["card_bg"]).grid(row=row, column=0, sticky="w", pady=(12, 2))
        row += 1

        hosts_frame = tk.Frame(container, bg=COLORS["card_bg"])
        hosts_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        row += 1

        self.hosts_listbox = tk.Listbox(
            hosts_frame, font=("Consolas", 9), bg=COLORS["input_bg"],
            fg=COLORS["text"], selectbackground=COLORS["accent"],
            height=3, width=50,
        )
        self.hosts_listbox.pack(side="left", fill="both", expand=True)
        self.hosts_listbox.bind("<Double-Button-1>", lambda e: self._edit_host())

        hosts_btn_frame = tk.Frame(hosts_frame, bg=COLORS["card_bg"])
        hosts_btn_frame.pack(side="right", padx=(8, 0))

        for text, color, cmd in [
            ("+ Add", COLORS["accent"], self._add_host),
            ("Edit", COLORS["orange"], self._edit_host),
            ("- Remove", COLORS["btn_danger"], self._remove_host),
            ("\u25B2 Up", COLORS["share_bg"], lambda: self._move_host(-1)),
            ("\u25BC Down", COLORS["share_bg"], lambda: self._move_host(1)),
        ]:
            fg = "white" if color != COLORS["share_bg"] else COLORS["text"]
            tk.Button(
                hosts_btn_frame, text=text, font=("Consolas", 8),
                bg=color, fg=fg, relief="flat", cursor="hand2",
                command=cmd, width=8,
            ).pack(pady=2)

        # ── Populate fields if editing ──
        if node:
            self.name_entry.insert(0, node.get("name", ""))
            self.ip_entry.insert(0, node.get("ip", "") or "")
            self.url_entry.insert(0, node.get("manage_url", "") or "")
            self.label_entry.insert(0, node.get("manage_label", ""))
            self.mac_entry.insert(0, node.get("mac", ""))
            self.tags_entry.insert(0, ", ".join(node.get("tags", [])))
            self.notes_text.insert("1.0", node.get("notes", ""))
            self._refresh_conn_listbox()
            self._refresh_shares_listbox()
            self._refresh_hosts_listbox()

    def _add_field(self, parent, row, label_text, attr_name):
        tk.Label(parent, text=label_text, font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=row, column=0, sticky="w", pady=(8, 2))
        row += 1
        entry = tk.Entry(parent, font=("Consolas", 10), bg=COLORS["input_bg"],
                         fg=COLORS["text"], insertbackground=COLORS["text"], width=45)
        entry.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        setattr(self, attr_name, entry)
        row += 1
        return row

    # ── Connection methods management ──

    def _refresh_conn_listbox(self):
        self.conn_listbox.delete(0, tk.END)
        for c in self.connections_list:
            ctype = c.get("type", "Custom")
            port = c.get("port", 0)
            info = CONNECTION_TYPES.get(ctype, CONNECTION_TYPES["Custom"])
            self.conn_listbox.insert(tk.END, f"  {info['icon']}  {ctype}  :  {port}")

    def _connection_dialog(self, title, btn_text, existing=None):
        """Small dialog to pick a connection type and port."""
        dlg = tk.Toplevel(self.dlg)
        dlg.title(title)
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 320, 260, self.parent)
        dlg.resizable(False, False)
        dlg.grab_set()

        result = {"ok": False}

        tk.Label(dlg, text="Protocol:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).pack(anchor="w", padx=15, pady=(15, 2))

        type_var = tk.StringVar(value=existing.get("type", "SMB") if existing else "SMB")

        # Protocol picker as compact grid of buttons
        picker_frame = tk.Frame(dlg, bg=COLORS["card_bg"])
        picker_frame.pack(padx=15, fill="x")

        type_buttons = {}
        cols = 5
        for i, ctype in enumerate(CONNECTION_TYPES):
            info = CONNECTION_TYPES[ctype]
            btn = tk.Label(
                picker_frame, text=f"{info['icon']}\n{ctype}",
                font=("Consolas", 7), fg=COLORS["text"], bg=COLORS["share_bg"],
                cursor="hand2", width=6, height=2, relief="flat", justify="center",
            )
            btn.grid(row=i // cols, column=i % cols, padx=2, pady=2)
            type_buttons[ctype] = btn

            def on_pick(e, ct=ctype):
                type_var.set(ct)
                # Auto-fill default port
                default_port = CONNECTION_TYPES[ct]["port"]
                port_e.delete(0, tk.END)
                port_e.insert(0, str(default_port))
                # Highlight selected
                for k, b in type_buttons.items():
                    b.configure(bg=COLORS["accent"] if k == ct else COLORS["share_bg"])

            btn.bind("<Button-1>", on_pick)
            btn.bind("<Enter>", lambda e, w=btn: w.configure(bg=COLORS["card_highlight"])
                     if w.cget("bg") != COLORS["accent"] else None)
            btn.bind("<Leave>", lambda e, w=btn: w.configure(bg=COLORS["share_bg"])
                     if w.cget("bg") != COLORS["accent"] else None)

        # Highlight initial selection
        init_type = type_var.get()
        if init_type in type_buttons:
            type_buttons[init_type].configure(bg=COLORS["accent"])

        tk.Label(dlg, text="Port:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).pack(anchor="w", padx=15, pady=(10, 2))

        port_e = tk.Entry(dlg, font=("Consolas", 10), bg=COLORS["input_bg"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], width=8)
        port_e.pack(anchor="w", padx=15)
        port_e.insert(0, str(existing.get("port", 445) if existing else 445))

        def do_action():
            try:
                port = int(port_e.get().strip() or "0")
            except ValueError:
                return
            result["ok"] = True
            result["type"] = type_var.get()
            result["port"] = port
            dlg.destroy()

        tk.Button(dlg, text=btn_text, font=("Consolas", 9, "bold"),
                  bg=COLORS["green"], fg="white", relief="flat", padx=15, pady=3,
                  command=do_action, cursor="hand2").pack(pady=(10, 5))

        dlg.bind("<Return>", lambda e: do_action())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()
        return result if result["ok"] else None

    def _add_connection(self):
        result = self._connection_dialog("Add Connection", "Add")
        if result:
            self.connections_list.append({"type": result["type"], "port": result["port"]})
            self._refresh_conn_listbox()

    def _edit_connection(self):
        sel = self.conn_listbox.curselection()
        if not sel:
            messagebox.showinfo("Edit", "Select a connection to edit.", parent=self.dlg)
            return
        idx = sel[0]
        result = self._connection_dialog("Edit Connection", "Save", existing=self.connections_list[idx])
        if result:
            self.connections_list[idx] = {"type": result["type"], "port": result["port"]}
            self._refresh_conn_listbox()

    def _remove_connection(self):
        sel = self.conn_listbox.curselection()
        if sel:
            if len(self.connections_list) <= 1:
                messagebox.showwarning("Cannot Remove",
                                       "Server must have at least one connection method.",
                                       parent=self.dlg)
                return
            del self.connections_list[sel[0]]
            self._refresh_conn_listbox()

    # ── Share dialog with icon picker ──

    def _build_share_dialog(self, title, btn_text, existing=None):
        dlg = tk.Toplevel(self.dlg)
        dlg.title(title)
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 420, 480, self.parent)
        dlg.resizable(False, False)
        dlg.grab_set()

        result = {"ok": False}

        fields = tk.Frame(dlg, bg=COLORS["card_bg"])
        fields.pack(padx=15, pady=(15, 5), fill="x")

        tk.Label(fields, text="Share Name:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=0, column=0, sticky="w", pady=3)
        name_e = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["input_bg"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], width=30)
        name_e.grid(row=0, column=1, pady=3, padx=(5, 0))
        name_e.focus_set()

        tk.Label(fields, text="Display Label:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=1, column=0, sticky="w", pady=3)
        label_e = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["input_bg"],
                           fg=COLORS["text"], insertbackground=COLORS["text"], width=30)
        label_e.grid(row=1, column=1, pady=3, padx=(5, 0))

        # ── Saved credentials (optional) ──
        tk.Label(fields, text="Username:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=2, column=0, sticky="w", pady=3)
        user_e = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["input_bg"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], width=30)
        user_e.grid(row=2, column=1, pady=3, padx=(5, 0))

        tk.Label(fields, text="Password:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=3, column=0, sticky="w", pady=3)
        pass_e = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["input_bg"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], width=30, show="*")
        pass_e.grid(row=3, column=1, pady=3, padx=(5, 0))

        # Security warning
        tk.Label(fields, text="\u26A0 Credentials are saved in plain text in the JSON config.\n"
                              "   This is NOT recommended for production / sensitive environments.",
                 font=("Consolas", 7), fg=COLORS["orange"], bg=COLORS["card_bg"],
                 justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))

        if existing:
            name_e.insert(0, existing.get("name", ""))
            label_e.insert(0, existing.get("label", ""))
            user_e.insert(0, existing.get("user", ""))
            pass_e.insert(0, existing.get("pass", ""))

        # Icon picker
        tk.Label(dlg, text="Choose an icon:", font=("Consolas", 9, "bold"),
                 fg=COLORS["text"], bg=COLORS["card_bg"]).pack(anchor="w", padx=15, pady=(8, 4))

        icon_var = tk.StringVar(value=existing.get("icon", "\U0001F4C1") if existing else "\U0001F4C1")

        preview_frame = tk.Frame(dlg, bg=COLORS["card_bg"])
        preview_frame.pack(padx=15, fill="x")

        tk.Label(preview_frame, text="Selected:", font=("Consolas", 8),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).pack(side="left")

        preview_label = tk.Label(preview_frame, text="", font=("Segoe UI", 14),
                                 bg=COLORS["card_bg"], width=3)
        preview_label.pack(side="left", padx=(2, 5))

        preview_name = tk.Label(preview_frame, text="", font=("Consolas", 9),
                                fg=COLORS["text"], bg=COLORS["card_bg"])
        preview_name.pack(side="left")

        def update_preview(*_):
            val = icon_var.get()
            preview_label.configure(text=val)
            for emoji, lbl in SHARE_ICONS:
                if emoji == val:
                    preview_name.configure(text=lbl)
                    return
            preview_name.configure(text="Custom")

        icon_var.trace_add("write", update_preview)

        grid_frame = tk.Frame(dlg, bg=COLORS["card_bg"])
        grid_frame.pack(padx=15, pady=5, fill="both")

        cols = 6
        for i, (emoji, lbl) in enumerate(SHARE_ICONS):
            btn = tk.Label(grid_frame, text=emoji, font=("Segoe UI", 14),
                           bg=COLORS["share_bg"], cursor="hand2", width=2, height=1,
                           relief="flat", bd=1)
            btn.grid(row=i // cols, column=i % cols, padx=2, pady=2)

            def on_click(e, em=emoji):
                icon_var.set(em)
                for child in grid_frame.winfo_children():
                    child.configure(bg=COLORS["share_bg"])
                e.widget.configure(bg=COLORS["accent"])

            def on_enter(e, w=btn):
                if w.cget("bg") != COLORS["accent"]:
                    w.configure(bg=COLORS["card_highlight"])

            def on_leave(e, w=btn):
                if w.cget("bg") != COLORS["accent"]:
                    w.configure(bg=COLORS["share_bg"])

            btn.bind("<Button-1>", on_click)
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)
            self._create_tooltip(btn, lbl)

            if existing and emoji == existing.get("icon"):
                btn.configure(bg=COLORS["accent"])
            elif not existing and emoji == "\U0001F4C1":
                btn.configure(bg=COLORS["accent"])

        update_preview()

        def do_action():
            name = name_e.get().strip()
            if not name:
                name_e.configure(bg=COLORS["btn_danger"])
                name_e.after(800, lambda: name_e.configure(bg=COLORS["input_bg"]))
                return
            result["ok"] = True
            result["name"] = name
            result["label"] = label_e.get().strip()
            result["icon"] = icon_var.get() or "\U0001F4C1"
            result["user"] = user_e.get().strip()
            result["pass"] = pass_e.get()
            dlg.destroy()

        tk.Button(dlg, text=btn_text, font=("Consolas", 10, "bold"),
                  bg=COLORS["green"], fg="white", relief="flat", padx=20, pady=5,
                  command=do_action, cursor="hand2").pack(pady=(8, 10))

        dlg.bind("<Return>", lambda e: do_action())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()
        return result if result["ok"] else None

    @staticmethod
    def _create_tooltip(widget, text):
        tip = None
        def show(event):
            nonlocal tip
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 8}")
            tk.Label(tip, text=text, font=("Consolas", 8),
                     bg="#1e293b", fg="#cbd5e1", padx=5, pady=2, relief="solid", bd=1).pack()
        def hide(event):
            nonlocal tip
            if tip:
                tip.destroy()
                tip = None
        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    def _add_share(self):
        result = self._build_share_dialog("Add Share", "\U0001F4BE  Add Share")
        if result:
            share = {"name": result["name"], "icon": result["icon"]}
            if result["label"]:
                share["label"] = result["label"]
            if result.get("user"):
                share["user"] = result["user"]
                share["pass"] = result.get("pass", "")
            self.shares_list.append(share)
            self._refresh_shares_listbox()

    def _edit_share(self):
        sel = self.shares_listbox.curselection()
        if not sel:
            messagebox.showinfo("Edit Share", "Select a share to edit.", parent=self.dlg)
            return
        idx = sel[0]
        existing = self.shares_list[idx]
        result = self._build_share_dialog("Edit Share", "\U0001F4BE  Save Share", existing=existing)
        if result:
            share = {"name": result["name"], "icon": result["icon"]}
            if result["label"]:
                share["label"] = result["label"]
            if result.get("user"):
                share["user"] = result["user"]
                share["pass"] = result.get("pass", "")
            self.shares_list[idx] = share
            self._refresh_shares_listbox()

    def _move_share(self, direction):
        sel = self.shares_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if 0 <= new_idx < len(self.shares_list):
            self.shares_list[idx], self.shares_list[new_idx] = self.shares_list[new_idx], self.shares_list[idx]
            self._refresh_shares_listbox()
            self.shares_listbox.selection_set(new_idx)

    def _remove_share(self):
        sel = self.shares_listbox.curselection()
        if sel:
            del self.shares_list[sel[0]]
            self._refresh_shares_listbox()

    def _refresh_shares_listbox(self):
        self.shares_listbox.delete(0, tk.END)
        for s in self.shares_list:
            icon = s.get("icon", "\U0001F4C1")
            label = s.get("label", s["name"])
            cred = " \U0001F511" if s.get("user") else ""
            self.shares_listbox.insert(tk.END, f"  {icon}  {label}  ({s['name']}){cred}")

    def _add_host(self):
        self._host_dialog("Add Sub-Host", "Add")

    def _edit_host(self):
        sel = self.hosts_listbox.curselection()
        if not sel:
            messagebox.showinfo("Edit Host", "Select a host to edit.", parent=self.dlg)
            return
        idx = sel[0]
        self._host_dialog("Edit Sub-Host", "Save", existing=self.hosts_list[idx], idx=idx)

    def _host_dialog(self, title, btn_text, existing=None, idx=None):
        dlg = tk.Toplevel(self.dlg)
        dlg.title(title)
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 400, 220, self.parent)
        dlg.resizable(False, False)
        dlg.grab_set()

        fields = tk.Frame(dlg, bg=COLORS["card_bg"])
        fields.pack(padx=15, pady=15, fill="x")

        tk.Label(fields, text="Host IP:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=0, column=0, sticky="w", pady=3)
        ip_e = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["input_bg"],
                        fg=COLORS["text"], insertbackground=COLORS["text"], width=22)
        ip_e.grid(row=0, column=1, columnspan=2, pady=3, padx=(5, 0), sticky="w")
        ip_e.focus_set()

        tk.Label(fields, text="Label:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=1, column=0, sticky="w", pady=3)
        label_e = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["input_bg"],
                           fg=COLORS["text"], insertbackground=COLORS["text"], width=22)
        label_e.grid(row=1, column=1, columnspan=2, pady=3, padx=(5, 0), sticky="w")

        tk.Label(fields, text="Protocol:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=2, column=0, sticky="w", pady=3)
        protocol_var = tk.StringVar(value="http")
        protocol_choices = ["http", "https", "rdp", "ssh", "telnet", "vnc", "custom"]
        proto_menu = ttk.Combobox(fields, textvariable=protocol_var, values=protocol_choices,
                                  state="readonly", width=10, font=("Consolas", 9))
        proto_menu.grid(row=2, column=1, pady=3, padx=(5, 0), sticky="w")

        tk.Label(fields, text="Port:", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=3, column=0, sticky="w", pady=3)
        port_e = tk.Entry(fields, font=("Consolas", 10), bg=COLORS["input_bg"],
                          fg=COLORS["text"], insertbackground=COLORS["text"], width=8)
        port_e.grid(row=3, column=1, pady=3, padx=(5, 0), sticky="w")
        tk.Label(fields, text="(blank = default)", font=("Consolas", 7),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=3, column=2, sticky="w", padx=3)

        if existing:
            ip_e.insert(0, existing.get("ip", ""))
            label_e.insert(0, existing.get("label", ""))
            protocol_var.set(existing.get("protocol", "http"))
            if existing.get("port"):
                port_e.insert(0, str(existing["port"]))

        def do_action():
            ip = ip_e.get().strip()
            if not ip:
                return
            label = label_e.get().strip() or f"Host {ip}"
            proto = protocol_var.get()
            port_str = port_e.get().strip()
            host_data = {"ip": ip, "label": label, "protocol": proto}
            if port_str:
                try:
                    host_data["port"] = int(port_str)
                except ValueError:
                    pass
            if idx is not None:
                self.hosts_list[idx] = host_data
            else:
                self.hosts_list.append(host_data)
            self._refresh_hosts_listbox()
            dlg.destroy()

        tk.Button(dlg, text=btn_text, font=("Consolas", 9, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat", padx=15, pady=3,
                  command=do_action, cursor="hand2").pack(pady=5)
        dlg.bind("<Return>", lambda e: do_action())

    def _move_host(self, direction):
        sel = self.hosts_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if 0 <= new_idx < len(self.hosts_list):
            self.hosts_list[idx], self.hosts_list[new_idx] = self.hosts_list[new_idx], self.hosts_list[idx]
            self._refresh_hosts_listbox()
            self.hosts_listbox.selection_set(new_idx)

    def _remove_host(self):
        sel = self.hosts_listbox.curselection()
        if sel:
            del self.hosts_list[sel[0]]
            self._refresh_hosts_listbox()

    def _refresh_hosts_listbox(self):
        self.hosts_listbox.delete(0, tk.END)
        for h in self.hosts_list:
            self.hosts_listbox.insert(tk.END, f"  {h['ip']}  -  {h['label']}")

    def _save(self):
        name = self.name_entry.get().strip()
        ip = self.ip_entry.get().strip() or None

        if not name:
            messagebox.showwarning("Missing Field", "Server name is required.", parent=self.dlg)
            return

        if not self.connections_list:
            messagebox.showwarning("Missing Field", "Add at least one connection method.", parent=self.dlg)
            return

        manage_url = self.url_entry.get().strip() or None
        manage_label = self.label_entry.get().strip() or f"Manage {name}"

        # Auto-generate management URL if not provided
        if not manage_url and ip:
            # Check if there's an HTTP/HTTPS connection defined
            for conn in self.connections_list:
                if conn["type"] in ("HTTP", "HTTPS"):
                    proto = conn["type"].lower()
                    port_str = f":{conn['port']}" if conn["port"] not in (80, 443) else ""
                    manage_url = f"{proto}://{ip}{port_str}"
                    break
            if not manage_url:
                manage_url = f"http://{ip}"

        notes = self.notes_text.get("1.0", tk.END).strip()
        mac = self.mac_entry.get().strip()
        tags_raw = self.tags_entry.get().strip()
        tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        node = {
            "name": name,
            "ip": ip,
            "connections": self.connections_list,
            "manage_url": manage_url,
            "manage_label": manage_label,
        }

        if mac:
            node["mac"] = mac
        if tags:
            node["tags"] = tags
        if notes:
            node["notes"] = notes
        if self.shares_list:
            node["shares"] = self.shares_list
        if self.hosts_list:
            node["hosts"] = self.hosts_list

        self.result = node
        self.dlg.destroy()


# ─── Main Application ───────────────────────────────────────────────────────

class NOCDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("REGTeches NOC Dashboard")
        self.root.configure(bg=COLORS["bg"])
        self.root.geometry("1200x850")
        self.root.minsize(800, 600)

        # Set window icon
        try:
            if os.path.exists(ICON_ICO):
                self.root.iconbitmap(ICON_ICO)
        except Exception:
            pass

        # Load icon image for About dialog
        self.app_icon_img = None
        try:
            if os.path.exists(ICON_PNG):
                self.app_icon_img = tk.PhotoImage(file=ICON_PNG)
        except Exception:
            pass

        self.nodes = load_config()
        self.event_log = EventLog()
        self.status_indicators = {}   # ip -> (canvas, oval_id)
        self.status_labels = {}       # ip -> label widget
        self.node_statuses = {}       # ip -> bool (current)
        self.prev_statuses = {}       # ip -> bool (previous, for change detection)
        self.ping_history = {}        # ip -> deque of (ms | -1) for sparkline
        self.sparkline_canvases = {}  # ip -> canvas widget
        self.uptime_labels = {}       # ip -> label widget for uptime %
        self.uptime_data = {}         # ip -> {"up": int, "total": int}
        self.uptime_history = {}      # ip -> deque(maxlen=1440) of True/False/None (24h @ 1-min)
        self.disk_alerts = {}         # ip -> {drive: percent_used}
        self.disk_alert_labels = {}   # ip -> label widget for disk alerts on card
        self.disk_alert_threshold = 90  # alert when disk is 90%+ full
        self.disk_check_interval = 300  # check disk space every 5 minutes
        self.all_cards = []
        self.ping_thread = None
        self.running = True
        self.ping_interval = PING_INTERVAL  # user-adjustable check-in time
        self.countdown_seconds = self.ping_interval
        self.alerts_enabled = True
        self.sms_config = load_sms_config()
        self.sms_cooldowns = {}  # ip → last_alert_time
        self.maintenance_ips = set()  # IPs currently in maintenance mode
        self.maintenance_timers = {}  # ip -> {"end": timestamp, "label": str, "reminded": bool}
        self.log_panel_visible = tk.BooleanVar(value=True)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", self._on_filter_change)
        self.tag_filter_var = tk.StringVar(value="All")
        self.last_check_var = tk.StringVar(value="Last check: never")

        self._build_ui()
        self._start_ping_loop()
        self._start_countdown()
        self._start_disk_check_loop()

        self.event_log.log(f"Dashboard started — monitoring {len(self.nodes)} nodes", "INFO")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Keyboard shortcuts
        self.root.bind("<Control-r>", lambda e: self._refresh_now())
        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.root.bind("<Control-n>", lambda e: self._add_server())
        self.root.bind("<Control-l>", lambda e: self._toggle_log_panel())
        self.root.bind("<Escape>", lambda e: self._clear_filter())

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self.root, bg=COLORS["header_bg"], pady=10, padx=20)
        header.pack(fill="x")

        title_frame = tk.Frame(header, bg=COLORS["header_bg"])
        title_frame.pack(side="left")

        tk.Label(
            title_frame, text="REGTECHES NOC",
            font=("Consolas", 18, "bold"),
            fg=COLORS["accent"], bg=COLORS["header_bg"],
        ).pack(anchor="w")

        tk.Label(
            title_frame,
            text="Network Operations Center // Multi-Protocol Node Manager",
            font=("Consolas", 8),
            fg=COLORS["text_dim"], bg=COLORS["header_bg"],
        ).pack(anchor="w")

        # Right side of header
        right_frame = tk.Frame(header, bg=COLORS["header_bg"])
        right_frame.pack(side="right")

        # Add Server button
        tk.Button(
            right_frame, text="+ Add Server",
            font=("Consolas", 9, "bold"), bg=COLORS["green"], fg="white",
            activebackground="#16a34a", activeforeground="white",
            relief="flat", cursor="hand2", padx=10, command=self._add_server,
        ).pack(side="left", padx=(0, 10))

        # Tag filter dropdown with label
        tag_frame = tk.Frame(right_frame, bg=COLORS["header_bg"])
        tag_frame.pack(side="left", padx=(0, 10))

        tk.Label(tag_frame, text="Filter:", font=("Consolas", 8),
                 fg=COLORS["text_dim"], bg=COLORS["header_bg"]).pack(side="left", padx=(0, 3))

        self.tag_combo = ttk.Combobox(
            tag_frame, textvariable=self.tag_filter_var,
            values=["All"], state="readonly", width=14,
            font=("Consolas", 9),
        )
        self.tag_combo.pack(side="left")
        self.tag_combo.bind("<<ComboboxSelected>>", lambda e: self._on_filter_change())
        self._refresh_tag_list()

        # Search box
        search_frame = tk.Frame(right_frame, bg=COLORS["card_border"], bd=1, relief="solid")
        search_frame.pack(side="left", padx=(0, 10))

        tk.Label(search_frame, text=" \U0001F50D ", font=("Segoe UI", 9),
                 bg=COLORS["card_bg"], fg=COLORS["text_dim"]).pack(side="left")

        self.search_entry = tk.Entry(
            search_frame, textvariable=self.filter_var,
            font=("Consolas", 10), bg=COLORS["card_bg"],
            fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", width=18,
        )
        self.search_entry.pack(side="left", padx=(0, 5), pady=2)

        # Refresh button
        tk.Button(
            right_frame, text="\u21BB Refresh",
            font=("Consolas", 9), bg=COLORS["card_bg"], fg=COLORS["accent"],
            activebackground=COLORS["accent_dim"], activeforeground="white",
            relief="flat", cursor="hand2", command=self._refresh_now,
        ).pack(side="left", padx=(0, 6))

        # Alert toggle
        self.alert_btn = tk.Button(
            right_frame, text="\U0001F514",
            font=("Segoe UI", 10), bg=COLORS["card_bg"], fg=COLORS["green"],
            relief="flat", cursor="hand2", command=self._toggle_alerts,
        )
        self.alert_btn.pack(side="left", padx=(0, 6))

        # Config menu button
        tk.Button(
            right_frame, text="\u2699",
            font=("Segoe UI", 12), bg=COLORS["card_bg"], fg=COLORS["text_dim"],
            activebackground=COLORS["accent_dim"], activeforeground="white",
            relief="flat", cursor="hand2", command=self._show_config_menu,
        ).pack(side="left", padx=(0, 10))

        # Last check label
        tk.Label(
            right_frame, textvariable=self.last_check_var,
            font=("Consolas", 8), fg=COLORS["text_dim"], bg=COLORS["header_bg"],
        ).pack(side="left")

        # ── Main paned window (cards + log) ──
        self.paned = tk.PanedWindow(
            self.root, orient="vertical", bg=COLORS["bg"],
            sashwidth=4, sashrelief="flat",
        )
        self.paned.pack(fill="both", expand=True)

        # ── Scrollable card area ──
        card_container = tk.Frame(self.paned, bg=COLORS["bg"])
        self.paned.add(card_container, stretch="always")

        self.canvas = tk.Canvas(card_container, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(card_container, orient="vertical", command=self.canvas.yview)

        self.scroll_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # ── Build node cards ──
        self._build_cards()

        # ── Activity Log Panel ──
        self.log_frame = tk.Frame(self.paned, bg=COLORS["log_bg"])
        self.paned.add(self.log_frame, height=160, stretch="never")

        log_header = tk.Frame(self.log_frame, bg=COLORS["header_bg"], pady=3)
        log_header.pack(fill="x")

        tk.Label(log_header, text="\U0001F4DC  ACTIVITY LOG",
                 font=("Consolas", 8, "bold"), fg=COLORS["accent"],
                 bg=COLORS["header_bg"]).pack(side="left", padx=10)

        tk.Button(log_header, text="Clear", font=("Consolas", 7),
                  bg=COLORS["share_bg"], fg=COLORS["text_dim"], relief="flat",
                  cursor="hand2", command=self._clear_log).pack(side="right", padx=5)

        tk.Button(log_header, text="Hide (Ctrl+L)", font=("Consolas", 7),
                  bg=COLORS["share_bg"], fg=COLORS["text_dim"], relief="flat",
                  cursor="hand2", command=self._toggle_log_panel).pack(side="right", padx=5)

        self.log_text = tk.Text(
            self.log_frame, font=("Consolas", 8), bg=COLORS["log_bg"],
            fg=COLORS["text_dim"], insertbackground=COLORS["text"],
            relief="flat", state="disabled", wrap="word", height=8,
        )
        log_scroll = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=5, pady=(0, 3))

        # Configure log text tags for colors
        self.log_text.tag_configure("INFO", foreground=COLORS["log_info"])
        self.log_text.tag_configure("WARN", foreground=COLORS["log_warn"])
        self.log_text.tag_configure("ERROR", foreground=COLORS["log_error"])
        self.log_text.tag_configure("OK", foreground=COLORS["log_success"])
        self.log_text.tag_configure("timestamp", foreground=COLORS["text_dim"])

        # Hook up log listener
        self.event_log.on_entry(lambda entry: self.root.after(0, self._append_log_entry, entry))

        # ── Footer ──
        footer = tk.Frame(self.root, bg=COLORS["footer_bg"], pady=6)
        footer.pack(fill="x")

        tk.Label(
            footer,
            text="Ctrl+N: Add  |  Ctrl+R: Refresh  |  Ctrl+F: Search  |  Ctrl+L: Toggle Log  |  Esc: Clear  |  Right-click: Options",
            font=("Consolas", 7), fg=COLORS["text_dim"], bg=COLORS["footer_bg"],
        ).pack()

        # Summary bar with live countdown
        self.summary_frame = tk.Frame(self.root, bg=COLORS["header_bg"], pady=4)
        self.summary_frame.pack(fill="x")

        self.summary_label = tk.Label(
            self.summary_frame, text="Checking nodes...",
            font=("Consolas", 9), fg=COLORS["text_dim"], bg=COLORS["header_bg"],
        )
        self.summary_label.pack()

    def _append_log_entry(self, entry):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{entry['ts']}] ", "timestamp")
        self.log_text.insert("end", f"[{entry['level']}] {entry['msg']}\n", entry['level'])
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _toggle_log_panel(self):
        if self.log_panel_visible.get():
            self.paned.forget(self.log_frame)
            self.log_panel_visible.set(False)
        else:
            self.paned.add(self.log_frame, height=160, stretch="never")
            self.log_panel_visible.set(True)

    def _toggle_alerts(self):
        self.alerts_enabled = not self.alerts_enabled
        if self.alerts_enabled:
            self.alert_btn.configure(text="\U0001F514", fg=COLORS["green"])
            self.event_log.log("Sound alerts ENABLED", "INFO")
        else:
            self.alert_btn.configure(text="\U0001F515", fg=COLORS["text_dim"])
            self.event_log.log("Sound alerts MUTED", "WARN")

    # ── SMS Text Alerts ─────────────────────────────────────────────────────

    def _send_sms_for_ip(self, ip, name, online=False, ms=0):
        """Send SMS alert with cooldown to prevent spam.
        Offline and online alerts have separate cooldowns so one doesn't block the other."""
        cooldown = self.sms_config.get("cooldown_minutes", 5) * 60
        now = time.time()
        # Separate cooldown keys for online vs offline
        cooldown_key = f"{ip}_{'on' if online else 'off'}"
        last = self.sms_cooldowns.get(cooldown_key, 0)
        if now - last < cooldown:
            return  # still in cooldown
        self.sms_cooldowns[cooldown_key] = now

        timestamp = datetime.now().strftime("%I:%M %p")
        if online:
            subject = f"NOC: {name} ONLINE"
            body = f"[NOC] {name} is back ONLINE at {timestamp} ({ms}ms)"
        else:
            subject = f"NOC: {name} OFFLINE"
            body = f"[NOC ALERT] {name} went OFFLINE at {timestamp}"

        send_sms_alert(self.sms_config, subject, body)
        self.event_log.log(f"SMS alert sent: {subject}", "INFO")

    def _show_sms_settings(self):
        """Full SMS/Text Alert configuration dialog."""
        dlg = tk.Toplevel(self.root)
        dlg.title("📱 SMS Text Alert Settings")
        dlg.configure(bg=COLORS["bg"])
        _center_dialog(dlg, 560, 680, self.root)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        cfg = self.sms_config.copy()
        cfg["recipients"] = [r.copy() for r in cfg.get("recipients", [])]

        # ── Title ──
        tk.Label(dlg, text="📱  SMS Text Alerts", font=("Consolas", 14, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(15, 5))
        tk.Label(dlg, text="Get text messages when servers go offline or come back online",
                 font=("Consolas", 8), fg=COLORS["text_dim"], bg=COLORS["bg"]).pack()

        main = tk.Frame(dlg, bg=COLORS["bg"])
        main.pack(fill="both", expand=True, padx=20, pady=10)

        # ── Enable toggle ──
        enable_var = tk.BooleanVar(value=cfg.get("enabled", False))
        enable_frame = tk.Frame(main, bg=COLORS["bg"])
        enable_frame.pack(fill="x", pady=(0, 10))
        tk.Checkbutton(enable_frame, text="  Enable SMS Text Alerts", variable=enable_var,
                        font=("Consolas", 10, "bold"), fg=COLORS["green"], bg=COLORS["bg"],
                        selectcolor=COLORS["card_bg"], activebackground=COLORS["bg"],
                        activeforeground=COLORS["green"]).pack(side="left")

        # ── Alert types ──
        alert_frame = tk.Frame(main, bg=COLORS["card_bg"], highlightbackground=COLORS["card_border"],
                                highlightthickness=1)
        alert_frame.pack(fill="x", pady=(0, 10))
        tk.Label(alert_frame, text="Alert When:", font=("Consolas", 9, "bold"),
                 fg=COLORS["text"], bg=COLORS["card_bg"]).pack(anchor="w", padx=10, pady=(8, 2))
        offline_var = tk.BooleanVar(value=cfg.get("alert_offline", True))
        online_var = tk.BooleanVar(value=cfg.get("alert_online", True))
        tk.Checkbutton(alert_frame, text="  🔴 Server goes OFFLINE", variable=offline_var,
                        font=("Consolas", 9), fg=COLORS["red"], bg=COLORS["card_bg"],
                        selectcolor=COLORS["bg"], activebackground=COLORS["card_bg"]).pack(anchor="w", padx=20)
        tk.Checkbutton(alert_frame, text="  🟢 Server comes back ONLINE", variable=online_var,
                        font=("Consolas", 9), fg=COLORS["green"], bg=COLORS["card_bg"],
                        selectcolor=COLORS["bg"], activebackground=COLORS["card_bg"]).pack(anchor="w", padx=20)

        # Cooldown
        cd_frame = tk.Frame(alert_frame, bg=COLORS["card_bg"])
        cd_frame.pack(fill="x", padx=10, pady=(5, 8))
        tk.Label(cd_frame, text="Cooldown (min between alerts per server):",
                 font=("Consolas", 8), fg=COLORS["text_dim"], bg=COLORS["card_bg"]).pack(side="left")
        cooldown_var = tk.StringVar(value=str(cfg.get("cooldown_minutes", 5)))
        cd_spin = tk.Spinbox(cd_frame, from_=1, to=60, textvariable=cooldown_var, width=4,
                              font=("Consolas", 9), bg=COLORS["share_bg"], fg=COLORS["text"])
        cd_spin.pack(side="left", padx=5)

        # ── Email Sender (SMTP) ──
        smtp_frame = tk.LabelFrame(main, text="  📧 Email Sender (SMTP)  ", font=("Consolas", 9, "bold"),
                                    fg=COLORS["accent"], bg=COLORS["card_bg"],
                                    highlightbackground=COLORS["card_border"])
        smtp_frame.pack(fill="x", pady=(0, 10))

        smtp_inner = tk.Frame(smtp_frame, bg=COLORS["card_bg"])
        smtp_inner.pack(fill="x", padx=10, pady=8)

        tk.Label(smtp_inner, text="We send texts via email-to-SMS gateways.\n"
                 "Use a Gmail account with an App Password.",
                 font=("Consolas", 7), fg=COLORS["text_dim"], bg=COLORS["card_bg"],
                 justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))

        labels = ["SMTP Server:", "SMTP Port:", "Email Address:", "App Password:"]
        keys = ["smtp_server", "smtp_port", "smtp_user", "smtp_pass"]
        defaults = ["smtp.gmail.com", "587", "", ""]
        smtp_entries = {}
        for i, (lbl, key, dflt) in enumerate(zip(labels, keys, defaults)):
            tk.Label(smtp_inner, text=lbl, font=("Consolas", 9),
                     fg=COLORS["text_dim"], bg=COLORS["card_bg"]).grid(row=i+1, column=0, sticky="w", pady=2)
            show = "*" if "pass" in key.lower() else ""
            e = tk.Entry(smtp_inner, font=("Consolas", 9), bg=COLORS["share_bg"],
                         fg=COLORS["text"], insertbackground=COLORS["text"], width=35, show=show)
            e.grid(row=i+1, column=1, sticky="w", padx=(8, 0), pady=2)
            e.insert(0, str(cfg.get(key, dflt)))
            smtp_entries[key] = e

        # ── Phone Recipients ──
        recip_frame = tk.LabelFrame(main, text="  📱 Phone Numbers  ", font=("Consolas", 9, "bold"),
                                     fg=COLORS["accent"], bg=COLORS["card_bg"],
                                     highlightbackground=COLORS["card_border"])
        recip_frame.pack(fill="both", expand=True, pady=(0, 10))

        recip_list_frame = tk.Frame(recip_frame, bg=COLORS["card_bg"])
        recip_list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Scrollable list of recipients
        recip_canvas = tk.Canvas(recip_list_frame, bg=COLORS["card_bg"], highlightthickness=0, height=100)
        recip_scrollbar = tk.Scrollbar(recip_list_frame, orient="vertical", command=recip_canvas.yview)
        recip_inner = tk.Frame(recip_canvas, bg=COLORS["card_bg"])

        recip_inner.bind("<Configure>", lambda e: recip_canvas.configure(scrollregion=recip_canvas.bbox("all")))
        recip_canvas.create_window((0, 0), window=recip_inner, anchor="nw")
        recip_canvas.configure(yscrollcommand=recip_scrollbar.set)

        recip_canvas.pack(side="left", fill="both", expand=True)
        recip_scrollbar.pack(side="right", fill="y")

        recipient_rows = []

        def rebuild_recipient_list():
            for w in recip_inner.winfo_children():
                w.destroy()
            recipient_rows.clear()

            for idx, recip in enumerate(cfg["recipients"]):
                row = tk.Frame(recip_inner, bg=COLORS["card_bg"])
                row.pack(fill="x", pady=1)

                tk.Label(row, text=f"  {recip.get('label', 'Phone')}",
                         font=("Consolas", 9), fg=COLORS["text"], bg=COLORS["card_bg"],
                         width=10, anchor="w").pack(side="left")
                tk.Label(row, text=recip.get("phone", ""),
                         font=("Consolas", 9), fg=COLORS["accent"], bg=COLORS["card_bg"],
                         width=12, anchor="w").pack(side="left")
                tk.Label(row, text=recip.get("carrier", ""),
                         font=("Consolas", 8), fg=COLORS["text_dim"], bg=COLORS["card_bg"],
                         width=16, anchor="w").pack(side="left")

                del_btn = tk.Label(row, text="  ✕", font=("Consolas", 9, "bold"),
                                    fg=COLORS["red"], bg=COLORS["card_bg"], cursor="hand2")
                del_btn.pack(side="right", padx=5)
                del_btn.bind("<Button-1>", lambda e, i=idx: remove_recipient(i))

                recipient_rows.append(row)

            if not cfg["recipients"]:
                tk.Label(recip_inner, text="No phone numbers added yet",
                         font=("Consolas", 8), fg=COLORS["text_dim"],
                         bg=COLORS["card_bg"]).pack(pady=10)

        def remove_recipient(idx):
            cfg["recipients"].pop(idx)
            rebuild_recipient_list()

        def add_recipient():
            add_dlg = tk.Toplevel(dlg)
            add_dlg.title("Add Phone Number")
            add_dlg.configure(bg=COLORS["bg"])
            _center_dialog(add_dlg, 380, 280, self.root)
            add_dlg.resizable(False, False)
            add_dlg.transient(dlg)
            add_dlg.grab_set()

            tk.Label(add_dlg, text="📱  Add Phone Number", font=("Consolas", 12, "bold"),
                     fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(15, 10))

            af = tk.Frame(add_dlg, bg=COLORS["bg"])
            af.pack(padx=20, fill="x")

            tk.Label(af, text="Label (name):", font=("Consolas", 9),
                     fg=COLORS["text_dim"], bg=COLORS["bg"]).grid(row=0, column=0, sticky="w", pady=4)
            label_entry = tk.Entry(af, font=("Consolas", 10), bg=COLORS["share_bg"],
                                    fg=COLORS["text"], insertbackground=COLORS["text"], width=22)
            label_entry.grid(row=0, column=1, pady=4, padx=(8, 0))

            tk.Label(af, text="Phone number:", font=("Consolas", 9),
                     fg=COLORS["text_dim"], bg=COLORS["bg"]).grid(row=1, column=0, sticky="w", pady=4)
            phone_entry = tk.Entry(af, font=("Consolas", 10), bg=COLORS["share_bg"],
                                    fg=COLORS["text"], insertbackground=COLORS["text"], width=22)
            phone_entry.grid(row=1, column=1, pady=4, padx=(8, 0))

            tk.Label(af, text="Carrier:", font=("Consolas", 9),
                     fg=COLORS["text_dim"], bg=COLORS["bg"]).grid(row=2, column=0, sticky="w", pady=4)
            carrier_var = tk.StringVar()
            carrier_combo = ttk.Combobox(af, textvariable=carrier_var,
                                          values=sorted(SMS_CARRIERS.keys()),
                                          state="readonly", width=20, font=("Consolas", 9))
            carrier_combo.grid(row=2, column=1, pady=4, padx=(8, 0))
            carrier_combo.set("Xfinity / Comcast")

            status_lbl = tk.Label(add_dlg, text="", font=("Consolas", 8),
                                   fg=COLORS["red"], bg=COLORS["bg"])
            status_lbl.pack(pady=5)

            def do_add():
                phone = phone_entry.get().strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
                carrier = carrier_var.get()
                label = label_entry.get().strip() or "Phone"
                if not phone or not phone.isdigit() or len(phone) < 10:
                    status_lbl.configure(text="Enter a valid 10-digit phone number")
                    return
                if not carrier:
                    status_lbl.configure(text="Select a carrier")
                    return
                cfg["recipients"].append({"phone": phone, "carrier": carrier, "label": label})
                rebuild_recipient_list()
                add_dlg.destroy()

            btn_frame = tk.Frame(add_dlg, bg=COLORS["bg"])
            btn_frame.pack(pady=10)
            tk.Button(btn_frame, text="Add", font=("Consolas", 10, "bold"),
                      bg=COLORS["accent"], fg="white", relief="flat", padx=20, pady=4,
                      cursor="hand2", command=do_add).pack(side="left", padx=5)
            tk.Button(btn_frame, text="Cancel", font=("Consolas", 10),
                      bg=COLORS["card_bg"], fg=COLORS["text"], relief="flat", padx=15, pady=4,
                      cursor="hand2", command=add_dlg.destroy).pack(side="left", padx=5)

            label_entry.focus_set()

        rebuild_recipient_list()

        add_btn_frame = tk.Frame(recip_frame, bg=COLORS["card_bg"])
        add_btn_frame.pack(fill="x", padx=10, pady=(0, 8))
        tk.Button(add_btn_frame, text="➕  Add Phone Number", font=("Consolas", 9),
                  bg=COLORS["accent_dim"], fg="white", relief="flat", padx=10, pady=3,
                  cursor="hand2", command=add_recipient).pack(side="left")

        # ── Test & Save buttons ──
        test_status = tk.Label(dlg, text="", font=("Consolas", 8),
                                fg=COLORS["text_dim"], bg=COLORS["bg"])
        test_status.pack()

        def test_sms():
            # Build temp config from current form values
            tmp = build_config()
            if not tmp["smtp_user"] or not tmp["smtp_pass"]:
                test_status.configure(text="⚠ Fill in email address and app password first", fg=COLORS["yellow"])
                return
            if not tmp["recipients"]:
                test_status.configure(text="⚠ Add at least one phone number first", fg=COLORS["yellow"])
                return
            test_status.configure(text="📤 Sending test message...", fg=COLORS["accent"])
            dlg.update()

            def _do_test():
                smtp_user = tmp.get("smtp_user", "")
                smtp_pass = tmp.get("smtp_pass", "")
                smtp_server = tmp.get("smtp_server", "smtp.gmail.com")
                smtp_port = tmp.get("smtp_port", 587)
                body = f"[NOC] Test alert from NOC Dashboard at {datetime.now().strftime('%I:%M %p')}"
                sent_to = []
                errors = []
                try:
                    server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(smtp_user, smtp_pass)
                    for recip in tmp.get("recipients", []):
                        phone = recip.get("phone", "").strip().replace("-", "").replace(" ", "")
                        carrier = recip.get("carrier", "")
                        gateway = SMS_CARRIERS.get(carrier)
                        label = recip.get("label", phone)
                        if not phone or not gateway:
                            errors.append(f"No gateway for '{carrier}' — skipped {label}")
                            continue
                        to_addr = f"{phone}@{gateway}"
                        msg = MIMEText(body)
                        msg["From"] = smtp_user
                        msg["To"] = to_addr
                        msg["Subject"] = "NOC Test"
                        server.sendmail(smtp_user, to_addr, msg.as_string())
                        sent_to.append(f"{label} → {to_addr}")
                    server.quit()
                except smtplib.SMTPAuthenticationError as e:
                    err_detail = e.smtp_error.decode() if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
                    errors.append(f"SMTP login failed: {err_detail}")
                except smtplib.SMTPException as e:
                    errors.append(f"SMTP error: {e}")
                except socket.timeout:
                    errors.append(f"Connection timed out — {smtp_server}:{smtp_port} unreachable")
                except ConnectionRefusedError:
                    errors.append(f"Connection refused — {smtp_server}:{smtp_port}")
                except Exception as e:
                    errors.append(f"{type(e).__name__}: {e}")

                # Build result message
                if errors and not sent_to:
                    title = "❌ SMS Test Failed"
                    detail = "ERRORS:\n" + "\n".join(f"  • {e}" for e in errors)
                    log_msg = f"❌ SMS test FAILED: {errors[0]}"
                    log_level = "ERROR"
                elif errors:
                    title = "⚠️ SMS Test Partial"
                    detail = (f"SENT TO:\n" + "\n".join(f"  ✅ {s}" for s in sent_to) +
                              f"\n\nERRORS:\n" + "\n".join(f"  ❌ {e}" for e in errors))
                    log_msg = f"⚠️ SMS test: {len(sent_to)} sent, {len(errors)} error(s)"
                    log_level = "WARN"
                else:
                    title = "✅ SMS Test Sent"
                    detail = "SENT TO:\n" + "\n".join(f"  ✅ {s}" for s in sent_to)
                    log_msg = f"✅ SMS test sent to {len(sent_to)} recipient(s)"
                    log_level = "OK"

                def _show_result():
                    # Log it
                    self.event_log.log(log_msg, log_level)
                    # Update status label
                    try:
                        if errors and not sent_to:
                            test_status.configure(text=f"❌ FAILED — see popup", fg=COLORS["red"])
                        elif errors:
                            test_status.configure(text=f"⚠ Partial — see popup", fg=COLORS["yellow"])
                        else:
                            test_status.configure(text=f"✅ Sent to {len(sent_to)}! Check phone.", fg=COLORS["green"])
                    except Exception:
                        pass
                    # Show messagebox so user can't miss it
                    messagebox.showinfo(title, detail)

                # Use self.root.after so it works even if SMS dialog was closed
                self.root.after(0, _show_result)

            threading.Thread(target=_do_test, daemon=True).start()

        def build_config():
            # Validate SMTP port
            try:
                port = int(smtp_entries["smtp_port"].get().strip() or "587")
                if port < 1 or port > 65535:
                    port = 587
            except ValueError:
                port = 587
            # Validate cooldown
            try:
                cooldown = int(cooldown_var.get() or "5")
                if cooldown < 1:
                    cooldown = 5
            except ValueError:
                cooldown = 5
            return {
                "enabled": enable_var.get(),
                "recipients": cfg["recipients"],
                "smtp_server": smtp_entries["smtp_server"].get().strip(),
                "smtp_port": port,
                "smtp_user": smtp_entries["smtp_user"].get().strip(),
                "smtp_pass": smtp_entries["smtp_pass"].get().strip(),
                "alert_offline": offline_var.get(),
                "alert_online": online_var.get(),
                "cooldown_minutes": cooldown,
            }

        def do_save():
            self.sms_config = build_config()
            save_sms_config(self.sms_config)
            self.event_log.log(
                f"SMS alerts {'ENABLED' if self.sms_config['enabled'] else 'DISABLED'} — "
                f"{len(self.sms_config['recipients'])} recipient(s)", "INFO")
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=COLORS["bg"])
        btn_row.pack(pady=(5, 15))
        tk.Button(btn_row, text="📤  Send Test", font=("Consolas", 10),
                  bg=COLORS["card_bg"], fg=COLORS["accent"], relief="flat", padx=15, pady=5,
                  cursor="hand2", command=test_sms).pack(side="left", padx=5)
        tk.Button(btn_row, text="💾  Save", font=("Consolas", 10, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat", padx=25, pady=5,
                  cursor="hand2", command=do_save).pack(side="left", padx=5)
        tk.Button(btn_row, text="Cancel", font=("Consolas", 10),
                  bg=COLORS["card_bg"], fg=COLORS["text"], relief="flat", padx=15, pady=5,
                  cursor="hand2", command=dlg.destroy).pack(side="left", padx=5)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _refresh_tag_list(self):
        all_tags = set()
        for node in self.nodes:
            for tag in node.get("tags", []):
                all_tags.add(tag)
        if all_tags:
            self.tag_combo["values"] = ["All Servers"] + sorted(all_tags)
        else:
            self.tag_combo["values"] = ["All Servers (no tags yet)"]
        if self.tag_filter_var.get() not in self.tag_combo["values"]:
            self.tag_filter_var.set(self.tag_combo["values"][0])

    def _build_cards(self):
        self.grid_frame = tk.Frame(self.scroll_frame, bg=COLORS["bg"], padx=15, pady=10)
        self.grid_frame.pack(fill="both", expand=True)

        for node in self.nodes:
            card = self._build_node_card(self.grid_frame, node)
            self.all_cards.append((card, node))

        self._layout_cards()
        self.root.bind("<Configure>", lambda e: self._layout_cards())

    def _layout_cards(self):
        width = self.root.winfo_width()
        cols = 1 if width < 800 else (2 if width < 1100 else 3)

        for card, _ in self.all_cards:
            card.grid_forget()

        # Get current filter state so layout respects it
        query = self.filter_var.get().lower().strip()
        tag_filter = self.tag_filter_var.get()

        row, col = 0, 0
        for card, node in self.all_cards:
            # Check text filter
            visible = True
            if query:
                searchable = node["name"].lower()
                if node.get("ip"):
                    searchable += " " + node["ip"]
                for conn in _get_connections(node):
                    searchable += " " + conn.get("type", "").lower()
                searchable += " " + " ".join(node.get("tags", []))
                for s in node.get("shares", []):
                    searchable += " " + s["name"].lower() + " " + s.get("label", "").lower()
                for h in node.get("hosts", []):
                    searchable += " " + h["ip"] + " " + h["label"].lower()
                visible = query in searchable

            # Check tag filter
            if visible and tag_filter and not tag_filter.startswith("All"):
                visible = tag_filter in node.get("tags", [])

            if visible:
                card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
                col += 1
                if col >= cols:
                    col = 0
                    row += 1

        # Make all columns the same width
        for c in range(cols):
            self.grid_frame.columnconfigure(c, weight=1, uniform="card")

    def _build_node_card(self, parent, node):
        card = tk.Frame(
            parent, bg=COLORS["card_bg"],
            highlightbackground=COLORS["card_border"],
            highlightthickness=1, padx=12, pady=10,
        )

        # ── Card header ──
        header = tk.Frame(card, bg=COLORS["card_bg"])
        header.pack(fill="x", pady=(0, 6))

        # Connection type badges (compact, all shown in header)
        connections = _get_connections(node)
        for conn in reversed(connections):  # reversed so first shows leftmost
            ctype = conn.get("type", "Custom")
            cport = conn.get("port", 0)
            info = CONNECTION_TYPES.get(ctype, CONNECTION_TYPES["Custom"])
            tk.Label(
                header, text=f"{info['icon']}{ctype}:{cport}",
                font=("Consolas", 6), fg=COLORS["text_bright"], bg=COLORS["accent_dim"],
                padx=3,
            ).pack(side="right", padx=(2, 0))

        # Manage link
        manage_label = node.get("manage_label", "")
        if node.get("manage_url"):
            manage_btn = tk.Label(
                header, text=manage_label.upper(),
                font=("Consolas", 7, "bold"), fg=COLORS["accent"],
                bg=COLORS["card_bg"], cursor="hand2",
            )
            manage_btn.pack(side="left")
            url = node["manage_url"]
            manage_btn.bind("<Button-1>", lambda e, u=url: open_url(u))
            manage_btn.bind("<Enter>", lambda e, w=manage_btn: w.configure(fg="white"))
            manage_btn.bind("<Leave>", lambda e, w=manage_btn: w.configure(fg=COLORS["accent"]))
        else:
            tk.Label(
                header, text=manage_label.upper(),
                font=("Consolas", 7, "bold"), fg=COLORS["text_dim"],
                bg=COLORS["card_bg"],
            ).pack(side="left")

        # Status indicator
        if node.get("ip"):
            status_canvas = tk.Canvas(
                header, width=14, height=14, bg=COLORS["card_bg"], highlightthickness=0,
            )
            status_canvas.pack(side="right")
            oval = status_canvas.create_oval(3, 3, 11, 11, fill=COLORS["yellow"], outline="")
            self.status_indicators[node["ip"]] = (status_canvas, oval)

            rt_label = tk.Label(
                header, text="...", font=("Consolas", 7),
                fg=COLORS["text_dim"], bg=COLORS["card_bg"],
            )
            rt_label.pack(side="right", padx=(0, 5))
            self.status_labels[node["ip"]] = rt_label

        # ── Node name ──
        name_frame = tk.Frame(card, bg=COLORS["card_bg"])
        name_frame.pack(fill="x", pady=(0, 4))

        name_label = tk.Label(
            name_frame, text=node["name"],
            font=("Consolas", 12, "bold"), fg=COLORS["text_bright"],
            bg=COLORS["card_bg"], anchor="w",
        )
        name_label.pack(fill="x")

        if node.get("manage_url"):
            name_label.configure(cursor="hand2")
            url = node["manage_url"]
            name_label.bind("<Button-1>", lambda e, u=url: open_url(u))
            name_label.bind("<Enter>", lambda e, w=name_label: w.configure(fg=COLORS["accent"]))
            name_label.bind("<Leave>", lambda e, w=name_label: w.configure(fg=COLORS["text_bright"]))

        # IP + uptime row
        if node.get("ip"):
            info_row = tk.Frame(name_frame, bg=COLORS["card_bg"])
            info_row.pack(fill="x")

            tk.Label(
                info_row, text=node["ip"],
                font=("Consolas", 8), fg=COLORS["text_dim"],
                bg=COLORS["card_bg"], anchor="w",
            ).pack(side="left")

            # Uptime percentage label
            uptime_lbl = tk.Label(
                info_row, text="",
                font=("Consolas", 7), fg=COLORS["text_dim"],
                bg=COLORS["card_bg"],
            )
            uptime_lbl.pack(side="right")
            self.uptime_labels[node["ip"]] = uptime_lbl
            self.uptime_data.setdefault(node["ip"], {"up": 0, "total": 0})

            # Disk alert label (subtle, shown when disk threshold is breached)
            disk_lbl = tk.Label(
                name_frame, text="",
                font=("Consolas", 7), fg=COLORS["orange"],
                bg=COLORS["card_bg"], anchor="w",
            )
            disk_lbl.pack(fill="x")
            self.disk_alert_labels[node["ip"]] = disk_lbl

        # Tags
        tags = node.get("tags", [])
        if tags:
            tag_frame = tk.Frame(name_frame, bg=COLORS["card_bg"])
            tag_frame.pack(fill="x", pady=(2, 0))
            for tag in tags[:5]:  # max 5 visible tags
                tk.Label(
                    tag_frame, text=f" {tag} ",
                    font=("Consolas", 7), fg=COLORS["tag_fg"],
                    bg=COLORS["tag_bg"], relief="flat",
                ).pack(side="left", padx=(0, 3))

        # Notes
        if node.get("notes"):
            tk.Label(
                name_frame,
                text=f"\U0001F4DD {node['notes'][:80]}{'...' if len(node.get('notes', '')) > 80 else ''}",
                font=("Consolas", 7), fg=COLORS["yellow"],
                bg=COLORS["card_bg"], anchor="w", wraplength=300, justify="left",
            ).pack(fill="x", pady=(2, 0))

        # ── Ping History Sparkline ──
        if node.get("ip"):
            sparkline = tk.Canvas(
                card, width=200, height=25,
                bg=COLORS["sparkline_bg"], highlightthickness=0,
            )
            sparkline.pack(fill="x", pady=(4, 4))
            self.sparkline_canvases[node["ip"]] = sparkline
            self.ping_history.setdefault(node["ip"], deque(maxlen=PING_HISTORY_SIZE))

        # ── Compact connect buttons row (one per connection method) ──
        if node.get("ip") and connections:
            connect_row = tk.Frame(card, bg=COLORS["card_bg"])
            connect_row.pack(fill="x", pady=(0, 4))

            for conn in connections:
                ctype = conn.get("type", "Custom")
                cport = conn.get("port", 0)
                info = CONNECTION_TYPES.get(ctype, CONNECTION_TYPES["Custom"])
                btn = tk.Label(
                    connect_row,
                    text=f"{info['icon']} {ctype}",
                    font=("Consolas", 7, "bold"),
                    fg="white", bg=COLORS["accent_dim"],
                    cursor="hand2", padx=5, pady=2, relief="flat",
                )
                btn.pack(side="left", padx=(0, 3))
                btn.bind("<Button-1>",
                         lambda e, i=node["ip"], t=ctype, p=cport: connect_by_type(i, t, p))
                btn.bind("<Enter>", lambda e, w=btn: w.configure(bg=COLORS["accent"]))
                btn.bind("<Leave>", lambda e, w=btn: w.configure(bg=COLORS["accent_dim"]))

        # Separator
        tk.Frame(card, bg=COLORS["card_border"], height=1).pack(fill="x", pady=(0, 6))

        # ── Collapsible Drives section ──
        has_shares = bool(node.get("shares"))
        has_hosts = bool(node.get("hosts"))

        def _make_collapsible(card_parent, label, count, build_fn, start_open=True):
            """Create a collapsible section with a toggle button."""
            frame = tk.Frame(card_parent, bg=COLORS["card_bg"])
            toggle_state = {"open": False}

            def toggle(tf=frame, ts=toggle_state, tb_ref=[None]):
                tb = tb_ref[0]
                if ts["open"]:
                    tf.pack_forget()
                    ts["open"] = False
                    if tb:
                        tb.configure(text=f"\u25B6  {label} ({count})",
                                     fg=COLORS["accent"])
                else:
                    tf.pack(fill="x", after=tb)
                    ts["open"] = True
                    if tb:
                        tb.configure(text=f"\u25BC  {label} ({count})",
                                     fg=COLORS["text_bright"])

            if start_open:
                btn_text = f"\u25BC  {label} ({count})"
                btn_fg = COLORS["text_bright"]
            else:
                btn_text = f"\u25B6  {label} ({count})"
                btn_fg = COLORS["accent"]

            btn = tk.Label(
                card_parent,
                text=btn_text,
                font=("Consolas", 9, "bold"),
                fg=btn_fg, bg=COLORS["share_bg"],
                anchor="w", padx=8, pady=4, cursor="hand2",
            )
            toggle_state["btn_ref"] = [btn]
            btn.pack(fill="x", pady=(0, 2))
            btn.bind("<Button-1>", lambda e, tb_ref=[btn]: toggle(tb_ref=tb_ref))
            btn.bind("<Enter>", lambda e, w=btn: w.configure(bg=COLORS["card_highlight"]))
            btn.bind("<Leave>", lambda e, w=btn: w.configure(bg=COLORS["share_bg"]))

            # Build items inside frame
            build_fn(frame)
            # Show expanded if start_open
            if start_open:
                frame.pack(fill="x", after=btn)
                toggle_state["open"] = True
            return frame

        if has_shares:
            share_count = len(node["shares"])
            def build_shares(parent):
                for share in node["shares"]:
                    self._build_share_button(parent, node["ip"], share)
            _make_collapsible(card, "Drives", share_count, build_shares)

        if has_hosts:
            host_count = len(node["hosts"])
            def build_hosts(parent):
                for host in node["hosts"]:
                    self._build_host_button(parent, host)
            _make_collapsible(card, "Hosts", host_count, build_hosts)

        # Hover effects + context menu
        self._add_card_hover(card)
        card.bind("<Button-3>", lambda e, n=node: self._card_context_menu(e, n))
        name_label.bind("<Button-3>", lambda e, n=node: self._card_context_menu(e, n))

        return card

    def _draw_sparkline(self, ip):
        """Redraw the sparkline graph for a given IP."""
        if ip not in self.sparkline_canvases or ip not in self.ping_history:
            return
        canvas = self.sparkline_canvases[ip]
        history = list(self.ping_history[ip])

        canvas.delete("all")
        w = canvas.winfo_width() or 200
        h = canvas.winfo_height() or 25

        if len(history) < 2:
            canvas.create_text(w // 2, h // 2, text="Collecting data...",
                               font=("Consolas", 7), fill=COLORS["text_dim"])
            return

        # Filter valid pings for scaling
        valid = [ms for ms in history if ms >= 0]
        if not valid:
            canvas.create_text(w // 2, h // 2, text="No response",
                               font=("Consolas", 7), fill=COLORS["red"])
            return

        max_ms = max(max(valid), 1)
        padding = 2
        usable_w = w - padding * 2
        usable_h = h - padding * 2
        step = usable_w / max(len(history) - 1, 1)

        # Build points
        points = []
        for i, ms in enumerate(history):
            x = padding + i * step
            if ms < 0:  # timeout
                y = h - padding  # bottom
            else:
                y = h - padding - (ms / max_ms) * usable_h
            points.append((x, y))

        # Fill area under line
        fill_points = [(padding, h - padding)] + points + [(padding + (len(history) - 1) * step, h - padding)]
        if len(fill_points) >= 4:
            flat = [coord for pt in fill_points for coord in pt]
            canvas.create_polygon(flat, fill=COLORS["sparkline_fill"], outline="")

        # Draw the line
        if len(points) >= 2:
            flat = [coord for pt in points for coord in pt]
            canvas.create_line(flat, fill=COLORS["sparkline_line"], width=1.5, smooth=True)

        # Draw dots for timeouts (red) and latest (green/red)
        for i, ms in enumerate(history):
            if ms < 0:
                x, y = points[i]
                canvas.create_oval(x - 2, h - padding - 2, x + 2, h - padding + 2,
                                   fill=COLORS["red"], outline="")

        # Latest point dot
        if points:
            lx, ly = points[-1]
            color = COLORS["green"] if history[-1] >= 0 else COLORS["red"]
            canvas.create_oval(lx - 3, ly - 3, lx + 3, ly + 3, fill=color, outline="")

        # Max/latest text
        latest = history[-1]
        latest_txt = f"{latest}ms" if latest >= 0 else "TIMEOUT"
        canvas.create_text(w - padding, padding, text=latest_txt,
                           font=("Consolas", 6), fill=COLORS["text_dim"], anchor="ne")
        canvas.create_text(padding, padding, text=f"max:{max_ms}ms",
                           font=("Consolas", 6), fill=COLORS["text_dim"], anchor="nw")

    def _build_share_button(self, parent, ip, share):
        display_name = share.get("label", share["name"])
        icon = share.get("icon", "\U0001F4C1")
        cred_icon = " \U0001F511" if share.get("user") else ""
        text = f"  {icon}  {display_name}{cred_icon}"

        btn = tk.Label(
            parent, text=text, font=("Consolas", 8),
            fg=COLORS["accent"], bg=COLORS["share_bg"],
            anchor="w", padx=8, pady=3, cursor="hand2", relief="flat",
        )
        btn.pack(fill="x", pady=1)

        share_name = share["name"]
        saved_user = share.get("user")
        saved_pass = share.get("pass", "")
        btn.bind("<Button-1>", lambda e, i=ip, s=share_name, u=saved_user, p=saved_pass:
                 open_share(i, s, u, p))
        btn.bind("<Enter>", lambda e, w=btn: w.configure(bg=COLORS["share_hover"], fg="white"))
        btn.bind("<Leave>", lambda e, w=btn: w.configure(bg=COLORS["share_bg"], fg=COLORS["accent"]))
        btn.bind("<Button-3>", lambda e, i=ip, s=share_name, u=saved_user, p=saved_pass:
                 self._share_context_menu(e, i, s, u, p))

    def _build_host_button(self, parent, host):
        text = f"  \U0001F517  {host['label']}"

        btn_frame = tk.Frame(parent, bg=COLORS["share_bg"])
        btn_frame.pack(fill="x", pady=1)

        btn = tk.Label(
            btn_frame, text=text, font=("Consolas", 8),
            fg=COLORS["accent"], bg=COLORS["share_bg"],
            anchor="w", padx=8, pady=3, cursor="hand2",
        )
        btn.pack(side="left", fill="x", expand=True)

        # Build unique key for this host — ip:port so multiple services
        # on the same IP (Sonarr:8989, Radarr:7878, etc.) each get their own indicator
        proto = host.get("protocol", "http")
        host_ip = host["ip"].split(":")[0] if ":" in host["ip"] else host["ip"]
        host_port = host.get("port")
        # If no explicit port, check if IP has :port suffix (legacy format)
        if not host_port and ":" in host.get("ip", ""):
            try:
                host_port = int(host["ip"].split(":")[-1])
            except ValueError:
                host_port = None

        # Unique key: "192.168.1.161:8989" or just "192.168.1.161" if no port
        unique_key = f"{host_ip}:{host_port}" if host_port else host_ip

        status_canvas = tk.Canvas(
            btn_frame, width=14, height=14, bg=COLORS["share_bg"], highlightthickness=0,
        )
        status_canvas.pack(side="right", padx=5)
        oval = status_canvas.create_oval(3, 3, 11, 11, fill=COLORS["yellow"], outline="")
        self.status_indicators[unique_key] = (status_canvas, oval)

        rt_label = tk.Label(
            btn_frame, text="...", font=("Consolas", 7),
            fg=COLORS["text_dim"], bg=COLORS["share_bg"],
        )
        rt_label.pack(side="right", padx=(0, 2))
        self.status_labels[unique_key] = rt_label

        if proto in ("http", "https"):
            default_port = 443 if proto == "https" else 80
            if host_port and host_port != default_port:
                url = f"{proto}://{host_ip}:{host_port}"
            else:
                url = f"{proto}://{host_ip}"
            btn.bind("<Button-1>", lambda e, u=url: open_url(u))
        elif proto == "rdp":
            btn.bind("<Button-1>", lambda e, h=host_ip, p=host_port:
                     subprocess.Popen(["mstsc", f"/v:{h}:{p}" if p else f"/v:{h}"]))
        elif proto == "ssh":
            p_flag = f" -p {host_port}" if host_port else ""
            btn.bind("<Button-1>", lambda e, h=host_ip, pf=p_flag:
                     os.system(f'start cmd /k "ssh{pf} {h}"'))
        elif proto == "telnet":
            btn.bind("<Button-1>", lambda e, h=host_ip, p=host_port or 23:
                     os.system(f'start cmd /k "telnet {h} {p}"'))
        elif proto == "vnc":
            url = f"vnc://{host_ip}:{host_port}" if host_port else f"vnc://{host_ip}"
            btn.bind("<Button-1>", lambda e, u=url: open_url(u))
        else:  # custom — try opening as URL
            if host_port:
                url = f"http://{host_ip}:{host_port}"
            else:
                url = f"http://{host_ip}"
            btn.bind("<Button-1>", lambda e, u=url: open_url(u))

        btn.bind("<Enter>", lambda e, w=btn: w.configure(bg=COLORS["share_hover"], fg="white"))
        btn.bind("<Leave>", lambda e, w=btn: w.configure(bg=COLORS["share_bg"], fg=COLORS["accent"]))
        # Right-click context menu for individual host — use unique_key for maintenance
        btn.bind("<Button-3>", lambda e, h=host, uk=unique_key, hp=host_ip:
                 self._host_context_menu(e, h, uk, hp))

    def _host_context_menu(self, event, host, host_ip_key, ping_ip):
        """Right-click menu for an individual sub-host."""
        menu = tk.Menu(self.root, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                       activebackground=COLORS["accent"], activeforeground="white",
                       font=("Consolas", 9))
        label = host.get("label", host_ip_key)

        # Maintenance toggle for this single host
        if host_ip_key in self.maintenance_ips:
            remaining = ""
            if host_ip_key in self.maintenance_timers:
                left = self.maintenance_timers[host_ip_key]["end"] - time.time()
                if left > 0:
                    mins = int(left // 60)
                    remaining = f" ({mins}m left)"
            menu.add_command(label=f"✅  Exit Maintenance{remaining}",
                             command=lambda: self._exit_maintenance({host_ip_key}))
        else:
            menu.add_command(label=f"🔧  Maintenance Mode",
                             command=lambda: self._enter_maintenance_dialog({host_ip_key}))

        menu.add_separator()
        menu.add_command(label=f"Ping {ping_ip} (continuous)",
                         command=lambda: self._manual_ping(ping_ip))
        menu.add_command(label=f"Traceroute {ping_ip}",
                         command=lambda: self._traceroute(ping_ip))
        menu.add_command(label=f"Port Scan {ping_ip}",
                         command=lambda: self._port_scan(ping_ip))
        menu.add_separator()
        menu.add_command(label=f"Copy IP: {host_ip_key}",
                         command=lambda: self._copy_to_clipboard(host_ip_key))
        menu.tk_popup(event.x_root, event.y_root)

    def _share_context_menu(self, event, ip, share_name, saved_user=None, saved_pass=None):
        menu = tk.Menu(self.root, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                       activebackground=COLORS["accent"], activeforeground="white",
                       font=("Consolas", 9))
        path = f"\\\\{ip}\\{share_name}"
        menu.add_command(label=f"Browse {path}",
                         command=lambda: open_share(ip, share_name, saved_user, saved_pass))
        menu.add_command(label=f"📁 Map drive letter ({path})",
                         command=lambda: map_share(ip, share_name, saved_user, saved_pass))
        menu.add_separator()
        menu.add_command(label="Copy path to clipboard", command=lambda: self._copy_to_clipboard(path))
        menu.add_separator()
        menu.add_command(label=f"Ping {ip}", command=lambda: self._manual_ping(ip))
        menu.add_command(label=f"Open {ip} in browser", command=lambda: open_url(f"http://{ip}"))
        menu.tk_popup(event.x_root, event.y_root)

    def _card_context_menu(self, event, node):
        menu = tk.Menu(self.root, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                       activebackground=COLORS["accent"], activeforeground="white",
                       font=("Consolas", 9))

        menu.add_command(label=f"\u270F  Edit \"{node['name']}\"",
                         command=lambda: self._edit_server(node))
        menu.add_command(label=f"\U0001F4CB  Duplicate \"{node['name']}\"",
                         command=lambda: self._duplicate_server(node))
        menu.add_separator()

        if node.get("ip"):
            # Show all connection methods
            conns = _get_connections(node)
            for conn in conns:
                ctype = conn.get("type", "Custom")
                cport = conn.get("port", 0)
                info = CONNECTION_TYPES.get(ctype, CONNECTION_TYPES["Custom"])
                menu.add_command(
                    label=f"\u25B6  {info['icon']} Connect {ctype}:{cport}",
                    command=lambda t=ctype, p=cport: connect_by_type(node["ip"], t, p),
                )
            menu.add_separator()

            # Network tools submenu
            net_menu = tk.Menu(menu, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                               activebackground=COLORS["accent"], activeforeground="white",
                               font=("Consolas", 9))
            net_menu.add_command(label=f"Ping {node['ip']} (continuous)",
                                 command=lambda: self._manual_ping(node["ip"]))
            net_menu.add_command(label=f"Traceroute {node['ip']}",
                                 command=lambda: self._traceroute(node["ip"]))
            net_menu.add_command(label=f"NSLookup {node['ip']}",
                                 command=lambda: self._nslookup(node["ip"]))
            net_menu.add_command(label=f"Port Scan {node['ip']}",
                                 command=lambda: self._port_scan(node["ip"]))
            net_menu.add_separator()
            net_menu.add_command(label=f"Open in browser",
                                 command=lambda: open_url(f"http://{node['ip']}"))
            menu.add_cascade(label="\U0001F527  Network Tools", menu=net_menu)

            # System Info (WMI)
            menu.add_command(label="\U0001F4CA  System Info",
                             command=lambda: self._show_system_info(node))

            # Uptime History
            menu.add_command(label="\U0001F4C8  Uptime History",
                             command=lambda: self._show_uptime_history(node))

            # Full Server Report
            menu.add_command(label="\U0001F4CB  Full Report",
                             command=lambda: self._show_server_report(node))

            # Wake-on-LAN
            if node.get("mac"):
                menu.add_command(label=f"\u26A1  Wake-on-LAN ({node['mac']})",
                                 command=lambda: self._wake_on_lan(node))
            else:
                menu.add_command(label="\u26A1  Wake-on-LAN (set MAC first)",
                                 state="disabled")

            menu.add_separator()

        # Maintenance mode — submenu for individual IPs
        maint_menu = tk.Menu(menu, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                             activebackground=COLORS["accent"], activeforeground="white",
                             font=("Consolas", 9))

        node_ip = node.get("ip", "")
        all_ips = []
        if node_ip:
            all_ips.append((node_ip, node.get("name", node_ip)))
        for h in node.get("hosts", []):
            if h.get("ip"):
                # Build unique key matching _build_host_button logic
                h_ip = h["ip"].split(":")[0] if ":" in h["ip"] else h["ip"]
                h_port = h.get("port")
                if not h_port and ":" in h.get("ip", ""):
                    try:
                        h_port = int(h["ip"].split(":")[-1])
                    except ValueError:
                        h_port = None
                h_key = f"{h_ip}:{h_port}" if h_port else h_ip
                all_ips.append((h_key, h.get("label", h["ip"])))

        # "All" option
        all_ip_set = {ip for ip, _ in all_ips}
        any_in_maint = bool(all_ip_set & self.maintenance_ips)
        all_in_maint = all_ip_set and all_ip_set.issubset(self.maintenance_ips)
        if all_in_maint:
            maint_menu.add_command(label="✅  Exit ALL from Maintenance",
                                   command=lambda ips=all_ip_set: self._exit_maintenance(ips))
        elif len(all_ips) > 1:
            maint_menu.add_command(label="🔧  Put ALL in Maintenance",
                                   command=lambda ips=all_ip_set: self._enter_maintenance_dialog(ips))
        if len(all_ips) > 1:
            maint_menu.add_separator()

        # Individual IP options
        for ip, label in all_ips:
            if ip in self.maintenance_ips:
                remaining = ""
                if ip in self.maintenance_timers:
                    left = self.maintenance_timers[ip]["end"] - time.time()
                    if left > 0:
                        mins = int(left // 60)
                        remaining = f" ({mins}m left)"
                maint_menu.add_command(
                    label=f"✅  Exit: {label}{remaining}",
                    command=lambda i=ip: self._exit_maintenance({i}))
            else:
                maint_menu.add_command(
                    label=f"🔧  {label}",
                    command=lambda i=ip: self._enter_maintenance_dialog({i}))

        menu.add_cascade(label="🔧  Maintenance Mode", menu=maint_menu)

        menu.add_separator()
        menu.add_command(label=f"\U0001F5D1  Delete \"{node['name']}\"",
                         command=lambda: self._delete_server(node))
        menu.tk_popup(event.x_root, event.y_root)

    def _enter_maintenance_dialog(self, ips):
        """Show a dialog asking how long the maintenance window should be."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Maintenance Mode")
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 380, 320, self.root)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="🔧  Enter Maintenance Mode",
                 font=("Consolas", 13, "bold"), fg=COLORS["accent"],
                 bg=COLORS["card_bg"]).pack(pady=(20, 5))

        ip_list = ", ".join(ips)
        tk.Label(dlg, text=ip_list, font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"],
                 wraplength=340).pack(pady=(0, 15))

        tk.Frame(dlg, bg=COLORS["card_border"], height=1).pack(fill="x", padx=30)

        tk.Label(dlg, text="How long is this maintenance window?",
                 font=("Consolas", 10), fg=COLORS["text"],
                 bg=COLORS["card_bg"]).pack(pady=(15, 10))

        duration_var = tk.IntVar(value=30)
        options = [
            ("15 minutes", 15),
            ("30 minutes", 30),
            ("1 hour", 60),
            ("2 hours", 120),
            ("4 hours", 240),
            ("8 hours (full day)", 480),
            ("No limit (remind every hour)", 0),
        ]

        radio_frame = tk.Frame(dlg, bg=COLORS["card_bg"])
        radio_frame.pack(padx=40, anchor="w")
        for label, minutes in options:
            tk.Radiobutton(
                radio_frame, text=label, variable=duration_var, value=minutes,
                font=("Consolas", 9), fg=COLORS["text"], bg=COLORS["card_bg"],
                selectcolor=COLORS["bg"], activebackground=COLORS["card_bg"],
                activeforeground=COLORS["accent"],
            ).pack(anchor="w", pady=1)

        def do_enter():
            minutes = duration_var.get()
            self._enter_maintenance(ips, minutes)
            dlg.destroy()

        tk.Button(dlg, text="🔧 Start Maintenance", font=("Consolas", 10, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat",
                  padx=20, pady=5, command=do_enter, cursor="hand2").pack(pady=(15, 10))

    def _enter_maintenance(self, ips, duration_minutes=30):
        """Put IPs into maintenance mode with a timer."""
        self.maintenance_ips.update(ips)
        now = time.time()
        for ip in ips:
            if ip in self.status_indicators:
                canvas, oval = self.status_indicators[ip]
                canvas.itemconfig(oval, fill="#2196F3")  # blue
            if ip in self.status_labels:
                self.status_labels[ip].configure(text="MAINT")
            # Set timer
            if duration_minutes > 0:
                end_time = now + (duration_minutes * 60)
            else:
                # No limit — set reminder for 1 hour from now, repeating
                end_time = now + 3600
            self.maintenance_timers[ip] = {
                "end": end_time,
                "label": ip,
                "reminded": False,
                "no_limit": (duration_minutes == 0),
                "duration": duration_minutes,
            }

        if duration_minutes > 0:
            if duration_minutes >= 60:
                dur_str = f"{duration_minutes // 60}h"
                if duration_minutes % 60:
                    dur_str += f" {duration_minutes % 60}m"
            else:
                dur_str = f"{duration_minutes}m"
            self.event_log.log(
                f"🔧 Maintenance ON ({dur_str}): {', '.join(ips)}", "WARN")
        else:
            self.event_log.log(
                f"🔧 Maintenance ON (no limit, hourly reminders): {', '.join(ips)}", "WARN")

        # Start the maintenance check timer if not already running
        if not hasattr(self, '_maint_check_running') or not self._maint_check_running:
            self._maint_check_running = True
            self._check_maintenance_timers()

    def _exit_maintenance(self, ips):
        """Remove IPs from maintenance mode."""
        self.maintenance_ips -= ips
        for ip in ips:
            if ip in self.status_indicators:
                canvas, oval = self.status_indicators[ip]
                canvas.itemconfig(oval, fill=COLORS["yellow"])
            if ip in self.status_labels:
                self.status_labels[ip].configure(text="...")
            self.maintenance_timers.pop(ip, None)
        self.event_log.log(f"✅ Maintenance OFF: {', '.join(ips)}", "OK")

    def _check_maintenance_timers(self):
        """Check if any maintenance windows have expired — remind the user."""
        if not self.running:
            self._maint_check_running = False
            return

        now = time.time()
        expired_ips = []

        for ip, info in list(self.maintenance_timers.items()):
            if ip not in self.maintenance_ips:
                # Already exited maintenance
                self.maintenance_timers.pop(ip, None)
                continue

            if now >= info["end"]:
                if info.get("no_limit"):
                    # No-limit mode: remind every hour, reset timer
                    expired_ips.append(ip)
                    info["end"] = now + 3600  # next reminder in 1 hour
                    info["reminded"] = False
                else:
                    # Timed mode: window expired
                    expired_ips.append(ip)

        if expired_ips:
            # Find display names for the expired IPs
            names = []
            for ip in expired_ips:
                display = ip
                for _card, _node in self.all_cards:
                    if _node is None:
                        continue
                    if (_node.get("ip") or "") == ip:
                        display = f"{_node.get('name', '')} ({ip})"
                        break
                    for h in _node.get("hosts", []):
                        if h.get("ip", "") == ip:
                            display = f"{_node.get('name', '')} > {h.get('label', '')} ({ip})"
                            break
                    if display != ip:
                        break
                names.append(display)

            name_str = "\n".join(names)
            self.event_log.log(
                f"⚠️ Maintenance window expired: {', '.join(expired_ips)}", "WARN")

            # Alert sound
            if self.alerts_enabled:
                try:
                    for _ in range(3):
                        winsound.Beep(1000, 300)
                        winsound.Beep(1500, 300)
                        time.sleep(0.1)
                except Exception:
                    pass

            # SMS reminder
            if self.sms_config.get("enabled"):
                from datetime import datetime as _dt
                timestamp = _dt.now().strftime("%I:%M %p")
                subject = "NOC: Maintenance Reminder"
                body = (f"[NOC REMINDER] The following servers are STILL in "
                        f"maintenance mode at {timestamp}:\n\n{name_str}\n\n"
                        f"Don't forget to exit maintenance mode when done!")
                try:
                    send_sms_alert(self.sms_config, subject, body)
                except Exception:
                    pass

            # Show popup reminder
            answer = messagebox.askyesno(
                "⚠️ Maintenance Window Expired",
                f"The maintenance window has expired for:\n\n"
                f"{name_str}\n\n"
                f"These servers are STILL in maintenance mode.\n"
                f"Alerts are suppressed — you won't be notified if they go down!\n\n"
                f"Exit maintenance mode now?",
                icon="warning",
            )
            if answer:
                self._exit_maintenance(set(expired_ips))

        # Keep checking every 30 seconds if there are active timers
        if self.maintenance_timers and self.running:
            self.root.after(30000, self._check_maintenance_timers)
        else:
            self._maint_check_running = False

    def _copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def _manual_ping(self, ip):
        subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", f"ping {ip} -t"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def _traceroute(self, ip):
        self.event_log.log(f"Traceroute started to {ip}", "INFO")
        subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", f"tracert {ip}"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def _nslookup(self, ip):
        self.event_log.log(f"NSLookup started for {ip}", "INFO")
        subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", f"nslookup {ip}"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def _port_scan(self, ip):
        """Scan common ports on a host and show results."""
        self.event_log.log(f"Port scan started on {ip}", "INFO")

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Port Scan — {ip}")
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 420, 500, self.root)
        dlg.resizable(False, True)

        tk.Label(dlg, text=f"\U0001F50D Scanning {ip}...",
                 font=("Consolas", 11, "bold"), fg=COLORS["accent"],
                 bg=COLORS["card_bg"]).pack(pady=(15, 5))

        progress_var = tk.StringVar(value="Starting scan...")
        progress_lbl = tk.Label(dlg, textvariable=progress_var,
                                font=("Consolas", 8), fg=COLORS["text_dim"],
                                bg=COLORS["card_bg"])
        progress_lbl.pack()

        results_frame = tk.Frame(dlg, bg=COLORS["card_bg"])
        results_frame.pack(fill="both", expand=True, padx=15, pady=10)

        results_text = tk.Text(
            results_frame, font=("Consolas", 9), bg=COLORS["log_bg"],
            fg=COLORS["text"], state="disabled", wrap="word",
        )
        results_text.pack(fill="both", expand=True)
        results_text.tag_configure("open", foreground=COLORS["green"])
        results_text.tag_configure("closed", foreground=COLORS["text_dim"])
        results_text.tag_configure("header", foreground=COLORS["accent"])

        def do_scan():
            ports = sorted(COMMON_PORTS.keys())
            open_ports = []
            for i, port in enumerate(ports):
                progress_var.set(f"Scanning port {port}/{ports[-1]} ({i + 1}/{len(ports)})")
                is_open = scan_port(ip, port, timeout=0.5)
                service = COMMON_PORTS[port]
                line = f"  Port {port:>5}  ({service:>12})  —  {'OPEN' if is_open else 'closed'}\n"
                tag = "open" if is_open else "closed"

                if is_open:
                    open_ports.append((port, service))

                dlg.after(0, lambda l=line, t=tag: _add_result(l, t))

            summary = f"\n  Scan complete: {len(open_ports)}/{len(ports)} ports open"
            dlg.after(0, lambda: _add_result(summary + "\n", "header"))
            dlg.after(0, lambda: progress_var.set("Scan complete!"))

            self.event_log.log(
                f"Port scan on {ip}: {len(open_ports)} open — "
                + ", ".join(f"{p}({s})" for p, s in open_ports),
                "OK" if open_ports else "WARN",
            )

        def _add_result(line, tag):
            results_text.configure(state="normal")
            results_text.insert("end", line, tag)
            results_text.see("end")
            results_text.configure(state="disabled")

        threading.Thread(target=do_scan, daemon=True).start()

    def _wake_on_lan(self, node):
        mac = node.get("mac", "")
        if not mac:
            messagebox.showinfo("WOL", "No MAC address set for this server.\nEdit the server to add one.")
            return
        try:
            send_wol(mac)
            self.event_log.log(f"Wake-on-LAN sent to {node['name']} ({mac})", "OK")
            messagebox.showinfo("WOL", f"Magic packet sent to {mac}\n\nServer should wake up shortly.")
        except Exception as e:
            self.event_log.log(f"WOL failed for {node['name']}: {e}", "ERROR")
            messagebox.showerror("WOL Error", f"Could not send magic packet:\n{e}")

    def _map_network_drive(self, ip, share_name, saved_user=None, saved_pass=None):
        map_share(ip, share_name, saved_user, saved_pass)

    def _add_card_hover(self, card):
        def on_enter(e):
            card.configure(highlightbackground=COLORS["accent"])
        def on_leave(e):
            card.configure(highlightbackground=COLORS["card_border"])
        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)

    # ── Server Management ─────────────────────────────────────────────────────

    def _add_server(self):
        dialog = ServerDialog(self.root, title="Add Server")
        if dialog.result:
            self.nodes.append(dialog.result)
            save_config(self.nodes)
            self.event_log.log(f"Server added: {dialog.result['name']}", "OK")
            self._rebuild_all_cards()

    def _edit_server(self, node):
        dialog = ServerDialog(self.root, title=f"Edit: {node['name']}", node=node)
        if dialog.result:
            idx = self.nodes.index(node)
            self.nodes[idx] = dialog.result
            save_config(self.nodes)
            self.event_log.log(f"Server updated: {dialog.result['name']}", "INFO")
            self._rebuild_all_cards()

    def _delete_server(self, node):
        if messagebox.askyesno("Delete Server",
                               f"Are you sure you want to delete \"{node['name']}\"?\n\n"
                               "This cannot be undone.", icon="warning"):
            # Clean up tracking dicts for this node's IPs
            ips_to_clean = set()
            if node.get("ip"):
                ips_to_clean.add(node["ip"])
            for h in node.get("hosts", []):
                if h.get("ip"):
                    ips_to_clean.add(h["ip"])
            for old_ip in ips_to_clean:
                self.ping_history.pop(old_ip, None)
                self.node_statuses.pop(old_ip, None)
                self.prev_statuses.pop(old_ip, None)
                self.uptime_data.pop(old_ip, None)
                self.uptime_labels.pop(old_ip, None)
                self.status_indicators.pop(old_ip, None)
                self.status_labels.pop(old_ip, None)
                self.sparkline_canvases.pop(old_ip, None)
                self.disk_alert_labels.pop(old_ip, None)
                self.disk_alerts.pop(old_ip, None)
                self.uptime_history.pop(old_ip, None)
                self.maintenance_ips.discard(old_ip)
                self.maintenance_timers.pop(old_ip, None)

            self.nodes.remove(node)
            save_config(self.nodes)
            self.event_log.log(f"Server deleted: {node['name']}", "WARN")
            self._rebuild_all_cards()

    def _duplicate_server(self, node):
        new_node = copy.deepcopy(node)
        new_node["name"] = f"{node['name']} (Copy)"
        self.nodes.append(new_node)
        save_config(self.nodes)
        self.event_log.log(f"Server duplicated: {node['name']}", "INFO")
        self._rebuild_all_cards()

    def _rebuild_all_cards(self):
        self.status_indicators.clear()
        self.status_labels.clear()
        self.node_statuses.clear()
        self.sparkline_canvases.clear()
        self.uptime_labels.clear()
        self.disk_alert_labels.clear()
        self.all_cards.clear()

        self.grid_frame.destroy()
        self._build_cards()
        self._refresh_tag_list()
        self._refresh_now()

    def _show_config_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                       activebackground=COLORS["accent"], activeforeground="white",
                       font=("Consolas", 9))

        # ── Check-in Interval submenu ──
        interval_menu = tk.Menu(menu, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                                activebackground=COLORS["accent"], activeforeground="white",
                                font=("Consolas", 9))
        intervals = [
            ("15 seconds", 15),
            ("30 seconds", 30),
            ("1 minute",   60),
            ("2 minutes",  120),
            ("5 minutes",  300),
            ("10 minutes", 600),
        ]
        for label, secs in intervals:
            check = " ✓" if self.ping_interval == secs else ""
            interval_menu.add_command(
                label=f"  {label}{check}",
                command=lambda s=secs: self._set_ping_interval(s),
            )
        menu.add_cascade(label="⏱  Check-in Interval", menu=interval_menu)
        menu.add_separator()

        # ── SMS Alerts ──
        sms_status = "ON ✓" if self.sms_config.get("enabled") else "OFF"
        sms_count = len(self.sms_config.get("recipients", []))
        menu.add_command(
            label=f"📱  SMS Text Alerts ({sms_status}, {sms_count} phones)",
            command=self._show_sms_settings,
        )
        menu.add_separator()

        menu.add_command(label="\u270F\uFE0F  Edit Config File (JSON)...", command=self._edit_config_file)
        menu.add_separator()
        menu.add_command(label="\U0001F4BE  Export Config...", command=self._export_config)
        menu.add_command(label="\U0001F4C2  Import Config...", command=self._import_config)
        menu.add_separator()
        menu.add_command(label="\U0001F4DC  Open Event Log File",
                         command=lambda: os.startfile(LOG_FILE) if os.path.exists(LOG_FILE)
                         else messagebox.showinfo("Log", "No log file yet."))
        menu.add_separator()
        menu.add_command(label="\U0001F504  Reset to Defaults", command=self._reset_defaults)
        menu.add_separator()
        menu.add_command(label=f"\U0001F4C4  Copy Config Path",
                         command=lambda: self._copy_to_clipboard(CONFIG_FILE))
        menu.add_command(label=f"     {CONFIG_FILE}", state="disabled")
        menu.add_separator()
        # ── Launch REGTeches Tools submenu ──
        tools_menu = tk.Menu(menu, tearoff=0, bg=COLORS["card_bg"], fg=COLORS["text"],
                             activebackground=COLORS["accent"], activeforeground="white",
                             font=("Consolas", 9))
        for tool_name, tool_path in REGTECHES_TOOLS:
            if os.path.exists(tool_path):
                tools_menu.add_command(
                    label=f"  {tool_name}",
                    command=lambda n=tool_name, p=tool_path: self._launch_tool(n, p),
                )
            else:
                tools_menu.add_command(label=f"  {tool_name}  (not found)", state="disabled")
        menu.add_cascade(label="\U0001F680  Launch REGTeches Tools", menu=tools_menu)
        menu.add_separator()

        menu.add_command(label="\U0001F4CB  Master Report (All Servers)",
                         command=self._generate_master_report)
        menu.add_separator()
        menu.add_command(label="\U0001F4D6  User Manual", command=self._show_manual)
        menu.add_command(label="\u2139\uFE0F  About", command=self._show_about)
        menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def _set_ping_interval(self, seconds):
        """Change how often the dashboard checks server status."""
        self.ping_interval = seconds
        self.countdown_seconds = seconds  # reset countdown to new interval
        if seconds < 60:
            label = f"{seconds}s"
        else:
            label = f"{seconds // 60}m"
        self.event_log.log(f"Check-in interval changed to {label}", "OK")
        # Update the status bar immediately to show new countdown
        online = sum(1 for v in self.node_statuses.values() if v)
        total = len(self.node_statuses) if self.node_statuses else len(self.status_indicators)
        if total > 0:
            self.summary_label.configure(
                text=f"  \u25CF  {online}/{total} nodes online  |  Next check in {self.countdown_seconds}s",
            )

    def _edit_config_file(self):
        """Open the JSON config in a built-in editor so you can edit it directly."""
        # Make sure current config is saved to disk first
        save_config(self.nodes)

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Edit Config — {CONFIG_FILE}")
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 700, 600, self.root)
        dlg.minsize(500, 400)

        # Header showing file path
        path_frame = tk.Frame(dlg, bg=COLORS["header_bg"], pady=6)
        path_frame.pack(fill="x")

        tk.Label(path_frame, text="\U0001F4C4  Config File:",
                 font=("Consolas", 9, "bold"), fg=COLORS["accent"],
                 bg=COLORS["header_bg"]).pack(side="left", padx=(10, 5))

        tk.Label(path_frame, text=CONFIG_FILE,
                 font=("Consolas", 8), fg=COLORS["text"],
                 bg=COLORS["header_bg"]).pack(side="left")

        # Buttons bar
        btn_bar = tk.Frame(dlg, bg=COLORS["header_bg"], pady=6)
        btn_bar.pack(fill="x")

        def save_and_reload():
            try:
                new_text = editor.get("1.0", tk.END).strip()
                data = json.loads(new_text)
                nodes = data.get("nodes")
                if nodes is None:
                    messagebox.showerror("Invalid Config",
                                         "JSON is valid but missing 'nodes' key.",
                                         parent=dlg)
                    return
                # Write to file
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    f.write(new_text)
                # Reload into dashboard
                self.nodes = nodes
                self.event_log.log(f"Config file edited and reloaded ({len(nodes)} nodes)", "OK")
                self._rebuild_all_cards()
                dlg.destroy()
            except json.JSONDecodeError as e:
                messagebox.showerror("JSON Error",
                                     f"Invalid JSON — fix the error and try again:\n\n{e}",
                                     parent=dlg)
                # Highlight the error line
                try:
                    line = e.lineno
                    editor.tag_remove("json_error", "1.0", "end")
                    editor.tag_add("json_error", f"{line}.0", f"{line}.end")
                    editor.see(f"{line}.0")
                except Exception:
                    pass

        def open_in_notepad():
            try:
                subprocess.Popen(["notepad.exe", CONFIG_FILE])
            except Exception as ex:
                messagebox.showerror("Error", f"Could not open Notepad:\n{ex}", parent=dlg)

        tk.Button(btn_bar, text="\U0001F4BE  Save & Reload",
                  font=("Consolas", 10, "bold"), bg=COLORS["green"], fg="white",
                  relief="flat", padx=15, pady=4, cursor="hand2",
                  command=save_and_reload).pack(side="left", padx=(10, 5))

        tk.Button(btn_bar, text="Open in Notepad",
                  font=("Consolas", 9), bg=COLORS["share_bg"], fg=COLORS["text"],
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=open_in_notepad).pack(side="left", padx=5)

        tk.Button(btn_bar, text="Cancel",
                  font=("Consolas", 9), bg=COLORS["share_bg"], fg=COLORS["text"],
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=dlg.destroy).pack(side="left", padx=5)

        status_lbl = tk.Label(btn_bar, text="", font=("Consolas", 8),
                              fg=COLORS["text_dim"], bg=COLORS["header_bg"])
        status_lbl.pack(side="right", padx=10)

        # Editor area with line numbers
        editor_frame = tk.Frame(dlg, bg=COLORS["log_bg"])
        editor_frame.pack(fill="both", expand=True, padx=5, pady=5)

        editor_scroll = ttk.Scrollbar(editor_frame, orient="vertical")
        editor_scroll.pack(side="right", fill="y")

        editor = tk.Text(
            editor_frame, font=("Consolas", 10), bg=COLORS["log_bg"],
            fg=COLORS["text"], insertbackground=COLORS["text_bright"],
            wrap="none", undo=True, relief="flat",
            yscrollcommand=editor_scroll.set,
        )
        editor.pack(fill="both", expand=True)
        editor_scroll.configure(command=editor.yview)

        # Error highlight tag
        editor.tag_configure("json_error", background=COLORS["btn_danger"],
                             foreground="white")

        # Load current file content
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            content = json.dumps({"version": 2, "saved": datetime.now().isoformat(),
                                  "nodes": self.nodes}, indent=2, ensure_ascii=False)

        editor.insert("1.0", content)

        # Count info
        try:
            data = json.loads(content)
            count = len(data.get("nodes", []))
            status_lbl.configure(text=f"{count} nodes  |  {len(content)} chars")
        except Exception:
            status_lbl.configure(text=f"{len(content)} chars")

    def _export_config(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export NOC Config",
        )
        if path:
            data = {"version": 2, "saved": datetime.now().isoformat(), "nodes": self.nodes}
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self.event_log.log(f"Config exported to {path}", "OK")
                messagebox.showinfo("Exported", f"Config saved to:\n{path}")
            except IOError as e:
                messagebox.showerror("Export Error", str(e))

    def _import_config(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import NOC Config",
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                nodes = data.get("nodes", [])
                if not nodes:
                    messagebox.showwarning("Empty Config", "No nodes found in the file.")
                    return
                if messagebox.askyesno("Import Config",
                                       f"Replace current config with {len(nodes)} nodes from file?"):
                    self.nodes = nodes
                    save_config(self.nodes)
                    self.event_log.log(f"Config imported: {len(nodes)} nodes from {path}", "OK")
                    self._rebuild_all_cards()
            except (json.JSONDecodeError, IOError) as e:
                messagebox.showerror("Import Error", f"Could not read config:\n{e}")

    def _reset_defaults(self):
        if messagebox.askyesno("Reset to Defaults",
                               "This will replace all servers with the built-in defaults.\nContinue?",
                               icon="warning"):
            self.nodes = copy.deepcopy(DEFAULT_NODES)
            save_config(self.nodes)
            self.event_log.log("Config reset to defaults", "WARN")
            self._rebuild_all_cards()

    def _show_about(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("About REGTeches NOC Dashboard")
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 520, 620, self.root)
        dlg.resizable(False, False)
        dlg.grab_set()

        # Scrollable content
        canvas = tk.Canvas(dlg, bg=COLORS["card_bg"], highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        inner = tk.Frame(canvas, bg=COLORS["card_bg"])
        cw_id = canvas.create_window((0, 0), window=inner, anchor="n")

        def _center_inner(event=None):
            canvas.coords(cw_id, event.width // 2 if event else 260, 0)
        canvas.bind("<Configure>", _center_inner)

        # App icon
        if self.app_icon_img:
            tk.Label(inner, image=self.app_icon_img,
                     bg=COLORS["card_bg"]).pack(pady=(20, 5))
        else:
            tk.Label(inner, text="\U0001F6E1\uFE0F", font=("Segoe UI", 36),
                     bg=COLORS["card_bg"]).pack(pady=(20, 5))

        tk.Label(inner, text=APP_NAME, font=("Consolas", 18, "bold"),
                 fg=COLORS["accent"], bg=COLORS["card_bg"]).pack()

        tk.Label(inner, text=f"Version {APP_VERSION}", font=("Consolas", 10),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).pack(pady=(2, 5))

        tk.Label(inner, text="Built with Python & tkinter", font=("Consolas", 8),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).pack(pady=(0, 15))

        tk.Frame(inner, bg=COLORS["accent"], height=2).pack(fill="x", padx=40)

        tk.Label(inner, text="Developed by", font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["card_bg"]).pack(pady=(15, 2))

        tk.Label(inner, text=APP_AUTHOR, font=("Consolas", 16, "bold"),
                 fg=COLORS["text_bright"], bg=COLORS["card_bg"]).pack()

        tk.Label(inner, text="REGTeches", font=("Consolas", 12, "bold"),
                 fg=COLORS["accent"], bg=COLORS["card_bg"]).pack(pady=(2, 3))

        tk.Label(inner, text="Technology Solutions & IT Infrastructure",
                 font=("Consolas", 8), fg=COLORS["text_dim"],
                 bg=COLORS["card_bg"]).pack(pady=(0, 15))

        tk.Frame(inner, bg=COLORS["accent"], height=2).pack(fill="x", padx=40)

        # Feature list
        features = (
            "FEATURES\n\n"
            "\u2022  Real-time server monitoring with configurable check-ins\n"
            "\u2022  Multi-protocol: SMB, FTP, FTPS, RDP, SSH, Telnet, HTTP/S\n"
            "\u2022  SMS text alerts via email-to-SMS (13 carriers supported)\n"
            "\u2022  Ping sparkline history & uptime percentage tracking\n"
            "\u2022  Network share browsing & drive letter mapping\n"
            "\u2022  Saved credentials per share (auto-authentication)\n"
            "\u2022  Port scanning & network diagnostics (traceroute, nslookup)\n"
            "\u2022  Wake-on-LAN magic packet support\n"
            "\u2022  Sub-host monitoring with per-host protocol support\n"
            "\u2022  Maintenance mode (suppress alerts during work)\n"
            "\u2022  Server tagging, filtering, and search\n"
            "\u2022  Activity event log with file persistence\n"
            "\u2022  Full JSON config import/export & built-in editor\n"
            "\u2022  Dark theme NOC-style interface"
        )
        tk.Label(inner, text=features, font=("Consolas", 8),
                 fg=COLORS["text"], bg=COLORS["card_bg"], justify="left").pack(pady=(15, 10))

        tk.Frame(inner, bg=COLORS["card_border"], height=1).pack(fill="x", padx=40)

        # Live stats
        online = sum(1 for ip, v in self.node_statuses.items()
                     if v and ip not in self.maintenance_ips)
        maint = sum(1 for ip in self.node_statuses if ip in self.maintenance_ips)
        total = len(self.nodes)
        stats = f"Managing {total} servers  |  {online} online"
        if maint:
            stats += f"  |  {maint} in maintenance"
        tk.Label(inner, text=stats, font=("Consolas", 9, "bold"),
                 fg=COLORS["green"], bg=COLORS["card_bg"]).pack(pady=(10, 5))

        tk.Label(inner, text="\u00A9 2025-2026 REGTeches. All rights reserved.",
                 font=("Consolas", 7), fg=COLORS["text_dim"],
                 bg=COLORS["card_bg"]).pack(pady=(5, 15))

        # Buttons
        btn_frame = tk.Frame(inner, bg=COLORS["card_bg"])
        btn_frame.pack(pady=(0, 20))
        tk.Button(btn_frame, text="\U0001F4D6 User Manual", font=("Consolas", 9, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat",
                  padx=15, pady=5, command=self._show_manual, cursor="hand2").pack(side="left", padx=5)
        tk.Button(btn_frame, text="Close", font=("Consolas", 9),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=20, pady=5, command=dlg.destroy, cursor="hand2").pack(side="left", padx=5)

        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _show_manual(self):
        """Show the full user manual in a scrollable window."""
        dlg = tk.Toplevel(self.root)
        dlg.title("NOC Dashboard - User Manual")
        dlg.configure(bg=COLORS["card_bg"])
        _center_dialog(dlg, 700, 650, self.root)
        dlg.resizable(True, True)
        dlg.grab_set()

        # Header
        hdr = tk.Frame(dlg, bg=COLORS["accent"], padx=15, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="\U0001F4D6  REGTeches NOC Dashboard — User Manual",
                 font=("Consolas", 13, "bold"), fg="white",
                 bg=COLORS["accent"]).pack(side="left")
        tk.Label(hdr, text=f"v{APP_VERSION}", font=("Consolas", 9),
                 fg="#B0BEC5", bg=COLORS["accent"]).pack(side="right")

        # Scrollable text area
        text_frame = tk.Frame(dlg, bg=COLORS["card_bg"])
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        manual_text = tk.Text(
            text_frame, wrap="word", font=("Consolas", 9),
            bg=COLORS["bg"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat",
            padx=15, pady=15, spacing1=2, spacing3=2,
            yscrollcommand=scrollbar.set,
        )
        manual_text.pack(fill="both", expand=True)
        scrollbar.config(command=manual_text.yview)

        # Configure text tags for formatting
        manual_text.tag_configure("h1", font=("Consolas", 14, "bold"),
                                  foreground=COLORS["accent"], spacing1=15, spacing3=5)
        manual_text.tag_configure("h2", font=("Consolas", 11, "bold"),
                                  foreground=COLORS["text_bright"], spacing1=12, spacing3=4)
        manual_text.tag_configure("h3", font=("Consolas", 10, "bold"),
                                  foreground=COLORS["accent"], spacing1=8, spacing3=3)
        manual_text.tag_configure("body", font=("Consolas", 9),
                                  foreground=COLORS["text"])
        manual_text.tag_configure("bullet", font=("Consolas", 9),
                                  foreground=COLORS["text"], lmargin1=20, lmargin2=35)
        manual_text.tag_configure("tip", font=("Consolas", 8, "italic"),
                                  foreground=COLORS["green"])
        manual_text.tag_configure("warn", font=("Consolas", 8, "italic"),
                                  foreground=COLORS["yellow"])
        manual_text.tag_configure("key", font=("Consolas", 9, "bold"),
                                  foreground=COLORS["accent"])

        def h1(text): manual_text.insert("end", text + "\n", "h1")
        def h2(text): manual_text.insert("end", text + "\n", "h2")
        def h3(text): manual_text.insert("end", text + "\n", "h3")
        def p(text): manual_text.insert("end", text + "\n\n", "body")
        def bullet(text): manual_text.insert("end", f"  \u2022  {text}\n", "bullet")
        def tip(text): manual_text.insert("end", f"  \U0001F4A1 TIP: {text}\n\n", "tip")
        def warn(text): manual_text.insert("end", f"  \u26A0 {text}\n\n", "warn")
        def key(text): manual_text.insert("end", f"  {text}\n", "key")
        def br(): manual_text.insert("end", "\n")

        # ── MANUAL CONTENT ──
        h1("GETTING STARTED")
        p("The REGTeches NOC Dashboard is a real-time Network Operations Center tool "
          "for monitoring servers, services, and network devices on your infrastructure. "
          "It provides at-a-glance status for all your servers with visual indicators, "
          "alerts, and quick-access connection tools.")

        h2("Dashboard Layout")
        bullet("Top Bar: Search/filter, tag dropdown, summary status, and settings gear")
        bullet("Main Area: Server cards in a responsive grid (auto-adjusts to window width)")
        bullet("Bottom Panel: Activity log (toggle with Ctrl+L)")
        br()

        h1("ADDING SERVERS")
        h2("Add a New Server")
        p("Click the + Add Server button or press Ctrl+N to open the server dialog.")
        h3("Server Fields:")
        bullet("Server Name: A friendly name (e.g. 'Plex Media Server')")
        bullet("IP Address: The server's IP or hostname (e.g. 192.168.1.161)")
        bullet("Connection Types: Add one or more protocols (SMB, FTP, FTPS, RDP, SSH, Telnet, HTTP, HTTPS, Custom)")
        bullet("Each connection type has its own port number")
        bullet("Management URL: Optional web interface link (e.g. http://192.168.1.161:32400/web)")
        bullet("Management Label: Button text for the manage link (e.g. 'Plex Interface')")
        bullet("Tags: Comma-separated labels for filtering (e.g. media, production)")
        bullet("Notes: Free-text notes about the server")
        bullet("MAC Address: For Wake-on-LAN support (e.g. AA:BB:CC:DD:EE:FF)")
        br()

        h2("Editing & Deleting")
        bullet("Right-click any server card to Edit, Duplicate, or Delete")
        bullet("All changes are auto-saved to noc_config.json")
        br()

        h1("NETWORK SHARES (DRIVES)")
        h2("Adding Shares")
        p("In the Add/Edit Server dialog, scroll to the Shares section. Each share needs:")
        bullet("Share Name: The network share name (e.g. 'Media' or 'C')")
        bullet("Icon: Pick a visual icon from the emoji grid")
        bullet("Label: Display text shown on the button")
        bullet("Username/Password: Optional saved credentials for auto-authentication")
        warn("Credentials are stored in plain text in the JSON config. Use at your own risk.")
        br()

        h2("Using Shares")
        bullet("Left-click a share: Browse it in Windows Explorer (temporary, no drive mapping)")
        bullet("Right-click a share: Context menu with 'Map drive letter' to assign a drive letter")
        tip("When you close the Explorer window from a left-click, the connection is gone. "
            "Use right-click > Map Drive to keep it permanently.")
        br()

        h1("SUB-HOSTS (CLUSTER MONITORING)")
        p("Sub-hosts let you monitor multiple IPs/services inside one server card. "
          "Perfect for VM clusters, multi-service boxes, or grouping related devices.")
        h2("Adding Sub-Hosts")
        bullet("In Add/Edit Server, go to the Hosts section and click Add Host")
        bullet("Enter the IP address, a label, protocol (http/https/rdp/ssh/telnet/vnc), and optional port")
        bullet("Each sub-host gets its own independent status dot and ping monitoring")
        h2("Example Uses")
        bullet("Proxmox host with 5 VMs: Main IP = Proxmox, sub-hosts = each VM")
        bullet("Multi-service server: Sub-hosts for web (443), Plex (32400), game server (25565)")
        bullet("Static monitoring group: No main IP, just a collection of IPs to watch")
        br()

        h1("MONITORING & STATUS")
        h2("Status Indicators")
        bullet("\U0001F7E2 Green dot = Online (responding to ping)")
        bullet("\U0001F534 Red dot = Offline (not responding)")
        bullet("\U0001F7E1 Yellow dot = Unknown/checking")
        bullet("\U0001F535 Blue dot = Maintenance mode (alerts suppressed)")
        br()

        h2("Check-in Interval")
        p("Click the gear icon and select 'Check-in Interval' to change how often "
          "servers are pinged. Options: 15s, 30s, 1m, 2m, 5m, 10m.")
        tip("For critical servers, use 15-30 seconds. For general monitoring, 1-2 minutes saves resources.")
        br()

        h2("Sparkline & Uptime")
        bullet("Each server shows a mini latency graph (sparkline) of recent ping times")
        bullet("Uptime percentage tracks how often the server has been online since dashboard start")
        br()

        h1("MAINTENANCE MODE")
        p("When you need to reboot, update, or work on a server, put it in "
          "Maintenance Mode so you don't get flooded with offline alerts.")
        bullet("Right-click a server card > 'Enter Maintenance Mode'")
        bullet("Status dot turns blue and shows 'MAINT'")
        bullet("No beeps, no SMS alerts, no flashing for that server")
        bullet("Right-click again > 'Exit Maintenance Mode' to resume normal monitoring")
        bullet("The summary bar shows how many servers are in maintenance")
        tip("Always enable maintenance mode BEFORE taking a server offline for planned work.")
        br()

        h1("SMS TEXT ALERTS")
        h2("Setup")
        bullet("Click the gear icon > 'SMS Text Alerts'")
        bullet("Enter your Gmail address and an App Password (not your regular password)")
        bullet("App Password: Go to myaccount.google.com/apppasswords, create one for 'NOC Dashboard'")
        bullet("Add phone numbers with their carrier (AT&T, T-Mobile, Verizon, Comcast/Xfinity, etc.)")
        bullet("Enable/disable alerts for offline events, online events, or both")
        bullet("Set a cooldown period to prevent alert spam (default: 5 minutes)")
        br()

        h2("Supported Carriers")
        bullet("AT&T, T-Mobile, Verizon, Sprint, Boost Mobile, Cricket, Metro PCS")
        bullet("U.S. Cellular, Virgin Mobile, Google Fi, Mint Mobile, Visible")
        bullet("Xfinity / Comcast Mobile")
        br()

        h2("Alert Messages")
        bullet("Offline: '[NOC ALERT] ServerName (IP) went OFFLINE at 3:28 PM'")
        bullet("Online: '[NOC] ServerName (IP) is back ONLINE at 3:30 PM (43ms)'")
        tip("Use 'Send Test' button to verify your setup before relying on it.")
        br()

        h1("NETWORK TOOLS")
        p("Right-click any server card to access network diagnostic tools:")
        bullet("Ping (continuous): Opens a terminal window with 'ping -t' running")
        bullet("Traceroute: Shows the network path to the server")
        bullet("NSLookup: DNS lookup for the server's IP/hostname")
        bullet("Port Scan: Scans common ports (FTP, SSH, HTTP, HTTPS, SMB, RDP, MySQL, etc.)")
        bullet("Wake-on-LAN: Sends a magic packet to wake up a sleeping/powered-off server")
        br()

        h1("CONNECTION METHODS")
        p("Click a connection type badge on a server card to connect:")
        bullet("SMB: Opens Windows Explorer to the server's file shares")
        bullet("RDP: Launches Remote Desktop Connection (mstsc)")
        bullet("SSH: Opens a terminal with SSH to the server")
        bullet("Telnet: Opens a terminal with Telnet connection")
        bullet("HTTP/HTTPS: Opens the server's web interface in your browser")
        bullet("FTP/FTPS: Opens the FTP address in your browser or default FTP client")
        br()

        h1("CONFIGURATION")
        h2("JSON Config File")
        bullet("All server data is stored in noc_config.json")
        bullet("Gear icon > 'Edit Raw JSON' to view/edit the config directly")
        bullet("Gear icon > 'Import Config' / 'Export Config' for backup/restore")
        bullet("Gear icon > 'Copy Config Path' to get the file location")
        br()

        h2("Import / Export")
        p("Use Export to back up your configuration before making big changes. "
          "Use Import to load a config from another machine or restore from backup.")
        tip("Export your config after adding all your servers. Keep the backup somewhere safe!")
        br()

        h1("KEYBOARD SHORTCUTS")
        key("Ctrl+N     Add new server")
        key("Ctrl+R     Refresh all cards")
        key("Ctrl+F     Focus search box")
        key("Ctrl+L     Toggle activity log panel")
        key("Escape     Clear search filter")
        br()

        h1("TROUBLESHOOTING")
        h2("Server shows offline but is running")
        bullet("Check if the IP is correct in the server settings")
        bullet("IPs with ports (e.g. 192.168.1.87:8006) — the port is stripped for ping")
        bullet("Hostnames that resolve to IPv6 are supported")
        bullet("Windows Firewall on the target may block ICMP ping requests")
        br()

        h2("Share drive prompts for login even with saved credentials")
        bullet("Make sure the username format is correct (e.g. 'admin' not 'DOMAIN\\\\admin')")
        bullet("Try the credentials manually: net use \\\\\\\\server\\\\share /user:name password")
        bullet("Check if another mapping to the same server exists (net use to see all)")
        br()

        h2("SMS alerts not sending")
        bullet("Verify Gmail App Password (not your regular Google password)")
        bullet("Make sure 2-Step Verification is enabled on your Google account")
        bullet("Check the carrier selection matches your phone provider")
        bullet("Use 'Send Test' to check for error messages")
        bullet("Check cooldown period — alerts won't repeat within the cooldown window")
        br()

        h1("CREDITS")
        p(f"Developed by {APP_AUTHOR}")
        p("REGTeches - Technology Solutions & IT Infrastructure")
        p(f"\u00A9 2025-2026 REGTeches. All rights reserved.")

        manual_text.configure(state="disabled")  # read-only

        # Close button
        tk.Button(dlg, text="Close", font=("Consolas", 10),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=25, pady=5, command=dlg.destroy, cursor="hand2").pack(pady=(0, 10))

    # ── Filter / Search ──────────────────────────────────────────────────────

    def _on_filter_change(self, *args):
        query = self.filter_var.get().lower().strip()
        tag_filter = self.tag_filter_var.get()

        for card, node in self.all_cards:
            # Text filter
            text_match = True
            if query:
                searchable = node["name"].lower()
                if node.get("ip"):
                    searchable += " " + node["ip"]
                for conn in _get_connections(node):
                    searchable += " " + conn.get("type", "").lower()
                searchable += " " + " ".join(node.get("tags", []))
                for s in node.get("shares", []):
                    searchable += " " + s["name"].lower() + " " + s.get("label", "").lower()
                for h in node.get("hosts", []):
                    searchable += " " + h["ip"] + " " + h["label"].lower()
                text_match = query in searchable

            # Tag filter — only filter if an actual tag is selected (not "All..." entries)
            tag_match = True
            if tag_filter and not tag_filter.startswith("All"):
                tag_match = tag_filter in node.get("tags", [])

            if text_match and tag_match:
                card.grid()
            else:
                card.grid_remove()

    def _clear_filter(self):
        self.filter_var.set("")
        vals = list(self.tag_combo["values"])
        self.tag_filter_var.set(vals[0] if vals else "All Servers")
        self.search_entry.selection_clear()
        self.root.focus_set()

    # ── Ping / Status Loop ───────────────────────────────────────────────────

    def _start_ping_loop(self):
        self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self.ping_thread.start()

    def _start_countdown(self):
        """Tick the countdown timer every second."""
        if not self.running:
            return
        self.countdown_seconds -= 1
        if self.countdown_seconds < 0:
            self.countdown_seconds = self.ping_interval

        # Update summary label with countdown
        online = sum(1 for ip, v in self.node_statuses.items()
                     if v and ip not in self.maintenance_ips)
        maint = sum(1 for ip in self.node_statuses if ip in self.maintenance_ips)
        total = len(self.node_statuses) if self.node_statuses else len(self.status_indicators)
        active = total - maint
        if total > 0:
            maint_str = f"  |  🔧 {maint} maintenance" if maint else ""
            self.summary_label.configure(
                text=f"  \u25CF  {online}/{active} nodes online{maint_str}  |  Next check in {self.countdown_seconds}s",
                fg=COLORS["green"] if online == active else COLORS["yellow"],
            )

        self.root.after(1000, self._start_countdown)

    def _ping_loop(self):
        while self.running:
            all_keys = list(self.status_indicators.keys())
            threads = []
            # Cache ping results per base IP so we don't ping the same IP multiple times
            ping_cache = {}
            ping_cache_lock = threading.Lock()

            def check_key(key):
                # key is either "192.168.1.161" or "192.168.1.161:8989"
                if ":" in key and not key.startswith("["):
                    parts = key.rsplit(":", 1)
                    base_ip = parts[0]
                    try:
                        port = int(parts[1])
                    except ValueError:
                        base_ip = key
                        port = None
                else:
                    base_ip = key
                    port = None

                start = time.time()
                # Ping the base IP (use cache if already pinged)
                with ping_cache_lock:
                    cached = ping_cache.get(base_ip)
                if cached is None:
                    result = ping_host(base_ip)
                    with ping_cache_lock:
                        ping_cache[base_ip] = result
                    ip_alive = result
                else:
                    ip_alive = cached

                # If there's a specific port, also check the port is open
                if port and ip_alive:
                    alive = scan_port(base_ip, port, timeout=2)
                else:
                    alive = ip_alive

                elapsed = round((time.time() - start) * 1000)
                # Update this host immediately as it comes in
                if self.running:
                    self.root.after(0, self._update_statuses, {key: (alive, elapsed)})

            for key in all_keys:
                t = threading.Thread(target=check_key, args=(key,))
                t.start()
                threads.append(t)

            for t in threads:
                t.join(timeout=PING_TIMEOUT + 2)

            self.countdown_seconds = self.ping_interval
            for _ in range(self.ping_interval * 10):
                if not self.running:
                    return
                time.sleep(0.1)

    def _update_statuses(self, results):
        online_count = 0
        total_count = len(results)

        for ip, (alive, ms) in results.items():
            # ── Maintenance mode — skip alerts, show blue ──
            if ip in self.maintenance_ips:
                if ip in self.status_indicators:
                    canvas, oval = self.status_indicators[ip]
                    canvas.itemconfig(oval, fill="#2196F3")  # blue
                if ip in self.status_labels:
                    self.status_labels[ip].configure(text="MAINT", fg="#2196F3")
                self.prev_statuses[ip] = alive
                self.node_statuses[ip] = alive
                continue

            # ── Status change detection ──
            prev = self.prev_statuses.get(ip)
            # Alert on status CHANGE only (not first-ever check)
            status_changed = (prev is not None and prev != alive)

            if status_changed:
                # Find server/host name for this IP/key
                srv_name = ""
                host_label = ""
                for _card, _node in self.all_cards:
                    if _node is None:
                        continue
                    node_ip = _node.get("ip") or ""
                    # Check main node IP
                    if node_ip == ip:
                        srv_name = _node.get("name", "")
                        break
                    # Check sub-hosts — build unique key to match
                    for h in _node.get("hosts", []):
                        h_raw = h.get("ip", "")
                        h_base = h_raw.split(":")[0] if ":" in h_raw else h_raw
                        h_port = h.get("port")
                        if not h_port and ":" in h_raw:
                            try:
                                h_port = int(h_raw.split(":")[-1])
                            except ValueError:
                                h_port = None
                        h_key = f"{h_base}:{h_port}" if h_port else h_base
                        if h_key == ip or h_raw == ip:
                            host_label = h.get("label", "")
                            srv_name = _node.get("name", "")
                            break
                    if srv_name:
                        break
                # Build display name: "CardName > HostLabel (IP)" or "CardName (IP)"
                if host_label and srv_name:
                    display_name = f"{srv_name} > {host_label} ({ip})"
                elif srv_name:
                    display_name = f"{srv_name} ({ip})"
                else:
                    display_name = ip

                if alive:
                    self.event_log.log(f"\u2705 {display_name} came ONLINE ({ms}ms)", "OK")
                    if self.alerts_enabled:
                        try:
                            winsound.Beep(800, 200)
                            winsound.Beep(1200, 300)
                        except Exception:
                            pass
                    # SMS alert — server back online
                    if self.sms_config.get("enabled") and self.sms_config.get("alert_online"):
                        self._send_sms_for_ip(ip, display_name, online=True, ms=ms)
                else:
                    self.event_log.log(f"\u274C {display_name} went OFFLINE", "ERROR")
                    if self.alerts_enabled:
                        try:
                            # LOUD alarm — high frequency, longer duration, more repeats
                            for _ in range(5):
                                winsound.Beep(3000, 400)
                                winsound.Beep(2200, 400)
                                winsound.Beep(1500, 400)
                                time.sleep(0.05)
                        except Exception:
                            pass
                    # Flash the card border red
                    self._flash_card_for_ip(ip)
                    # SMS alert — server went offline
                    if self.sms_config.get("enabled") and self.sms_config.get("alert_offline"):
                        self._send_sms_for_ip(ip, display_name, online=False)

            self.prev_statuses[ip] = alive
            self.node_statuses[ip] = alive

            # ── Update ping history for sparkline ──
            if ip in self.ping_history:
                self.ping_history[ip].append(ms if alive else -1)
                self._draw_sparkline(ip)

            # ── Update uptime tracking ──
            if ip in self.uptime_data:
                self.uptime_data[ip]["total"] += 1
                if alive:
                    self.uptime_data[ip]["up"] += 1
                # Update uptime label
                data = self.uptime_data[ip]
                pct = (data["up"] / data["total"] * 100) if data["total"] > 0 else 0
                if ip in self.uptime_labels:
                    color = COLORS["green"] if pct >= 95 else (COLORS["yellow"] if pct >= 80 else COLORS["red"])
                    self.uptime_labels[ip].configure(
                        text=f"uptime: {pct:.0f}%", fg=color,
                    )

            # ── Update uptime history for timeline chart ──
            if ip not in self.uptime_history:
                self.uptime_history[ip] = deque(maxlen=1440)
            self.uptime_history[ip].append(alive)

            # ── Update status indicators ──
            if ip in self.status_indicators:
                canvas, oval = self.status_indicators[ip]
                color = COLORS["green"] if alive else COLORS["red"]
                canvas.itemconfig(oval, fill=color)
                if alive:
                    self._pulse_indicator(canvas, oval)

            if ip in self.status_labels:
                if alive:
                    self.status_labels[ip].configure(text=f"{ms}ms", fg=COLORS["green"])
                    online_count += 1
                else:
                    self.status_labels[ip].configure(text="OFFLINE", fg=COLORS["red"])

        now = datetime.now().strftime("%H:%M:%S")
        self.last_check_var.set(f"Last check: {now}")
        self.countdown_seconds = self.ping_interval

    def _flash_card_for_ip(self, ip):
        """Flash the card border red for a server that went offline."""
        for card, node in self.all_cards:
            if node.get("ip") == ip:
                card.configure(highlightbackground=COLORS["red"], highlightthickness=3)
                card.after(3000, lambda c=card: c.configure(
                    highlightbackground=COLORS["card_border"], highlightthickness=1))
                break

    def _pulse_indicator(self, canvas, oval):
        coords = canvas.coords(oval)
        if not coords:
            return
        canvas.coords(oval, coords[0] - 1, coords[1] - 1, coords[2] + 1, coords[3] + 1)
        canvas.after(200, lambda: canvas.coords(oval, 3, 3, 11, 11))

    def _refresh_now(self):
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        all_ips = list(self.status_indicators.keys())
        results = {}
        threads = []

        def check_ip(ip):
            start = time.time()
            alive = ping_host(ip)
            elapsed = round((time.time() - start) * 1000)
            results[ip] = (alive, elapsed)
            # Update this one host immediately as it comes in
            if self.running:
                self.root.after(0, self._update_statuses, {ip: (alive, elapsed)})

        for ip in all_ips:
            t = threading.Thread(target=check_ip, args=(ip,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=PING_TIMEOUT + 2)

    # ── Feature: Remote System Info (WMI / Synology API) ─────────────────────

    def _show_system_info(self, node):
        """Show CPU, RAM, and disk usage. Auto-detects Synology NAS vs Windows."""
        ip = node.get("ip")
        if not ip:
            return

        # Detect if this is a Synology NAS
        synology_url = _detect_synology_url(node)
        if synology_url:
            self._show_synology_info(node, synology_url)
            return

        # Detect if this is a ZimaOS / CasaOS device
        zimaos_url = _detect_zimaos_url(node)
        if zimaos_url:
            self._show_zimaos_info(node, zimaos_url)
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(f"\U0001F4CA System Info \u2014 {node.get('name', ip)}")
        dlg.configure(bg=COLORS["bg"])
        _center_dialog(dlg, 500, 480, self.root)
        dlg.resizable(False, True)
        dlg.transient(self.root)

        tk.Label(dlg, text=f"\U0001F4CA  System Info: {node.get('name', ip)}",
                 font=("Consolas", 13, "bold"), fg=COLORS["accent"],
                 bg=COLORS["bg"]).pack(pady=(15, 2))
        tk.Label(dlg, text=ip, font=("Consolas", 9),
                 fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(pady=(0, 10))

        progress_var = tk.StringVar(value="Querying remote system...")
        progress_lbl = tk.Label(dlg, textvariable=progress_var,
                                font=("Consolas", 8), fg=COLORS["yellow"],
                                bg=COLORS["bg"])
        progress_lbl.pack()

        results_text = tk.Text(
            dlg, font=("Consolas", 9), bg=COLORS["log_bg"],
            fg=COLORS["text"], state="disabled", wrap="word",
        )
        results_text.pack(fill="both", expand=True, padx=15, pady=10)
        results_text.tag_configure("header", foreground=COLORS["accent"], font=("Consolas", 10, "bold"))
        results_text.tag_configure("good", foreground=COLORS["green"])
        results_text.tag_configure("warn", foreground=COLORS["yellow"])
        results_text.tag_configure("bad", foreground=COLORS["red"])
        results_text.tag_configure("dim", foreground=COLORS["text_dim"])

        def _append(text, tag=""):
            results_text.configure(state="normal")
            if tag:
                results_text.insert("end", text, tag)
            else:
                results_text.insert("end", text)
            results_text.see("end")
            results_text.configure(state="disabled")

        def _clear():
            results_text.configure(state="normal")
            results_text.delete("1.0", "end")
            results_text.configure(state="disabled")

        def _ps_run(ps_script, timeout=20):
            """Run a PowerShell command and return the result."""
            cmd = [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                ps_script
            ]
            return subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

        def do_query():
            _clear()
            host = ip.split(":")[0] if ":" in ip else ip

            # Use DCOM protocol — works without WinRM, no domain needed
            session_setup = (
                f"$opt = New-CimSessionOption -Protocol Dcom; "
                f"$s = New-CimSession -ComputerName '{host}' -SessionOption $opt "
                f"-ErrorAction Stop; "
            )

            # CPU
            progress_var.set("Querying CPU...")
            try:
                ps = (session_setup +
                      "$cpu = Get-CimInstance Win32_Processor -CimSession $s; "
                      "Write-Output $cpu.LoadPercentage; "
                      "Remove-CimSession $s")
                result = _ps_run(ps)
                dlg.after(0, lambda: _append("\n  CPU USAGE\n", "header"))
                cpu_pct = None
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line.isdigit():
                        cpu_pct = int(line)
                        break
                if cpu_pct is not None:
                    tag = "good" if cpu_pct < 70 else ("warn" if cpu_pct < 90 else "bad")
                    dlg.after(0, lambda t=tag, c=cpu_pct: _append(f"    Load: {c}%\n\n", t))
                else:
                    err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else ""
                    if "WinRM" in err or "DCOM" in err or "RPC" in err or "access" in err.lower():
                        dlg.after(0, lambda: _append(
                            "    ⚠️ Cannot connect — this may be a Linux/NAS device\n"
                            "    or the remote Windows firewall is blocking DCOM/RPC.\n\n"
                            "    For Windows servers, try running on the remote machine:\n"
                            "      netsh advfirewall firewall set rule group=\"Windows Management Instrumentation (WMI)\" new enable=Yes\n\n", "dim"))
                        progress_var.set("Connection failed — see details below")
                        return
                    msg = f"    Could not retrieve CPU data\n" + (f"    {err}\n\n" if err else "\n")
                    dlg.after(0, lambda m=msg: _append(m, "dim"))
            except subprocess.TimeoutExpired:
                dlg.after(0, lambda: _append("    CPU query timed out — host may be unreachable\n\n", "bad"))
                progress_var.set("Timed out")
                return
            except Exception as e:
                dlg.after(0, lambda: _append(f"    CPU query failed: {e}\n\n", "bad"))

            # RAM
            progress_var.set("Querying RAM...")
            try:
                ps = (session_setup +
                      "$os = Get-CimInstance Win32_OperatingSystem -CimSession $s; "
                      "Write-Output \"$($os.FreePhysicalMemory) $($os.TotalVisibleMemorySize)\"; "
                      "Remove-CimSession $s")
                result = _ps_run(ps)
                dlg.after(0, lambda: _append("  RAM USAGE\n", "header"))
                parsed = False
                for line in result.stdout.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        free_kb = int(parts[0])
                        total_kb = int(parts[1])
                        used_kb = total_kb - free_kb
                        pct = (used_kb / total_kb * 100) if total_kb > 0 else 0
                        total_gb = total_kb / 1048576
                        used_gb = used_kb / 1048576
                        free_gb = free_kb / 1048576
                        tag = "good" if pct < 70 else ("warn" if pct < 90 else "bad")
                        dlg.after(0, lambda t=tag, p=pct: _append(f"    Used: {p:.1f}%\n", t))
                        dlg.after(0, lambda tg=total_gb, ug=used_gb, fg=free_gb: _append(
                            f"    Total: {tg:.1f} GB  |  Used: {ug:.1f} GB  |  Free: {fg:.1f} GB\n\n", ""))
                        parsed = True
                        break
                if not parsed:
                    err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else ""
                    msg = f"    Could not parse RAM data\n" + (f"    {err}\n\n" if err else "\n")
                    dlg.after(0, lambda m=msg: _append(m, "dim"))
            except Exception as e:
                dlg.after(0, lambda: _append(f"    RAM query failed: {e}\n\n", "bad"))

            # Disks
            progress_var.set("Querying disks...")
            try:
                ps = (session_setup +
                      "Get-CimInstance Win32_LogicalDisk -CimSession $s -Filter 'DriveType=3' | "
                      "ForEach-Object { Write-Output \"$($_.DeviceID) $($_.FreeSpace) $($_.Size)\" }; "
                      "Remove-CimSession $s")
                result = _ps_run(ps)
                dlg.after(0, lambda: _append("  DISK SPACE\n", "header"))
                found = False
                for line in result.stdout.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 3 and ":" in parts[0]:
                        drive = parts[0]
                        try:
                            free_bytes = int(parts[1])
                            total_bytes = int(parts[2])
                            used_bytes = total_bytes - free_bytes
                            pct = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0
                            total_gb = total_bytes / (1024 ** 3)
                            free_gb = free_bytes / (1024 ** 3)
                            tag = "good" if pct < 80 else ("warn" if pct < 95 else "bad")
                            dlg.after(0, lambda d=drive, p=pct, t=tag, tg=total_gb, fg=free_gb:
                                      _append(f"    {d}  {p:.1f}% used  ({fg:.1f} GB free / {tg:.1f} GB total)\n", t))
                            found = True
                        except ValueError:
                            continue
                if not found:
                    err = result.stderr.strip().split("\n")[0] if result.stderr.strip() else ""
                    msg = f"    No disk data available\n" + (f"    {err}\n" if err else "")
                    dlg.after(0, lambda m=msg: _append(m, "dim"))
            except Exception as e:
                dlg.after(0, lambda: _append(f"    Disk query failed: {e}\n\n", "bad"))

            dlg.after(0, lambda: progress_var.set("Done."))

        def refresh():
            threading.Thread(target=do_query, daemon=True).start()

        btn_frame = tk.Frame(dlg, bg=COLORS["bg"])
        btn_frame.pack(pady=(0, 10))
        tk.Button(btn_frame, text="\U0001F504  Refresh", font=("Consolas", 9, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat", padx=15, pady=4,
                  cursor="hand2", command=refresh).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Close", font=("Consolas", 9),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=15, pady=4, cursor="hand2", command=dlg.destroy).pack(side="left", padx=5)

        refresh()

    # ── Feature: Synology NAS System Info ───────────────────────────────────

    def _show_synology_info(self, node, base_url):
        """Show CPU, RAM, and disk/volume info from a Synology NAS via DSM API."""
        ip = node.get("ip", "")

        dlg = tk.Toplevel(self.root)
        dlg.title(f"\U0001F4CA Synology Info \u2014 {node.get('name', ip)}")
        dlg.configure(bg=COLORS["bg"])
        _center_dialog(dlg, 540, 520, self.root)
        dlg.resizable(False, True)
        dlg.transient(self.root)

        tk.Label(dlg, text=f"\U0001F4CA  Synology NAS: {node.get('name', ip)}",
                 font=("Consolas", 13, "bold"), fg=COLORS["accent"],
                 bg=COLORS["bg"]).pack(pady=(15, 2))
        tk.Label(dlg, text=f"{ip}  •  {base_url}",
                 font=("Consolas", 8), fg=COLORS["text_dim"],
                 bg=COLORS["bg"]).pack(pady=(0, 10))

        progress_var = tk.StringVar(value="Connecting to Synology DSM API...")
        progress_lbl = tk.Label(dlg, textvariable=progress_var,
                                font=("Consolas", 8), fg=COLORS["yellow"],
                                bg=COLORS["bg"])
        progress_lbl.pack()

        results_text = tk.Text(
            dlg, font=("Consolas", 9), bg=COLORS["log_bg"],
            fg=COLORS["text"], state="disabled", wrap="word",
        )
        results_text.pack(fill="both", expand=True, padx=15, pady=10)
        results_text.tag_configure("header", foreground=COLORS["accent"],
                                   font=("Consolas", 10, "bold"))
        results_text.tag_configure("good", foreground=COLORS["green"])
        results_text.tag_configure("warn", foreground=COLORS["yellow"])
        results_text.tag_configure("bad", foreground=COLORS["red"])
        results_text.tag_configure("dim", foreground=COLORS["text_dim"])

        def _append(text, tag=""):
            results_text.configure(state="normal")
            if tag:
                results_text.insert("end", text, tag)
            else:
                results_text.insert("end", text)
            results_text.see("end")
            results_text.configure(state="disabled")

        def _clear():
            results_text.configure(state="normal")
            results_text.delete("1.0", "end")
            results_text.configure(state="disabled")

        def do_query():
            _clear()
            progress_var.set("Logging in to DSM API...")

            # Get credentials from saved shares
            user, pwd = _get_synology_creds(node)
            if not user:
                dlg.after(0, lambda: _append(
                    "\n  ⚠️ No saved credentials found!\n\n"
                    "  Add a username/password to one of this NAS's\n"
                    "  share drives and try again.\n", "warn"))
                dlg.after(0, lambda: progress_var.set("No credentials"))
                return

            # Login
            try:
                sid = synology_login(base_url, user, pwd)
            except Exception as e:
                dlg.after(0, lambda: _append(
                    f"\n  ❌ Could not connect to DSM API\n\n"
                    f"  URL: {base_url}\n"
                    f"  Error: {e}\n\n"
                    f"  Make sure the NAS web interface is accessible.\n", "bad"))
                dlg.after(0, lambda: progress_var.set("Connection failed"))
                return

            if not sid:
                dlg.after(0, lambda: _append(
                    "\n  ❌ Login failed — check username/password\n\n"
                    f"  Tried: {user} / {'*' * len(pwd)}\n"
                    "  (Credentials come from saved share drives)\n", "bad"))
                dlg.after(0, lambda: progress_var.set("Login failed"))
                return

            try:
                # CPU & RAM
                progress_var.set("Querying system utilization...")
                try:
                    util = synology_system_info(base_url, sid)
                    if util:
                        # CPU
                        cpu_data = util.get("cpu", {})
                        if cpu_data:
                            user_load = cpu_data.get("user_load", 0)
                            sys_load = cpu_data.get("system_load", 0)
                            total_cpu = user_load + sys_load
                            tag = "good" if total_cpu < 70 else ("warn" if total_cpu < 90 else "bad")
                            dlg.after(0, lambda: _append("\n  CPU USAGE\n", "header"))
                            dlg.after(0, lambda t=tag, tc=total_cpu, ul=user_load, sl=sys_load:
                                      _append(f"    Total: {tc}%  (User: {ul}%  System: {sl}%)\n\n", t))

                        # RAM
                        mem_data = util.get("memory", {})
                        if mem_data:
                            total_kb = mem_data.get("memory_size", 0)
                            avail_kb = mem_data.get("avail_real", 0)
                            # Synology reports in KB
                            if total_kb > 0:
                                used_kb = total_kb - avail_kb
                                pct = (used_kb / total_kb) * 100
                                total_gb = total_kb / 1048576
                                used_gb = used_kb / 1048576
                                free_gb = avail_kb / 1048576
                                tag = "good" if pct < 70 else ("warn" if pct < 90 else "bad")
                                dlg.after(0, lambda: _append("  RAM USAGE\n", "header"))
                                dlg.after(0, lambda t=tag, p=pct: _append(f"    Used: {p:.1f}%\n", t))
                                dlg.after(0, lambda tg=total_gb, ug=used_gb, fg=free_gb: _append(
                                    f"    Total: {tg:.1f} GB  |  Used: {ug:.1f} GB  |  Free: {fg:.1f} GB\n\n", ""))

                        # Swap if available
                        swap_data = util.get("memory", {})
                        swap_total = swap_data.get("memory_size", 0)
                        swap_avail = swap_data.get("avail_swap", 0)
                        if swap_total > 0 and swap_avail < swap_total:
                            swap_used_pct = ((swap_total - swap_avail) / swap_total) * 100
                            if swap_used_pct > 5:
                                dlg.after(0, lambda sp=swap_used_pct:
                                          _append(f"    Swap: {sp:.1f}% used\n\n", "dim"))
                    else:
                        dlg.after(0, lambda: _append(
                            "\n  CPU/RAM data not available from this DSM version.\n\n", "dim"))
                except Exception as e:
                    dlg.after(0, lambda: _append(f"\n  CPU/RAM query error: {e}\n\n", "bad"))

                # Storage / Volumes
                progress_var.set("Querying storage volumes...")
                try:
                    storage = synology_storage_info(base_url, sid)
                    if storage:
                        volumes = storage.get("volumes", [])
                        if volumes:
                            dlg.after(0, lambda: _append("  STORAGE VOLUMES\n", "header"))
                            for vol in volumes:
                                vol_path = vol.get("deploy_path", vol.get("id", "?"))
                                status = vol.get("status", "unknown")
                                total_bytes = int(vol.get("size", {}).get("total", "0"))
                                used_bytes = int(vol.get("size", {}).get("used", "0"))
                                if total_bytes > 0:
                                    pct = (used_bytes / total_bytes) * 100
                                    total_gb = total_bytes / (1024 ** 3)
                                    used_gb = used_bytes / (1024 ** 3)
                                    free_gb = (total_bytes - used_bytes) / (1024 ** 3)
                                    tag = "good" if pct < 80 else ("warn" if pct < 95 else "bad")
                                    status_icon = "🟢" if status == "normal" else "🔴"
                                    dlg.after(0, lambda vp=vol_path, p=pct, t=tag, fg=free_gb, tg=total_gb, si=status_icon:
                                              _append(f"    {si} {vp}  {p:.1f}% used  ({fg:.1f} GB free / {tg:.1f} GB total)\n", t))
                                else:
                                    dlg.after(0, lambda vp=vol_path, st=status:
                                              _append(f"    {vp}  Status: {st}\n", "dim"))

                        # Disks (physical)
                        disks = storage.get("disks", [])
                        if disks:
                            dlg.after(0, lambda: _append("\n  PHYSICAL DISKS\n", "header"))
                            for disk in disks:
                                name = disk.get("name", disk.get("id", "?"))
                                model = disk.get("model", "Unknown")
                                size_bytes = int(disk.get("size_total", "0"))
                                temp = disk.get("temp", 0)
                                status = disk.get("status", "unknown")
                                size_gb = size_bytes / (1024 ** 3) if size_bytes > 0 else 0
                                status_icon = "🟢" if status == "normal" else "🔴"
                                temp_tag = "good" if temp < 45 else ("warn" if temp < 55 else "bad")
                                dlg.after(0, lambda n=name, m=model, sg=size_gb, tp=temp, si=status_icon, tt=temp_tag:
                                          _append(f"    {si} {n}: {m}  ({sg:.0f} GB)  Temp: {tp}°C\n", tt))
                    else:
                        dlg.after(0, lambda: _append("\n  Storage data not available.\n", "dim"))
                except Exception as e:
                    dlg.after(0, lambda: _append(f"\n  Storage query error: {e}\n\n", "bad"))

            finally:
                synology_logout(base_url, sid)

            dlg.after(0, lambda: progress_var.set("Done."))

        def refresh():
            threading.Thread(target=do_query, daemon=True).start()

        btn_frame = tk.Frame(dlg, bg=COLORS["bg"])
        btn_frame.pack(pady=(0, 10))
        tk.Button(btn_frame, text="\U0001F504  Refresh", font=("Consolas", 9, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat", padx=15, pady=4,
                  cursor="hand2", command=refresh).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Close", font=("Consolas", 9),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=15, pady=4, cursor="hand2", command=dlg.destroy).pack(side="left", padx=5)

        refresh()

    # ── Feature: ZimaOS / CasaOS System Info ────────────────────────────────

    def _show_zimaos_info(self, node, base_url):
        """Show CPU, RAM, and disk info from a ZimaOS/CasaOS device via REST API."""
        ip = node.get("ip", "")

        dlg = tk.Toplevel(self.root)
        dlg.title(f"\U0001F4CA ZimaOS Info \u2014 {node.get('name', ip)}")
        dlg.configure(bg=COLORS["bg"])
        _center_dialog(dlg, 540, 520, self.root)
        dlg.resizable(False, True)
        dlg.transient(self.root)

        tk.Label(dlg, text=f"\U0001F4CA  ZimaOS: {node.get('name', ip)}",
                 font=("Consolas", 13, "bold"), fg=COLORS["accent"],
                 bg=COLORS["bg"]).pack(pady=(15, 2))
        tk.Label(dlg, text=f"{ip}  •  {base_url}",
                 font=("Consolas", 8), fg=COLORS["text_dim"],
                 bg=COLORS["bg"]).pack(pady=(0, 5))

        # Credential fields (ZimaOS web login may differ from SMB)
        cred_frame = tk.Frame(dlg, bg=COLORS["bg"])
        cred_frame.pack(pady=(0, 5))

        share_user, share_pass = _get_synology_creds(node)  # reuse same helper
        # Also check node-level creds
        zima_user = node.get("zima_user", share_user or "")
        zima_pass = node.get("zima_pass", share_pass or "")

        tk.Label(cred_frame, text="Web Login:", font=("Consolas", 8),
                 fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(side="left", padx=(0, 5))
        user_entry = tk.Entry(cred_frame, font=("Consolas", 9), bg=COLORS["share_bg"],
                              fg=COLORS["text"], insertbackground=COLORS["text"], width=14)
        user_entry.pack(side="left", padx=(0, 5))
        user_entry.insert(0, zima_user)

        pass_entry = tk.Entry(cred_frame, font=("Consolas", 9), bg=COLORS["share_bg"],
                              fg=COLORS["text"], insertbackground=COLORS["text"], width=14, show="*")
        pass_entry.pack(side="left", padx=(0, 5))
        pass_entry.insert(0, zima_pass)

        progress_var = tk.StringVar(value="Click Refresh to connect...")
        progress_lbl = tk.Label(dlg, textvariable=progress_var,
                                font=("Consolas", 8), fg=COLORS["yellow"],
                                bg=COLORS["bg"])
        progress_lbl.pack()

        results_text = tk.Text(
            dlg, font=("Consolas", 9), bg=COLORS["log_bg"],
            fg=COLORS["text"], state="disabled", wrap="word",
        )
        results_text.pack(fill="both", expand=True, padx=15, pady=10)
        results_text.tag_configure("header", foreground=COLORS["accent"],
                                   font=("Consolas", 10, "bold"))
        results_text.tag_configure("good", foreground=COLORS["green"])
        results_text.tag_configure("warn", foreground=COLORS["yellow"])
        results_text.tag_configure("bad", foreground=COLORS["red"])
        results_text.tag_configure("dim", foreground=COLORS["text_dim"])

        def _append(text, tag=""):
            results_text.configure(state="normal")
            if tag:
                results_text.insert("end", text, tag)
            else:
                results_text.insert("end", text)
            results_text.see("end")
            results_text.configure(state="disabled")

        def _clear():
            results_text.configure(state="normal")
            results_text.delete("1.0", "end")
            results_text.configure(state="disabled")

        def do_query():
            dlg.after(0, _clear)
            username = user_entry.get().strip()
            password = pass_entry.get()

            if not username:
                dlg.after(0, lambda: _append(
                    "\n  ⚠️ Enter your ZimaOS web login credentials above\n"
                    "  and click Refresh.\n\n"
                    "  (This may be different from your SMB share credentials)\n", "warn"))
                dlg.after(0, lambda: progress_var.set("Need credentials"))
                return

            dlg.after(0, lambda: progress_var.set("Logging in to ZimaOS..."))

            # Try to login
            token, login_err = zimaos_login(base_url, username, password)
            if not token:
                err_detail = login_err or "Unknown error"
                dlg.after(0, lambda e=err_detail: _append(
                    "\n  ❌ Login failed\n\n"
                    f"  User: {username}\n"
                    f"  Error: {e}\n", "bad"))
                dlg.after(0, lambda: progress_var.set("Login failed — check credentials"))
                return

            # Save working creds to node for next time
            node["zima_user"] = username
            node["zima_pass"] = password
            save_config(self.nodes)

            # CPU & RAM utilization
            dlg.after(0, lambda: progress_var.set("Querying system utilization..."))
            try:
                data = zimaos_get(base_url, "/v1/sys/utilization", token)
                info = data.get("data", data) if isinstance(data, dict) else {}

                # CPU
                cpu = info.get("cpu", {})
                if cpu:
                    dlg.after(0, lambda: _append("\n  CPU USAGE\n", "header"))
                    # CasaOS reports per-core or total
                    if isinstance(cpu, dict):
                        total = cpu.get("percent", cpu.get("total", 0))
                        tag = "good" if total < 70 else ("warn" if total < 90 else "bad")
                        dlg.after(0, lambda t=tag, c=total: _append(f"    Load: {c:.1f}%\n\n", t))
                    elif isinstance(cpu, (int, float)):
                        tag = "good" if cpu < 70 else ("warn" if cpu < 90 else "bad")
                        dlg.after(0, lambda t=tag, c=cpu: _append(f"    Load: {c:.1f}%\n\n", t))

                # Memory
                mem = info.get("mem", info.get("memory", {}))
                if mem:
                    dlg.after(0, lambda: _append("  RAM USAGE\n", "header"))
                    if isinstance(mem, dict):
                        total = mem.get("total", 0)
                        used = mem.get("used", 0)
                        avail = mem.get("avail", mem.get("available", total - used))
                        if total > 0:
                            pct = (used / total) * 100
                            total_gb = total / (1024 ** 3)
                            used_gb = used / (1024 ** 3)
                            free_gb = avail / (1024 ** 3)
                            tag = "good" if pct < 70 else ("warn" if pct < 90 else "bad")
                            dlg.after(0, lambda t=tag, p=pct: _append(f"    Used: {p:.1f}%\n", t))
                            dlg.after(0, lambda tg=total_gb, ug=used_gb, fg=free_gb: _append(
                                f"    Total: {tg:.1f} GB  |  Used: {ug:.1f} GB  |  Free: {fg:.1f} GB\n\n", ""))
            except Exception as e:
                err_msg = str(e)
                dlg.after(0, lambda m=err_msg: _append(f"\n  Utilization query: {m}\n\n", "dim"))

            # Disk / Storage
            dlg.after(0, lambda: progress_var.set("Querying storage..."))
            try:
                data = zimaos_get(base_url, "/v1/disks", token)
                disks_data = data.get("data", []) if isinstance(data, dict) else []
                if disks_data:
                    dlg.after(0, lambda: _append("  STORAGE\n", "header"))
                    disk_list = disks_data if isinstance(disks_data, list) else [disks_data]
                    for disk in disk_list:
                        if isinstance(disk, dict):
                            name = disk.get("name", disk.get("path", "?"))
                            model = disk.get("model", "")
                            size = disk.get("size", 0)
                            children = disk.get("children", [])
                            size_gb = size / (1024 ** 3) if size > 0 else 0
                            temp = disk.get("temperature", 0)
                            health = disk.get("health", "unknown")
                            status_icon = "🟢" if health in ("OK", "Passed", "PASSED", "normal") else "🟡"
                            temp_str = f"  Temp: {temp}°C" if temp else ""
                            temp_tag = "good" if temp < 45 else ("warn" if temp < 55 else "bad")
                            dlg.after(0, lambda n=name, m=model, sg=size_gb, si=status_icon, ts=temp_str, tt=temp_tag:
                                      _append(f"    {si} {n}: {m}  ({sg:.0f} GB){ts}\n", tt if ts else ""))
                            # Show partitions/children
                            for child in (children if isinstance(children, list) else []):
                                cname = child.get("name", child.get("path", ""))
                                mount = child.get("mount_point", "")
                                csize = child.get("size", 0)
                                avail = child.get("avail", 0)
                                if csize > 0 and mount:
                                    used_pct = ((csize - avail) / csize) * 100 if avail else 0
                                    csize_gb = csize / (1024 ** 3)
                                    avail_gb = avail / (1024 ** 3)
                                    tag = "good" if used_pct < 80 else ("warn" if used_pct < 95 else "bad")
                                    dlg.after(0, lambda cn=cname, mt=mount, p=used_pct, t=tag, ag=avail_gb, cg=csize_gb:
                                              _append(f"      └ {mt}  {p:.1f}% used  ({ag:.1f} GB free / {cg:.1f} GB)\n", t))
            except Exception as e:
                err_msg = str(e)
                dlg.after(0, lambda m=err_msg: _append(f"\n  Storage query: {m}\n\n", "dim"))

            # System info
            dlg.after(0, lambda: progress_var.set("Querying system info..."))
            try:
                data = zimaos_get(base_url, "/v1/sys/info", token)
                sys_info = data.get("data", data) if isinstance(data, dict) else {}
                if sys_info and isinstance(sys_info, dict):
                    dlg.after(0, lambda: _append("\n  SYSTEM INFO\n", "header"))
                    for key in ("os_version", "arch", "hostname", "model", "uptime"):
                        val = sys_info.get(key, "")
                        if val:
                            label = key.replace("_", " ").title()
                            dlg.after(0, lambda l=label, v=val: _append(f"    {l}: {v}\n", "dim"))
            except Exception:
                pass  # Optional info, don't show errors

            dlg.after(0, lambda: progress_var.set("Done."))

        def refresh():
            threading.Thread(target=do_query, daemon=True).start()

        btn_frame = tk.Frame(dlg, bg=COLORS["bg"])
        btn_frame.pack(pady=(0, 10))
        tk.Button(btn_frame, text="\U0001F504  Refresh", font=("Consolas", 9, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat", padx=15, pady=4,
                  cursor="hand2", command=refresh).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Close", font=("Consolas", 9),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=15, pady=4, cursor="hand2", command=dlg.destroy).pack(side="left", padx=5)

        refresh()

    # ── Feature: Master Report (HTML) ────────────────────────────────────────

    def _generate_master_report(self):
        """Generate an HTML report of all servers with live disk data and open in browser."""
        report_path = os.path.join(APP_DIR, "noc_master_report.html")

        # Show progress dialog while querying
        dlg = tk.Toplevel(self.root)
        dlg.title("Generating Master Report...")
        dlg.configure(bg=COLORS["bg"])
        _center_dialog(dlg, 400, 120, self.root)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        tk.Label(dlg, text="📋  Generating Master Report",
                 font=("Consolas", 12, "bold"), fg=COLORS["accent"],
                 bg=COLORS["bg"]).pack(pady=(20, 5))
        progress_var = tk.StringVar(value="Querying live disk data from all servers...")
        tk.Label(dlg, textvariable=progress_var,
                 font=("Consolas", 9), fg=COLORS["yellow"],
                 bg=COLORS["bg"]).pack()

        def _query_node_disks(node):
            """Query disk data for a single node. Returns list of (label, pct, total_gb, free_gb)."""
            ip = node.get("ip", "")
            if not ip:
                return []
            host = ip.split(":")[0] if ":" in ip else ip
            disk_data = []

            # 1) Try WMI (Windows)
            try:
                ps = (
                    f"$opt = New-CimSessionOption -Protocol Dcom; "
                    f"$s = New-CimSession -ComputerName '{host}' -SessionOption $opt -ErrorAction Stop; "
                    f"Get-CimInstance Win32_LogicalDisk -CimSession $s -Filter 'DriveType=3' | "
                    f"ForEach-Object {{ Write-Output \"$($_.DeviceID) $($_.FreeSpace) $($_.Size)\" }}; "
                    f"Remove-CimSession $s"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True, text=True, timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 3 and ":" in parts[0]:
                        try:
                            drive = parts[0]
                            free_bytes = int(parts[1])
                            total_bytes = int(parts[2])
                            if total_bytes > 0:
                                used_pct = ((total_bytes - free_bytes) / total_bytes) * 100
                                total_gb = total_bytes / (1024 ** 3)
                                free_gb = free_bytes / (1024 ** 3)
                                disk_data.append((drive, used_pct, total_gb, free_gb))
                        except ValueError:
                            continue
            except Exception:
                pass
            if disk_data:
                return disk_data

            # 2) Try Synology API
            synology_url = _detect_synology_url(node)
            if synology_url:
                try:
                    user, pwd = _get_synology_creds(node)
                    if user:
                        sid = synology_login(synology_url, user, pwd)
                        if sid:
                            try:
                                storage = synology_storage_info(synology_url, sid)
                                if storage:
                                    for vol in storage.get("volumes", []):
                                        vol_path = vol.get("deploy_path", vol.get("id", "?"))
                                        total_bytes = int(vol.get("size", {}).get("total", "0"))
                                        used_bytes = int(vol.get("size", {}).get("used", "0"))
                                        if total_bytes > 0:
                                            pct = (used_bytes / total_bytes) * 100
                                            total_gb = total_bytes / (1024 ** 3)
                                            free_gb = (total_bytes - used_bytes) / (1024 ** 3)
                                            disk_data.append((vol_path, pct, total_gb, free_gb))
                            finally:
                                synology_logout(synology_url, sid)
                except Exception:
                    pass
            if disk_data:
                return disk_data

            # 3) Try ZimaOS API
            zimaos_url = _detect_zimaos_url(node)
            if zimaos_url:
                try:
                    share_user, share_pass = _get_synology_creds(node)
                    zima_user = node.get("zima_user", share_user or "")
                    zima_pass = node.get("zima_pass", share_pass or "")
                    if zima_user:
                        token, _ = zimaos_login(zimaos_url, zima_user, zima_pass)
                        if token:
                            data = zimaos_get(zimaos_url, "/v1/disks", token)
                            disks_list = data.get("data", []) if isinstance(data, dict) else []
                            if isinstance(disks_list, list):
                                for disk in disks_list:
                                    for child in disk.get("children", []):
                                        mount = child.get("mount_point", "")
                                        csize = child.get("size", 0)
                                        avail = child.get("avail", 0)
                                        if csize > 0 and mount:
                                            used_pct = ((csize - avail) / csize) * 100
                                            total_gb = csize / (1024 ** 3)
                                            free_gb = avail / (1024 ** 3)
                                            disk_data.append((mount, used_pct, total_gb, free_gb))
                except Exception:
                    pass

            return disk_data

        def _query_node_sysinfo(node):
            """Query CPU and RAM for a node. Returns dict with cpu_pct, ram_pct, ram_total_gb, ram_used_gb, ram_free_gb."""
            ip = node.get("ip", "")
            if not ip:
                return {}
            host = ip.split(":")[0] if ":" in ip else ip
            info = {}

            # 1) Try WMI (Windows)
            try:
                ps = (
                    f"$opt = New-CimSessionOption -Protocol Dcom; "
                    f"$s = New-CimSession -ComputerName '{host}' -SessionOption $opt -ErrorAction Stop; "
                    f"$cpu = Get-CimInstance Win32_Processor -CimSession $s; "
                    f"$os = Get-CimInstance Win32_OperatingSystem -CimSession $s; "
                    f"$cs = Get-CimInstance Win32_ComputerSystem -CimSession $s; "
                    f"Write-Output \"CPU:$($cpu.LoadPercentage)\"; "
                    f"Write-Output \"RAM:$($os.FreePhysicalMemory) $($os.TotalVisibleMemorySize)\"; "
                    f"Write-Output \"OS:$($os.Caption)\"; "
                    f"Write-Output \"MODEL:$($cs.Model)\"; "
                    f"Write-Output \"BOOT:$($os.LastBootUpTime)\"; "
                    f"Remove-CimSession $s"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True, text=True, timeout=25,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line.startswith("CPU:"):
                        val = line[4:]
                        if val.isdigit():
                            info["cpu_pct"] = int(val)
                    elif line.startswith("RAM:"):
                        parts = line[4:].split()
                        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                            free_kb = int(parts[0])
                            total_kb = int(parts[1])
                            used_kb = total_kb - free_kb
                            info["ram_pct"] = (used_kb / total_kb * 100) if total_kb > 0 else 0
                            info["ram_total_gb"] = total_kb / 1048576
                            info["ram_used_gb"] = used_kb / 1048576
                            info["ram_free_gb"] = free_kb / 1048576
                    elif line.startswith("OS:"):
                        val = line[3:].strip()
                        if val:
                            info["os_name"] = val
                    elif line.startswith("MODEL:"):
                        val = line[6:].strip()
                        if val:
                            info["model"] = val
                    elif line.startswith("BOOT:"):
                        val = line[5:].strip()
                        if val:
                            info["last_boot"] = val
            except Exception:
                pass
            if info:
                return info

            # 2) Synology API
            synology_url = _detect_synology_url(node)
            if synology_url:
                try:
                    user, pwd = _get_synology_creds(node)
                    if user:
                        sid = synology_login(synology_url, user, pwd)
                        if sid:
                            try:
                                util = synology_system_info(synology_url, sid)
                                if util:
                                    cpu_data = util.get("cpu", {})
                                    if cpu_data:
                                        info["cpu_pct"] = cpu_data.get("user_load", 0) + cpu_data.get("system_load", 0)
                                    mem = util.get("memory", {})
                                    if mem:
                                        total_kb = mem.get("memory_size", 0)
                                        avail_kb = mem.get("avail_real", 0)
                                        if total_kb > 0:
                                            used_kb = total_kb - avail_kb
                                            info["ram_pct"] = (used_kb / total_kb) * 100
                                            info["ram_total_gb"] = total_kb / 1048576
                                            info["ram_used_gb"] = used_kb / 1048576
                                            info["ram_free_gb"] = avail_kb / 1048576
                                    info["os_name"] = "Synology DSM"
                            finally:
                                synology_logout(synology_url, sid)
                except Exception:
                    pass
            if info:
                return info

            # 3) ZimaOS API
            zimaos_url = _detect_zimaos_url(node)
            if zimaos_url:
                try:
                    share_user, share_pass = _get_synology_creds(node)
                    zima_user = node.get("zima_user", share_user or "")
                    zima_pass = node.get("zima_pass", share_pass or "")
                    if zima_user:
                        token, _ = zimaos_login(zimaos_url, zima_user, zima_pass)
                        if token:
                            data = zimaos_get(zimaos_url, "/v1/sys/utilization", token)
                            util = data.get("data", data) if isinstance(data, dict) else {}
                            cpu = util.get("cpu", {})
                            if isinstance(cpu, dict):
                                info["cpu_pct"] = cpu.get("percent", cpu.get("total", 0))
                            elif isinstance(cpu, (int, float)):
                                info["cpu_pct"] = cpu
                            mem = util.get("mem", util.get("memory", {}))
                            if isinstance(mem, dict) and mem.get("total", 0) > 0:
                                total = mem["total"]
                                used = mem.get("used", 0)
                                avail = mem.get("avail", mem.get("available", total - used))
                                info["ram_pct"] = (used / total) * 100
                                info["ram_total_gb"] = total / (1024 ** 3)
                                info["ram_used_gb"] = used / (1024 ** 3)
                                info["ram_free_gb"] = avail / (1024 ** 3)
                            info["os_name"] = "ZimaOS"
                except Exception:
                    pass

            return info

        def _do_build():
            # Query all nodes in parallel
            all_disk_data = {}   # ip -> list of (label, pct, total_gb, free_gb)
            all_sys_info = {}    # ip -> dict
            threads = []

            def _worker(node):
                ip = node.get("ip", "")
                if ip:
                    dlg.after(0, lambda n=node.get("name", ip): progress_var.set(f"Querying {n}..."))
                    all_sys_info[ip] = _query_node_sysinfo(node)
                    all_disk_data[ip] = _query_node_disks(node)

            for node in self.nodes:
                t = threading.Thread(target=_worker, args=(node,), daemon=True)
                threads.append(t)
                t.start()
            for t in threads:
                t.join(timeout=30)

            dlg.after(0, lambda: progress_var.set("Building HTML report..."))

            now = datetime.now()
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

            # Gather summary stats
            total_nodes = 0
            total_hosts = 0
            online_count = 0
            offline_count = 0
            maint_count = 0
            for node in self.nodes:
                ip = node.get("ip")
                if ip:
                    total_nodes += 1
                    if ip in self.maintenance_ips:
                        maint_count += 1
                    elif self.node_statuses.get(ip) is True:
                        online_count += 1
                    elif self.node_statuses.get(ip) is False:
                        offline_count += 1
                for h in node.get("hosts", []):
                    h_raw = h.get("ip", "")
                    h_base = h_raw.split(":")[0] if ":" in h_raw else h_raw
                    h_port = h.get("port")
                    if not h_port and ":" in h_raw:
                        try:
                            h_port = int(h_raw.split(":")[-1])
                        except ValueError:
                            h_port = None
                    h_key = f"{h_base}:{h_port}" if h_port else h_base
                    total_hosts += 1
                    if h_key in self.maintenance_ips:
                        maint_count += 1
                    elif self.node_statuses.get(h_key) is True:
                        online_count += 1
                    elif self.node_statuses.get(h_key) is False:
                        offline_count += 1
            unknown_count = (total_nodes + total_hosts) - online_count - offline_count - maint_count

            # Grand total disk across all servers
            grand_total_gb = 0
            grand_free_gb = 0
            for disks in all_disk_data.values():
                for _, _, tgb, fgb in disks:
                    grand_total_gb += tgb
                    grand_free_gb += fgb
            grand_used_gb = grand_total_gb - grand_free_gb
            grand_pct = (grand_used_gb / grand_total_gb * 100) if grand_total_gb > 0 else 0

            def _bar_color(pct):
                if pct < 70: return "#22c55e"
                if pct < 85: return "#eab308"
                if pct < 95: return "#f97316"
                return "#ef4444"

            def _pct_class(pct):
                if pct < 70: return "good"
                if pct < 90: return "warn"
                return "bad"

            # Build server cards HTML
            cards_html = []
            for node in self.nodes:
                ip = node.get("ip", "")
                name = node.get("name", ip or "Unknown")
                tags = node.get("tags", [])
                conns = _get_connections(node)
                shares = node.get("shares", [])
                hosts = node.get("hosts", [])
                manage_url = node.get("manage_url", "")
                mac = node.get("mac", "")

                # Status
                if ip in self.maintenance_ips:
                    status_class = "maint"
                    status_text = "🔧 MAINTENANCE"
                elif self.node_statuses.get(ip) is True:
                    status_class = "online"
                    status_text = "🟢 ONLINE"
                elif self.node_statuses.get(ip) is False:
                    status_class = "offline"
                    status_text = "🔴 OFFLINE"
                else:
                    status_class = "unknown"
                    status_text = "⚪ UNKNOWN"

                # System info section (CPU, RAM, OS, etc.)
                sysinfo_html = ""
                si = all_sys_info.get(ip, {})
                if si:
                    sysinfo_html = '<div class="subsection"><h4>🖥️ System Info</h4>'
                    if si.get("os_name"):
                        sysinfo_html += f'<div class="stat-row"><span class="stat-label">OS:</span> <span>{si["os_name"]}</span></div>'
                    if si.get("model"):
                        sysinfo_html += f'<div class="stat-row"><span class="stat-label">Hardware:</span> <span>{si["model"]}</span></div>'
                    if si.get("last_boot"):
                        sysinfo_html += f'<div class="stat-row"><span class="stat-label">Last Boot:</span> <span class="dim">{si["last_boot"]}</span></div>'
                    # CPU gauge
                    if "cpu_pct" in si:
                        c = si["cpu_pct"]
                        cc = _bar_color(c)
                        sysinfo_html += f'''<div class="gauge-row"><span class="gauge-label">CPU</span>
                            <div class="gauge-bg"><div class="gauge-fill" style="width:{c}%;background:{cc};"></div>
                            <span class="gauge-text">{c:.0f}%</span></div></div>'''
                    # RAM gauge
                    if "ram_pct" in si:
                        r = si["ram_pct"]
                        rc = _bar_color(r)
                        ram_detail = ""
                        if "ram_total_gb" in si:
                            ram_detail = f' — {si["ram_used_gb"]:.1f} / {si["ram_total_gb"]:.1f} GB'
                        sysinfo_html += f'''<div class="gauge-row"><span class="gauge-label">RAM</span>
                            <div class="gauge-bg"><div class="gauge-fill" style="width:{r}%;background:{rc};"></div>
                            <span class="gauge-text">{r:.0f}%{ram_detail}</span></div></div>'''
                    sysinfo_html += '</div>'

                # Latency
                latency_html = ""
                hist = list(self.ping_history.get(ip, []))
                if hist:
                    valid = [v for v in hist if v > 0]
                    if valid:
                        avg_ms = sum(valid) / len(valid)
                        min_ms = min(valid)
                        max_ms = max(valid)
                        latency_html = f'<div class="stat-row"><span class="stat-label">Latency:</span> <span>{avg_ms:.1f}ms avg (min {min_ms:.1f} / max {max_ms:.1f})</span></div>'

                # Uptime
                uptime_html = ""
                up_hist = list(self.uptime_history.get(ip, []))
                if up_hist:
                    up_count = sum(1 for v in up_hist if v is True)
                    total_count = sum(1 for v in up_hist if v is not None)
                    if total_count > 0:
                        pct = (up_count / total_count * 100)
                        u_class = _pct_class(100 - pct)  # invert: high uptime = good
                        if pct >= 95: u_class = "good"
                        elif pct >= 80: u_class = "warn"
                        else: u_class = "bad"
                        uptime_html = f'<div class="stat-row"><span class="stat-label">Uptime:</span> <span class="{u_class}">{pct:.1f}% ({up_count}/{total_count})</span></div>'

                # Connections
                conn_badges = ""
                for c in conns:
                    ctype = c.get("type", "Custom")
                    cport = c.get("port", 0)
                    cinfo = CONNECTION_TYPES.get(ctype, CONNECTION_TYPES["Custom"])
                    conn_badges += f'<span class="badge">{cinfo["icon"]} {ctype}:{cport}</span> '

                # Shares
                shares_html = ""
                if shares:
                    shares_html = '<div class="subsection"><h4>📁 Share Drives</h4><table class="share-table">'
                    for sh in shares:
                        sh_icon = sh.get("icon", "📁")
                        sh_name = sh.get("name", "?")
                        sh_label = sh.get("label", sh_name)
                        cred_icon = "🔒" if sh.get("user") else "🔓"
                        esc_ip = ip if ip else "N/A"
                        shares_html += f'<tr><td>{sh_icon} {sh_label}</td><td>\\\\{esc_ip}\\{sh_name}</td><td>{cred_icon}</td></tr>'
                    shares_html += '</table></div>'

                # Sub-hosts
                hosts_html = ""
                if hosts:
                    hosts_html = '<div class="subsection"><h4>👥 Sub-Hosts</h4><table class="share-table">'
                    for h in hosts:
                        h_ip = h.get("ip", "?")
                        h_label = h.get("label", h_ip)
                        h_port = h.get("port", "")
                        h_proto = h.get("protocol", "")
                        ping_ip = h_ip.split(":")[0] if ":" in h_ip else h_ip
                        h_key = f"{ping_ip}:{h_port}" if h_port else ping_ip
                        h_status = self.node_statuses.get(h_key)
                        h_icon = "🟢" if h_status is True else ("🔴" if h_status is False else "⚪")
                        detail = f"{h_proto}://{h_ip}:{h_port}" if h_proto and h_port else h_ip
                        hosts_html += f'<tr><td>{h_icon} {h_label}</td><td>{detail}</td></tr>'
                    hosts_html += '</table></div>'

                # Disk bar charts (LIVE data with full size info)
                disk_html = ""
                node_disks = all_disk_data.get(ip, [])
                if node_disks:
                    disk_html = '<div class="subsection"><h4>📊 Disk Usage</h4>'
                    node_total = 0
                    node_free = 0
                    for drive_label, pct, total_gb, free_gb in node_disks:
                        bc = _bar_color(pct)
                        used_gb = total_gb - free_gb
                        node_total += total_gb
                        node_free += free_gb
                        disk_html += f'''<div class="disk-bar-row">
                            <span class="disk-label">{drive_label}</span>
                            <div class="disk-bar-bg">
                                <div class="disk-bar-fill" style="width:{pct:.1f}%;background:{bc};"></div>
                                <span class="disk-bar-text">{pct:.1f}% — {used_gb:.1f} / {total_gb:.1f} GB</span>
                            </div>
                            <span class="disk-size">{free_gb:.1f} GB free</span>
                        </div>'''
                    # Per-server total
                    if len(node_disks) > 1:
                        node_used = node_total - node_free
                        np = (node_used / node_total * 100) if node_total > 0 else 0
                        disk_html += f'<div class="disk-summary">Total: {node_total:.1f} GB | Used: {node_used:.1f} GB | Free: {node_free:.1f} GB | {np:.1f}% used</div>'
                    disk_html += '</div>'

                # Tags
                tags_html = ""
                if tags:
                    tags_html = " ".join(f'<span class="tag">{t}</span>' for t in tags)
                    tags_html = f'<div class="tags">{tags_html}</div>'

                # Info rows
                info_rows = ""
                if ip:
                    info_rows += f'<div class="stat-row"><span class="stat-label">IP Address:</span> <span>{ip}</span></div>'
                if mac:
                    info_rows += f'<div class="stat-row"><span class="stat-label">MAC:</span> <span>{mac}</span></div>'
                if manage_url:
                    info_rows += f'<div class="stat-row"><span class="stat-label">Management:</span> <a href="{manage_url}" target="_blank">{manage_url}</a></div>'

                card_html = f'''
                <div class="server-card {status_class}">
                    <div class="card-header">
                        <h3>{name}</h3>
                        <span class="status-badge {status_class}">{status_text}</span>
                    </div>
                    {tags_html}
                    <div class="connections">{conn_badges}</div>
                    {info_rows}
                    {latency_html}
                    {uptime_html}
                    {sysinfo_html}
                    {shares_html}
                    {hosts_html}
                    {disk_html}
                </div>'''
                cards_html.append(card_html)

            # Grand storage summary card
            grand_html = ""
            if grand_total_gb > 0:
                gc = _bar_color(grand_pct)
                grand_html = f'''
                <div class="grand-storage">
                    <h3>💾 Total Storage Across All Servers</h3>
                    <div class="disk-bar-row" style="margin:10px 0;">
                        <div class="disk-bar-bg" style="height:32px;">
                            <div class="disk-bar-fill" style="width:{grand_pct:.1f}%;background:{gc};height:100%;"></div>
                            <span class="disk-bar-text" style="font-size:13px;">{grand_pct:.1f}% — {grand_used_gb:.1f} TB used of {grand_total_gb/1024:.2f} TB</span>
                        </div>
                    </div>
                    <div class="grand-stats">
                        <span>Total: <b>{grand_total_gb:.1f} GB ({grand_total_gb/1024:.2f} TB)</b></span>
                        <span>Used: <b>{grand_used_gb:.1f} GB</b></span>
                        <span>Free: <b>{grand_free_gb:.1f} GB</b></span>
                    </div>
                </div>'''

            # Assemble full HTML
            html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NOC Master Report — {timestamp}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        background: #0a0f1a;
        color: #cbd5e1;
        font-family: 'Consolas', 'Courier New', monospace;
        padding: 20px;
    }}
    .report-header {{
        text-align: center;
        padding: 30px 20px;
        border-bottom: 2px solid #3b82f6;
        margin-bottom: 30px;
    }}
    .report-header h1 {{ color: #3b82f6; font-size: 28px; margin-bottom: 8px; }}
    .report-header .subtitle {{ color: #475569; font-size: 13px; }}
    .report-header .branding {{ color: #a855f7; font-size: 11px; margin-top: 8px; }}
    .summary-bar {{
        display: flex; justify-content: center; gap: 20px;
        margin-bottom: 30px; flex-wrap: wrap;
    }}
    .summary-card {{
        background: #0f172a; border: 1px solid #1e293b; border-radius: 10px;
        padding: 18px 28px; text-align: center; min-width: 130px;
    }}
    .summary-card .num {{ font-size: 32px; font-weight: bold; display: block; }}
    .summary-card .lbl {{ font-size: 11px; color: #475569; text-transform: uppercase; letter-spacing: 1px; }}
    .summary-card.online .num {{ color: #22c55e; }}
    .summary-card.offline .num {{ color: #ef4444; }}
    .summary-card.maint .num {{ color: #3b82f6; }}
    .summary-card.total .num {{ color: #cbd5e1; }}
    .summary-card.unknown .num {{ color: #475569; }}
    .grid {{
        display: grid; grid-template-columns: repeat(auto-fill, minmax(540px, 1fr));
        gap: 20px; padding: 0 10px;
    }}
    .server-card {{
        background: #0f172a; border: 1px solid #1e293b; border-radius: 10px;
        padding: 20px; transition: border-color 0.2s;
    }}
    .server-card:hover {{ border-color: #3b82f6; }}
    .server-card.online {{ border-left: 4px solid #22c55e; }}
    .server-card.offline {{ border-left: 4px solid #ef4444; }}
    .server-card.maint {{ border-left: 4px solid #3b82f6; }}
    .server-card.unknown {{ border-left: 4px solid #475569; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
    .card-header h3 {{ color: #f1f5f9; font-size: 16px; }}
    .status-badge {{ font-size: 12px; padding: 3px 10px; border-radius: 12px; font-weight: bold; }}
    .status-badge.online {{ background: #052e16; color: #22c55e; }}
    .status-badge.offline {{ background: #450a0a; color: #ef4444; }}
    .status-badge.maint {{ background: #0c1a3d; color: #3b82f6; }}
    .status-badge.unknown {{ background: #1e293b; color: #475569; }}
    .connections {{ margin: 8px 0; }}
    .badge {{ display: inline-block; background: #1e293b; color: #94a3b8; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 2px; }}
    .tags {{ margin: 6px 0; }}
    .tag {{ display: inline-block; background: #1e293b; color: #a78bfa; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 2px; }}
    .stat-row {{ padding: 3px 0; font-size: 13px; }}
    .stat-label {{ color: #475569; display: inline-block; width: 120px; }}
    .stat-row a {{ color: #3b82f6; text-decoration: none; }}
    .stat-row a:hover {{ text-decoration: underline; }}
    .good {{ color: #22c55e; }}
    .warn {{ color: #eab308; }}
    .bad {{ color: #ef4444; }}
    .dim {{ color: #475569; }}
    .subsection {{ margin-top: 12px; padding-top: 8px; border-top: 1px solid #1e293b; }}
    .subsection h4 {{ color: #3b82f6; font-size: 13px; margin-bottom: 6px; }}
    .share-table {{ width: 100%; font-size: 12px; border-collapse: collapse; }}
    .share-table td {{ padding: 3px 8px; border-bottom: 1px solid #0a0f1a; }}
    .share-table tr:hover td {{ background: #1e293b; }}
    /* Gauge bars for CPU/RAM */
    .gauge-row {{ display: flex; align-items: center; margin: 4px 0; }}
    .gauge-label {{ width: 40px; font-size: 11px; font-weight: bold; color: #94a3b8; text-align: right; padding-right: 8px; }}
    .gauge-bg {{ flex: 1; background: #1e293b; border-radius: 6px; height: 20px; position: relative; overflow: hidden; }}
    .gauge-fill {{ height: 100%; border-radius: 6px; }}
    .gauge-text {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 10px; font-weight: bold; color: white; text-shadow: 0 0 4px rgba(0,0,0,0.8); }}
    /* Disk bar charts */
    .disk-bar-row {{ display: flex; align-items: center; margin: 5px 0; }}
    .disk-label {{ min-width: 80px; font-size: 12px; font-weight: bold; text-align: right; padding-right: 10px; white-space: nowrap; }}
    .disk-bar-bg {{ flex: 1; background: #1e293b; border-radius: 6px; height: 26px; position: relative; overflow: hidden; }}
    .disk-bar-fill {{ height: 100%; border-radius: 6px; }}
    .disk-bar-text {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 11px; font-weight: bold; color: white; text-shadow: 0 0 4px rgba(0,0,0,0.8); white-space: nowrap; }}
    .disk-size {{ min-width: 100px; font-size: 11px; color: #94a3b8; padding-left: 10px; white-space: nowrap; }}
    .disk-summary {{ font-size: 12px; color: #94a3b8; margin-top: 6px; padding: 6px 10px; background: #0a0f1a; border-radius: 4px; text-align: center; }}
    /* Grand storage */
    .grand-storage {{
        background: #0f172a; border: 2px solid #3b82f6; border-radius: 10px;
        padding: 20px 30px; margin: 0 10px 30px 10px; text-align: center;
    }}
    .grand-storage h3 {{ color: #3b82f6; margin-bottom: 10px; font-size: 16px; }}
    .grand-stats {{ display: flex; justify-content: center; gap: 30px; margin-top: 8px; font-size: 13px; }}
    .grand-stats b {{ color: #f1f5f9; }}
    .report-footer {{
        text-align: center; padding: 30px 20px; margin-top: 30px;
        border-top: 1px solid #1e293b; color: #475569; font-size: 11px;
    }}
    .report-footer a {{ color: #3b82f6; text-decoration: none; }}
    @media print {{
        body {{ background: white; color: #1e293b; }}
        .server-card {{ border: 1px solid #ccc; page-break-inside: avoid; }}
        .summary-card {{ border: 1px solid #ccc; }}
        .disk-bar-bg, .gauge-bg {{ background: #e2e8f0; }}
        .badge, .tag {{ background: #e2e8f0; color: #334155; }}
        .grand-storage {{ border-color: #3b82f6; }}
        .no-print {{ display: none; }}
    }}
</style>
</head>
<body>

<div class="report-header">
    <h1>📋 NOC Master Report</h1>
    <div class="subtitle">Generated: {timestamp}  •  {APP_NAME} v{APP_VERSION}</div>
    <div class="branding">Developed by {APP_AUTHOR} — REGTeches / Bay Area Tech</div>
</div>

<div class="summary-bar">
    <div class="summary-card total"><span class="num">{total_nodes + total_hosts}</span><span class="lbl">Total Endpoints</span></div>
    <div class="summary-card online"><span class="num">{online_count}</span><span class="lbl">Online</span></div>
    <div class="summary-card offline"><span class="num">{offline_count}</span><span class="lbl">Offline</span></div>
    <div class="summary-card maint"><span class="num">{maint_count}</span><span class="lbl">Maintenance</span></div>
    <div class="summary-card unknown"><span class="num">{unknown_count}</span><span class="lbl">Unknown</span></div>
</div>

{grand_html}

<div class="no-print" style="text-align:center;margin-bottom:20px;">
    <button onclick="window.print()" style="background:#3b82f6;color:white;border:none;padding:10px 24px;border-radius:6px;font-family:Consolas;font-size:13px;cursor:pointer;">🖨️ Print Report</button>
    <button onclick="location.reload()" style="background:#1e293b;color:#cbd5e1;border:1px solid #334155;padding:10px 24px;border-radius:6px;font-family:Consolas;font-size:13px;cursor:pointer;margin-left:10px;">🔄 Refresh</button>
</div>

<div class="grid">
{"".join(cards_html)}
</div>

<div class="report-footer">
    {APP_NAME} v{APP_VERSION} &mdash; &copy; {now.year} {APP_AUTHOR} / REGTeches / Bay Area Tech<br>
    Report generated {timestamp}
</div>

</body>
</html>'''

            def _write_and_open():
                try:
                    dlg.destroy()
                except Exception:
                    pass
                try:
                    with open(report_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    webbrowser.open(report_path)
                    self.event_log.log(f"📋 Master Report generated: {report_path}", "OK")
                except Exception as e:
                    messagebox.showerror("Report Error", f"Could not generate report:\n{e}")

            dlg.after(0, _write_and_open)

        threading.Thread(target=_do_build, daemon=True).start()

    # ── Feature: Full Server Report ──────────────────────────────────────────

    def _show_server_report(self, node):
        """Show a comprehensive report for a server with bar charts for drives."""
        ip = node.get("ip", "N/A")
        name = node.get("name", ip)

        dlg = tk.Toplevel(self.root)
        dlg.title(f"\U0001F4CB Full Report \u2014 {name}")
        dlg.configure(bg=COLORS["bg"])
        _center_dialog(dlg, 700, 750, self.root)
        dlg.resizable(True, True)
        dlg.transient(self.root)

        # ── Title bar ──
        tk.Label(dlg, text=f"\U0001F4CB  Full Server Report",
                 font=("Consolas", 14, "bold"), fg=COLORS["accent"],
                 bg=COLORS["bg"]).pack(pady=(15, 2))
        tk.Label(dlg, text=f"{name}  \u2022  {ip}",
                 font=("Consolas", 10), fg=COLORS["text_dim"],
                 bg=COLORS["bg"]).pack(pady=(0, 5))

        progress_var = tk.StringVar(value="")
        progress_lbl = tk.Label(dlg, textvariable=progress_var,
                                font=("Consolas", 8), fg=COLORS["yellow"],
                                bg=COLORS["bg"])
        progress_lbl.pack()

        # ── Scrollable content area ──
        container = tk.Frame(dlg, bg=COLORS["bg"])
        container.pack(fill="both", expand=True, padx=10, pady=5)

        report_canvas = tk.Canvas(container, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=report_canvas.yview)
        scroll_inner = tk.Frame(report_canvas, bg=COLORS["bg"])
        scroll_inner.bind("<Configure>",
                          lambda e: report_canvas.configure(scrollregion=report_canvas.bbox("all")))
        report_canvas.create_window((0, 0), window=scroll_inner, anchor="nw")
        report_canvas.configure(yscrollcommand=scrollbar.set)
        report_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Enable mousewheel scroll inside report
        def _on_mw(event):
            report_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        report_canvas.bind_all("<MouseWheel>", _on_mw)
        dlg.bind("<Destroy>", lambda e: report_canvas.unbind_all("<MouseWheel>") if e.widget == dlg else None)

        # Track the canvas frame width for responsive layout
        def _resize_inner(event):
            report_canvas.itemconfigure(report_canvas.find_all()[0], width=event.width)
        report_canvas.bind("<Configure>", _resize_inner)

        # ── Helper to add section headers ──
        def add_section(parent, title):
            f = tk.Frame(parent, bg=COLORS["bg"])
            f.pack(fill="x", pady=(12, 4), padx=5)
            tk.Label(f, text=title, font=("Consolas", 11, "bold"),
                     fg=COLORS["accent"], bg=COLORS["bg"]).pack(anchor="w")
            sep = tk.Frame(f, bg=COLORS["accent"], height=1)
            sep.pack(fill="x", pady=(2, 0))
            return f

        def add_row(parent, label, value, value_fg=None):
            f = tk.Frame(parent, bg=COLORS["bg"])
            f.pack(fill="x", padx=15, pady=1)
            tk.Label(f, text=label, font=("Consolas", 9, "bold"),
                     fg=COLORS["text_dim"], bg=COLORS["bg"], width=20,
                     anchor="w").pack(side="left")
            tk.Label(f, text=str(value), font=("Consolas", 9),
                     fg=value_fg or COLORS["text"], bg=COLORS["bg"],
                     anchor="w", wraplength=400).pack(side="left", fill="x")

        def draw_bar_chart(parent, label, used_pct, total_str, free_str, width=420, height=28):
            """Draw a single horizontal bar chart for a drive."""
            f = tk.Frame(parent, bg=COLORS["bg"])
            f.pack(fill="x", padx=15, pady=3)

            tk.Label(f, text=label, font=("Consolas", 9, "bold"),
                     fg=COLORS["text"], bg=COLORS["bg"], width=8,
                     anchor="w").pack(side="left")

            bar_canvas = tk.Canvas(f, width=width, height=height,
                                   bg=COLORS["card_bg"], highlightthickness=1,
                                   highlightbackground=COLORS["card_border"])
            bar_canvas.pack(side="left", padx=(5, 8))

            # Determine color based on usage
            if used_pct < 70:
                fill_color = COLORS["green"]
            elif used_pct < 85:
                fill_color = COLORS["yellow"]
            elif used_pct < 95:
                fill_color = COLORS["orange"]
            else:
                fill_color = COLORS["red"]

            # Draw the filled portion
            fill_w = max(1, int((used_pct / 100.0) * width))
            bar_canvas.create_rectangle(0, 0, fill_w, height, fill=fill_color, outline="")

            # Draw percentage text centered on bar
            bar_canvas.create_text(width // 2, height // 2,
                                   text=f"{used_pct:.1f}% used",
                                   font=("Consolas", 8, "bold"),
                                   fill="white" if used_pct > 15 else COLORS["text"])

            # Size label to the right
            tk.Label(f, text=f"{free_str} free / {total_str}",
                     font=("Consolas", 8), fg=COLORS["text_dim"],
                     bg=COLORS["bg"]).pack(side="left")

        # ══════════════════════════════════════════════════════════════════
        # SECTION 1: Server Identity
        # ══════════════════════════════════════════════════════════════════
        add_section(scroll_inner, "\U0001F3F7\uFE0F  SERVER IDENTITY")
        add_row(scroll_inner, "Name:", name)
        add_row(scroll_inner, "IP Address:", ip)
        if node.get("mac"):
            add_row(scroll_inner, "MAC Address:", node["mac"])
        tags = node.get("tags", [])
        if tags:
            add_row(scroll_inner, "Tags:", ", ".join(tags))
        if node.get("manage_url"):
            add_row(scroll_inner, "Management URL:", node["manage_url"])
        if node.get("manage_label"):
            add_row(scroll_inner, "Manage Label:", node["manage_label"])

        # ══════════════════════════════════════════════════════════════════
        # SECTION 2: Connection Status
        # ══════════════════════════════════════════════════════════════════
        add_section(scroll_inner, "\U0001F4E1  CONNECTION STATUS")
        is_online = self.node_statuses.get(ip)
        if is_online is True:
            add_row(scroll_inner, "Ping Status:", "\U0001F7E2  ONLINE", COLORS["green"])
        elif is_online is False:
            add_row(scroll_inner, "Ping Status:", "\U0001F534  OFFLINE", COLORS["red"])
        else:
            add_row(scroll_inner, "Ping Status:", "\u26AA  Unknown", COLORS["text_dim"])

        # Latency from ping history
        hist = list(self.ping_history.get(ip, []))
        if hist:
            valid = [v for v in hist if v > 0]
            if valid:
                avg_ms = sum(valid) / len(valid)
                min_ms = min(valid)
                max_ms = max(valid)
                add_row(scroll_inner, "Avg Latency:", f"{avg_ms:.1f} ms")
                add_row(scroll_inner, "Min / Max:", f"{min_ms:.1f} ms / {max_ms:.1f} ms")

        # Uptime
        up_hist = list(self.uptime_history.get(ip, []))
        if up_hist:
            up_count = sum(1 for v in up_hist if v is True)
            total_count = sum(1 for v in up_hist if v is not None)
            if total_count > 0:
                pct = (up_count / total_count * 100)
                color = COLORS["green"] if pct >= 95 else (COLORS["yellow"] if pct >= 80 else COLORS["red"])
                add_row(scroll_inner, "Uptime:", f"{pct:.1f}%  ({up_count}/{total_count} checks)", color)

        # Maintenance
        if ip in self.maintenance_ips:
            remaining = ""
            if ip in self.maintenance_timers:
                left = self.maintenance_timers[ip]["end"] - time.time()
                if left > 0:
                    mins = int(left // 60)
                    remaining = f" ({mins}m remaining)"
            add_row(scroll_inner, "Maintenance:", f"\U0001F527  Active{remaining}", COLORS["yellow"])

        # ══════════════════════════════════════════════════════════════════
        # SECTION 3: Connection Types
        # ══════════════════════════════════════════════════════════════════
        conns = _get_connections(node)
        if conns:
            add_section(scroll_inner, "\U0001F50C  CONNECTION TYPES")
            for conn in conns:
                ctype = conn.get("type", "Custom")
                cport = conn.get("port", 0)
                info = CONNECTION_TYPES.get(ctype, CONNECTION_TYPES["Custom"])
                add_row(scroll_inner, f"  {info['icon']} {ctype}:",
                        f"Port {cport}  \u2014  {info['desc']}")

        # ══════════════════════════════════════════════════════════════════
        # SECTION 4: Share Drives
        # ══════════════════════════════════════════════════════════════════
        shares = node.get("shares", [])
        if shares:
            add_section(scroll_inner, "\U0001F4C1  SHARE DRIVES")
            for sh in shares:
                sh_icon = sh.get("icon", "\U0001F4C1")
                sh_name = sh.get("name", "?")
                sh_label = sh.get("label", sh_name)
                has_cred = "\U0001F512" if sh.get("user") else "\U0001F513"
                add_row(scroll_inner, f"  {sh_icon} {sh_label}:",
                        f"\\\\{ip}\\{sh_name}  {has_cred}")

        # ══════════════════════════════════════════════════════════════════
        # SECTION 5: Sub-Hosts
        # ══════════════════════════════════════════════════════════════════
        hosts = node.get("hosts", [])
        if hosts:
            add_section(scroll_inner, "\U0001F465  SUB-HOSTS")
            for h in hosts:
                h_ip = h.get("ip", "?")
                h_label = h.get("label", h_ip)
                h_port = h.get("port", "")
                h_proto = h.get("protocol", "")
                ping_ip = h_ip.split(":")[0] if ":" in h_ip else h_ip
                h_key = f"{ping_ip}:{h_port}" if h_port else ping_ip
                h_status = self.node_statuses.get(h_key)
                status_icon = "\U0001F7E2" if h_status is True else ("\U0001F534" if h_status is False else "\u26AA")
                detail = f"{h_proto}://{h_ip}:{h_port}" if h_proto and h_port else h_ip
                add_row(scroll_inner, f"  {status_icon} {h_label}:", detail)

        # ══════════════════════════════════════════════════════════════════
        # SECTION 6: Disk Space Bar Charts (the main attraction!)
        # ══════════════════════════════════════════════════════════════════
        # First show cached disk data if we have it
        cached_disks = self.disk_alerts.get(ip, {})
        if cached_disks:
            add_section(scroll_inner, "\U0001F4CA  DISK USAGE (cached)")
            for drive, pct in sorted(cached_disks.items()):
                draw_bar_chart(scroll_inner, drive, pct,
                               "", "")  # no size info from cache

        # Placeholder for live disk data
        disk_section_frame = tk.Frame(scroll_inner, bg=COLORS["bg"])
        disk_section_frame.pack(fill="x")

        # ── Buttons ──
        btn_frame = tk.Frame(dlg, bg=COLORS["bg"])
        btn_frame.pack(pady=(5, 10))

        def _fetch_live_disks():
            """Query live disk data and draw bar charts."""
            if not ip or ip == "N/A":
                return
            progress_var.set("Querying live disk data...")

            def _do_query():
                host = ip.split(":")[0] if ":" in ip else ip
                disk_data = []

                # Try WMI (Windows) first
                try:
                    ps = (
                        f"$opt = New-CimSessionOption -Protocol Dcom; "
                        f"$s = New-CimSession -ComputerName '{host}' -SessionOption $opt -ErrorAction Stop; "
                        f"Get-CimInstance Win32_LogicalDisk -CimSession $s -Filter 'DriveType=3' | "
                        f"ForEach-Object {{ Write-Output \"$($_.DeviceID) $($_.FreeSpace) $($_.Size)\" }}; "
                        f"Remove-CimSession $s"
                    )
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                        capture_output=True, text=True, timeout=20,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    for line in result.stdout.strip().splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 3 and ":" in parts[0]:
                            try:
                                drive = parts[0]
                                free_bytes = int(parts[1])
                                total_bytes = int(parts[2])
                                if total_bytes > 0:
                                    used_pct = ((total_bytes - free_bytes) / total_bytes) * 100
                                    total_gb = total_bytes / (1024 ** 3)
                                    free_gb = free_bytes / (1024 ** 3)
                                    disk_data.append((drive, used_pct, total_gb, free_gb))
                            except ValueError:
                                continue
                except Exception:
                    pass

                # If no WMI data, try Synology API
                if not disk_data:
                    synology_url = _detect_synology_url(node)
                    if synology_url:
                        try:
                            user, pwd = _get_synology_creds(node)
                            if user:
                                sid = synology_login(synology_url, user, pwd)
                                if sid:
                                    try:
                                        storage = synology_storage_info(synology_url, sid)
                                        if storage:
                                            for vol in storage.get("volumes", []):
                                                vol_path = vol.get("deploy_path", vol.get("id", "?"))
                                                total_bytes = int(vol.get("size", {}).get("total", "0"))
                                                used_bytes = int(vol.get("size", {}).get("used", "0"))
                                                if total_bytes > 0:
                                                    pct = (used_bytes / total_bytes) * 100
                                                    total_gb = total_bytes / (1024 ** 3)
                                                    free_gb = (total_bytes - used_bytes) / (1024 ** 3)
                                                    disk_data.append((vol_path, pct, total_gb, free_gb))
                                    finally:
                                        synology_logout(synology_url, sid)
                        except Exception:
                            pass

                # If no Synology, try ZimaOS
                if not disk_data:
                    zimaos_url = _detect_zimaos_url(node)
                    if zimaos_url:
                        try:
                            share_user, share_pass = _get_synology_creds(node)
                            zima_user = node.get("zima_user", share_user or "")
                            zima_pass = node.get("zima_pass", share_pass or "")
                            if zima_user:
                                token, _ = zimaos_login(zimaos_url, zima_user, zima_pass)
                                if token:
                                    data = zimaos_get(zimaos_url, "/v1/disks", token)
                                    disks_list = data.get("data", []) if isinstance(data, dict) else []
                                    if isinstance(disks_list, list):
                                        for disk in disks_list:
                                            for child in disk.get("children", []):
                                                mount = child.get("mount_point", "")
                                                csize = child.get("size", 0)
                                                avail = child.get("avail", 0)
                                                if csize > 0 and mount:
                                                    used_pct = ((csize - avail) / csize) * 100
                                                    total_gb = csize / (1024 ** 3)
                                                    free_gb = avail / (1024 ** 3)
                                                    disk_data.append((mount, used_pct, total_gb, free_gb))
                        except Exception:
                            pass

                # Render on main thread
                def _render():
                    # Check if dialog/frame still exists
                    try:
                        if not disk_section_frame.winfo_exists():
                            return
                    except Exception:
                        return
                    # Clear old disk section content
                    for w in disk_section_frame.winfo_children():
                        w.destroy()

                    if disk_data:
                        sf = tk.Frame(disk_section_frame, bg=COLORS["bg"])
                        sf.pack(fill="x", pady=(12, 4), padx=5)
                        tk.Label(sf, text="\U0001F4CA  DISK USAGE (live)",
                                 font=("Consolas", 11, "bold"),
                                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(anchor="w")
                        sep = tk.Frame(sf, bg=COLORS["accent"], height=1)
                        sep.pack(fill="x", pady=(2, 0))

                        for drive_label, used_pct, total_gb, free_gb in disk_data:
                            draw_bar_chart(disk_section_frame, drive_label,
                                           used_pct,
                                           f"{total_gb:.1f} GB",
                                           f"{free_gb:.1f} GB")

                        # Summary stats
                        total_space = sum(d[2] for d in disk_data)
                        total_free = sum(d[3] for d in disk_data)
                        total_used = total_space - total_free
                        overall_pct = (total_used / total_space * 100) if total_space > 0 else 0

                        summary_f = tk.Frame(disk_section_frame, bg=COLORS["card_bg"],
                                             padx=10, pady=6)
                        summary_f.pack(fill="x", padx=15, pady=(8, 4))
                        tk.Label(summary_f,
                                 text=f"\U0001F4CA  Total: {total_space:.1f} GB  |  Used: {total_used:.1f} GB  |  Free: {total_free:.1f} GB  |  Overall: {overall_pct:.1f}%",
                                 font=("Consolas", 9, "bold"),
                                 fg=COLORS["text_bright"], bg=COLORS["card_bg"]).pack()

                        progress_var.set(f"Done \u2014 {len(disk_data)} drive(s) found")
                    else:
                        tk.Label(disk_section_frame,
                                 text="    \u26A0\uFE0F  Could not retrieve live disk data (WMI/API not available)",
                                 font=("Consolas", 9), fg=COLORS["text_dim"],
                                 bg=COLORS["bg"]).pack(anchor="w", padx=15, pady=5)
                        progress_var.set("No live disk data available")

                try:
                    dlg.after(0, _render)
                except Exception:
                    pass

            threading.Thread(target=_do_query, daemon=True).start()

        tk.Button(btn_frame, text="\U0001F4CA  Fetch Live Disk Data",
                  font=("Consolas", 9, "bold"),
                  bg=COLORS["accent"], fg="white", relief="flat",
                  padx=15, pady=4, cursor="hand2",
                  command=_fetch_live_disks).pack(side="left", padx=5)
        tk.Button(btn_frame, text="\U0001F504  Refresh Report",
                  font=("Consolas", 9),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=15, pady=4, cursor="hand2",
                  command=lambda: [dlg.destroy(), self._show_server_report(node)]).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Close", font=("Consolas", 9),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=15, pady=4, cursor="hand2",
                  command=dlg.destroy).pack(side="left", padx=5)

        # Auto-fetch live disk data on open
        if ip and ip != "N/A":
            dlg.after(500, _fetch_live_disks)

    # ── Feature: Uptime History Chart ─────────────────────────────────────────

    def _show_uptime_history(self, node):
        """Show a timeline chart of uptime history for a server."""
        ip = node.get("ip")
        if not ip:
            return

        history = list(self.uptime_history.get(ip, []))

        dlg = tk.Toplevel(self.root)
        dlg.title(f"\U0001F4C8 Uptime History \u2014 {node.get('name', ip)}")
        dlg.configure(bg=COLORS["bg"])
        _center_dialog(dlg, 600, 300, self.root)
        dlg.resizable(True, False)
        dlg.transient(self.root)

        tk.Label(dlg, text=f"\U0001F4C8  Uptime History: {node.get('name', ip)}",
                 font=("Consolas", 13, "bold"), fg=COLORS["accent"],
                 bg=COLORS["bg"]).pack(pady=(15, 2))

        # Uptime percentage
        if history:
            up_count = sum(1 for v in history if v is True)
            total_count = sum(1 for v in history if v is not None)
            pct = (up_count / total_count * 100) if total_count > 0 else 0
            color = COLORS["green"] if pct >= 95 else (COLORS["yellow"] if pct >= 80 else COLORS["red"])
            tk.Label(dlg, text=f"Uptime: {pct:.1f}%  ({up_count}/{total_count} checks passed)",
                     font=("Consolas", 11, "bold"), fg=color,
                     bg=COLORS["bg"]).pack(pady=(2, 2))

            # Time range
            interval_sec = self.ping_interval
            total_seconds = len(history) * interval_sec
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            range_str = f"Showing last {hours}h {minutes}m ({len(history)} checks at {interval_sec}s intervals)"
            tk.Label(dlg, text=range_str, font=("Consolas", 8),
                     fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(pady=(0, 8))
        else:
            tk.Label(dlg, text="No uptime data collected yet. Wait for a few check cycles.",
                     font=("Consolas", 9), fg=COLORS["text_dim"],
                     bg=COLORS["bg"]).pack(pady=20)

        # Timeline canvas
        timeline = tk.Canvas(dlg, height=60, bg=COLORS["sparkline_bg"], highlightthickness=0)
        timeline.pack(fill="x", padx=20, pady=(0, 5))

        def draw_timeline(canvas, data):
            canvas.delete("all")
            w = canvas.winfo_width() or 560
            h = canvas.winfo_height() or 60
            if not data:
                canvas.create_text(w // 2, h // 2, text="No data",
                                   font=("Consolas", 9), fill=COLORS["text_dim"])
                return
            bar_h = 30
            y_top = (h - bar_h) // 2
            seg_w = w / len(data)
            for i, val in enumerate(data):
                x0 = i * seg_w
                x1 = (i + 1) * seg_w
                if val is True:
                    fill = COLORS["green"]
                elif val is False:
                    fill = COLORS["red"]
                else:
                    fill = COLORS["text_dim"]
                canvas.create_rectangle(x0, y_top, x1, y_top + bar_h, fill=fill, outline="")
            # Labels
            canvas.create_text(4, h - 4, text="oldest", font=("Consolas", 7),
                               fill=COLORS["text_dim"], anchor="sw")
            canvas.create_text(w - 4, h - 4, text="newest", font=("Consolas", 7),
                               fill=COLORS["text_dim"], anchor="se")

        # Draw after widget is realized
        dlg.after(100, lambda: draw_timeline(timeline, history))
        timeline.bind("<Configure>", lambda e: draw_timeline(timeline, history))

        # Legend
        legend = tk.Frame(dlg, bg=COLORS["bg"])
        legend.pack(pady=(0, 5))
        for color, label in [(COLORS["green"], "Online"), (COLORS["red"], "Offline"), (COLORS["text_dim"], "No Data")]:
            f = tk.Frame(legend, bg=COLORS["bg"])
            f.pack(side="left", padx=10)
            tk.Canvas(f, width=12, height=12, bg=color, highlightthickness=0).pack(side="left", padx=(0, 4))
            tk.Label(f, text=label, font=("Consolas", 8), fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")

        tk.Button(dlg, text="Close", font=("Consolas", 9),
                  bg=COLORS["share_bg"], fg=COLORS["text"], relief="flat",
                  padx=20, pady=4, cursor="hand2", command=dlg.destroy).pack(pady=(5, 10))

    # ── Feature: Launch REGTeches Tools ───────────────────────────────────────

    def _launch_tool(self, name, path):
        """Launch a REGTeches tool in a new console process."""
        if not os.path.exists(path):
            messagebox.showwarning("Tool Not Found", f"Cannot find:\n{path}")
            return
        try:
            subprocess.Popen(["python", path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.event_log.log(f"\U0001F680 Launched: {name}", "OK")
        except Exception as e:
            self.event_log.log(f"Failed to launch {name}: {e}", "ERROR")
            messagebox.showerror("Launch Error", f"Could not launch {name}:\n{e}")

    # ── Feature: Disk Space Alerts ────────────────────────────────────────────

    def _start_disk_check_loop(self):
        """Start a background loop that checks disk space on SMB-connected nodes."""
        def loop():
            while self.running:
                self._check_disk_space()
                for _ in range(self.disk_check_interval * 10):
                    if not self.running:
                        return
                    time.sleep(0.1)
        threading.Thread(target=loop, daemon=True).start()

    def _check_disk_space(self):
        """Query disk space via WMI for nodes with SMB connections."""
        for node in self.nodes:
            ip = node.get("ip")
            if not ip:
                continue
            conns = _get_connections(node)
            has_smb = any(c.get("type") == "SMB" for c in conns)
            if not has_smb:
                continue
            # Only check if the node is currently online
            if not self.node_statuses.get(ip):
                continue

            def _query_disk(target_ip=ip, target_node=node):
                try:
                    host = target_ip.split(":")[0] if ":" in target_ip else target_ip
                    ps = (f"$opt = New-CimSessionOption -Protocol Dcom; "
                          f"$s = New-CimSession -ComputerName '{host}' -SessionOption $opt -ErrorAction Stop; "
                          f"Get-CimInstance Win32_LogicalDisk -CimSession $s -Filter 'DriveType=3' | "
                          f"ForEach-Object {{ Write-Output \"$($_.DeviceID) $($_.FreeSpace) $($_.Size)\" }}; "
                          f"Remove-CimSession $s")
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                        capture_output=True, text=True, timeout=20,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    alerts = {}
                    for line in result.stdout.strip().splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 3 and ":" in parts[0]:
                            drive = parts[0]
                            try:
                                free_bytes = int(parts[1])
                                total_bytes = int(parts[2])
                                if total_bytes > 0:
                                    used_pct = ((total_bytes - free_bytes) / total_bytes) * 100
                                    alerts[drive] = round(used_pct, 1)
                            except ValueError:
                                continue
                    if alerts:
                        self.disk_alerts[target_ip] = alerts
                        # Update disk label on the card
                        over_threshold = {d: p for d, p in alerts.items() if p >= self.disk_alert_threshold}
                        if target_ip in self.disk_alert_labels:
                            if over_threshold:
                                parts = [f"{d} {p:.0f}%" for d, p in sorted(over_threshold.items())]
                                txt = "\u26A0\uFE0F DISK: " + "  ".join(parts)
                                self.root.after(0, lambda t=txt, lip=target_ip:
                                    self.disk_alert_labels.get(lip, tk.Label()).configure(text=t))
                            else:
                                self.root.after(0, lambda lip=target_ip:
                                    self.disk_alert_labels.get(lip, tk.Label()).configure(text=""))
                        # Check for threshold breaches
                        for drive, pct in alerts.items():
                            if pct >= 95 and self.sms_config.get("enabled"):
                                # Critical disk alert via SMS
                                cooldown_key = f"disk_{target_ip}_{drive}"
                                now = time.time()
                                last = self.sms_cooldowns.get(cooldown_key, 0)
                                if now - last > 3600:  # 1-hour cooldown for disk alerts
                                    self.sms_cooldowns[cooldown_key] = now
                                    name = target_node.get("name", target_ip)
                                    send_sms_alert(
                                        self.sms_config,
                                        f"NOC: DISK CRITICAL {name}",
                                        f"[NOC] DISK CRITICAL: {name} ({target_ip}) drive {drive} is {pct:.0f}% full!"
                                    )
                            if pct >= self.disk_alert_threshold:
                                name = target_node.get("name", target_ip)
                                self.root.after(0, lambda n=name, d=drive, p=pct:
                                    self.event_log.log(
                                        f"\u26A0\uFE0F DISK: {n} drive {d} is {p:.0f}% full", "WARN"))
                except Exception:
                    pass

            threading.Thread(target=_query_disk, daemon=True).start()

    def _on_close(self):
        self.running = False
        self.event_log.log("Dashboard shutting down", "INFO")
        self.root.destroy()


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()

    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Vertical.TScrollbar",
        background=COLORS["card_border"],
        troughcolor=COLORS["bg"],
        bordercolor=COLORS["bg"],
        arrowcolor=COLORS["text_dim"],
    )

    app = NOCDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
