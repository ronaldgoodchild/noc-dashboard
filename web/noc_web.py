"""
REGTeches NOC Web Dashboard
Network Operations Center - Web-Based Server Monitor
Developed by Ronald Goodchild
Runs on ZimaOS as a Docker container and windows stand a lone with host networking
"""

import os
import sys
import json
import time
import socket
import platform
import subprocess
import threading
import smtplib
import ssl
import zipfile
import urllib.request
try:
    import speedtest as _speedtest_mod
    SPEEDTEST_OK = True
except ImportError:
    SPEEDTEST_OK = False
import urllib.parse
from datetime import datetime
from collections import deque
from email.mime.text import MIMEText
from functools import wraps

from flask import (Flask, render_template, request, jsonify, session,
                   redirect, url_for, flash)

# ─── Configuration ───────────────────────────────────────────────────────────

APP_VERSION = "5.12.0"
APP_AUTHOR  = "Ronald Goodchild"

_SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE   = os.path.join(_SCRIPT_DIR, "noc_settings.json")
SERVERS_FILE    = os.path.join(_SCRIPT_DIR, "noc_servers.json")
SMS_CONFIG_FILE = os.path.join(_SCRIPT_DIR, "noc_sms.json")
LOG_FILE        = os.path.join(_SCRIPT_DIR, "noc_events.log")

# Status file lives next to the script on Windows; override via NOC_DATA_DIR env var
DATA_DIR    = os.environ.get("NOC_DATA_DIR", _SCRIPT_DIR)
STATUS_FILE = os.path.join(DATA_DIR, "noc_status.json")

# ─── Load noc_settings.json ──────────────────────────────────────────────────
def _load_app_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

_cfg = _load_app_settings()

def _bootstrap_credentials(cfg):
    """First run: replace missing/default credentials with random ones and save them.

    The web UI is reachable by anyone on the network, so it must never run with the
    old built-in defaults (admin / changeme, "change-this-secret").
    """
    import secrets
    changed = False
    env_secret = os.environ.get("SECRET_KEY")
    if env_secret:
        cfg["secret_key"] = env_secret
    elif cfg.get("secret_key") in (None, "", "change-this-secret"):
        cfg["secret_key"] = secrets.token_hex(32)
        changed = True
    if cfg.get("auth_pass") in (None, "", "changeme"):
        cfg["auth_user"] = cfg.get("auth_user") or "admin"
        cfg["auth_pass"] = secrets.token_urlsafe(9)
        print("=" * 60)
        print("  First run - generated login credentials")
        print(f"  Username: {cfg['auth_user']}")
        print(f"  Password: {cfg['auth_pass']}")
        print("  Saved to noc_settings.json (change them under Settings)")
        print("=" * 60)
        changed = True
    if changed:
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except OSError as e:
            print(f"  WARNING: could not save {SETTINGS_FILE}: {e}")
    return cfg


_cfg = _bootstrap_credentials(_cfg)

APP_NAME      = _cfg.get("title",        "REGTeches NOC Web Dashboard")
AUTH_USER     = _cfg["auth_user"]
AUTH_PASS     = _cfg["auth_pass"]
SECRET_KEY    = _cfg["secret_key"]
SCAN_INTERVAL = int(_cfg.get("scan_interval", os.environ.get("SCAN_INTERVAL", "30")))
PING_TIMEOUT  = int(_cfg.get("ping_timeout",  2))
HISTORY_SIZE  = 60

_BUILTIN_NODES = []  # all server config lives in noc_servers.json

CONNECTION_TYPES = {
    "SMB": {"port": 445, "icon": "📁", "desc": "Windows File Share (SMB/CIFS)"},
    "FTP": {"port": 21, "icon": "📥", "desc": "FTP File Transfer"},
    "FTPS": {"port": 990, "icon": "🔒", "desc": "FTP over SSL/TLS"},
    "RDP": {"port": 3389, "icon": "🖥️", "desc": "Remote Desktop Protocol"},
    "SSH": {"port": 22, "icon": "📟", "desc": "Secure Shell"},
    "Telnet": {"port": 23, "icon": "📟", "desc": "Telnet Terminal"},
    "HTTP": {"port": 80, "icon": "🌐", "desc": "Web Interface (HTTP)"},
    "HTTPS": {"port": 443, "icon": "🔒", "desc": "Web Interface (HTTPS)"},
    "Plex": {"port": 32400, "icon": "🎬", "desc": "Plex Media Server"},
    "Custom": {"port": 0, "icon": "🔧", "desc": "Custom Port / Protocol"},
}

SMS_CARRIERS = {
    "AT&T": "txt.att.net",
    "T-Mobile": "tmomail.net",
    "Verizon": "vtext.com",
    "Sprint": "messaging.sprintpcs.com",
    "Xfinity / Comcast": "vtext.com",
    "US Cellular": "email.uscc.net",
    "Boost Mobile": "sms.myboostmobile.com",
    "Cricket": "sms.cricketwireless.net",
    "Metro PCS": "mymetropcs.com",
    "Google Fi": "msg.fi.google.com",
    "Mint Mobile": "tmomail.net",
    "Visible": "vtext.com",
    "Consumer Cellular": "mailmymobile.net",
    "Straight Talk": "vtext.com",
}

# ─── SSL context for self-signed certs ───────────────────────────────────────
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# ─── Flask App ───────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder=os.path.join(_SCRIPT_DIR, "templates"),
    static_folder=os.path.join(_SCRIPT_DIR, "static"),
)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours

# ─── Global State ────────────────────────────────────────────────────────────
nodes = []
node_statuses = {}        # ip_key -> {"online": bool, "ms": int, "last_check": str}
prev_statuses = {}        # ip_key -> bool (for change detection)
ping_history = {}         # ip_key -> deque of ms values (-1 = offline)
uptime_data = {}          # ip_key -> {"up": int, "total": int}
maintenance_ips = set()
maintenance_timers = {}   # ip -> {"end": timestamp, "label": str}
event_log = deque(maxlen=1000)
sms_config = {}
sms_cooldowns = {}
scan_running = False
scan_lock = threading.Lock()
service_stats = {}        # ip_key -> list of {val, lbl} for inline card display


# ─── Config Persistence ─────────────────────────────────────────────────────

def load_config():
    global nodes
    if os.path.exists(SERVERS_FILE):
        try:
            with open(SERVERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            nodes = data if isinstance(data, list) else data.get("nodes", [])
            if nodes:
                return
        except (json.JSONDecodeError, IOError):
            pass
    # Last resort: built-in stub (user should populate noc_servers.json)
    nodes = [dict(n) for n in _BUILTIN_NODES]
    save_config(backup=False)


def save_config(backup=True):
    global nodes
    if backup:
        _create_backup("pre-edit")
    try:
        with open(SERVERS_FILE, "w", encoding="utf-8") as f:
            json.dump(nodes, f, indent=2, ensure_ascii=False)
    except IOError as e:
        log_event(f"Config save error: {e}", "ERROR")


def load_sms_config():
    global sms_config
    if os.path.exists(SMS_CONFIG_FILE):
        try:
            with open(SMS_CONFIG_FILE, "r", encoding="utf-8") as f:
                sms_config = json.load(f)
                return
        except (json.JSONDecodeError, IOError):
            pass
    sms_config = {
        "enabled": False,
        "recipients": [],
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": "",
        "alert_offline": True,
        "alert_online": True,
        "cooldown_minutes": 5,
        # Email alerts
        "email_enabled": False,
        "email_recipients": [],
        # Webhook alerts
        "discord_webhook": "",
        "slack_webhook": "",
    }


def save_sms_config():
    try:
        with open(SMS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(sms_config, f, indent=2, ensure_ascii=False)
    except IOError:
        pass


# ─── Backup / Restore ────────────────────────────────────────────────────────

BACKUP_DIR  = os.path.join(_SCRIPT_DIR, "backups")
MAX_BACKUPS = 5          # keep 5 rolling copies; oldest is removed first


def _create_backup(reason="auto"):
    """Zip every file in the script directory into a timestamped backup."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{ts}_{reason}.zip"
        path = os.path.join(BACKUP_DIR, filename)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in sorted(os.listdir(_SCRIPT_DIR)):
                fpath = os.path.join(_SCRIPT_DIR, fname)
                # skip the backups subdirectory and compiled Python cache
                if os.path.isfile(fpath) and not fname.endswith(".pyc"):
                    zf.write(fpath, fname)
        _prune_backups()
        log_event(f"Backup created: {filename}", "INFO")
        return filename
    except Exception as e:
        log_event(f"Backup create error: {e}", "ERROR")
        return None


def _prune_backups():
    """Delete oldest backups so only MAX_BACKUPS zip files are kept."""
    try:
        files = sorted([
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith("backup_") and f.endswith(".zip")
        ])
        while len(files) > MAX_BACKUPS:
            os.remove(os.path.join(BACKUP_DIR, files.pop(0)))
    except Exception:
        pass


# ─── Event Logger ────────────────────────────────────────────────────────────

def log_event(message, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"ts": ts, "level": level, "msg": message}
    event_log.append(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {message}\n")
    except IOError:
        pass


# ─── SMS Alerts ──────────────────────────────────────────────────────────────

def send_sms_alert(subject, body):
    if not sms_config.get("enabled") or not sms_config.get("recipients"):
        return
    smtp_user = sms_config.get("smtp_user", "")
    smtp_pass = sms_config.get("smtp_pass", "")
    if not smtp_user or not smtp_pass:
        return

    def _send():
        try:
            server = smtplib.SMTP(sms_config.get("smtp_server", "smtp.gmail.com"),
                                  sms_config.get("smtp_port", 587), timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            for recip in sms_config.get("recipients", []):
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
            log_event(f"SMS send error: {e}", "ERROR")

    threading.Thread(target=_send, daemon=True).start()


def send_email_alert(subject, body):
    """Send a plain-text email to each address in sms_config['email_recipients']."""
    if not sms_config.get("email_enabled"):
        return
    recipients = [r.strip() for r in sms_config.get("email_recipients", []) if r.strip()]
    if not recipients:
        return
    smtp_user = sms_config.get("smtp_user", "")
    smtp_pass = sms_config.get("smtp_pass", "")
    if not smtp_user or not smtp_pass:
        return

    def _send():
        try:
            srv = smtplib.SMTP(sms_config.get("smtp_server", "smtp.gmail.com"),
                               sms_config.get("smtp_port", 587), timeout=15)
            srv.ehlo(); srv.starttls(); srv.ehlo()
            srv.login(smtp_user, smtp_pass)
            for addr in recipients:
                msg = MIMEText(body)
                msg["From"] = smtp_user
                msg["To"] = addr
                msg["Subject"] = subject
                srv.sendmail(smtp_user, addr, msg.as_string())
            srv.quit()
        except Exception as e:
            log_event(f"Email alert error: {e}", "ERROR")

    threading.Thread(target=_send, daemon=True).start()


def send_webhook_alert(subject, body, online=False):
    """POST alert to Discord and/or Slack webhooks."""
    discord_url = sms_config.get("discord_webhook", "").strip()
    slack_url   = sms_config.get("slack_webhook",   "").strip()
    if not discord_url and not slack_url:
        return
    color_int = 0x22c55e if online else 0xef4444   # green / red
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _send():
        if discord_url:
            try:
                payload = json.dumps({
                    "embeds": [{
                        "title": subject,
                        "description": body,
                        "color": color_int,
                        "footer": {"text": f"REGTeches NOC • {ts}"},
                    }]
                }).encode()
                req = urllib.request.Request(
                    discord_url, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10)
                log_event(f"Discord alert sent: {subject}", "INFO")
            except Exception as e:
                log_event(f"Discord webhook error: {e}", "ERROR")

        if slack_url:
            try:
                payload = json.dumps({
                    "attachments": [{
                        "color": "good" if online else "danger",
                        "title": subject,
                        "text": body,
                        "footer": f"REGTeches NOC • {ts}",
                    }]
                }).encode()
                req = urllib.request.Request(
                    slack_url, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10)
                log_event(f"Slack alert sent: {subject}", "INFO")
            except Exception as e:
                log_event(f"Slack webhook error: {e}", "ERROR")

    threading.Thread(target=_send, daemon=True).start()


def send_sms_for_ip(ip, name, online=False, ms=0):
    cooldown = sms_config.get("cooldown_minutes", 5) * 60
    now = time.time()
    cooldown_key = f"{ip}_{'on' if online else 'off'}"
    last = sms_cooldowns.get(cooldown_key, 0)
    if now - last < cooldown:
        return
    sms_cooldowns[cooldown_key] = now
    timestamp = datetime.now().strftime("%I:%M %p")
    if online:
        subject = f"NOC: {name} ONLINE"
        body = f"[NOC] {name} is back ONLINE at {timestamp} ({ms}ms)"
    else:
        subject = f"NOC: {name} OFFLINE"
        body = f"[NOC ALERT] {name} went OFFLINE at {timestamp}"
    send_sms_alert(subject, body)
    send_email_alert(subject, body)
    send_webhook_alert(subject, body, online=online)
    log_event(f"Alert sent: {subject}", "INFO")


# ─── Network Scanning ───────────────────────────────────────────────────────

def check_port(host, port, timeout=PING_TIMEOUT):
    """Check if a TCP port is open. Returns (online, ms)."""
    try:
        # Resolve hostname first
        try:
            resolved = socket.gethostbyname(host)
        except Exception:
            resolved = host
        start = time.monotonic()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((resolved, port))
        ms = int((time.monotonic() - start) * 1000)
        s.close()
        return True, max(ms, 1)
    except Exception:
        return False, 0


def ping_host(host, timeout=PING_TIMEOUT):
    """Ping via ICMP using system ping command. Returns (online, ms)."""
    import subprocess
    host = host.split(":")[0] if ":" in host and not host.startswith("[") else host
    try:
        # Linux ping syntax
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            capture_output=True, text=True, timeout=timeout + 2
        )
        if result.returncode == 0:
            # Parse ms from output
            out = result.stdout
            for line in out.splitlines():
                if "time=" in line:
                    try:
                        ms_str = line.split("time=")[1].split()[0].replace("ms", "")
                        return True, max(1, int(float(ms_str)))
                    except (ValueError, IndexError):
                        return True, 1
            return True, 1
        return False, 0
    except Exception:
        return False, 0


def _get_connections(node):
    if "connections" in node and node["connections"]:
        return node["connections"]
    ctype = node.get("type", "SMB")
    port = node.get("port", CONNECTION_TYPES.get(ctype, {}).get("port", 0))
    return [{"type": ctype, "port": port}]


def _find_name_for_ip(ip_key):
    """Find the display name for an ip_key."""
    for node in nodes:
        node_ip = node.get("ip", "")
        if node_ip == ip_key:
            return node.get("name", ip_key)
        for h in node.get("hosts", []):
            h_ip = h.get("ip", "")
            h_port = h.get("port")
            h_proto = h.get("protocol", "")
            if h_port:
                key = f"{h_ip}:{h_port}"
            elif h_proto:
                key = f"{h_ip}:{h_proto}"
            else:
                key = h_ip
            if key == ip_key:
                return f"{node.get('name', '')} → {h.get('label', h_ip)}"
    return ip_key


def do_scan():
    """Scan all servers and update global state."""
    global scan_running
    with scan_lock:
        if scan_running:
            return
        scan_running = True

    try:
        all_checks = []  # list of (ip_key, host, port, name)

        for node in nodes:
            ip = node.get("ip", "")
            if not ip:
                continue
            name = node.get("name", ip)
            conns = _get_connections(node)
            # Use first connection's port for primary check
            if conns:
                primary = conns[0]
                port = primary.get("port", 80)
            else:
                port = 80
            # Strip port from IP if embedded (like "192.168.1.87:8006")
            if ":" in ip and not ip.startswith("["):
                parts = ip.rsplit(":", 1)
                host = parts[0]
                try:
                    port = int(parts[1])
                except ValueError:
                    host = ip
            else:
                host = ip
            all_checks.append((ip, host, port, name))

            # Sub-hosts
            for h in node.get("hosts", []):
                h_ip = h.get("ip", "")
                h_label = h.get("label", h_ip)
                h_port = h.get("port")
                h_proto = h.get("protocol", "")
                if not h_ip:
                    continue
                # Build unique key
                if h_port:
                    ip_key = f"{h_ip}:{h_port}"
                    h_check_host = h_ip.split(":")[0]
                    h_check_port = int(h_port)
                elif h_proto:
                    default_port = {"http": 80, "https": 443}.get(h_proto.lower(), 80)
                    ip_key = f"{h_ip}:{default_port}"
                    h_check_host = h_ip.split(":")[0]
                    h_check_port = default_port
                else:
                    ip_key = h_ip
                    h_check_host = h_ip.split(":")[0]
                    h_check_port = 80
                all_checks.append((ip_key, h_check_host, h_check_port,
                                   f"{name} → {h_label}"))

        # Run checks in parallel threads
        results = {}
        results_lock = threading.Lock()

        def check_one(ck_ip_key, ck_host, ck_port, ck_name):
            online, ms = check_port(ck_host, ck_port)
            # If port check fails, try ICMP ping
            if not online:
                online, ms = ping_host(ck_host)
            with results_lock:
                results[ck_ip_key] = {"online": online, "ms": ms, "name": ck_name}

        threads = []
        for ip_key, host, port, name in all_checks:
            t = threading.Thread(target=check_one, args=(ip_key, host, port, name))
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=PING_TIMEOUT + 3)

        # Update global state
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for ip_key, result in results.items():
            online = result["online"]
            ms = result["ms"]
            name = result["name"]

            # Check for status changes (not during maintenance)
            prev = prev_statuses.get(ip_key)
            if prev is not None and prev != online and ip_key not in maintenance_ips:
                if online:
                    log_event(f"🟢 {name} ({ip_key}) came ONLINE ({ms}ms)", "OK")
                    if sms_config.get("alert_online"):
                        send_sms_for_ip(ip_key, name, online=True, ms=ms)
                else:
                    log_event(f"🔴 {name} ({ip_key}) went OFFLINE", "ERROR")
                    if sms_config.get("alert_offline"):
                        send_sms_for_ip(ip_key, name, online=False)

            prev_statuses[ip_key] = online
            node_statuses[ip_key] = {
                "online": online, "ms": ms, "last_check": now_str
            }

            # Ping history for sparkline
            if ip_key not in ping_history:
                ping_history[ip_key] = deque(maxlen=HISTORY_SIZE)
            ping_history[ip_key].append(ms if online else -1)

            # Uptime tracking
            if ip_key not in uptime_data:
                uptime_data[ip_key] = {"up": 0, "total": 0}
            uptime_data[ip_key]["total"] += 1
            if online:
                uptime_data[ip_key]["up"] += 1

        # Write backwards-compatible JSON for PHP NOC page
        _write_status_json(results, now_str)

        # Check maintenance timers
        expired = []
        for ip, timer in maintenance_timers.items():
            if time.time() > timer["end"]:
                expired.append(ip)
        for ip in expired:
            maintenance_ips.discard(ip)
            del maintenance_timers[ip]
            log_event(f"🔧 Maintenance ended for {ip}", "INFO")

        # Refresh inline service stats in background (non-blocking)
        threading.Thread(target=fetch_all_service_stats, daemon=True).start()

    except Exception as e:
        log_event(f"Scan error: {e}", "ERROR")
    finally:
        with scan_lock:
            scan_running = False


def _write_status_json(results, timestamp):
    """Write status JSON compatible with the PHP NOC page scanner."""
    servers = []
    for node in nodes:
        ip = node.get("ip", "")
        if not ip:
            continue
        status = results.get(ip, {})
        conns = _get_connections(node)
        primary_type = conns[0].get("type", "TCP") if conns else "TCP"
        primary_port = conns[0].get("port", 80) if conns else 80
        manage_url = node.get("manage_url", "")
        tags = node.get("tags", [])
        icon = tags[0] if tags else "server"
        servers.append({
            "name": node.get("name", ip),
            "ip": ip,
            "port": primary_port,
            "type": primary_type,
            "manage_url": manage_url,
            "icon": icon,
            "online": status.get("online", False),
            "response_time": status.get("ms", 0),
        })
    data = {"timestamp": timestamp, "servers": servers}
    try:
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, STATUS_FILE)
    except Exception:
        pass


def scan_loop():
    """Background scanner thread."""
    log_event(f"Scanner started — monitoring {len(nodes)} nodes every {SCAN_INTERVAL}s", "INFO")
    while True:
        do_scan()
        time.sleep(SCAN_INTERVAL)


# ─── Synology DSM API ───────────────────────────────────────────────────────

def synology_login(base_url, username, password):
    params = {
        "api": "SYNO.API.Auth", "version": "6", "method": "login",
        "account": username, "passwd": password, "format": "sid",
    }
    url = f"{base_url}/webapi/auth.cgi?{urllib.parse.urlencode(params)}"
    try:
        resp = urllib.request.urlopen(urllib.request.Request(url), timeout=15, context=_ssl_ctx)
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("success"):
            return data["data"]["sid"]
    except Exception:
        pass
    return None


def synology_logout(base_url, sid):
    try:
        params = {"api": "SYNO.API.Auth", "version": "6", "method": "logout", "_sid": sid}
        url = f"{base_url}/webapi/auth.cgi?{urllib.parse.urlencode(params)}"
        urllib.request.urlopen(urllib.request.Request(url), timeout=5, context=_ssl_ctx)
    except Exception:
        pass


def synology_api_call(base_url, api, version, method, sid=None, extra_params=None):
    params = {"api": api, "version": str(version), "method": method}
    if sid:
        params["_sid"] = sid
    if extra_params:
        params.update(extra_params)
    url = f"{base_url}/webapi/entry.cgi?{urllib.parse.urlencode(params)}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=15, context=_ssl_ctx)
    return json.loads(resp.read().decode("utf-8"))


def _detect_synology_url(node):
    ip = node.get("ip", "")
    if not ip:
        return None
    for conn in _get_connections(node):
        port = conn.get("port", 0)
        if port == 5001:
            return f"https://{ip}:{port}"
        if port == 5000:
            return f"http://{ip}:{port}"
    manage_url = node.get("manage_url", "")
    if manage_url and (":5000" in manage_url or ":5001" in manage_url):
        return manage_url.rstrip("/")
    return None


def _get_node_creds(node):
    for share in node.get("shares", []):
        user = share.get("user")
        pwd = share.get("pass", "")
        if user:
            return user, pwd
    return None, None


def get_synology_info(node):
    """Get Synology system info. Returns dict with cpu, ram, storage."""
    base_url = _detect_synology_url(node)
    if not base_url:
        return None
    user, pwd = _get_node_creds(node)
    if not user:
        return {"error": "No credentials found in shares"}
    sid = synology_login(base_url, user, pwd)
    if not sid:
        return {"error": "Login failed"}
    try:
        info = {"type": "synology"}
        # Uptime
        try:
            data = synology_api_call(base_url, "SYNO.Core.System", 3, "info", sid=sid)
            if data.get("success"):
                uptime_sec = data.get("data", {}).get("uptime", 0)
                if uptime_sec:
                    info["uptime_days"] = round(uptime_sec / 86400, 1)
        except Exception:
            pass
        # System utilization
        try:
            data = synology_api_call(base_url, "SYNO.Core.System.Utilization", 1, "get", sid=sid)
            if data.get("success"):
                cpu_data = data.get("data", {}).get("cpu", {})
                mem_data = data.get("data", {}).get("memory", {})
                if cpu_data:
                    info["cpu_pct"] = cpu_data.get("user_load", 0) + cpu_data.get("system_load", 0)
                if mem_data:
                    total_kb = mem_data.get("memory_size", 0)
                    avail_kb = mem_data.get("avail_real", 0)
                    if total_kb > 0:
                        used_kb = total_kb - avail_kb
                        info["ram_pct"] = round((used_kb / total_kb) * 100, 1)
                        info["ram_total_gb"] = round(total_kb / 1048576, 1)
                        info["ram_used_gb"] = round(used_kb / 1048576, 1)
                        info["ram_free_gb"] = round(avail_kb / 1048576, 1)
        except Exception:
            pass
        # Storage
        try:
            data = synology_api_call(base_url, "SYNO.Storage.CGI.Storage", 1, "load_info", sid=sid)
            if data.get("success"):
                storage_data = data.get("data", {})
                volumes = []
                for vol in storage_data.get("volumes", []):
                    vol_path = vol.get("deploy_path", vol.get("id", "?"))
                    total = int(vol.get("size", {}).get("total", "0"))
                    used = int(vol.get("size", {}).get("used", "0"))
                    if total > 0:
                        volumes.append({
                            "label": vol_path,
                            "used_pct": round((used / total) * 100, 1),
                            "total_gb": round(total / (1024**3), 1),
                            "free_gb": round((total - used) / (1024**3), 1),
                        })
                disks = []
                for disk in storage_data.get("disks", []):
                    disks.append({
                        "name": disk.get("name", "?"),
                        "model": disk.get("model", "Unknown"),
                        "size_gb": round(int(disk.get("size_total", 0)) / (1024**3), 1),
                        "temp": disk.get("temp", "N/A"),
                        "status": disk.get("status", "unknown"),
                    })
                info["volumes"] = volumes
                info["disks"] = disks
        except Exception:
            pass
        return info
    finally:
        synology_logout(base_url, sid)


# ─── ZimaOS / CasaOS API ────────────────────────────────────────────────────

def _detect_zimaos_url(node):
    ip = node.get("ip", "")
    if not ip:
        return None
    name = node.get("name", "").lower()
    tags = [t.lower() for t in node.get("tags", [])]
    if any(kw in name for kw in ("zima", "casa")):
        return f"http://{ip}"
    if any(kw in t for t in tags for kw in ("zima", "casa")):
        return f"http://{ip}"
    return None


def zimaos_login(base_url, username, password):
    endpoints = ["/v1/users/login", "/v2/users/login"]
    for ep in endpoints:
        url = f"{base_url}{ep}"
        if "/v1/" in ep:
            payload = urllib.parse.urlencode({"username": username, "password": password}).encode()
            content_type = "application/x-www-form-urlencoded"
        else:
            payload = json.dumps({"username": username, "password": password}).encode()
            content_type = "application/json"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", content_type)
        try:
            resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
            data = json.loads(resp.read().decode("utf-8"))
            token = data.get("data", {}).get("token")
            if data.get("success") == 200 or token:
                return token
        except Exception:
            pass
    return None


def get_zimaos_info(node):
    """Get ZimaOS / CasaOS system info — CPU, RAM, uptime, and disk volumes."""
    base_url = _detect_zimaos_url(node)
    if not base_url:
        return None
    user, pwd = _get_node_creds(node)
    if not user:
        return {"error": "No credentials found"}
    token = zimaos_login(base_url, user, pwd)
    if not token:
        return {"error": "Login failed"}
    try:
        info = {"type": "zimaos"}

        def zima_get(path):
            req = urllib.request.Request(f"{base_url}{path}")
            req.add_header("Authorization", f"Bearer {token}")
            resp = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx)
            return json.loads(resp.read().decode("utf-8"))

        # CPU, RAM, uptime — try CasaOS v1 then v2 system usage endpoint
        for usage_path in ("/v1/sys/usage", "/v2/sys/usage", "/v1/system/usage"):
            try:
                data = zima_get(usage_path)
                d = data.get("data", data)

                # Uptime (seconds)
                uptime_sec = d.get("uptime", 0)
                if uptime_sec:
                    info["uptime_days"] = round(int(uptime_sec) / 86400, 1)

                # CPU — array of per-core percentages or a single float
                cpu = d.get("cpu", None)
                if isinstance(cpu, list) and cpu:
                    info["cpu_pct"] = round(sum(cpu) / len(cpu), 1)
                elif isinstance(cpu, (int, float)):
                    info["cpu_pct"] = round(float(cpu), 1)

                # Memory
                mem = d.get("memory", d.get("mem", {}))
                if mem:
                    total = mem.get("total", 0)
                    used = mem.get("used", 0)
                    used_pct = mem.get("usedPercent", mem.get("used_percent", 0))
                    if used_pct:
                        info["ram_pct"] = round(float(used_pct), 1)
                    elif total > 0 and used > 0:
                        info["ram_pct"] = round((used / total) * 100, 1)
                    if total:
                        info["ram_total_gb"] = round(total / (1024 ** 3), 1)
                    if used:
                        info["ram_used_gb"] = round(used / (1024 ** 3), 1)
                        info["ram_free_gb"] = round((total - used) / (1024 ** 3), 1)

                if "cpu_pct" in info or "ram_pct" in info:
                    break
            except Exception:
                continue

        # Disk volumes
        try:
            data = zima_get("/v1/disks")
            volumes = []
            for disk in data.get("data", []):
                for child in disk.get("children", []):
                    mount = child.get("mount_point", "")
                    csize = child.get("size", 0)
                    avail = child.get("avail", 0)
                    if csize > 0 and mount:
                        volumes.append({
                            "label": mount,
                            "used_pct": round(((csize - avail) / csize) * 100, 1),
                            "total_gb": round(csize / (1024 ** 3), 1),
                            "free_gb": round(avail / (1024 ** 3), 1),
                        })
            if volumes:
                info["volumes"] = volumes
        except Exception:
            pass

        return info
    except Exception as e:
        return {"error": str(e)}


# ─── Plex API ───────────────────────────────────────────────────────────────

def get_plex_info(node):
    """Get Plex activity and library stats via the X-Plex-Token."""
    ip = node.get("ip", "")
    token = node.get("api_key", "")
    if not token:
        return {"error": "No API token configured"}
    host = ip.split(":")[0] if ":" in ip else ip
    base_url = f"http://{host}:32400"
    try:
        info = {"type": "plex"}

        def plex_get(path):
            req = urllib.request.Request(f"{base_url}{path}?X-Plex-Token={token}")
            req.add_header("Accept", "application/json")
            resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
            return json.loads(resp.read().decode("utf-8"))

        sessions = plex_get("/status/sessions")
        info["streams"] = sessions.get("MediaContainer", {}).get("size", 0)

        libraries = plex_get("/library/sections")
        for sec in libraries.get("MediaContainer", {}).get("Directory", []):
            sec_type = sec.get("type", "")
            sec_key = sec.get("key", "")
            try:
                if sec_type == "artist":
                    # type=9 returns albums in Plex music libraries
                    req = urllib.request.Request(
                        f"{base_url}/library/sections/{sec_key}/all"
                        f"?X-Plex-Token={token}&type=9"
                        f"&X-Plex-Container-Size=0&X-Plex-Container-Start=0"
                    )
                    req.add_header("Accept", "application/json")
                    resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
                    d = json.loads(resp.read().decode("utf-8"))
                    info["albums"] = info.get("albums", 0) + d.get("MediaContainer", {}).get("totalSize", 0)
                else:
                    req = urllib.request.Request(
                        f"{base_url}/library/sections/{sec_key}/all"
                        f"?X-Plex-Token={token}"
                        f"&X-Plex-Container-Size=0&X-Plex-Container-Start=0"
                    )
                    req.add_header("Accept", "application/json")
                    resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
                    d = json.loads(resp.read().decode("utf-8"))
                    count = d.get("MediaContainer", {}).get("totalSize", 0)
                    if sec_type == "movie":
                        info["movies"] = info.get("movies", 0) + count
                    elif sec_type == "show":
                        info["tv_shows"] = info.get("tv_shows", 0) + count
            except Exception:
                pass

        return info
    except Exception as e:
        return {"error": str(e)}


# ─── *arr API (Sonarr / Radarr / Lidarr) ────────────────────────────────────

def _arr_get(base_url, endpoint, api_key, api_ver="v3"):
    req = urllib.request.Request(f"{base_url}/api/{api_ver}/{endpoint}")
    req.add_header("X-Api-Key", api_key)
    resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
    return json.loads(resp.read().decode("utf-8"))


def _arr_base_url(node, default_port):
    ip = node.get("ip", "")
    if ":" in ip and not ip.startswith("["):
        host, port = ip.rsplit(":", 1)
    else:
        host, port = ip, str(default_port)
    return f"http://{host}:{port}"


def get_sonarr_info(node):
    """Get Sonarr series and queue stats."""
    api_key = node.get("api_key", "")
    if not api_key:
        return {"error": "No API key configured"}
    base_url = _arr_base_url(node, 8989)
    try:
        info = {"type": "sonarr"}
        series = _arr_get(base_url, "series", api_key)
        info["series_count"] = len(series)
        queue = _arr_get(base_url, "queue", api_key)
        info["queue_count"] = queue.get("totalRecords", 0)
        try:
            wanted = _arr_get(base_url, "wanted/missing?pageSize=0", api_key)
            info["wanted"] = wanted.get("totalRecords", 0)
        except Exception:
            info["wanted"] = 0
        return info
    except Exception as e:
        return {"error": str(e)}


def get_radarr_info(node):
    """Get Radarr movie and queue stats."""
    api_key = node.get("api_key", "")
    if not api_key:
        return {"error": "No API key configured"}
    base_url = _arr_base_url(node, 7878)
    try:
        info = {"type": "radarr"}
        movies = _arr_get(base_url, "movie", api_key)
        info["movie_count"] = len(movies)
        monitored = sum(1 for m in movies if m.get("monitored"))
        downloaded = sum(1 for m in movies if m.get("hasFile"))
        info["wanted"] = max(0, monitored - downloaded)
        info["missing"] = max(0, info["movie_count"] - downloaded)
        info["downloaded"] = downloaded
        queue = _arr_get(base_url, "queue", api_key)
        info["queue_count"] = queue.get("totalRecords", 0)
        return info
    except Exception as e:
        return {"error": str(e)}


def get_lidarr_info(node):
    """Get Lidarr artist and queue stats. Lidarr uses /api/v1/ not /api/v3/."""
    api_key = node.get("api_key", "")
    if not api_key:
        return {"error": "No API key configured"}
    base_url = _arr_base_url(node, 8686)
    try:
        info = {"type": "lidarr"}
        artists = _arr_get(base_url, "artist", api_key, api_ver="v1")
        info["artist_count"] = len(artists)
        queue = _arr_get(base_url, "queue", api_key, api_ver="v1")
        info["queue_count"] = queue.get("totalRecords", 0)
        try:
            wanted = _arr_get(base_url, "wanted/missing?pageSize=0", api_key, api_ver="v1")
            info["wanted"] = wanted.get("totalRecords", 0)
        except Exception:
            info["wanted"] = 0
        return info
    except Exception as e:
        return {"error": str(e)}


# ─── SABnzbd API ─────────────────────────────────────────────────────────────

def get_sabnzbd_info(node):
    """Get SABnzbd queue and speed info."""
    ip = node.get("ip", "")
    api_key = node.get("api_key", "")
    if not api_key:
        return {"error": "No API key configured"}
    if ":" in ip and not ip.startswith("["):
        host, port = ip.rsplit(":", 1)
    else:
        host, port = ip, "8080"
    base_url = f"http://{host}:{port}"
    try:
        url = f"{base_url}/api?mode=queue&output=json&apikey={api_key}"
        resp = urllib.request.urlopen(urllib.request.Request(url), timeout=10, context=_ssl_ctx)
        data = json.loads(resp.read().decode("utf-8"))
        q = data.get("queue", {})
        return {
            "type": "sabnzbd",
            "status": q.get("status", "Unknown"),
            "speed": q.get("speed", "0"),
            "queue_count": int(q.get("noofslots", 0)),
            "queue_mb": round(float(q.get("mbleft", 0) or 0), 1),
            "eta": q.get("eta", "N/A"),
        }
    except Exception as e:
        return {"error": str(e)}


# ─── Immich API ──────────────────────────────────────────────────────────────

def get_immich_info(node):
    """Get Immich photo/video counts, storage usage, and user count."""
    ip = node.get("ip", "")
    api_key = node.get("api_key", "")
    if not api_key:
        return {"error": "No API key configured"}
    if ":" in ip and not ip.startswith("["):
        host, port = ip.rsplit(":", 1)
    else:
        host, port = ip, "2283"
    base_url = f"http://{host}:{port}"
    try:
        def immich_get(path):
            req = urllib.request.Request(f"{base_url}{path}")
            req.add_header("x-api-key", api_key)
            resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
            return json.loads(resp.read().decode("utf-8"))

        # Try v2 endpoint first, fall back to v1
        try:
            data = immich_get("/api/server/statistics")
        except Exception:
            data = immich_get("/api/server-info/statistics")

        usage_bytes = data.get("usage", 0)
        info = {
            "type": "immich",
            "photos": data.get("photos", 0),
            "videos": data.get("videos", 0),
            "usage_bytes": usage_bytes,
            "usage_gb": round(usage_bytes / (1024 ** 3), 1),
        }
        # User count from usageByUser list or a separate endpoint
        by_user = data.get("usageByUser", [])
        if by_user:
            info["users"] = len(by_user)
        else:
            try:
                users = immich_get("/api/user")
                info["users"] = len(users) if isinstance(users, list) else 0
            except Exception:
                info["users"] = 0
        return info
    except Exception as e:
        return {"error": str(e)}


# ─── NOC Agent (Windows / Linux PC system info) ──────────────────────────────

def _agent_base_url(node):
    """Return the base URL for the noc_agent running on this node."""
    ip = node.get("ip", "")
    host = ip.split(":")[0] if ":" in ip and not ip.startswith("[") else ip
    # Look for a custom port in connections; default 9182
    port = 9182
    for c in node.get("connections", []):
        if str(c.get("port", "")) not in ("", "0"):
            port = int(c["port"])
            break
    # Allow manage_url override
    mu = node.get("manage_url", "")
    if mu and ("9182" in mu or "noc-agent" in mu.lower()):
        return mu.rstrip("/")
    return f"http://{host}:{port}"


def get_noc_agent_info(node):
    """Query a NOC Agent and return its system info dict."""
    api_key = node.get("api_key", "")
    if not api_key:
        return {"error": "No API key configured — copy the key printed by noc_agent.py"}
    base = _agent_base_url(node)
    try:
        url = f"{base}/info?key={urllib.parse.quote(api_key)}"
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
        data = json.loads(resp.read().decode("utf-8"))
        data["type"] = "noc-agent"   # ensure type field is set
        return data
    except Exception as e:
        return {"error": str(e)}


# ─── Inline Stats Builder ────────────────────────────────────────────────────

def _fmt(n):
    """Format a number with thousands separator, or return 'N/A'."""
    if n is None:
        return "N/A"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _fmt_bytes(b):
    """Format bytes into a human-readable string."""
    try:
        b = int(b)
    except (TypeError, ValueError):
        return "0 B"
    if b == 0:
        return "0 B"
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024 ** 3:.1f} GB"


def _build_stats_from_info(info):
    """Convert a service info dict to a [{val, lbl}] list for inline card display."""
    if not info or "error" in info:
        return []
    t = info.get("type", "")
    stats = []

    if t == "synology":
        if "uptime_days" in info:
            days = info["uptime_days"]
            stats.append({"val": f"{int(days)}d" if days >= 1 else f"{int(days*24)}h", "lbl": "UPTIME"})
        if info.get("volumes"):
            free_pct = round(100 - info["volumes"][0]["used_pct"], 1)
            stats.append({"val": f"{free_pct}%", "lbl": "AVAILABLE"})
        if "cpu_pct" in info:
            stats.append({"val": f"{info['cpu_pct']}%", "lbl": "CPU"})
        if "ram_pct" in info:
            stats.append({"val": f"{info['ram_pct']}%", "lbl": "MEM"})

    elif t == "zimaos":
        if "uptime_days" in info:
            days = info["uptime_days"]
            stats.append({"val": f"{int(days)}d" if days >= 1 else f"{int(days * 24)}h", "lbl": "UPTIME"})
        if info.get("volumes"):
            free_pct = round(100 - info["volumes"][0]["used_pct"], 1)
            stats.append({"val": f"{free_pct}%", "lbl": "AVAILABLE"})
        if "cpu_pct" in info:
            stats.append({"val": f"{info['cpu_pct']}%", "lbl": "CPU"})
        if "ram_pct" in info:
            stats.append({"val": f"{info['ram_pct']}%", "lbl": "MEM"})

    elif t == "plex":
        stats.append({"val": _fmt(info.get("streams", 0)), "lbl": "ACTIVE STREAMS"})
        if "albums" in info:
            stats.append({"val": _fmt(info["albums"]), "lbl": "ALBUMS"})
        if "movies" in info:
            stats.append({"val": _fmt(info["movies"]), "lbl": "MOVIES"})
        if "tv_shows" in info:
            stats.append({"val": _fmt(info["tv_shows"]), "lbl": "TV SHOWS"})

    elif t == "sonarr":
        stats.append({"val": _fmt(info.get("wanted", 0)), "lbl": "WANTED"})
        stats.append({"val": _fmt(info.get("queue_count", 0)), "lbl": "QUEUED"})
        stats.append({"val": _fmt(info.get("series_count", 0)), "lbl": "SERIES"})

    elif t == "radarr":
        stats.append({"val": _fmt(info.get("wanted", 0)), "lbl": "WANTED"})
        stats.append({"val": _fmt(info.get("missing", 0)), "lbl": "MISSING"})
        stats.append({"val": _fmt(info.get("queue_count", 0)), "lbl": "QUEUED"})
        stats.append({"val": _fmt(info.get("movie_count", 0)), "lbl": "MOVIES"})

    elif t == "lidarr":
        stats.append({"val": _fmt(info.get("wanted", 0)), "lbl": "WANTED"})
        stats.append({"val": _fmt(info.get("queue_count", 0)), "lbl": "QUEUED"})
        stats.append({"val": _fmt(info.get("artist_count", 0)), "lbl": "ARTISTS"})

    elif t == "sabnzbd":
        speed = info.get("speed", "0") or "0"
        stats.append({"val": f"{speed} B/s", "lbl": "RATE"})
        stats.append({"val": _fmt(info.get("queue_count", 0)), "lbl": "QUEUE"})
        stats.append({"val": info.get("eta", "0:00:00") or "0:00:00", "lbl": "TIME LEFT"})

    elif t == "immich":
        stats.append({"val": _fmt(info.get("users", 0)), "lbl": "USERS"})
        stats.append({"val": _fmt(info.get("photos", 0)), "lbl": "PHOTOS"})
        stats.append({"val": _fmt(info.get("videos", 0)), "lbl": "VIDEOS"})
        stats.append({"val": _fmt_bytes(info.get("usage_bytes", 0)), "lbl": "STORAGE"})

    elif t == "noc-agent":
        if "cpu_pct" in info:
            stats.append({"val": f"{info['cpu_pct']}%", "lbl": "CPU"})
        if "ram_pct" in info:
            stats.append({"val": f"{info['ram_pct']}%", "lbl": "MEM"})
        if info.get("volumes"):
            # show the least-free volume's free %
            worst = min(info["volumes"], key=lambda v: v.get("free_gb", 999))
            stats.append({"val": f"{worst['free_gb']}GB", "lbl": "FREE"})
        if "uptime_str" in info:
            stats.append({"val": info["uptime_str"], "lbl": "UPTIME"})

    return stats


def _fetch_node_stats(node):
    """Fetch and cache inline stats for a single node."""
    ip = node.get("ip", "")
    tags = {t.lower() for t in node.get("tags", [])}
    tag_dispatch = {
        "plex":      get_plex_info,
        "sonarr":    get_sonarr_info,
        "radarr":    get_radarr_info,
        "lidarr":    get_lidarr_info,
        "sabnzbd":   get_sabnzbd_info,
        "immich":    get_immich_info,
        "noc-agent": get_noc_agent_info,
    }
    for tag, fn in tag_dispatch.items():
        if tag in tags:
            info = fn(node)
            service_stats[ip] = _build_stats_from_info(info)
            return
    # Synology / ZimaOS
    if any(t in tags for t in ("synology", "nas", "zima")):
        info = get_synology_info(node) or get_zimaos_info(node)
        if info:
            service_stats[ip] = _build_stats_from_info(info)


def fetch_all_service_stats():
    """Refresh inline stats for all nodes that support it, in parallel."""
    AGENT_TAGS = {"plex","sonarr","radarr","lidarr","sabnzbd","immich","noc-agent"}
    threads = []
    for node in list(nodes):
        tags = {t.lower() for t in node.get("tags", [])}
        has_api = bool(node.get("api_key")) or any(
            t in tags for t in ("synology", "nas", "zima", "noc-agent")
        )
        if not has_api:
            continue
        t = threading.Thread(target=_fetch_node_stats, args=(node,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=20)


# ─── Port Scanner ────────────────────────────────────────────────────────────

COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 135: "RPC", 139: "NetBIOS", 143: "IMAP",
    443: "HTTPS", 445: "SMB", 993: "IMAPS", 990: "FTPS", 995: "POP3S",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 5900: "VNC",
    5000: "Synology HTTP", 5001: "Synology HTTPS",
    8006: "Proxmox", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
    8686: "Lidarr", 8989: "Sonarr", 7878: "Radarr",
    9090: "WebUI", 9182: "NOC Agent", 32400: "Plex",
}


def scan_ports(host, ports=None, timeout=1):
    """Scan common ports on a host. Returns list of {port, name, open}."""
    if ports is None:
        ports = sorted(COMMON_PORTS.keys())
    host = host.split(":")[0] if ":" in host else host
    results = []
    results_lock = threading.Lock()

    def check(port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            result = s.connect_ex((host, port))
            s.close()
            is_open = result == 0
        except Exception:
            is_open = False
        with results_lock:
            results.append({
                "port": port,
                "name": COMMON_PORTS.get(port, "Unknown"),
                "open": is_open
            })

    threads = []
    for port in ports:
        t = threading.Thread(target=check, args=(port,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=timeout + 2)

    return sorted(results, key=lambda x: x["port"])


# ─── Wake-on-LAN ────────────────────────────────────────────────────────────

def send_wol(mac_address):
    mac = mac_address.replace(":", "").replace("-", "").replace(".", "")
    if len(mac) != 12:
        return False, "Invalid MAC address"
    try:
        mac_bytes = bytes.fromhex(mac)
        magic = b'\xff' * 6 + mac_bytes * 16
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic, ('<broadcast>', 9))
        sock.close()
        return True, "Magic packet sent"
    except Exception as e:
        return False, str(e)


# ─── Auth Decorator ──────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == AUTH_USER and password == AUTH_PASS:
            session["logged_in"] = True
            session["username"] = username
            session.permanent = True
            log_event(f"User '{username}' logged in from {request.remote_addr}", "INFO")
            return redirect(url_for("dashboard"))
        else:
            log_event(f"Failed login attempt from {request.remote_addr}", "WARN")
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", app_version=APP_VERSION, scan_interval=SCAN_INTERVAL)


@app.route("/api/status")
@login_required
def api_status():
    """Return full status data for the dashboard."""
    result_nodes = []
    for node in nodes:
        ip = node.get("ip", "")
        status = node_statuses.get(ip, {})
        conns = _get_connections(node)

        # Sub-hosts status
        host_statuses = []
        for h in node.get("hosts", []):
            h_ip = h.get("ip", "")
            h_port = h.get("port")
            h_proto = h.get("protocol", "")
            if h_port:
                h_key = f"{h_ip}:{h_port}"
            elif h_proto:
                default_port = {"http": 80, "https": 443}.get(h_proto.lower(), 80)
                h_key = f"{h_ip}:{default_port}"
            else:
                h_key = h_ip
            h_status = node_statuses.get(h_key, {})
            host_statuses.append({
                "label": h.get("label", h_ip),
                "ip": h_ip,
                "port": h_port or "",
                "protocol": h_proto,
                "online": h_status.get("online", False),
                "ms": h_status.get("ms", 0),
                "key": h_key,
            })

        # Sparkline data
        hist = list(ping_history.get(ip, []))

        # Uptime
        ud = uptime_data.get(ip, {"up": 0, "total": 0})
        uptime_pct = round((ud["up"] / ud["total"] * 100), 1) if ud["total"] > 0 else 0

        result_nodes.append({
            "name": node.get("name", ip),
            "ip": ip,
            "group": node.get("group", ""),
            "description": node.get("description", ""),
            "connections": conns,
            "manage_url": node.get("manage_url", ""),
            "manage_label": node.get("manage_label", "Manage"),
            "tags": node.get("tags", []),
            "icon": node.get("icon", ""),
            "api_key": node.get("api_key", ""),
            "shares": node.get("shares", []),
            "hosts": host_statuses,
            "mac": node.get("mac", ""),
            "online": status.get("online", False),
            "ms": status.get("ms", 0),
            "last_check": status.get("last_check", "never"),
            "in_maintenance": ip in maintenance_ips,
            "sparkline": hist,
            "uptime_pct": uptime_pct,
            "stats": service_stats.get(ip, []),
            "show_sysmon": node.get("show_sysmon", False),
            "notes":       node.get("notes", ""),
            "card_color":  node.get("card_color", ""),
            "favorite":    node.get("favorite", False),
            "rustdesk_id": node.get("rustdesk_id", ""),
        })

    online_count = sum(1 for n in result_nodes if n["online"] and not n["in_maintenance"])
    maint_count = sum(1 for n in result_nodes if n["in_maintenance"])
    total = len(result_nodes)

    return jsonify({
        "nodes": result_nodes,
        "summary": {
            "online": online_count,
            "total": total,
            "maintenance": maint_count,
            "last_scan": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "scan_interval": SCAN_INTERVAL,
        },
        "events": list(event_log)[-50:],
    })


@app.route("/api/refresh", methods=["POST"])
@login_required
def api_refresh():
    """Force an immediate scan."""
    threading.Thread(target=do_scan, daemon=True).start()
    return jsonify({"ok": True, "message": "Scan triggered"})


@app.route("/api/port-scan", methods=["POST"])
@login_required
def api_port_scan():
    """Scan ports on a host."""
    host = request.json.get("host", "")
    if not host:
        return jsonify({"error": "No host specified"}), 400
    results = scan_ports(host)
    return jsonify({"host": host, "results": results})


@app.route("/api/wol", methods=["POST"])
@login_required
def api_wol():
    """Send Wake-on-LAN packet."""
    mac = request.json.get("mac", "")
    if not mac:
        return jsonify({"error": "No MAC address"}), 400
    ok, msg = send_wol(mac)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/maintenance", methods=["POST"])
@login_required
def api_maintenance():
    """Toggle maintenance mode for an IP."""
    ip = request.json.get("ip", "")
    action = request.json.get("action", "toggle")
    duration = int(request.json.get("duration", 30))  # minutes

    if not ip:
        return jsonify({"error": "No IP"}), 400

    if action == "enter" or (action == "toggle" and ip not in maintenance_ips):
        maintenance_ips.add(ip)
        maintenance_timers[ip] = {
            "end": time.time() + duration * 60,
            "label": f"{duration}m maintenance",
        }
        name = _find_name_for_ip(ip)
        log_event(f"🔧 Maintenance mode ON for {name} ({ip}) — {duration}m", "WARN")
        return jsonify({"ok": True, "status": "entered"})
    else:
        maintenance_ips.discard(ip)
        maintenance_timers.pop(ip, None)
        name = _find_name_for_ip(ip)
        log_event(f"🔧 Maintenance mode OFF for {name} ({ip})", "INFO")
        return jsonify({"ok": True, "status": "exited"})


@app.route("/api/system-info", methods=["POST"])
@login_required
def api_system_info():
    """Get system info for a node — dispatches by tag then auto-detects."""
    ip = request.json.get("ip", "")
    node = None
    for n in nodes:
        if n.get("ip") == ip:
            node = n
            break
    if not node:
        return jsonify({"error": "Node not found"}), 404

    tags = {t.lower() for t in node.get("tags", [])}

    tag_dispatch = {
        "plex":      get_plex_info,
        "sonarr":    get_sonarr_info,
        "radarr":    get_radarr_info,
        "lidarr":    get_lidarr_info,
        "sabnzbd":   get_sabnzbd_info,
        "immich":    get_immich_info,
        "noc-agent": get_noc_agent_info,
    }
    for tag, fn in tag_dispatch.items():
        if tag in tags:
            info = fn(node)
            if info and "error" not in info:
                return jsonify(info)
            return jsonify(info)  # return error details too

    # Auto-detect Synology
    info = get_synology_info(node)
    if info and "error" not in info:
        return jsonify(info)

    # Auto-detect ZimaOS
    info = get_zimaos_info(node)
    if info and "error" not in info:
        return jsonify(info)

    return jsonify({"error": "Could not get system info", "details": info})


@app.route("/api/sms-config", methods=["GET", "POST"])
@login_required
def api_sms_config():
    global sms_config
    if request.method == "POST":
        sms_config = request.json
        save_sms_config()
        log_event("SMS config updated", "INFO")
        return jsonify({"ok": True})
    return jsonify(sms_config)


@app.route("/api/sms-test", methods=["POST"])
@login_required
def api_sms_test():
    """Send a test SMS to all configured SMS recipients."""
    if not sms_config.get("enabled"):
        return jsonify({"ok": False, "error": "SMS alerts are disabled — enable them first and save."}), 400
    if not sms_config.get("recipients"):
        return jsonify({"ok": False, "error": "No SMS recipients configured."}), 400
    if not sms_config.get("smtp_user") or not sms_config.get("smtp_pass"):
        return jsonify({"ok": False, "error": "SMTP credentials not set — enter your Gmail address and App Password."}), 400
    send_sms_alert("NOC Test", f"[NOC] Test alert from {APP_NAME} at {datetime.now():%I:%M %p}")
    return jsonify({"ok": True, "message": "Test SMS sent"})


@app.route("/api/email-test", methods=["POST"])
@login_required
def api_email_test():
    """Send a test email to all configured email recipients."""
    if not sms_config.get("email_enabled"):
        return jsonify({"ok": False, "error": "Email alerts are disabled — enable them first and save."}), 400
    if not sms_config.get("email_recipients"):
        return jsonify({"ok": False, "error": "No email recipients configured."}), 400
    if not sms_config.get("smtp_user") or not sms_config.get("smtp_pass"):
        return jsonify({"ok": False, "error": "SMTP credentials not set — enter your Gmail address and App Password."}), 400
    subject = f"NOC Test — {APP_NAME}"
    body = (
        f"This is a test alert from {APP_NAME}.\n\n"
        f"Your email notifications are configured correctly.\n"
        f"Sent at {datetime.now():%Y-%m-%d %I:%M %p}.\n\n"
        f"— REGTeches NOC Dashboard"
    )
    send_email_alert(subject, body)
    return jsonify({"ok": True, "message": "Test email sent"})


@app.route("/api/events")
@login_required
def api_events():
    return jsonify(list(event_log)[-100:])


@app.route("/api/nodes", methods=["GET", "POST", "PUT", "DELETE"])
@login_required
def api_nodes():
    """CRUD for nodes/servers."""
    global nodes
    if request.method == "GET":
        return jsonify(nodes)

    if request.method == "POST":
        # Add new node
        node = request.json
        nodes.append(node)
        save_config()
        log_event(f"Server added: {node.get('name', '?')}", "INFO")
        return jsonify({"ok": True})

    if request.method == "PUT":
        # Update node by index
        idx = request.json.get("index")
        node = request.json.get("node")
        if idx is not None and 0 <= idx < len(nodes):
            nodes[idx] = node
            save_config()
            log_event(f"Server updated: {node.get('name', '?')}", "INFO")
            return jsonify({"ok": True})
        return jsonify({"error": "Invalid index"}), 400

    if request.method == "DELETE":
        idx = request.json.get("index")
        if idx is not None and 0 <= idx < len(nodes):
            name = nodes[idx].get("name", "?")
            nodes.pop(idx)
            save_config()
            log_event(f"Server deleted: {name}", "WARN")
            return jsonify({"ok": True})
        return jsonify({"error": "Invalid index"}), 400


@app.route("/api/config/export")
@login_required
def api_config_export():
    return jsonify({"version": 2, "saved": datetime.now().isoformat(), "nodes": nodes})


@app.route("/api/config/import", methods=["POST"])
@login_required
def api_config_import():
    global nodes
    data = request.json
    nodes = data.get("nodes", [])
    save_config()
    log_event(f"Config imported — {len(nodes)} nodes", "INFO")
    return jsonify({"ok": True, "count": len(nodes)})


@app.route("/api/backups", methods=["GET"])
@login_required
def api_backups():
    """List available backup files, newest first."""
    if not os.path.exists(BACKUP_DIR):
        return jsonify([])
    entries = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.startswith("backup_") and f.endswith(".zip"):
            path = os.path.join(BACKUP_DIR, f)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            entries.append({"filename": f, "size": size})
    return jsonify(entries[:MAX_BACKUPS])


@app.route("/api/backup", methods=["POST"])
@login_required
def api_backup():
    """Create a manual zip backup of all files in the script directory."""
    filename = _create_backup("manual")
    if filename:
        return jsonify({"ok": True, "filename": filename})
    return jsonify({"ok": False, "error": "Backup failed"}), 500


@app.route("/api/restore", methods=["POST"])
@login_required
def api_restore():
    """Extract a backup zip back into the script directory, then reload config."""
    global nodes, sms_config
    filename = request.json.get("filename", "")
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "Backup not found"}), 404
    try:
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(_SCRIPT_DIR)
        # Reload in-memory config from the restored files
        load_config()
        load_sms_config()
        log_event(f"Restored from backup: {filename}", "INFO")
        return jsonify({"ok": True})
    except Exception as e:
        log_event(f"Restore error: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500


# ─── Speed Test ──────────────────────────────────────────────────────────────

@app.route("/api/speedtest", methods=["POST"])
@login_required
def api_speedtest():
    """Run a speed test and return download/upload/ping results."""
    if not SPEEDTEST_OK:
        return jsonify({"error": "speedtest-cli not installed — run install_deps.py"}), 503
    try:
        st = _speedtest_mod.Speedtest()
        st.get_best_server()
        download = st.download() / 1_000_000   # bits → Mbps
        upload   = st.upload()   / 1_000_000
        ping     = st.results.ping
        srv      = st.results.server
        server   = f"{srv.get('name','?')}, {srv.get('country','?')}"
        return jsonify({
            "download_mbps": round(download, 2),
            "upload_mbps":   round(upload,   2),
            "ping_ms":       round(ping,      1),
            "server":        server,
        })
    except Exception as e:
        log_event(f"Speed test error: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500


# ─── Live Ping ───────────────────────────────────────────────────────────────

@app.route("/api/ping", methods=["POST"])
@login_required
def api_ping():
    """Ping a host N times, return min/avg/max/loss stats."""
    host  = request.json.get("host", "")
    count = max(1, min(int(request.json.get("count", 4)), 10))
    if not host:
        return jsonify({"error": "No host specified"}), 400
    host = host.split(":")[0] if ":" in host and not host.startswith("[") else host
    results = []
    for _ in range(count):
        try:
            if platform.system() == "Windows":
                cmd = ["ping", "-n", "1", "-w", str(PING_TIMEOUT * 1000), host]
            else:
                cmd = ["ping", "-c", "1", "-W", str(PING_TIMEOUT), host]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=PING_TIMEOUT + 3)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if "time=" in line or "time<" in line:
                        try:
                            part = line.split("time=")[-1].split("time<")[-1]
                            ms = float(part.split()[0].replace("ms", "").replace("<", ""))
                            results.append(round(ms, 1))
                            break
                        except (ValueError, IndexError):
                            results.append(1.0)
                            break
                else:
                    results.append(1.0)
            else:
                results.append(None)
        except Exception:
            results.append(None)
    online = [r for r in results if r is not None]
    return jsonify({
        "host":     host,
        "sent":     count,
        "received": len(online),
        "lost":     count - len(online),
        "loss_pct": round((count - len(online)) / count * 100),
        "min_ms":   round(min(online), 1) if online else None,
        "max_ms":   round(max(online), 1) if online else None,
        "avg_ms":   round(sum(online) / len(online), 1) if online else None,
        "results":  results,
    })


# ─── Bulk Maintenance ─────────────────────────────────────────────────────────

@app.route("/api/bulk-maintenance", methods=["POST"])
@login_required
def api_bulk_maintenance():
    """Enter or exit maintenance for a list of IPs."""
    ips    = request.json.get("ips", [])
    action = request.json.get("action", "enter")
    for ip in ips:
        if action == "enter":
            maintenance_ips.add(ip)
            maintenance_timers[ip] = {"end": time.time() + 1800, "label": "bulk"}
        else:
            maintenance_ips.discard(ip)
            maintenance_timers.pop(ip, None)
    log_event(f"Bulk maintenance {action} for {len(ips)} servers", "WARN")
    return jsonify({"ok": True})


@app.route("/api/bulk-group", methods=["POST"])
@login_required
def api_bulk_group():
    """Move a list of IPs to a new group."""
    global nodes
    ips   = request.json.get("ips", [])
    group = request.json.get("group", "")
    changed = 0
    for node in nodes:
        if node.get("ip") in ips:
            node["group"] = group
            changed += 1
    if changed:
        save_config()
        log_event(f"Moved {changed} servers to group '{group}'", "INFO")
    return jsonify({"ok": True, "changed": changed})


@app.route("/api/bulk-delete", methods=["POST"])
@login_required
def api_bulk_delete():
    """Delete multiple servers by IP."""
    global nodes
    ips = set(request.json.get("ips", []))
    before = len(nodes)
    nodes = [n for n in nodes if n.get("ip") not in ips]
    if len(nodes) < before:
        save_config()
        log_event(f"Bulk deleted {before - len(nodes)} servers", "WARN")
    return jsonify({"ok": True, "deleted": before - len(nodes)})


# ─── Toggle Favorite ──────────────────────────────────────────────────────────

@app.route("/api/favorite", methods=["POST"])
@login_required
def api_favorite():
    """Toggle the favorite flag for a server IP."""
    global nodes
    ip = request.json.get("ip", "")
    for node in nodes:
        if node.get("ip") == ip:
            node["favorite"] = not node.get("favorite", False)
            save_config(backup=False)
            return jsonify({"ok": True, "favorite": node["favorite"]})
    return jsonify({"error": "Not found"}), 404


# ─── Remote Power Control (via noc_agent) ────────────────────────────────────

@app.route("/api/power", methods=["POST"])
@login_required
def api_power():
    """Proxy a power action to the noc_agent running on the target PC."""
    ip     = request.json.get("ip", "")
    action = request.json.get("action", "")
    if not ip or not action:
        return jsonify({"error": "ip and action required"}), 400

    node = next((n for n in nodes if n.get("ip") == ip), None)
    if not node:
        return jsonify({"error": "Node not found"}), 404

    api_key = node.get("api_key", "")
    if not api_key:
        return jsonify({"error": "No API key — add the noc_agent key to this server"}), 400

    # Build agent URL
    host = ip.split(":")[0] if ":" in ip and not ip.startswith("[") else ip
    port = 9182
    for c in node.get("connections", []):
        if str(c.get("port", "")) not in ("", "0"):
            port = int(c["port"])
            break
    url = f"http://{host}:{port}/power?key={urllib.parse.quote(api_key)}"
    try:
        payload = json.dumps({"action": action}).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
        data = json.loads(resp.read().decode())
        log_event(f"Power action '{action}' sent to {node.get('name', ip)}", "WARN")
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Network Discovery ────────────────────────────────────────────────────────

@app.route("/api/network-scan", methods=["POST"])
@login_required
def api_network_scan():
    """Scan a subnet for live hosts. Returns list of discovered devices."""
    subnet = request.json.get("subnet", "")     # e.g. "10.0.0"  or  "192.168.1"
    ports_to_try = [80, 443, 22, 3389, 445, 8080, 8006, 5000, 9182]
    if not subnet:
        return jsonify({"error": "subnet required (e.g. 10.0.0)"}), 400

    # Strip trailing dot/zero if user passed full CIDR-ish string
    subnet = subnet.rstrip(".").rsplit(".", 1)[0] if subnet.count(".") == 3 else subnet.rstrip(".")

    results = []
    results_lock = threading.Lock()

    def probe(last_octet):
        host = f"{subnet}.{last_octet}"
        open_ports = []
        hostname = ""
        for port in ports_to_try:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.4)
                if s.connect_ex((host, port)) == 0:
                    open_ports.append(port)
                s.close()
            except Exception:
                pass
        if not open_ports:
            return
        try:
            hostname = socket.gethostbyaddr(host)[0]
        except Exception:
            hostname = ""
        # Detect likely type from open ports
        tags = []
        if 9182 in open_ports: tags.append("noc-agent")
        if 3389 in open_ports: tags.append("windows")
        if 22 in open_ports:   tags.append("linux")
        if 8006 in open_ports: tags.append("proxmox")
        if 5000 in open_ports: tags.append("synology")
        if 445 in open_ports:  tags.append("smb")
        if 32400 in open_ports: tags.append("plex")

        with results_lock:
            results.append({
                "ip":       host,
                "hostname": hostname,
                "ports":    open_ports,
                "tags":     tags,
                "known":    any(n.get("ip","").split(":")[0] == host for n in nodes),
            })

    threads = []
    for i in range(1, 255):
        t = threading.Thread(target=probe, args=(i,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=3)

    results.sort(key=lambda x: int(x["ip"].split(".")[-1]))
    log_event(f"Network scan of {subnet}.x — {len(results)} hosts found", "INFO")
    return jsonify({"subnet": subnet, "hosts": results})


# ─── RustDesk Launcher ───────────────────────────────────────────────────────

RUSTDESK_PATHS = [
    r"C:\Program Files\RustDesk\rustdesk.exe",
    r"C:\Program Files (x86)\RustDesk\rustdesk.exe",
    os.path.expanduser(r"~\AppData\Local\Programs\RustDesk\rustdesk.exe"),
    "/usr/bin/rustdesk",
    "/usr/local/bin/rustdesk",
    "/opt/rustdesk/rustdesk",
    "/snap/bin/rustdesk",
]

@app.route("/api/launch-rustdesk", methods=["POST"])
@login_required
def api_launch_rustdesk():
    """Launch RustDesk on the NOC server machine pointing at a target ID/IP."""
    target = request.json.get("target", "")   # RustDesk peer ID or IP
    if not target:
        return jsonify({"error": "target ID/IP required"}), 400

    exe = None
    for path in RUSTDESK_PATHS:
        if os.path.isfile(path):
            exe = path
            break

    if not exe:
        return jsonify({
            "error": "RustDesk not found",
            "searched": RUSTDESK_PATHS,
            "tip": "Install RustDesk or set the path in noc_settings.json → rustdesk_path",
        }), 404

    try:
        subprocess.Popen([exe, "--connect", target],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        log_event(f"RustDesk launched → {target}", "INFO")
        return jsonify({"ok": True, "target": target, "exe": exe})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── RDP File Download ────────────────────────────────────────────────────────

@app.route("/api/server/<path:ip>/rdp")
@login_required
def api_rdp_file(ip):
    """Generate and return a .rdp file for the given server."""
    node = next((n for n in nodes if n.get("ip") == ip), None)
    if not node:
        return "Server not found", 404
    rdp_conn = next((c for c in node.get("connections", []) if c.get("type") == "RDP"), None)
    port = int(rdp_conn.get("port", 3389)) if rdp_conn else 3389
    name = node.get("name", ip).replace('"', '')
    content = "\r\n".join([
        f"full address:s:{ip}:{port}",
        "prompt for credentials:i:1",
        "desktopwidth:i:1920",
        "desktopheight:i:1080",
        "session bpp:i:32",
        "connection type:i:7",
        "networkautodetect:i:1",
        "bandwidthautodetect:i:1",
        "displayconnectionbar:i:1",
        "disable wallpaper:i:0",
        "allow font smoothing:i:1",
        "disableclipboardredirection:i:0",
        "redirectprinters:i:0",
        "smartsizing:i:0",
        "",
    ])
    safe_name = "".join(c for c in name if c.isalnum() or c in " _-")
    return content, 200, {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{safe_name}.rdp"',
    }


# ─── App Settings ────────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET", "POST"])
@login_required
def api_settings():
    """Read or write noc_settings.json."""
    global SCAN_INTERVAL, PING_TIMEOUT
    if request.method == "POST":
        data = request.json or {}
        # coerce numeric fields
        for key in ("scan_interval", "ping_timeout", "port"):
            if key in data:
                try:
                    data[key] = int(data[key])
                except (ValueError, TypeError):
                    pass
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # apply runtime-safe values immediately (no restart needed)
            SCAN_INTERVAL = data.get("scan_interval", SCAN_INTERVAL)
            PING_TIMEOUT  = data.get("ping_timeout",  PING_TIMEOUT)
            log_event("App settings saved", "INFO")
            return jsonify({"ok": True})
        except IOError as e:
            return jsonify({"error": str(e)}), 500
    # GET — return current file contents, filling in defaults for any missing keys
    cfg = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    cfg.setdefault("title",         APP_NAME)
    cfg.setdefault("auth_user",     AUTH_USER)
    cfg.setdefault("auth_pass",     AUTH_PASS)
    cfg.setdefault("secret_key",    SECRET_KEY)
    cfg.setdefault("scan_interval", SCAN_INTERVAL)
    cfg.setdefault("ping_timeout",  PING_TIMEOUT)
    cfg.setdefault("port",          int(_cfg.get("port", 8082)))
    return jsonify(cfg)





# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError:
        pass  # status file directory unavailable on this platform — non-fatal
    load_config()
    load_sms_config()
    log_event(f"{APP_NAME} v{APP_VERSION} starting — {len(nodes)} nodes configured", "INFO")

    # Start scanner in background thread
    scanner = threading.Thread(target=scan_loop, daemon=True)
    scanner.start()

    # Run Flask — port from noc_settings.json, then env var, then default
    port = int(os.environ.get("NOC_PORT", _cfg.get("port", 8082)))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
