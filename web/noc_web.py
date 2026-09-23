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

from flask import (Flask, render_template_string, request, jsonify, session,
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
app = Flask(__name__)
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
            return render_template_string(LOGIN_HTML, error="Invalid credentials")
    return render_template_string(LOGIN_HTML, error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template_string(DASHBOARD_HTML)


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


# ─── HTML Templates ──────────────────────────────────────────────────────────

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔐 NOC Login — REGTeches</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0a0f1a;
    color: #e2e8f0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
}
.login-card {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 16px;
    padding: 3rem;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 25px 50px rgba(0,0,0,0.5);
}
.logo { text-align: center; margin-bottom: 2rem; }
.logo h1 { font-size: 1.5rem; color: #3b82f6; letter-spacing: 2px; }
.logo p { font-size: 0.8rem; color: #94a3b8; margin-top: 0.5rem; }
.logo .icon { font-size: 3rem; display: block; margin-bottom: 0.5rem; }
.form-group { margin-bottom: 1.25rem; }
.form-group label { display: block; font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.4rem; }
.form-group input {
    width: 100%;
    padding: 0.75rem 1rem;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    color: #e2e8f0;
    font-size: 1rem;
    transition: border-color 0.2s;
}
.form-group input:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.2); }
.btn-login {
    width: 100%;
    padding: 0.8rem;
    background: linear-gradient(135deg, #3b82f6, #1d4ed8);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.1s, box-shadow 0.2s;
}
.btn-login:hover { transform: translateY(-1px); box-shadow: 0 4px 15px rgba(59,130,246,0.4); }
.error { background: rgba(239,68,68,0.15); border: 1px solid #ef4444; color: #f87171; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem; font-size: 0.85rem; text-align: center; }
.footer { text-align: center; margin-top: 1.5rem; font-size: 0.75rem; color: #475569; }
</style>
</head>
<body>
<div class="login-card">
    <div class="logo">
        <span class="icon">📡</span>
        <h1>REGTECHES NOC</h1>
        <p>Network Operations Center</p>
    </div>
    {% if error %}
    <div class="error">⚠️ {{ error }}</div>
    {% endif %}
    <form method="POST">
        <div class="form-group">
            <label>Username</label>
            <input type="text" name="username" autocomplete="username" autofocus required>
        </div>
        <div class="form-group">
            <label>Password</label>
            <input type="password" name="password" autocomplete="current-password" required>
        </div>
        <button type="submit" class="btn-login">🔐 Sign In</button>
    </form>
    <div class="footer">© 2026 REGTeches — Ronald Goodchild</div>
</div>
</body>
</html>"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📡 REGTeches NOC Dashboard</title>
<style>
:root {
    --bg: #0a0f1a;
    --card-bg: #0f172a;
    --card-border: #1e293b;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #3b82f6;
    --accent-dim: #1d4ed8;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #eab308;
    --orange: #f97316;
    --purple: #a855f7;
}
/* ── Light mode ── */
body.light {
    --bg: #f0f4f8;
    --card-bg: #ffffff;
    --card-border: #cbd5e1;
    --text: #1e293b;
    --text-dim: #64748b;
    --accent: #2563eb;
    --accent-dim: #1d4ed8;
    --green: #16a34a;
    --red: #dc2626;
    --yellow: #ca8a04;
    --orange: #ea580c;
    --purple: #9333ea;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;   /* body never scrolls — only groups-area does */
    transition: background 0.25s, color 0.25s;
}

/* ── Header ── */
.header {
    background: #060a14;
    padding: 0 0 0 1.2rem;
    display: flex;
    align-items: stretch;
    justify-content: flex-start;
    flex-shrink: 0;
    border-bottom: 1px solid var(--card-border);
    z-index: 100;
    min-height: 58px;
    transition: box-shadow 0.7s ease, border-bottom-color 0.7s ease;
}
.header.health-good {
    box-shadow: 0 2px 0 rgba(34,197,94,0.5), 0 4px 28px rgba(34,197,94,0.08);
    border-bottom-color: rgba(34,197,94,0.45);
}
.header.health-warn {
    box-shadow: 0 2px 0 rgba(234,179,8,0.55), 0 4px 28px rgba(234,179,8,0.1);
    border-bottom-color: rgba(234,179,8,0.45);
}
.header.health-bad {
    border-bottom-color: rgba(239,68,68,0.5);
    animation: header-pulse-red 2.2s ease-in-out infinite;
}
@keyframes header-pulse-red {
    0%,100% { box-shadow: 0 2px 0 rgba(239,68,68,0.5), 0 4px 28px rgba(239,68,68,0.12); }
    50%      { box-shadow: 0 2px 0 rgba(239,68,68,0.9), 0 4px 44px rgba(239,68,68,0.3); }
}

/* Brand zone */
.header-brand {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.5rem 1.1rem 0.5rem 0;
    flex-shrink: 0;
}
.header-signal {
    font-size: 1.55rem;
    filter: drop-shadow(0 0 9px rgba(59,130,246,0.65));
    animation: signal-pulse 3.5s ease-in-out infinite;
}
@keyframes signal-pulse {
    0%,100% { filter: drop-shadow(0 0 8px rgba(59,130,246,0.55)); }
    50%      { filter: drop-shadow(0 0 18px rgba(99,102,241,0.9)); }
}
.header-brand-text h1 {
    font-size: clamp(0.88rem, 1.55vw, 1.12rem);
    font-weight: 800;
    letter-spacing: 2px;
    background: linear-gradient(120deg, #60a5fa 0%, #a78bfa 55%, #60a5fa 100%);
    background-size: 200% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: title-shimmer 5s linear infinite;
    line-height: 1.1;
}
@keyframes title-shimmer {
    0%   { background-position: 0% center; }
    100% { background-position: 200% center; }
}
.header-meta {
    display: flex;
    align-items: center;
    gap: 0.28rem;
    margin-top: 0.18rem;
    flex-wrap: wrap;
}
.header-version {
    font-size: 0.61rem;
    background: rgba(59,130,246,0.13);
    border: 1px solid rgba(59,130,246,0.32);
    border-radius: 8px;
    padding: 0.04rem 0.42rem;
    color: #60a5fa;
    font-weight: 600;
    font-family: monospace;
    letter-spacing: 0.02em;
}
.header-sep   { font-size: 0.55rem; color: #2a3648; }
.header-author { font-size: 0.62rem; color: #5a6a82; }
.header-copy  { font-size: 0.58rem; color: #374151; }

/* Vertical dividers */
.header-vdivider {
    width: 1px;
    background: linear-gradient(to bottom, transparent, rgba(30,41,59,0.9) 25%, rgba(30,41,59,0.9) 75%, transparent);
    margin: 0 0.6rem;
    flex-shrink: 0;
    align-self: stretch;
}

/* Status zone */
.header-status {
    display: flex;
    align-items: center;
    flex-shrink: 0;
}
.hstat {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 0.72rem;
    min-width: 56px;
    cursor: default;
}
.hstat-sep {
    width: 1px;
    height: 20px;
    background: rgba(30,41,59,0.9);
    flex-shrink: 0;
}
.hstat-val {
    font-size: clamp(0.85rem, 1.35vw, 1.02rem);
    font-weight: 700;
    font-family: 'Consolas', 'Monaco', monospace;
    line-height: 1.1;
    transition: color 0.5s ease;
}
.hstat-lbl {
    font-size: 0.49rem;
    color: #4a5568;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 0.1rem;
    white-space: nowrap;
}

/* Actions zone */
.header-right {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    flex-wrap: wrap;
    padding: 0.4rem 0.8rem 0.4rem 0;
    margin-left: auto;
}
.btn {
    padding: 0.4rem 0.8rem;
    border: none;
    border-radius: 6px;
    font-size: 0.8rem;
    cursor: pointer;
    transition: all 0.15s;
    color: white;
    font-weight: 500;
}
.btn-primary { background: var(--accent); }
.btn-primary:hover { background: var(--accent-dim); }
.btn-danger { background: var(--red); }
.btn-warning { background: var(--orange); }
.btn-success { background: var(--green); }
.btn-outline {
    background: transparent;
    border: 1px solid var(--card-border);
    color: var(--text-dim);
}
.btn-outline:hover { border-color: var(--accent); color: var(--accent); }
.btn-sm { padding: 0.25rem 0.5rem; font-size: 0.7rem; }

/* ── Search & Filters ── */
.toolbar {
    padding: 0.5rem 1.2rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    flex-shrink: 0;           /* never compress — let groups-area shrink instead */
    border-bottom: 1px solid var(--card-border);
    background: rgba(15,23,42,0.5);
}
.search-box {
    flex: 1;
    min-width: 200px;
    padding: 0.5rem 1rem;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    color: var(--text);
    font-size: 0.85rem;
}
.search-box:focus { outline: none; border-color: var(--accent); }
.tag-filter {
    padding: 0.5rem;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    color: var(--text);
    font-size: 0.85rem;
}

/* ── Main Layout ── */
.main {
    display: flex;
    flex: 1;          /* fills whatever space the header+toolbar left */
    min-height: 0;    /* critical: allows flex child to shrink & scroll */
    overflow: hidden;
}
.groups-area {
    flex: 1;
    padding: 1rem;
    overflow-y: auto;   /* THE only scrollable region */
    overflow-x: hidden;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    min-height: 0;
}
.log-panel {
    width: 320px;
    min-width: 0;
    background: #050810;
    border-left: 1px solid var(--card-border);
    display: flex;
    flex-direction: column;
    overflow: hidden;     /* log entries scroll inside, not the panel itself */
}
.log-panel.collapsed { width: 0; border: none; overflow: hidden; }
.log-header {
    padding: 0.5rem 0.75rem;
    background: var(--card-bg);
    border-bottom: 1px solid var(--card-border);
    font-size: 0.8rem;
    font-weight: 600;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.log-entries {
    flex: 1;
    overflow-y: auto;
    padding: 0.5rem;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 0.7rem;
    line-height: 1.5;
}
.log-entry { padding: 0.15rem 0; border-bottom: 1px solid rgba(30,41,59,0.3); }
.log-ts { color: var(--text-dim); }
.log-INFO { color: #38bdf8; }
.log-WARN { color: #fbbf24; }
.log-ERROR { color: #f87171; }
.log-OK { color: #4ade80; }

/* ── Status dot animations ── */
@keyframes pulse-red      { 0%,100%{opacity:1}  50%{opacity:.45} }
@keyframes pulse-card-red { 0%,100%{box-shadow:0 0 0 1px rgba(239,68,68,.3),0 0 10px rgba(239,68,68,.15)}
                             50%   {box-shadow:0 0 0 2px rgba(239,68,68,.6),0 0 28px rgba(239,68,68,.35)} }

/* ── Group Sections ── */
.group-section {
    border: 1px solid rgba(59,130,246,0.25);
    border-radius: 12px;
    /* no overflow:hidden — that was clipping card bottoms */
}
.group-header {
    padding: 0.5rem 0.9rem;
    background: rgba(6,10,20,0.92);
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid rgba(30,41,59,0.4);
    border-radius: 11px 11px 0 0;   /* round top corners without overflow:hidden */
    transition: background 0.15s;
}
.group-header:hover { background: rgba(12,18,35,0.98); }
.group-chevron { font-size: 0.55rem; color: var(--text-dim); width: 10px; flex-shrink: 0; }
.group-icon   { font-size: 0.95rem; }
.group-title  {
    font-size: clamp(0.68rem, 1.1vw, 0.76rem);
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    font-family: 'Consolas','Monaco',monospace;
}
.group-badge {
    font-size: clamp(0.6rem, 0.9vw, 0.68rem);
    padding: 0.1rem 0.5rem;
    border-radius: 10px;
    background: rgba(30,41,59,0.7);
    margin-left: 0.2rem;
    font-family: monospace;
}
.group-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 270px), 1fr));
    grid-auto-rows: auto;          /* each row exactly fits its tallest card */
    align-items: start;            /* cards don't stretch beyond natural height */
    gap: 0.55rem;
    padding: 0.65rem;
    background: rgba(5,8,16,0.55);
    border-radius: 0 0 11px 11px;  /* match section rounded corners */
}
.group-cards.collapsed { display: none; }

/* ── Mini Card (full info) ── */
.mini-card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 11px;
    display: flex;
    flex-direction: column;
    width: 100%;           /* grid cell fills available column */
    min-width: 0;          /* prevent overflow in narrow columns */
    position: relative;
    transition: border-color 0.2s, transform 0.1s;
}
.mini-card:hover { transform: translateY(-1px); }
.mini-card.card-online  { border-color: rgba(34,197,94,0.5);  box-shadow: 0 0 0 1px rgba(34,197,94,0.15),  0 0 14px rgba(34,197,94,0.08); }
.mini-card.card-offline { border-color: rgba(239,68,68,0.6);  animation: pulse-card-red 2s ease-in-out infinite; }
.mini-card.card-maint   { border-color: rgba(59,130,246,0.5); box-shadow: 0 0 0 1px rgba(59,130,246,0.15); }

/* Status dot — top-right */
.mini-dot {
    position: absolute;
    top: 0.45rem; right: 0.5rem;
    width: 10px; height: 10px;
    border-radius: 50%;
}
.mini-dot.status-online  { background: var(--green); box-shadow: 0 0 7px rgba(34,197,94,.7); }
.mini-dot.status-offline { background: var(--red);   box-shadow: 0 0 7px rgba(239,68,68,.7); animation: pulse-red 2s infinite; }
.mini-dot.status-maint   { background: #2196F3;      box-shadow: 0 0 7px rgba(33,150,243,.7); }

/* Header */
.mini-header {
    padding: clamp(0.5rem, 1vw, 0.65rem) clamp(0.6rem, 1.5vw, 0.9rem);
    display: flex;
    align-items: center;
    gap: clamp(0.45rem, 1vw, 0.65rem);
    border-bottom: 1px solid var(--card-border);
}
.mini-icon {
    width: clamp(34px, 5vw, 42px); height: clamp(34px, 5vw, 42px);
    border-radius: 9px; flex-shrink: 0; overflow: hidden;
    background: rgba(255,255,255,0.05);
    display: flex; align-items: center; justify-content: center;
}
.mini-icon img { width: clamp(24px, 3.5vw, 32px); height: clamp(24px, 3.5vw, 32px); object-fit: contain; }
.mini-icon-fb {
    width: 100%; height: 100%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.05rem; font-weight: 800; color: #fff;
    background: linear-gradient(135deg,#3b82f6,#7c3aed);
    border-radius: 9px;
}
.mini-title-block { flex: 1; min-width: 0; }
.mini-name { font-size: clamp(0.75rem, 1.4vw, 0.92rem); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 1.3rem; }
.mini-ip   { font-size: clamp(0.6rem,  1.1vw, 0.7rem);  color: var(--text-dim); font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 0.05rem; }
.mini-ms   { font-size: clamp(0.58rem, 1vw,   0.68rem); padding: 0.12rem 0.45rem; border-radius: 10px; white-space: nowrap; flex-shrink: 0; }
.mini-ms.is-online  { background: rgba(34,197,94,0.15);  color: var(--green); }
.mini-ms.is-offline { background: rgba(239,68,68,0.15);  color: var(--red); }
.mini-ms.is-maint   { background: rgba(59,130,246,0.15); color: var(--accent); }

/* Body — no flex:1 so the grid can measure natural card height correctly */
.mini-body { padding: clamp(0.4rem, 1vw, 0.55rem) clamp(0.6rem, 1.5vw, 0.9rem); }
.mini-tags { display: flex; gap: 0.25rem; flex-wrap: wrap; margin-bottom: 0.4rem; }
.mini-tag  { font-size: clamp(0.55rem, 0.9vw, 0.62rem); padding: 0.08rem 0.45rem; background: var(--card-border); border-radius: 10px; color: #c4b5fd; }
.mini-conns { display: flex; gap: 0.28rem; flex-wrap: wrap; margin: 0.3rem 0; }
.mini-conn  { font-size: clamp(0.55rem, 0.9vw, 0.62rem); padding: 0.1rem 0.35rem; background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.3); border-radius: 4px; color: var(--accent); }
.mini-uptime  { display: flex; align-items: center; gap: 0.4rem; font-size: clamp(0.6rem, 1vw, 0.68rem); margin: 0.3rem 0; }
.mini-uptrack { flex: 1; height: 3px; background: #1e293b; border-radius: 2px; overflow: hidden; }
.mini-upfill  { height: 100%; border-radius: 2px; transition: width 0.3s; }
.mini-hosts { margin: 0.3rem 0; }
.mini-host-row { display: flex; align-items: center; gap: 0.4rem; padding: 0.15rem 0; font-size: clamp(0.62rem, 1.1vw, 0.72rem); border-bottom: 1px solid rgba(30,41,59,0.3); }
.mini-host-row:last-child { border-bottom: none; }
.mini-host-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }

/* Stat chips */
.mini-stats { display: flex; flex-wrap: wrap; border-top: 1px solid var(--card-border); margin: 0.4rem -0.9rem 0; }
.mini-stat  { flex: 1 1 24%; min-width: 52px; text-align: center; padding: 0.35rem 0.15rem; border-right: 1px solid var(--card-border); box-sizing: border-box; }
.mini-stat:last-child { border-right: none; }
.mini-stat-val { font-size: clamp(0.7rem, 1.1vw, 0.8rem); font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mini-stat-lbl { font-size: clamp(0.5rem, 0.8vw, 0.55rem); color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-top: 0.1rem; }

/* Footer / action buttons */
.mini-footer {
    padding: clamp(0.3rem, 0.8vw, 0.4rem) clamp(0.4rem, 1vw, 0.6rem);
    border-top: 1px solid var(--card-border);
    display: flex;
    gap: 0.22rem;
    flex-wrap: wrap;
    align-items: center;
}

/* ── Modal ── */
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.7);
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
}
.modal {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 12px;
    max-width: 700px;
    width: 95%;
    max-height: 85vh;
    overflow-y: auto;
    box-shadow: 0 25px 50px rgba(0,0,0,0.5);
}
.modal-header {
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--card-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.modal-header h2 { font-size: 1.1rem; color: var(--accent); }
.modal-close { background: none; border: none; color: var(--text-dim); font-size: 1.5rem; cursor: pointer; }
.modal-body { padding: 1rem 1.5rem; }
.modal-footer { padding: 0.75rem 1.5rem; border-top: 1px solid var(--card-border); display: flex; gap: 0.5rem; justify-content: flex-end; }

/* Form elements in modals */
.form-row { margin-bottom: 0.75rem; }
.form-row label { display: block; font-size: 0.8rem; color: var(--text-dim); margin-bottom: 0.3rem; }
.form-row input, .form-row select, .form-row textarea {
    width: 100%;
    padding: 0.5rem 0.75rem;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    color: var(--text);
    font-size: 0.85rem;
}
.form-row input:focus, .form-row select:focus { outline: none; border-color: var(--accent); }

/* Port scan results */
.port-results { max-height: 300px; overflow-y: auto; }
.port-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; font-size: 0.8rem; border-bottom: 1px solid rgba(30,41,59,0.3); }
.port-open { color: var(--green); }
.port-closed { color: var(--text-dim); }

/* ── Notification modal ── */
.notif-section { margin-bottom: 1rem; }
.notif-section-title {
    font-size: 0.72rem; font-weight: 700; color: var(--accent);
    text-transform: uppercase; letter-spacing: 0.07em;
    display: flex; align-items: center; gap: 0.4rem;
    margin-bottom: 0.55rem; padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--card-border);
}
.notif-info-box {
    background: rgba(59,130,246,0.07);
    border: 1px solid rgba(59,130,246,0.3);
    border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 0.75rem;
}
.notif-info-title { font-weight: 700; color: #60a5fa; font-size: 0.82rem; margin-bottom: 0.5rem; }
.notif-info-steps {
    margin: 0 0 0.5rem 1.15rem; padding: 0;
    color: var(--text-dim); line-height: 1.75; font-size: 0.78rem;
}
.notif-info-steps li { margin-bottom: 0.15rem; }
.notif-info-steps a { color: #60a5fa; text-decoration: underline; }
.notif-info-steps strong { color: var(--text); }
.notif-info-steps code {
    background: rgba(255,255,255,0.09); border-radius: 3px;
    padding: 1px 5px; font-family: monospace; font-size: 0.75rem;
}
.notif-info-warn { color: #fbbf24; font-size: 0.73rem; margin-top: 0.4rem; }
.notif-grid-2 { display: grid; grid-template-columns: 1fr 90px; gap: 0.45rem; }
.notif-grid-eq { display: grid; grid-template-columns: 1fr 1fr; gap: 0.45rem; }
.notif-pw-wrap { position: relative; }
.notif-pw-wrap input { padding-right: 2.4rem !important; }
.notif-pw-eye {
    position: absolute; right: 0.6rem; top: 50%; transform: translateY(-50%);
    background: none; border: none; color: var(--text-dim); cursor: pointer;
    font-size: 0.9rem; padding: 0; line-height: 1;
}
.notif-pw-eye:hover { color: var(--text); }
.recip-list { margin-top: 0.35rem; }
.recip-row {
    display: grid; grid-template-columns: 100px 1fr 1.3fr 28px;
    gap: 0.3rem; align-items: center; margin-bottom: 0.3rem;
}
.recip-row-email {
    display: grid; grid-template-columns: 1fr 28px;
    gap: 0.3rem; align-items: center; margin-bottom: 0.3rem;
}
.recip-row input, .recip-row select,
.recip-row-email input {
    width: 100%; padding: 0.38rem 0.55rem;
    background: #1e293b; border: 1px solid #334155;
    border-radius: 6px; color: var(--text); font-size: 0.8rem;
    box-sizing: border-box;
}
.recip-row input:focus, .recip-row select:focus,
.recip-row-email input:focus { outline: none; border-color: var(--accent); }
.recip-row select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2394a3b8'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 0.5rem center; padding-right: 1.5rem; }
.recip-del {
    width: 28px; height: 28px; background: rgba(239,68,68,0.12);
    border: 1px solid rgba(239,68,68,0.35); border-radius: 5px;
    color: #f87171; cursor: pointer; font-size: 0.85rem;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; transition: background 0.15s;
}
.recip-del:hover { background: rgba(239,68,68,0.28); }
.recip-col-hdr {
    display: grid; grid-template-columns: 100px 1fr 1.3fr 28px;
    gap: 0.3rem; margin-bottom: 0.15rem;
}
.recip-col-hdr span { font-size: 0.67rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; padding-left: 0.15rem; }
.add-recip-btn {
    width: 100%; margin-top: 0.2rem;
    background: rgba(59,130,246,0.08); border: 1px dashed rgba(59,130,246,0.4);
    border-radius: 6px; color: #60a5fa; cursor: pointer;
    font-size: 0.78rem; padding: 0.32rem; transition: background 0.15s;
}
.add-recip-btn:hover { background: rgba(59,130,246,0.18); }
.notif-toggle-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.45rem; font-size: 0.82rem; cursor: pointer; }
.notif-toggle-row input[type=checkbox] { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; }

/* ── Responsive ── */

/* Tablet — tighten spacing, hide log panel */
@media (max-width: 900px) {
    .log-panel   { display: none; }
    .groups-area { padding: 0.65rem; gap: 0.6rem; }
    .group-cards { gap: 0.45rem; padding: 0.55rem;
                   grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr)); }
    .mini-header { padding: 0.55rem 0.75rem; gap: 0.5rem; }
    .mini-icon   { width: 36px; height: 36px; }
    .mini-icon img { width: 26px; height: 26px; }
    .mini-body   { padding: 0.45rem 0.75rem; }
    .mini-footer { padding: 0.35rem 0.5rem; gap: 0.2rem; }
    .toolbar     { flex-direction: column; gap: 0.4rem; }
}

/* Phone landscape — 2-column grid minimum */
@media (max-width: 640px) {
    .groups-area { padding: 0.4rem; gap: 0.45rem; }
    .group-cards { padding: 0.4rem; gap: 0.35rem;
                   grid-template-columns: repeat(auto-fill, minmax(min(100%, 200px), 1fr)); }
    .group-header { padding: 0.4rem 0.7rem; }
    .group-title  { font-size: 0.68rem; }
    .btn          { padding: 0.3rem 0.55rem; font-size: 0.72rem; }
    .btn-sm       { padding: 0.18rem 0.3rem; font-size: 0.62rem; }
    .header-right .btn { padding: 0.25rem 0.45rem; font-size: 0.7rem; }
    .header-status, .header-vdivider { display: none; }
}

/* Phone portrait — single column */
@media (max-width: 420px) {
    .group-cards { grid-template-columns: 1fr; }
    .header-brand-text h1 { font-size: 0.8rem; }
    .header-meta { display: none; }
    .mini-stats  { display: none; }   /* hide stat chips on very small screens */
}

/* Toast notifications */
.toast {
    position: fixed;
    top: 80px;
    right: 20px;
    background: var(--card-bg);
    border: 1px solid var(--accent);
    border-radius: 8px;
    padding: 0.75rem 1rem;
    font-size: 0.85rem;
    z-index: 2000;
    animation: slideIn 0.3s ease;
    max-width: 350px;
}
@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
.toast.error { border-color: var(--red); }
.toast.success { border-color: var(--green); }

/* ── Setup Dropdown ── */
.setup-dropdown { position: relative; }
.setup-menu {
    display: none;
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 0.3rem;
    min-width: 195px;
    z-index: 500;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}
.setup-menu.open { display: block; }
.setup-item {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    width: 100%;
    text-align: left;
    padding: 0.55rem 0.75rem;
    background: none;
    border: none;
    color: var(--text);
    font-size: 0.82rem;
    border-radius: 7px;
    cursor: pointer;
    transition: background 0.15s;
    white-space: nowrap;
}
.setup-item:hover { background: rgba(59,130,246,0.15); color: var(--accent); }
.setup-divider { border: none; border-top: 1px solid var(--card-border); margin: 0.25rem 0; }

/* ── Backup list ── */
.backup-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.45rem 0.5rem;
    border-bottom: 1px solid rgba(30,41,59,0.4);
    font-size: 0.8rem;
}
.backup-row:last-child { border-bottom: none; }
.backup-name { flex: 1; font-family: monospace; font-size: 0.75rem; color: var(--text); }
.backup-meta { font-size: 0.68rem; color: var(--text-dim); white-space: nowrap; }

/* Mini-card sparkline strip */
.mini-sparkline { margin: 0.4rem -1rem -0.1rem; line-height: 0; }
.mini-sparkline svg { width: 100%; height: 28px; display: block; }

/* Last-seen stamp on offline cards */
.mini-lastseen {
    font-size: 0.68rem; color: var(--red); margin-top: 0.35rem;
    padding: 0.2rem 0.5rem; background: rgba(239,68,68,0.08);
    border-radius: 4px; border-left: 2px solid var(--red);
}

/* Notes badge on card */
.mini-notes-badge {
    display:inline-flex; align-items:center; gap:0.3rem;
    font-size:0.68rem; color:var(--yellow); margin-top:0.3rem;
    cursor:help; padding:0.15rem 0.4rem;
    background:rgba(234,179,8,0.08); border-radius:4px;
    border-left:2px solid var(--yellow);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    max-width:100%;
}

/* Favorite star */
.mini-fav { cursor:pointer; user-select:none; font-size:0.85rem;
            transition:transform 0.15s; }
.mini-fav:hover { transform:scale(1.25); }

/* Bulk-select checkbox on card */
.mini-check {
    position:absolute; top:0.4rem; left:0.4rem;
    width:16px; height:16px; accent-color:var(--accent);
    cursor:pointer; opacity:0; transition:opacity 0.15s;
    z-index:10;
}
.bulk-mode .mini-check { opacity:1; }
.bulk-mode .mini-card { padding-left:1.6rem; }

/* Bulk action bar */
.bulk-bar {
    display:none; align-items:center; gap:0.6rem;
    padding:0.5rem 1.2rem;
    background: linear-gradient(90deg,rgba(59,130,246,0.15),transparent);
    border-bottom:1px solid rgba(59,130,246,0.3);
    font-size:0.82rem; flex-wrap:wrap;
}
.bulk-bar.active { display:flex; }
.bulk-count { color:var(--accent); font-weight:700; margin-right:0.25rem; }

/* List-view mode */
.list-view .group-cards { display:flex; flex-direction:column; gap:0; }
.list-view .mini-card {
    display:flex; align-items:center; gap:0.6rem;
    border-radius:0; border-left:none; border-right:none;
    border-bottom:1px solid var(--card-border); padding:0.45rem 0.75rem;
    box-shadow:none !important;
}
.list-view .mini-card:first-child { border-top:1px solid var(--card-border); }
.list-view .mini-header { flex:1; border:none; padding:0; gap:0.5rem; }
.list-view .mini-body   { display:none; }
.list-view .mini-footer { flex-shrink:0; border:none; padding:0; flex-wrap:nowrap; }
.list-view .mini-icon   { width:22px; height:22px; border-radius:5px; }
.list-view .mini-icon img,.list-view .mini-icon-fb { width:16px; height:16px; font-size:0.6rem; }
.list-view .mini-name   { font-size:0.82rem; }
.list-view .mini-ip     { display:none; }
.list-view .mini-dot    { width:8px; height:8px; }

/* View-toggle button active state */
.btn-view-active { background:var(--accent) !important; color:#fff !important;
                   border-color:var(--accent) !important; }

/* RustDesk button — teal accent */
.btn-rustdesk {
    background: rgba(13,148,136,0.15) !important;
    color: #0d9488 !important;
    border: 1px solid rgba(13,148,136,0.4) !important;
}
.btn-rustdesk:hover { background: rgba(13,148,136,0.3) !important; }

/* Power button — amber */
.btn-warning {
    background: rgba(234,179,8,0.15) !important;
    color: #eab308 !important;
    border: 1px solid rgba(234,179,8,0.4) !important;
}
.btn-warning:hover { background: rgba(234,179,8,0.3) !important; }

/* Group ➕ button — hidden until header is hovered */
.group-add-btn {
    margin-left:auto; opacity:0; transition:opacity 0.15s;
    font-size:0.7rem; padding:0.15rem 0.4rem;
}
.group-header:hover .group-add-btn { opacity:1; }

/* Scrollbar styling */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--card-border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #334155; }
</style>
</head>
<body>

<!-- Header -->
<div class="header" id="mainHeader">

    <!-- Zone 1: Brand -->
    <div class="header-brand">
        <div class="header-signal">📡</div>
        <div class="header-brand-text">
            <h1>REGTECHES NOC</h1>
            <div class="header-meta">
                <span class="header-version">v""" + APP_VERSION + r"""</span>
                <span class="header-sep">·</span>
                <span class="header-author">Ronald Goodchild</span>
                <span class="header-sep">·</span>
                <span class="header-copy">© 2026 REGTeches</span>
            </div>
        </div>
    </div>

    <div class="header-vdivider"></div>

    <!-- Zone 2: Live Status -->
    <div class="header-status">
        <div class="hstat">
            <span class="hstat-val" id="hstat-online">—/—</span>
            <span class="hstat-lbl">Online</span>
        </div>
        <div class="hstat-sep"></div>
        <div class="hstat">
            <span class="hstat-val" id="hstat-offline">—</span>
            <span class="hstat-lbl">Offline</span>
        </div>
        <div class="hstat-sep"></div>
        <div class="hstat">
            <span class="hstat-val" id="hstat-maint">—</span>
            <span class="hstat-lbl">Maint</span>
        </div>
        <div class="hstat-sep"></div>
        <div class="hstat">
            <span class="hstat-val" id="countdown">—</span>
            <span class="hstat-lbl">Next Scan</span>
        </div>
    </div>

    <div class="header-vdivider"></div>

    <!-- Zone 3: Actions -->
    <div class="header-right">
        <button class="btn btn-primary" onclick="forceRefresh()">🔄 Refresh</button>
        <button class="btn btn-outline" onclick="toggleLog()">📋 Log</button>
        <button class="btn btn-outline" id="themeToggle" onclick="toggleTheme()" title="Toggle light / dark mode">🌙</button>
        <button class="btn btn-outline" onclick="showAddServer()">➕ Add Server</button>
        <div class="setup-dropdown">
            <button class="btn btn-outline" onclick="toggleSetupMenu(event)">⚙️ Setup ▾</button>
            <div class="setup-menu" id="setupMenu">
                <button class="setup-item" onclick="showAppSettings();closeSetupMenu()">🛠️ App Settings</button>
                <button class="setup-item" onclick="showNotifications();closeSetupMenu()">🔔 Notifications</button>
                <button class="setup-item" onclick="showBackupRestore();closeSetupMenu()">💾 Backup &amp; Restore</button>
                <button class="setup-item" onclick="runSpeedTest();closeSetupMenu()">🚀 Speed Test</button>
                <button class="setup-item" onclick="showNetworkScan();closeSetupMenu()">🔭 Network Discovery</button>
                <hr class="setup-divider">
                <button class="setup-item" onclick="showExportImport();closeSetupMenu()">📤 Import / Export</button>
            </div>
        </div>
        <a href="/logout" class="btn btn-danger" style="text-decoration:none;">🚪 Logout</a>
    </div>
</div>

<!-- Toolbar -->
<div class="toolbar">
    <input type="text" class="search-box" id="searchBox" placeholder="🔍 Search servers, IPs, tags, descriptions..." oninput="filterCards()">
    <select class="tag-filter" id="tagFilter" onchange="filterCards()">
        <option value="">All Servers</option>
    </select>
    <button class="btn btn-outline btn-sm" id="collapseAllBtn" onclick="toggleAllGroups()" title="Collapse / Expand all groups">⊟ Groups</button>
    <button class="btn btn-outline btn-sm" id="viewToggleBtn" onclick="toggleViewMode()" title="Toggle card / list view">🃏 Cards</button>
    <button class="btn btn-outline btn-sm" id="bulkModeBtn" onclick="toggleBulkMode()" title="Select multiple servers">☑ Select</button>
    <span style="font-size:0.75rem;color:var(--text-dim);" id="lastCheck"></span>
</div>

<!-- Bulk Action Bar -->
<div class="bulk-bar" id="bulkBar">
    <span><span class="bulk-count" id="bulkCount">0</span> selected</span>
    <button class="btn btn-sm btn-outline" onclick="bulkSelectAll()">Select All</button>
    <button class="btn btn-sm btn-outline" onclick="bulkClear()">Clear</button>
    <span style="width:1px;height:20px;background:var(--card-border);margin:0 0.25rem;"></span>
    <button class="btn btn-sm btn-outline" onclick="bulkMoveGroup()">📁 Move to Group</button>
    <button class="btn btn-sm btn-outline" onclick="bulkMaintenance('enter')">🔧 Maintenance ON</button>
    <button class="btn btn-sm btn-outline" onclick="bulkMaintenance('exit')">✅ Maintenance OFF</button>
    <button class="btn btn-sm btn-danger"  onclick="bulkDelete()">🗑️ Delete Selected</button>
    <span style="margin-left:auto;">
        <button class="btn btn-sm btn-outline" onclick="toggleBulkMode()">✕ Cancel</button>
    </span>
</div>

<!-- Main Content -->
<div class="main">
    <div class="groups-area" id="cardsArea"></div>
    <div class="log-panel" id="logPanel">
        <div class="log-header">
            📋 Activity Log
            <button class="btn btn-sm btn-outline" onclick="clearLogDisplay()">Clear</button>
        </div>
        <div class="log-entries" id="logEntries"></div>
    </div>
</div>

<!-- Modals will be injected here -->
<div id="modalContainer"></div>

<script>
// ─── State ───────────────────────────────────────────────────────────────
let state = { nodes: [], summary: {}, events: [] };
let countdown = 30;
let countdownTimer = null;
let refreshTimer = null;
let collapsedGroups = new Set();

// ─── API Helpers ─────────────────────────────────────────────────────────
async function api(url, opts = {}) {
    const defaults = { headers: { 'Content-Type': 'application/json' } };
    const resp = await fetch(url, { ...defaults, ...opts });
    if (!resp.ok) {
        let errMsg = `HTTP ${resp.status}`;
        try { const e = await resp.json(); errMsg = e.error || errMsg; } catch {}
        throw new Error(errMsg);
    }
    return resp.json();
}

// ─── Toast ───────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// ─── Data Refresh ────────────────────────────────────────────────────────
async function fetchStatus() {
    try {
        const data = await api('/api/status');
        state = data;
        renderCards();
        renderSummary();
        renderLog();
        updateTagFilter();
        countdown = data.summary.scan_interval || 30;
    } catch (e) {
        console.error('Fetch error:', e);
    }
}

function startCountdown() {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
        countdown--;
        document.getElementById('countdown').textContent = `${countdown}s`;
        if (countdown <= 0) {
            countdown = state.summary?.scan_interval || 30;
            fetchStatus();
        }
    }, 1000);
}

async function forceRefresh() {
    toast('🔄 Scan triggered...', 'info');
    await api('/api/refresh', { method: 'POST' });
    setTimeout(fetchStatus, 3000);
    countdown = state.summary?.scan_interval || 30;
}

// ─── Render Summary ──────────────────────────────────────────────────────
function renderSummary() {
    const s = state.summary;
    const active = s.total - s.maintenance;
    const offline = active - s.online;

    const onlineEl  = document.getElementById('hstat-online');
    const offlineEl = document.getElementById('hstat-offline');
    const maintEl   = document.getElementById('hstat-maint');

    if (onlineEl) {
        onlineEl.textContent = `${s.online}/${active}`;
        onlineEl.style.color = s.online === active ? 'var(--green)' : (s.online > 0 ? 'var(--yellow)' : 'var(--red)');
    }
    if (offlineEl) {
        offlineEl.textContent = offline;
        offlineEl.style.color = offline === 0 ? 'var(--green)' : (offline < active ? 'var(--yellow)' : 'var(--red)');
    }
    if (maintEl) {
        maintEl.textContent = s.maintenance || 0;
        maintEl.style.color = s.maintenance > 0 ? 'var(--accent)' : '#4a5568';
    }

    // Status-aware header glow
    const header = document.getElementById('mainHeader');
    if (header) {
        header.classList.remove('health-good', 'health-warn', 'health-bad');
        if (s.online === active)    header.classList.add('health-good');
        else if (s.online > 0)      header.classList.add('health-warn');
        else                        header.classList.add('health-bad');
    }

    document.getElementById('lastCheck').textContent = `Last: ${s.last_scan || 'never'}`;
}

// ─── Render Log ──────────────────────────────────────────────────────────
function renderLog() {
    const el = document.getElementById('logEntries');
    const events = state.events || [];
    el.innerHTML = events.slice().reverse().map(e =>
        `<div class="log-entry"><span class="log-ts">${e.ts}</span> <span class="log-${e.level}">[${e.level}]</span> ${escHtml(e.msg)}</div>`
    ).join('');
}

function clearLogDisplay() {
    document.getElementById('logEntries').innerHTML = '<div style="color:var(--text-dim);padding:1rem;">Log cleared (display only)</div>';
}

function toggleLog() {
    document.getElementById('logPanel').classList.toggle('collapsed');
}

// ─── Group constants ─────────────────────────────────────────────────────
const GROUP_COLORS = [
    '#0d9488','#3b82f6','#6366f1','#a855f7',
    '#f97316','#eab308','#22c55e','#ef4444',
];
const GROUP_ICON_MAP = {
    'nas':'🗄️','storage':'🗄️','nas & storage':'🗄️','nas storage':'🗄️',
    'virtualization':'⚡','virtual':'⚡','proxmox':'⚡',
    'media':'🎬','media services':'🎬',
    'security':'📹','cameras':'📹','security & cameras':'📹','security cameras':'📹',
    'casaos':'📦','casaos apps':'📦','apps':'📦',
    'network':'🌐','networking':'🌐',
    'cloud':'☁️','backup':'💾','database':'🗃️','home':'🏠',
};
function getGroupIcon(name) {
    return GROUP_ICON_MAP[name.toLowerCase()] || '🖥️';
}
function toggleGroup(name) {
    if (collapsedGroups.has(name)) collapsedGroups.delete(name);
    else collapsedGroups.add(name);
    renderGroups();
}

// ─── Render Groups ────────────────────────────────────────────────────────
function renderGroups() {
    const area      = document.getElementById('cardsArea');
    const search    = document.getElementById('searchBox').value.toLowerCase();
    const tagFilter = document.getElementById('tagFilter').value;

    const filtered = state.nodes.filter(n => {
        if (search) {
            const hay = `${n.name} ${n.ip} ${(n.tags||[]).join(' ')} ${n.description||''} ${(n.hosts||[]).map(h=>h.label).join(' ')}`.toLowerCase();
            if (!hay.includes(search)) return false;
        }
        if (tagFilter && !(n.tags||[]).includes(tagFilter)) return false;
        return true;
    });

    // Sort: favorites float to top within each group
    filtered.sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0));

    // Build ordered group map (first-seen order)
    const groupMap = new Map();
    filtered.forEach(n => {
        const g = n.group || 'Ungrouped';
        if (!groupMap.has(g)) groupMap.set(g, []);
        groupMap.get(g).push(n);
    });

    let gi = 0;
    area.innerHTML = [...groupMap.entries()].map(([g, gnodes]) => {
        const color  = GROUP_COLORS[gi++ % GROUP_COLORS.length];
        const icon   = getGroupIcon(g);
        const col    = collapsedGroups.has(g);
        const online = gnodes.filter(n => n.online && !n.in_maintenance).length;
        const total  = gnodes.length;
        const badgeColor = online === total ? 'var(--green)' : online > 0 ? 'var(--yellow)' : 'var(--red)';
        return `
        <div class="group-section" style="border-color:${color}40;">
            <div class="group-header" onclick="toggleGroup('${escHtml(g)}')" style="border-bottom-color:${color}22;">
                <span class="group-chevron">${col ? '▶' : '▼'}</span>
                <span class="group-icon">${icon}</span>
                <span class="group-title" style="color:${color}dd;">${escHtml(g)}</span>
                <span class="group-badge" style="color:${badgeColor};">${online}/${total}</span>
                <button class="btn btn-sm btn-outline group-add-btn"
                        onclick="event.stopPropagation();showAddServer('${escHtml(g)}')"
                        title="Add server to ${escHtml(g)}">➕</button>
            </div>
            <div class="group-cards${col ? ' collapsed' : ''}">
                ${gnodes.map(n => renderMiniCard(n)).join('')}
            </div>
        </div>`;
    }).join('');
}

function renderCards() { renderGroups(); }

// ─── Mini Card ────────────────────────────────────────────────────────────
function renderMiniCard(n) {
    const isMaint  = n.in_maintenance;
    const dotCls   = isMaint ? 'status-maint' : (n.online ? 'status-online'  : 'status-offline');
    const cardGlow = isMaint ? 'card-maint'   : (n.online ? 'card-online'    : 'card-offline');
    const msLabel  = isMaint ? 'MAINT'        : (n.online ? `${n.ms}ms`      : 'OFFLINE');
    const msCls    = isMaint ? 'is-maint'     : (n.online ? 'is-online'      : 'is-offline');

    // Icon
    const iconSlug = (n.icon || '').trim();
    const initial  = (n.name || '?').charAt(0).toUpperCase();
    const iconHtml = iconSlug
        ? `<div class="mini-icon">
               <img src="https://cdn.jsdelivr.net/gh/walkxcode/dashboard-icons@main/png/${escHtml(iconSlug)}.png"
                    alt="" loading="lazy"
                    onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
               <div class="mini-icon-fb" style="display:none;">${initial}</div>
           </div>`
        : `<div class="mini-icon"><div class="mini-icon-fb">${initial}</div></div>`;

    // IP / description subtitle
    const desc   = n.description || '';
    const ipLine = desc ? `${escHtml(desc)} · ${escHtml(n.ip)}` : escHtml(n.ip);

    // Tags
    const tags = (n.tags || []).map(t => `<span class="mini-tag">${escHtml(t)}</span>`).join('');

    // Connection badges
    const conns = (n.connections || []).map(c =>
        `<span class="mini-conn">${c.type}:${c.port}</span>`
    ).join('');

    // Uptime bar
    const upColor = n.uptime_pct >= 95 ? 'var(--green)' : n.uptime_pct >= 80 ? 'var(--yellow)' : 'var(--red)';

    // Sub-hosts
    const hosts = (n.hosts || []).map(h => {
        const dc = h.online ? 'status-online' : 'status-offline';
        const ms = h.online ? `${h.ms}ms` : 'offline';
        return `<div class="mini-host-row">
            <span class="mini-host-dot ${dc}"></span>
            <span>${escHtml(h.label)}</span>
            <span style="color:var(--text-dim);font-family:monospace;font-size:0.65rem;margin-left:0.2rem;">${h.ip}${h.port ? ':'+h.port : ''}</span>
            <span style="margin-left:auto;font-size:0.65rem;color:${h.online ? 'var(--green)' : 'var(--red)'}">${ms}</span>
        </div>`;
    }).join('');

    // Inline stat chips (Plex, Synology, etc.)
    const stats = (n.stats && n.stats.length)
        ? `<div class="mini-stats">${n.stats.map(s =>
            `<div class="mini-stat">
                <div class="mini-stat-val">${escHtml(String(s.val))}</div>
                <div class="mini-stat-lbl">${escHtml(s.lbl)}</div>
             </div>`).join('')}</div>`
        : '';

    // Footer buttons
    const manageBtn = n.manage_url
        ? `<a href="${escHtml(n.manage_url)}" target="_blank" class="btn btn-sm btn-primary" style="text-decoration:none;">🔗 ${escHtml(n.manage_label||'Manage')}</a>`
        : '';
    const wolBtn = n.mac
        ? `<button class="btn btn-sm btn-outline" onclick="wakeOnLan('${escHtml(n.mac)}')">⚡ WOL</button>` : '';
    const sysMon = n.show_sysmon
        ? `<button class="btn btn-sm btn-outline" onclick="showSystemInfo('${escHtml(n.ip)}')" title="CPU · RAM · Disks · Processes">📊 Info</button>` : '';

    // SSH / RDP one-click
    const sshConn = (n.connections || []).find(c => c.type === 'SSH');
    const rdpConn = (n.connections || []).find(c => c.type === 'RDP');
    const sshBtn  = sshConn
        ? `<a href="ssh://${escHtml(n.ip)}:${sshConn.port}" class="btn btn-sm btn-outline" style="text-decoration:none;" title="Open SSH session">🖲️ SSH</a>`
        : '';
    const rdpBtn  = rdpConn
        ? `<button class="btn btn-sm btn-outline" onclick="downloadRdp('${escHtml(n.ip)}')" title="Download RDP file">🖥️ RDP</button>`
        : '';

    // Sparkline (shown when data is available)
    const sparkHtml = (n.sparkline && n.sparkline.length > 3)
        ? `<div class="mini-sparkline">${renderSparkline(n.sparkline)}</div>` : '';

    // Last-seen line for offline nodes
    const lastSeen = (!n.online && !n.in_maintenance && n.last_check && n.last_check !== 'never')
        ? `<div class="mini-lastseen">⏱ Last seen: ${escHtml(n.last_check)}</div>` : '';

    // Notes badge
    const notesBadge = n.notes
        ? `<div class="mini-notes-badge" title="${escAttr(n.notes)}">📝 ${escHtml(n.notes.slice(0,80))}${n.notes.length > 80 ? '…' : ''}</div>` : '';

    // Copy-IP + Ping + Favorite buttons
    const copyBtn = `<button class="btn btn-sm btn-outline" onclick="copyToClipboard('${escHtml(n.ip)}',this)" title="Copy IP">📋</button>`;
    const pingBtn = `<button class="btn btn-sm btn-outline" onclick="livePing('${escHtml(n.ip)}')" title="Live Ping">📡 Ping</button>`;
    const favBtn  = `<span class="mini-fav" onclick="toggleFavorite('${escHtml(n.ip)}')" title="${n.favorite ? 'Unstar' : 'Star this server'}">${n.favorite ? '⭐' : '☆'}</span>`;

    // RustDesk button — always shown, uses rustdesk_id if set else falls back to IP
    const rdTarget  = n.rustdesk_id || n.ip.split(':')[0];
    const rustdeskBtn = `<button class="btn btn-sm btn-rustdesk" onclick="launchRustDesk('${escHtml(rdTarget)}','${escHtml(n.name)}')" title="Open in RustDesk → ${escHtml(rdTarget)}">🖥 RustDesk</button>`;

    // Power control — only for noc-agent tagged servers
    const hasAgent  = (n.tags||[]).some(t => t.toLowerCase() === 'noc-agent');
    const powerBtn  = hasAgent
        ? `<button class="btn btn-sm btn-warning" onclick="showPowerControl('${escHtml(n.ip)}','${escHtml(n.name)}')" title="Remote Power Control">⚡ Power</button>`
        : '';

    // Bulk-select checkbox
    const bulkChk = `<input type="checkbox" class="mini-check" data-ip="${escHtml(n.ip)}"
        onclick="event.stopPropagation();updateBulkCount()" title="Select for bulk action">`;

    // Custom card color override
    const colorStyle = n.card_color
        ? `style="border-color:${escAttr(n.card_color)}60;box-shadow:0 0 0 1px ${escAttr(n.card_color)}30,0 0 18px ${escAttr(n.card_color)}18;"` : '';

    return `<div class="mini-card ${cardGlow}" data-ip="${escHtml(n.ip)}" ${colorStyle}>
        ${bulkChk}
        <span class="mini-dot ${dotCls}" title="${msLabel}"></span>

        <div class="mini-header">
            ${iconHtml}
            <div class="mini-title-block">
                <div class="mini-name">${favBtn} ${escHtml(n.name)}</div>
                <div class="mini-ip">${ipLine}</div>
            </div>
            <span class="mini-ms ${msCls}">${msLabel}</span>
        </div>

        <div class="mini-body">
            ${tags  ? `<div class="mini-tags">${tags}</div>`   : ''}
            ${conns ? `<div class="mini-conns">${conns}</div>` : ''}
            <div class="mini-uptime">
                <span>Uptime: ${n.uptime_pct}%</span>
                <div class="mini-uptrack">
                    <div class="mini-upfill" style="width:${n.uptime_pct}%;background:${upColor}"></div>
                </div>
            </div>
            ${hosts ? `<div class="mini-hosts">${hosts}</div>` : ''}
            ${stats}
            ${sparkHtml}
            ${lastSeen}
            ${notesBadge}
        </div>

        <div class="mini-footer">
            ${manageBtn}
            ${wolBtn}
            ${sshBtn}
            ${rdpBtn}
            ${rustdeskBtn}
            ${sysMon}
            ${powerBtn}
            ${pingBtn}
            <button class="btn btn-sm btn-outline" onclick="showPortScan('${escHtml(n.ip)}')">🔍 Ports</button>
            <button class="btn btn-sm btn-outline" onclick="toggleMaintenance('${escHtml(n.ip)}')">🔧 Maint</button>
            ${copyBtn}
            <button class="btn btn-sm btn-outline" onclick="showEditServer('${escHtml(n.ip)}')">✏️ Edit</button>
            <button class="btn btn-sm btn-danger"  onclick="deleteServer('${escHtml(n.ip)}')">🗑️ Del</button>
        </div>
    </div>`;
}

function renderSparkline(data) {
    if (!data || data.length < 2) return '<svg class="sparkline" viewBox="0 0 300 32"><text x="150" y="20" fill="#94a3b8" text-anchor="middle" font-size="10">Collecting data...</text></svg>';
    const w = 300, h = 32, pad = 2;
    const validMs = data.filter(v => v > 0);
    const maxMs = Math.max(10, ...validMs);
    const step = (w - pad * 2) / (data.length - 1);
    let path = '';
    let dots = '';
    data.forEach((v, i) => {
        if (v < 0) return;  // skip offline points
        const x = pad + i * step;
        const y = h - pad - ((v / maxMs) * (h - pad * 2));
        if (!path) path = `M ${x} ${y}`;
        else path += ` L ${x} ${y}`;
        // Mark offline neighbors
        if (i > 0 && data[i-1] < 0) {
            dots += `<circle cx="${x}" cy="${y}" r="2" fill="var(--yellow)"/>`;
        }
    });
    // Fill area
    const firstValid = data.findIndex(v => v > 0);
    const lastValid = data.length - 1 - [...data].reverse().findIndex(v => v > 0);
    const fillPath = path + ` L ${pad + lastValid * step} ${h - pad} L ${pad + firstValid * step} ${h - pad} Z`;

    // Offline regions
    let offlineRects = '';
    let offStart = -1;
    data.forEach((v, i) => {
        if (v < 0 && offStart === -1) offStart = i;
        if ((v >= 0 || i === data.length - 1) && offStart !== -1) {
            const x1 = pad + offStart * step;
            const x2 = pad + (v < 0 ? i : i - 1) * step;
            offlineRects += `<rect x="${x1}" y="0" width="${Math.max(2, x2-x1)}" height="${h}" fill="rgba(239,68,68,0.1)"/>`;
            offStart = -1;
        }
    });

    return `<svg class="sparkline" viewBox="0 0 ${w} ${h}">
        ${offlineRects}
        <path d="${fillPath}" fill="rgba(59,130,246,0.15)" stroke="none"/>
        <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="1.5"/>
        ${dots}
    </svg>`;
}

// ─── Tag Filter ──────────────────────────────────────────────────────────
function updateTagFilter() {
    const sel = document.getElementById('tagFilter');
    const current = sel.value;
    const tags = new Set();
    state.nodes.forEach(n => (n.tags || []).forEach(t => tags.add(t)));
    sel.innerHTML = '<option value="">All Servers</option>' +
        [...tags].sort().map(t => `<option value="${t}" ${t===current?'selected':''}>${t}</option>`).join('');
}

function filterCards() { renderCards(); }

// ─── View mode ───────────────────────────────────────────────────────────
let _listView = false;
function toggleViewMode() {
    _listView = !_listView;
    const area = document.getElementById('cardsArea');
    const btn  = document.getElementById('viewToggleBtn');
    area.classList.toggle('list-view', _listView);
    btn.textContent  = _listView ? '🃏 Cards' : '📋 List';
    btn.classList.toggle('btn-view-active', _listView);
}

// ─── Bulk actions ────────────────────────────────────────────────────────
let _bulkMode = false;
function toggleBulkMode() {
    _bulkMode = !_bulkMode;
    document.getElementById('cardsArea').classList.toggle('bulk-mode', _bulkMode);
    document.getElementById('bulkBar').classList.toggle('active', _bulkMode);
    document.getElementById('bulkModeBtn').classList.toggle('btn-view-active', _bulkMode);
    if (!_bulkMode) { bulkClear(); }
}
function _selectedIps() {
    return [...document.querySelectorAll('.mini-check:checked')].map(el => el.dataset.ip);
}
function updateBulkCount() {
    document.getElementById('bulkCount').textContent = _selectedIps().length;
}
function bulkClear() {
    document.querySelectorAll('.mini-check').forEach(el => el.checked = false);
    updateBulkCount();
}
function bulkSelectAll() {
    document.querySelectorAll('.mini-check').forEach(el => el.checked = true);
    updateBulkCount();
}
async function bulkMaintenance(action) {
    const ips = _selectedIps();
    if (!ips.length) { toast('No servers selected', 'info'); return; }
    await api('/api/bulk-maintenance', { method:'POST', body:JSON.stringify({ips, action}) });
    toast(`🔧 Maintenance ${action === 'enter' ? 'ON' : 'OFF'} for ${ips.length} servers`, 'success');
    fetchStatus();
}
async function bulkMoveGroup() {
    const ips = _selectedIps();
    if (!ips.length) { toast('No servers selected', 'info'); return; }
    const group = prompt('Move selected servers to group:');
    if (group === null) return;
    await api('/api/bulk-group', { method:'POST', body:JSON.stringify({ips, group: group.trim()}) });
    toast(`📁 Moved ${ips.length} servers to "${group}"`, 'success');
    toggleBulkMode();
    fetchStatus();
}
async function bulkDelete() {
    const ips = _selectedIps();
    if (!ips.length) { toast('No servers selected', 'info'); return; }
    if (!confirm(`Delete ${ips.length} server(s)? This cannot be undone.`)) return;
    await api('/api/bulk-delete', { method:'POST', body:JSON.stringify({ips}) });
    toast(`🗑️ Deleted ${ips.length} servers`, 'success');
    toggleBulkMode();
    fetchStatus();
}

// ─── Favorite toggle ─────────────────────────────────────────────────────
async function toggleFavorite(ip) {
    const data = await api('/api/favorite', { method:'POST', body:JSON.stringify({ip}) });
    // Optimistic local update
    const node = state.nodes.find(n => n.ip === ip);
    if (node) node.favorite = data.favorite;
    renderCards();
}

// ─── RustDesk Launcher ───────────────────────────────────────────────────
async function launchRustDesk(target, name) {
    // Try URL scheme first (works if RustDesk is installed with protocol handler)
    const urlScheme = `rustdesk://connection/new/id=${encodeURIComponent(target)}`;

    openModal(`🖥 RustDesk — ${escHtml(name || target)}`,
    `<div style="text-align:center;padding:1rem 0;">
        <div style="font-size:3rem;margin-bottom:0.75rem;">🖥</div>
        <div style="font-size:1rem;font-weight:600;margin-bottom:0.25rem;">${escHtml(name || target)}</div>
        <div style="font-family:monospace;color:var(--accent);font-size:0.9rem;margin-bottom:1.5rem;">${escHtml(target)}</div>
        <div id="rdStatus" style="color:var(--text-dim);font-size:0.82rem;margin-bottom:1rem;">
            Click a button below to connect.
        </div>
        <div style="display:flex;flex-direction:column;gap:0.6rem;max-width:320px;margin:0 auto;">
            <button class="btn btn-primary" style="padding:0.7rem;"
                    onclick="rdLaunchUrl('${escHtml(urlScheme)}')">
                🚀 Open with RustDesk (URL scheme)
            </button>
            <button class="btn btn-outline" style="padding:0.7rem;"
                    onclick="rdLaunchServer('${escHtml(target)}')">
                🖥 Launch via NOC server
            </button>
        </div>
        <div style="margin-top:1.25rem;font-size:0.72rem;color:var(--text-dim);line-height:1.6;">
            <b>URL scheme</b> opens RustDesk directly in your browser if the app is installed.<br>
            <b>NOC server</b> calls the server machine to launch RustDesk there (useful when the<br>
            dashboard is open on the same PC where RustDesk is installed).
        </div>
        <div style="margin-top:1rem;padding:0.6rem;background:var(--card-border);border-radius:6px;font-size:0.72rem;text-align:left;">
            <b style="color:var(--text-dim);">Target ID / IP:</b>
            <span style="font-family:monospace;color:var(--accent);">${escHtml(target)}</span><br>
            <span style="color:var(--text-dim);">Change the RustDesk ID in ✏️ Edit → RustDesk ID field.</span>
        </div>
     </div>`, []);
}

function rdLaunchUrl(scheme) {
    document.getElementById('rdStatus').innerHTML =
        '<span style="color:var(--green);">✅ Opening RustDesk via URL scheme…</span>';
    window.location.href = scheme;
}

async function rdLaunchServer(target) {
    document.getElementById('rdStatus').innerHTML =
        '<span style="color:var(--accent);">⏳ Launching RustDesk on server…</span>';
    try {
        const data = await api('/api/launch-rustdesk',
            { method:'POST', body: JSON.stringify({ target }) });
        if (data.ok) {
            document.getElementById('rdStatus').innerHTML =
                `<span style="color:var(--green);">✅ RustDesk launched! (${escHtml(data.exe||'')})</span>`;
        } else {
            document.getElementById('rdStatus').innerHTML =
                `<span style="color:var(--red);">❌ ${escHtml(data.error||'Failed')}</span>
                 <div style="font-size:0.7rem;margin-top:0.4rem;color:var(--text-dim);">
                    Install RustDesk on this PC, or use the URL scheme button above.
                 </div>`;
        }
    } catch (e) {
        document.getElementById('rdStatus').innerHTML =
            `<span style="color:var(--red);">❌ ${escHtml(e.message)}</span>`;
    }
}

// ─── Remote Power Control ─────────────────────────────────────────────────
function showPowerControl(ip, name) {
    const actions = [
        { id:'reboot',    icon:'🔄', label:'Reboot',    desc:'Restarts in 10 seconds',    cls:'btn-warning' },
        { id:'shutdown',  icon:'⏹',  label:'Shutdown',  desc:'Powers off in 10 seconds',  cls:'btn-warning' },
        { id:'cancel',    icon:'🚫', label:'Cancel',    desc:'Abort pending shutdown/reboot', cls:'btn-outline' },
        { id:'lock',      icon:'🔒', label:'Lock',      desc:'Lock the screen now',        cls:'btn-outline' },
        { id:'sleep',     icon:'💤', label:'Sleep',     desc:'Put the PC to sleep',        cls:'btn-outline' },
        { id:'hibernate', icon:'❄️', label:'Hibernate', desc:'Hibernate the PC',           cls:'btn-outline' },
        { id:'logoff',    icon:'🚪', label:'Log Off',   desc:'Log off current user',       cls:'btn-outline' },
    ];
    const html = `
        <div style="text-align:center;margin-bottom:1rem;">
            <div style="font-size:0.85rem;color:var(--text-dim);">
                Sending command to <b style="color:var(--text);">${escHtml(name)}</b>
                via NOC Agent &nbsp;·&nbsp;
                <span style="font-family:monospace;color:var(--accent);">${escHtml(ip)}</span>
            </div>
            <div id="pwrStatus" style="margin-top:0.6rem;min-height:1.2rem;font-size:0.82rem;"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;">
            ${actions.map(a => `
            <button class="btn ${a.cls}" style="padding:0.65rem 0.5rem;text-align:left;display:flex;align-items:center;gap:0.5rem;"
                    onclick="sendPowerAction('${escHtml(ip)}','${a.id}','${escHtml(name)}')">
                <span style="font-size:1.2rem;">${a.icon}</span>
                <span>
                    <div style="font-weight:600;font-size:0.85rem;">${a.label}</div>
                    <div style="font-size:0.68rem;opacity:0.7;">${a.desc}</div>
                </span>
            </button>`).join('')}
        </div>
        <div style="margin-top:0.75rem;font-size:0.7rem;color:var(--text-dim);border-top:1px solid var(--card-border);padding-top:0.5rem;">
            ⚠️ Reboot &amp; Shutdown have a 10-second window — click Cancel to abort.
            Requires noc_agent.py running on <b>${escHtml(ip)}</b>.
        </div>`;
    openModal(`⚡ Power Control — ${escHtml(name)}`, html, []);
}

async function sendPowerAction(ip, action, name) {
    document.getElementById('pwrStatus').innerHTML =
        `<span style="color:var(--accent);">⏳ Sending ${action} to ${escHtml(name)}…</span>`;
    try {
        const data = await api('/api/power',
            { method:'POST', body: JSON.stringify({ ip, action }) });
        const ok = data.ok !== false && !data.error;
        document.getElementById('pwrStatus').innerHTML = ok
            ? `<span style="color:var(--green);">✅ ${escHtml(data.msg || action + ' sent')}</span>`
            : `<span style="color:var(--red);">❌ ${escHtml(data.error || 'Failed')}</span>`;
        if (ok) { setTimeout(fetchStatus, 15000); }
    } catch (e) {
        document.getElementById('pwrStatus').innerHTML =
            `<span style="color:var(--red);">❌ ${escHtml(e.message)}</span>`;
    }
}

// ─── Network Discovery ────────────────────────────────────────────────────
async function showNetworkScan() {
    // Auto-detect subnet from first server IP
    let guessSubnet = '10.0.0';
    if (state.nodes && state.nodes.length) {
        const firstIp = (state.nodes[0].ip || '').split(':')[0];
        if (firstIp.match(/^\d+\.\d+\.\d+/)) {
            guessSubnet = firstIp.split('.').slice(0,3).join('.');
        }
    }
    openModal('🔭 Network Discovery', `
        <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;align-items:flex-end;">
            <div style="flex:1;">
                <label style="display:block;font-size:0.8rem;color:var(--text-dim);margin-bottom:0.3rem;">
                    Subnet  (first 3 octets)
                </label>
                <input id="scanSubnet" value="${guessSubnet}"
                       style="width:100%;padding:0.5rem 0.75rem;background:#1e293b;border:1px solid #334155;border-radius:6px;color:var(--text);"
                       placeholder="e.g. 10.0.0">
            </div>
            <button class="btn btn-primary" onclick="runNetworkScan()" style="padding:0.55rem 1rem;">🔍 Scan</button>
        </div>
        <div id="scanStatus" style="font-size:0.8rem;color:var(--text-dim);margin-bottom:0.5rem;">
            Enter a subnet and click Scan. This scans .1–.254 for live hosts.
        </div>
        <div id="scanResults"></div>`, []);
}

async function runNetworkScan() {
    const subnet = document.getElementById('scanSubnet').value.trim();
    if (!subnet) { toast('Enter a subnet first', 'info'); return; }
    document.getElementById('scanStatus').innerHTML =
        `<span style="color:var(--accent);">⏳ Scanning ${escHtml(subnet)}.1–.254 … (may take 20-30s)</span>`;
    document.getElementById('scanResults').innerHTML = '';
    try {
        const data = await api('/api/network-scan',
            { method:'POST', body: JSON.stringify({ subnet }) });
        const hosts = data.hosts || [];
        document.getElementById('scanStatus').innerHTML =
            `<span style="color:var(--green);">✅ Found <b>${hosts.length}</b> live hosts</span>
             &nbsp;·&nbsp; <button class="btn btn-sm btn-success" onclick="addSelectedHosts()">➕ Add Selected to NOC</button>`;

        if (!hosts.length) {
            document.getElementById('scanResults').innerHTML =
                '<div style="color:var(--text-dim);padding:1rem;text-align:center;">No hosts found.</div>';
            return;
        }

        document.getElementById('scanResults').innerHTML = `
        <div style="max-height:380px;overflow-y:auto;margin-top:0.5rem;">
        <table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
            <thead><tr style="background:var(--card-border);">
                <th style="padding:0.4rem 0.5rem;text-align:left;width:32px;"></th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">IP</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Hostname</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Open Ports</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Detected Tags</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Status</th>
            </tr></thead>
            <tbody>
            ${hosts.map((h,i) => `
                <tr style="background:${i%2===0?'var(--card-bg)':'#0d1629'};" data-host='${JSON.stringify(h).replace(/'/g,"&#39;")}'>
                    <td style="padding:0.3rem 0.5rem;">
                        ${h.known
                            ? `<span title="Already in NOC" style="color:var(--green);">✅</span>`
                            : `<input type="checkbox" class="scan-pick" data-ip="${escHtml(h.ip)}" data-hostname="${escHtml(h.hostname)}" data-tags="${escHtml((h.tags||[]).join(','))}" style="accent-color:var(--accent);">`
                        }
                    </td>
                    <td style="padding:0.3rem 0.5rem;font-family:monospace;color:var(--accent);">${escHtml(h.ip)}</td>
                    <td style="padding:0.3rem 0.5rem;color:var(--text-dim);">${escHtml(h.hostname||'—')}</td>
                    <td style="padding:0.3rem 0.5rem;font-family:monospace;font-size:0.7rem;color:var(--text-dim);">${(h.ports||[]).join(', ')}</td>
                    <td style="padding:0.3rem 0.5rem;">${(h.tags||[]).map(t=>`<span class="mini-tag">${escHtml(t)}</span>`).join(' ')}</td>
                    <td style="padding:0.3rem 0.5rem;font-size:0.7rem;color:${h.known?'var(--text-dim)':'var(--green)'};">${h.known?'In NOC':'New'}</td>
                </tr>`).join('')}
            </tbody>
        </table>
        </div>`;
    } catch (e) {
        document.getElementById('scanStatus').innerHTML =
            `<span style="color:var(--red);">❌ ${escHtml(e.message)}</span>`;
    }
}

function addSelectedHosts() {
    const picks = [...document.querySelectorAll('.scan-pick:checked')];
    if (!picks.length) { toast('Select at least one host', 'info'); return; }
    picks.forEach(el => {
        const tags = el.dataset.tags ? el.dataset.tags.split(',').filter(Boolean) : [];
        const name = el.dataset.hostname || el.dataset.ip;
        closeModal();
        // Open the Add Server form pre-filled
        const fakeNode = {
            group: '', description: '', name: name,
            ip: el.dataset.ip, tags,
            connections: [{ type: 'HTTP', port: 80 }],
            manage_url: '', manage_label: 'Manage',
            mac: '', api_key: '', icon: '', rustdesk_id: '',
            show_sysmon: tags.includes('noc-agent'),
        };
        const html = serverFormHtml(fakeNode);
        openModal(`➕ Add  ${escHtml(el.dataset.ip)}`, html, [
            { text: '💾 Save', class: 'btn-success', onclick: () => saveServer() },
        ]);
    });
}

// ─── Live Ping ───────────────────────────────────────────────────────────
async function livePing(ip) {
    const host = ip.split(':')[0];
    openModal(`📡 Live Ping — ${host}`,
        `<div id="pingResult" style="text-align:center;padding:2rem;font-family:monospace;">
            Pinging ${escHtml(host)}…
         </div>`, [
        { text: '🔁 Ping Again', class: 'btn-primary', onclick: () => livePing(ip) },
    ]);
    const data = await api('/api/ping', {
        method: 'POST',
        body: JSON.stringify({ host, count: 4 }),
    });
    if (data.error) {
        document.getElementById('pingResult').innerHTML =
            `<div style="color:var(--red);">⚠️ ${escHtml(data.error)}</div>`;
        return;
    }
    const lossColor = data.loss_pct === 0 ? 'var(--green)' : data.loss_pct < 50 ? 'var(--yellow)' : 'var(--red)';
    const rows = (data.results || []).map((ms, i) =>
        `<div style="padding:0.25rem 0;border-bottom:1px solid var(--card-border);">
            Reply ${i+1}: ${ms !== null
                ? `<span style="color:var(--green);">${ms} ms</span>`
                : `<span style="color:var(--red);">Timed out</span>`}
         </div>`
    ).join('');
    document.getElementById('pingResult').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0.5rem;margin-bottom:1rem;">
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:var(--green);">${data.min_ms ?? '—'} ms</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">MIN</div>
            </div>
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:var(--accent);">${data.avg_ms ?? '—'} ms</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">AVG</div>
            </div>
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:var(--yellow);">${data.max_ms ?? '—'} ms</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">MAX</div>
            </div>
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:${lossColor};">${data.loss_pct}%</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">LOSS</div>
            </div>
        </div>
        <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:0.5rem;">
            Sent: ${data.sent}  ·  Received: ${data.received}  ·  Lost: ${data.lost}
        </div>
        <div style="font-family:monospace;font-size:0.82rem;">${rows}</div>`;
}

function toggleAllGroups() {
    const allGroups = [...new Set(state.nodes.map(n => n.group || 'Ungrouped'))];
    const allCollapsed = allGroups.every(g => collapsedGroups.has(g));
    if (allCollapsed) {
        collapsedGroups.clear();
        document.getElementById('collapseAllBtn').textContent = '⊟ Groups';
    } else {
        allGroups.forEach(g => collapsedGroups.add(g));
        document.getElementById('collapseAllBtn').textContent = '⊞ Groups';
    }
    renderGroups();
}

function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
        const orig = btn.textContent;
        btn.textContent = '✅';
        btn.style.color = 'var(--green)';
        setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1500);
    }).catch(() => toast('❌ Copy failed', 'error'));
}

// ─── Actions ─────────────────────────────────────────────────────────────
async function showPortScan(ip) {
    openModal('🔍 Port Scan — ' + ip, '<div id="portResults" style="text-align:center;padding:2rem;">Scanning ports...</div>', []);
    const data = await api('/api/port-scan', { method: 'POST', body: JSON.stringify({ host: ip }) });
    const open = data.results.filter(r => r.open);
    const closed = data.results.filter(r => !r.open);
    document.getElementById('portResults').innerHTML = `
        <div style="margin-bottom:0.5rem;font-size:0.85rem;color:var(--green);">✅ ${open.length} open ports</div>
        <div class="port-results">
            ${open.map(r => `<div class="port-row port-open">✅ <b>${r.port}</b> — ${r.name}</div>`).join('')}
            ${closed.map(r => `<div class="port-row port-closed">❌ ${r.port} — ${r.name}</div>`).join('')}
        </div>`;
}

async function showSystemInfo(ip) {
    openModal('📊 System Info — ' + ip, '<div id="sysInfoContent" style="text-align:center;padding:2rem;">Querying system...</div>', []);
    const data = await api('/api/system-info', { method: 'POST', body: JSON.stringify({ ip }) });
    if (data.error) {
        document.getElementById('sysInfoContent').innerHTML = `<div style="color:var(--red);">⚠️ ${escHtml(data.error)}</div><div style="color:var(--text-dim);font-size:0.8rem;margin-top:0.5rem;">${escHtml(data.details?.error || '')}</div>`;
        return;
    }
    let html = `<div style="font-size:0.8rem;color:var(--text-dim);margin-bottom:1rem;">Type: ${data.type || 'Unknown'}</div>`;
    if (data.cpu_pct !== undefined) {
        const cpuColor = data.cpu_pct < 70 ? 'var(--green)' : (data.cpu_pct < 90 ? 'var(--yellow)' : 'var(--red)');
        html += `<div class="form-row"><label>CPU</label><div style="color:${cpuColor};font-size:1.1rem;font-weight:600;">${data.cpu_pct}%</div></div>`;
    }
    if (data.ram_pct !== undefined) {
        const ramColor = data.ram_pct < 70 ? 'var(--green)' : (data.ram_pct < 90 ? 'var(--yellow)' : 'var(--red)');
        html += `<div class="form-row"><label>RAM</label><div style="color:${ramColor};font-size:1.1rem;font-weight:600;">${data.ram_pct}% — ${data.ram_used_gb||'?'}GB / ${data.ram_total_gb||'?'}GB</div></div>`;
    }
    if (data.volumes && data.volumes.length) {
        html += '<div class="form-row"><label>Storage Volumes</label></div>';
        data.volumes.forEach(v => {
            const color = v.used_pct < 70 ? 'var(--green)' : (v.used_pct < 85 ? 'var(--yellow)' : 'var(--red)');
            html += `<div style="margin-bottom:0.5rem;">
                <div style="font-size:0.8rem;margin-bottom:0.2rem;">${escHtml(v.label)} — ${v.free_gb}GB free / ${v.total_gb}GB</div>
                <div style="background:#1e293b;border-radius:4px;overflow:hidden;height:20px;">
                    <div style="background:${color};height:100%;width:${v.used_pct}%;display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:600;">${v.used_pct}%</div>
                </div>
            </div>`;
        });
    }
    if (data.disks && data.disks.length) {
        html += '<div class="form-row"><label>Physical Disks</label></div>';
        data.disks.forEach(d => {
            const statusColor = d.status === 'normal' ? 'var(--green)' : 'var(--yellow)';
            html += `<div style="font-size:0.8rem;padding:0.2rem 0;">${escHtml(d.name)} — ${escHtml(d.model)} (${d.size_gb}GB) — <span style="color:${statusColor}">${d.status}</span> ${d.temp !== 'N/A' ? '🌡️'+d.temp+'°C' : ''}</div>`;
        });
    }
    // Plex
    if (data.type === 'plex') {
        html += `<div class="form-row"><label>Active Streams</label><div style="color:var(--green);font-size:1.1rem;font-weight:600;">${data.streams ?? 0}</div></div>`;
        if (data.movies !== undefined) html += `<div class="form-row"><label>Movies</label><div>${data.movies.toLocaleString()}</div></div>`;
        if (data.tv_shows !== undefined) html += `<div class="form-row"><label>TV Shows</label><div>${data.tv_shows.toLocaleString()}</div></div>`;
        if (data.music_artists !== undefined) html += `<div class="form-row"><label>Music Artists</label><div>${data.music_artists.toLocaleString()}</div></div>`;
    }
    // Sonarr
    if (data.type === 'sonarr') {
        html += `<div class="form-row"><label>Series</label><div>${data.series_count ?? 0} total, ${data.monitored ?? 0} monitored</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items</div></div>`;
    }
    // Radarr
    if (data.type === 'radarr') {
        html += `<div class="form-row"><label>Movies</label><div>${(data.movie_count ?? 0).toLocaleString()} total — ${data.downloaded ?? 0} downloaded</div></div>`;
        html += `<div class="form-row"><label>Monitored</label><div>${data.monitored ?? 0}</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items</div></div>`;
    }
    // Lidarr
    if (data.type === 'lidarr') {
        html += `<div class="form-row"><label>Artists</label><div>${data.artist_count ?? 0}</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items</div></div>`;
    }
    // SABnzbd
    if (data.type === 'sabnzbd') {
        const statusColor = data.status === 'Downloading' ? 'var(--green)' : 'var(--text-dim)';
        html += `<div class="form-row"><label>Status</label><div style="color:${statusColor};font-weight:600;">${escHtml(data.status ?? 'Unknown')}</div></div>`;
        html += `<div class="form-row"><label>Speed</label><div>${escHtml(data.speed ?? '0')} B/s</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items — ${data.queue_mb ?? 0} MB remaining</div></div>`;
        if (data.eta && data.eta !== 'N/A') html += `<div class="form-row"><label>ETA</label><div>${escHtml(data.eta)}</div></div>`;
    }
    // Immich
    if (data.type === 'immich') {
        html += `<div class="form-row"><label>Photos</label><div>${(data.photos ?? 0).toLocaleString()}</div></div>`;
        html += `<div class="form-row"><label>Videos</label><div>${(data.videos ?? 0).toLocaleString()}</div></div>`;
        html += `<div class="form-row"><label>Storage Used</label><div>${data.usage_gb ?? 0} GB</div></div>`;
    }
    // ── NOC Agent (Windows / Linux PC) ──────────────────────────────────────
    if (data.type === 'noc-agent') {
        html = '';   // reset and build from scratch for the agent

        // Header strip
        const upColor = !data.cpu_pct ? '#94a3b8'
            : data.cpu_pct < 60 ? 'var(--green)' : data.cpu_pct < 85 ? 'var(--yellow)' : 'var(--red)';
        html += `<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:1rem;">
            ${_agentStat(data.cpu_pct?.toFixed(1)+'%','CPU', data.cpu_pct)}
            ${_agentStat(data.ram_pct?.toFixed(1)+'%','RAM', data.ram_pct)}
            ${_agentStat(data.uptime_str||'?','UPTIME', 0)}
            ${_agentStat(data.proc_count||'?','PROCS', 0)}
        </div>`;

        // CPU detail
        html += _agentSection('CPU');
        html += `<div class="form-row"><label>Processor</label><div>${escHtml(data.cpu_name||'?')}</div></div>`;
        html += `<div class="form-row"><label>Cores</label><div>${data.cpu_cores_phys||'?'} physical / ${data.cpu_cores_logi||'?'} logical</div></div>`;
        if (data.cpu_freq_mhz) html += `<div class="form-row"><label>Frequency</label><div>${data.cpu_freq_mhz.toLocaleString()} MHz  (max ${(data.cpu_freq_max||0).toLocaleString()} MHz)</div></div>`;
        html += _agentBar('Overall Usage', data.cpu_pct||0);
        if (data.cpu_temps && data.cpu_temps.length) {
            data.cpu_temps.forEach(t => {
                const c = t.cur < 60 ? 'var(--green)' : t.cur < 80 ? 'var(--yellow)' : 'var(--red)';
                html += `<div class="form-row"><label>${escHtml(t.label)}</label><div style="color:${c}">${t.cur}°C <span style="color:var(--text-dim)">(max ${t.high}°C)</span></div></div>`;
            });
        }

        // RAM
        html += _agentSection('Memory');
        html += _agentBar('RAM Used', data.ram_pct||0, `${data.ram_used_gb||'?'} GB / ${data.ram_total_gb||'?'} GB`);
        html += `<div class="form-row"><label>Available</label><div style="color:var(--green)">${data.ram_free_gb||'?'} GB</div></div>`;
        if ((data.ram_cached_gb||0) > 0)
            html += `<div class="form-row"><label>Cached</label><div>${data.ram_cached_gb} GB</div></div>`;
        if ((data.swap_total_gb||0) > 0)
            html += _agentBar('Swap Used', data.swap_pct||0, `${data.swap_used_gb||'?'} GB / ${data.swap_total_gb||'?'} GB`);

        // Disks
        if (data.volumes && data.volumes.length) {
            html += _agentSection('Storage');
            data.volumes.forEach(v => {
                html += _agentBar(`${escHtml(v.label)} (${escHtml(v.fstype||'')})`,
                    v.used_pct, `${v.used_gb} GB used &nbsp;/&nbsp; ${v.total_gb} GB total &nbsp;·&nbsp; ${v.free_gb} GB free`);
            });
            if (data.disk_read_gb !== undefined)
                html += `<div class="form-row"><label>I/O since boot</label><div>Read ${data.disk_read_gb} GB &nbsp;·&nbsp; Written ${data.disk_write_gb} GB</div></div>`;
        }

        // Network
        if (data.net_ifaces && data.net_ifaces.length) {
            html += _agentSection('Network');
            data.net_ifaces.forEach(i => {
                html += `<div class="form-row"><label>${escHtml(i.name)}</label><div style="font-family:monospace;">${escHtml(i.ipv4)} <span style="color:var(--text-dim)">${i.mask ? '/ '+escHtml(i.mask) : ''}</span></div></div>`;
            });
            if (data.net_sent_gb !== undefined)
                html += `<div class="form-row"><label>Traffic since boot</label><div>Sent ${data.net_sent_gb} GB &nbsp;·&nbsp; Recv ${data.net_recv_gb} GB</div></div>`;
        }

        // Battery
        if (data.battery_pct !== undefined) {
            html += _agentSection('Battery');
            const bc = data.battery_pct > 40 ? 'var(--green)' : data.battery_pct > 20 ? 'var(--yellow)' : 'var(--red)';
            html += _agentBar('Charge', data.battery_pct, data.battery_plugged ? 'Charging' : 'On battery');
            if (!data.battery_plugged && data.battery_secs > 0) {
                const bh = Math.floor(data.battery_secs/3600), bm = Math.floor((data.battery_secs%3600)/60);
                html += `<div class="form-row"><label>Time remaining</label><div style="color:${bc}">${bh}h ${bm}m</div></div>`;
            }
        }

        // System
        html += _agentSection('System');
        html += `<div class="form-row"><label>Hostname</label><div>${escHtml(data.hostname||'?')}</div></div>`;
        html += `<div class="form-row"><label>OS</label><div>${escHtml(data.os||'?')}</div></div>`;
        html += `<div class="form-row"><label>Architecture</label><div>${escHtml(data.arch||'?')}</div></div>`;
        html += `<div class="form-row"><label>Uptime</label><div style="color:var(--green)">${escHtml(data.uptime_str||'?')}</div></div>`;
        html += `<div class="form-row"><label>Boot time</label><div>${escHtml(data.boot_time||'?')}</div></div>`;
        html += `<div class="form-row"><label>Users logged in</label><div>${data.users||0}</div></div>`;
        if (data.load_avg)
            html += `<div class="form-row"><label>Load avg (Linux)</label><div>${data.load_avg.map(v=>v.toFixed(2)).join(' / ')}</div></div>`;

        // Processes table
        if (data.processes && data.processes.length) {
            html += _agentSection(`Top Processes  (${data.proc_count||'?'} total)`);
            html += `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;font-family:monospace;">
                <thead><tr style="background:var(--card-border);color:var(--text);">
                    <th style="padding:0.4rem 0.6rem;text-align:right;">PID</th>
                    <th style="padding:0.4rem 0.6rem;text-align:left;">Process</th>
                    <th style="padding:0.4rem 0.6rem;text-align:right;">CPU%</th>
                    <th style="padding:0.4rem 0.6rem;text-align:right;">MEM%</th>
                    <th style="padding:0.4rem 0.6rem;text-align:right;">RAM</th>
                    <th style="padding:0.4rem 0.6rem;text-align:left;">User</th>
                </tr></thead><tbody>`;
            data.processes.forEach((p, i) => {
                const bg = i % 2 === 0 ? 'var(--card-bg)' : '#0d1629';
                const cpuC = p.cpu_pct > 50 ? 'var(--red)' : p.cpu_pct > 20 ? 'var(--yellow)' : 'var(--text)';
                html += `<tr style="background:${bg};">
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:var(--text-dim);">${p.pid}</td>
                    <td style="padding:0.3rem 0.6rem;">${escHtml(p.name)}</td>
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:${cpuC};font-weight:600;">${p.cpu_pct}%</td>
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:var(--text-dim);">${p.mem_pct}%</td>
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:var(--text-dim);">${p.mem_mb} MB</td>
                    <td style="padding:0.3rem 0.6rem;color:var(--text-dim);">${escHtml(p.user||'')}</td>
                </tr>`;
            });
            html += `</tbody></table>`;
        }
    }

    document.getElementById('sysInfoContent').innerHTML = html;
}

// ── Agent display helpers ─────────────────────────────────────────────────
function _agentStat(val, lbl, pct) {
    const c = pct <= 0 ? 'var(--accent)' : pct < 60 ? 'var(--green)' : pct < 85 ? 'var(--yellow)' : 'var(--red)';
    return `<div style="flex:1;min-width:90px;text-align:center;padding:0.6rem 0.4rem;
                background:var(--card-border);border-radius:8px;">
        <div style="font-size:1.15rem;font-weight:700;color:${c};">${escHtml(String(val??'?'))}</div>
        <div style="font-size:0.65rem;color:var(--text-dim);letter-spacing:0.05em;">${lbl}</div>
    </div>`;
}
function _agentSection(title) {
    return `<div style="margin:0.9rem 0 0.35rem;display:flex;align-items:center;gap:0.6rem;">
        <span style="color:var(--accent);font-weight:700;font-size:0.9rem;">${title}</span>
        <span style="flex:1;height:1px;background:var(--card-border);"></span>
    </div>`;
}
function _agentBar(label, pct, detail) {
    const c = pct < 60 ? 'var(--green)' : pct < 85 ? 'var(--yellow)' : 'var(--red)';
    return `<div style="margin-bottom:0.5rem;">
        <div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:0.2rem;">
            <span style="color:var(--text);">${label}</span>
            <span style="color:var(--text-dim);">${detail||''}</span>
        </div>
        <div style="background:var(--card-border);border-radius:4px;height:18px;overflow:hidden;position:relative;">
            <div style="background:${c};width:${Math.min(pct,100)}%;height:100%;"></div>
            <span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
                         font-size:0.7rem;font-weight:700;color:#fff;">${pct.toFixed(1)}%</span>
        </div>
    </div>`;
}

async function toggleMaintenance(ip) {
    const data = await api('/api/maintenance', { method: 'POST', body: JSON.stringify({ ip, action: 'toggle', duration: 30 }) });
    toast(`🔧 Maintenance ${data.status === 'entered' ? 'ON' : 'OFF'} for ${ip}`, 'success');
    fetchStatus();
}

async function wakeOnLan(mac) {
    const data = await api('/api/wol', { method: 'POST', body: JSON.stringify({ mac }) });
    toast(data.ok ? '⚡ WOL packet sent!' : '❌ ' + data.message, data.ok ? 'success' : 'error');
}

async function deleteServer(ip) {
    const idx = state.nodes.findIndex(n => n.ip === ip);
    const node = state.nodes[idx];
    if (!confirm(`Delete server "${node.name}"?`)) return;
    await api('/api/nodes', { method: 'DELETE', body: JSON.stringify({ index: idx }) });
    toast('🗑️ Server deleted', 'success');
    fetchStatus();
}

// ─── Add/Edit Server ─────────────────────────────────────────────────────
function showAddServer(preGroup) {
    const html = serverFormHtml({ group: preGroup || '' });
    openModal('➕ Add Server', html, [
        { text: '💾 Save', class: 'btn-success', onclick: () => saveServer() },
    ]);
}

function showEditServer(ip) {
    const idx  = state.nodes.findIndex(n => n.ip === ip);
    const node = state.nodes[idx];
    const html = serverFormHtml(node);
    openModal('✏️ Edit Server — ' + node.name, html, [
        { text: '💾 Save',      class: 'btn-success', onclick: () => saveServer(idx) },
        { text: '📋 Duplicate', class: 'btn-outline',  onclick: () => duplicateServer(ip) },
    ]);
}

function duplicateServer(ip) {
    const node = state.nodes.find(n => n.ip === ip);
    if (!node) return;
    // Clone it, clear IP and append "(Copy)" to name
    const copy = JSON.parse(JSON.stringify(node));
    copy.name = (copy.name || '') + ' (Copy)';
    copy.ip   = '';
    copy.mac  = '';
    closeModal();
    const html = serverFormHtml(copy);
    openModal('📋 Duplicate Server', html, [
        { text: '💾 Save as New', class: 'btn-success', onclick: () => saveServer() },
    ]);
}

function serverFormHtml(n) {
    const cred = (n.shares || [])[0] || {};
    return `
        <div class="form-row"><label>Group</label><input id="sf_group" value="${escAttr(n.group||'')}" placeholder="e.g. NAS &amp; Storage, Media Services, Virtualization"></div>
        <div class="form-row"><label>Description</label><input id="sf_desc" value="${escAttr(n.description||'')}" placeholder="e.g. Primary NAS · ZimaOS Management"></div>
        <div class="form-row"><label>Server Name</label><input id="sf_name" value="${escAttr(n.name||'')}"></div>
        <div class="form-row"><label>IP Address / Hostname</label><input id="sf_ip" value="${escAttr(n.ip||'')}"></div>
        <div class="form-row"><label>Connection Type</label>
            <select id="sf_conn_type">
                ${Object.keys(CONNECTION_TYPES).map(t => `<option value="${t}" ${(n.connections||[{}])[0]?.type===t?'selected':''}>${t}</option>`).join('')}
            </select>
        </div>
        <div class="form-row"><label>Primary Port</label><input id="sf_port" type="number" value="${(n.connections||[{}])[0]?.port||''}"></div>
        <div class="form-row"><label>Management URL</label><input id="sf_manage" value="${escAttr(n.manage_url||'')}"></div>
        <div class="form-row"><label>Management Label</label><input id="sf_manage_label" value="${escAttr(n.manage_label||'Manage')}"></div>
        <div class="form-row"><label>Tags (comma separated)</label><input id="sf_tags" value="${escAttr((n.tags||[]).join(', '))}"></div>

        <div style="background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.4);border-radius:8px;padding:0.75rem 1rem;margin-bottom:0.75rem;">
            <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;margin:0;">
                <input type="checkbox" id="sf_sysmon" ${n.show_sysmon ? 'checked' : ''}
                       style="width:18px;height:18px;flex-shrink:0;accent-color:#3b82f6;cursor:pointer;">
                <span style="color:#e2e8f0;font-size:0.9rem;font-weight:600;">📊 Enable System Info button on card</span>
            </label>
            <div style="font-size:0.72rem;color:#94a3b8;margin-top:0.35rem;padding-left:1.6rem;line-height:1.5;">
                Adds a <b style="color:#e2e8f0;">📊 Info</b> button to the card footer — shows live CPU, RAM,
                disk volumes &amp; top processes. Works with Synology, ZimaOS, Plex, Sonarr, Radarr, Lidarr, SABnzbd &amp; Immich.
            </div>
        </div>

        <div class="form-row"><label>MAC Address (for WOL)</label><input id="sf_mac" value="${escAttr(n.mac||'')}"></div>
        <div class="form-row"><label>RustDesk ID</label>
            <input id="sf_rustdesk" value="${escAttr(n.rustdesk_id||'')}" placeholder="Peer ID (e.g. 123456789) or leave blank to use IP">
            <div style="font-size:0.68rem;color:var(--text-dim);margin-top:0.2rem;">Used by the 🖥 RustDesk button. If blank, the server IP is used.</div>
        </div>
        <div class="form-row"><label>API Key / Token</label><input id="sf_api_key" value="${escAttr(n.api_key||'')}"></div>
        <div class="form-row"><label>Brand Icon</label>
            <input id="sf_icon" value="${escAttr(n.icon||'')}" placeholder="e.g. plex, sonarr, proxmox, synology-dsm">
            <div style="font-size:0.68rem;color:var(--text-dim);margin-top:0.2rem;">
                Slug from <a href="https://github.com/walkxcode/dashboard-icons" target="_blank" style="color:var(--accent);">dashboard-icons</a>
                — leave blank for letter avatar
            </div>
        </div>
        <div class="form-row"><label>Card Accent Color</label>
            <div style="display:flex;align-items:center;gap:0.6rem;">
                <input type="color" id="sf_color" value="${n.card_color || '#3b82f6'}"
                       style="width:44px;height:32px;padding:2px;border:1px solid var(--card-border);border-radius:6px;background:var(--card-bg);cursor:pointer;">
                <span style="font-size:0.72rem;color:var(--text-dim);">Custom border &amp; glow colour for this card. Leave as-is for the default status colour.</span>
                <button type="button" onclick="document.getElementById('sf_color').value='#3b82f6'"
                        style="font-size:0.7rem;padding:0.2rem 0.5rem;background:var(--card-border);border:none;border-radius:4px;color:var(--text-dim);cursor:pointer;">Reset</button>
            </div>
        </div>
        <div class="form-row"><label>Notes</label>
            <textarea id="sf_notes" rows="3"
                      style="width:100%;padding:0.5rem 0.75rem;background:#1e293b;border:1px solid #334155;border-radius:6px;color:var(--text);font-size:0.85rem;resize:vertical;"
                      placeholder="Any notes about this server — location, purpose, contacts, quirks…">${escHtml(n.notes||'')}</textarea>
        </div>
        <hr style="border-color:var(--card-border);margin:0.5rem 0;">
        <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:0.4rem;">Login credentials (Synology DSM, ZimaOS, etc.)</div>
        <div class="form-row"><label>Username</label><input id="sf_login_user" value="${escAttr(cred.user||'')}"></div>
        <div class="form-row"><label>Password</label><input id="sf_login_pass" type="password" value="${escAttr(cred.pass||'')}"></div>
    `;
}

const CONNECTION_TYPES = {SMB:{port:445},FTP:{port:21},FTPS:{port:990},RDP:{port:3389},SSH:{port:22},Telnet:{port:23},HTTP:{port:80},HTTPS:{port:443},Plex:{port:32400},Custom:{port:0}};

async function saveServer(idx) {
    const loginUser = document.getElementById('sf_login_user').value.trim();
    const loginPass = document.getElementById('sf_login_pass').value;
    const existingShares = (idx !== undefined ? state.nodes[idx].shares : []) || [];
    let shares;
    if (loginUser) {
        // Replace first share entry with the form credentials; keep any others
        const rest = existingShares.slice(1);
        shares = [{ user: loginUser, pass: loginPass }, ...rest];
    } else {
        shares = existingShares;
    }
    const node = {
        group: document.getElementById('sf_group').value.trim(),
        description: document.getElementById('sf_desc').value.trim(),
        name: document.getElementById('sf_name').value,
        ip: document.getElementById('sf_ip').value,
        connections: [{ type: document.getElementById('sf_conn_type').value, port: parseInt(document.getElementById('sf_port').value) || 80 }],
        manage_url: document.getElementById('sf_manage').value,
        manage_label: document.getElementById('sf_manage_label').value,
        tags: document.getElementById('sf_tags').value.split(',').map(t => t.trim()).filter(Boolean),
        mac: document.getElementById('sf_mac').value,
        api_key: document.getElementById('sf_api_key').value.trim(),
        icon:        document.getElementById('sf_icon').value.trim(),
        show_sysmon: document.getElementById('sf_sysmon').checked,
        card_color:  document.getElementById('sf_color').value,
        notes:       document.getElementById('sf_notes').value.trim(),
        rustdesk_id: document.getElementById('sf_rustdesk').value.trim(),
        favorite:    idx !== undefined ? (state.nodes[idx].favorite || false) : false,
        shares,
        hosts: (idx !== undefined ? state.nodes[idx].hosts : []) || [],
    };
    try {
        if (idx !== undefined) {
            await api('/api/nodes', { method: 'PUT', body: JSON.stringify({ index: idx, node }) });
        } else {
            await api('/api/nodes', { method: 'POST', body: JSON.stringify(node) });
        }
        closeModal();
        toast('💾 Server saved!', 'success');
        fetchStatus();
    } catch (err) {
        toast('❌ Save failed: ' + err.message, 'error');
    }
}

// ─── Notifications ───────────────────────────────────────────────────────

// US carrier → SMS email gateway mapping
const SMS_CARRIER_LIST = [
    { name: 'AT&T',              gateway: 'txt.att.net' },
    { name: 'T-Mobile',          gateway: 'tmomail.net' },
    { name: 'Verizon',           gateway: 'vtext.com' },
    { name: 'Sprint',            gateway: 'messaging.sprintpcs.com' },
    { name: 'Xfinity / Comcast', gateway: 'vtext.com' },
    { name: 'US Cellular',       gateway: 'email.uscc.net' },
    { name: 'Boost Mobile',      gateway: 'sms.myboostmobile.com' },
    { name: 'Cricket',           gateway: 'sms.cricketwireless.net' },
    { name: 'Metro PCS',         gateway: 'mymetropcs.com' },
    { name: 'Google Fi',         gateway: 'msg.fi.google.com' },
    { name: 'Mint Mobile',       gateway: 'tmomail.net' },
    { name: 'Visible',           gateway: 'vtext.com' },
    { name: 'Consumer Cellular', gateway: 'mailmymobile.net' },
    { name: 'Straight Talk',     gateway: 'vtext.com' },
];

function _carrierOptions(selected) {
    return SMS_CARRIER_LIST.map(c =>
        `<option value="${escAttr(c.name)}"${c.name === selected ? ' selected' : ''}>${escHtml(c.name)}</option>`
    ).join('');
}

// Add a new SMS recipient row to the given container element
function addSmsRow(container, r) {
    r = r || {};
    const row = document.createElement('div');
    row.className = 'recip-row';
    row.innerHTML =
        `<input type="text"  class="rn-label"   placeholder="Name"         value="${escAttr(r.label||r.name||'')}">` +
        `<input type="tel"   class="rn-phone"   placeholder="4155551234"   value="${escAttr(r.phone||'')}">` +
        `<select class="rn-carrier"><option value="">-- Carrier --</option>${_carrierOptions(r.carrier||'')}</select>` +
        `<button class="recip-del" title="Remove" onclick="this.closest('.recip-row').remove()">✕</button>`;
    container.appendChild(row);
}

// Add a new email recipient row
function addEmailRow(container, email) {
    const row = document.createElement('div');
    row.className = 'recip-row-email';
    row.innerHTML =
        `<input type="email" placeholder="you@example.com" value="${escAttr(email||'')}">` +
        `<button class="recip-del" title="Remove" onclick="this.closest('.recip-row-email').remove()">✕</button>`;
    container.appendChild(row);
}

// Collect SMS recipients from the DOM rows
function _getSmsRecipients() {
    return [...document.querySelectorAll('#sms_recip_list .recip-row')].map(row => ({
        label:   row.querySelector('.rn-label').value.trim(),
        phone:   row.querySelector('.rn-phone').value.trim().replace(/\D/g, ''),
        carrier: row.querySelector('.rn-carrier').value,
    })).filter(r => r.phone && r.carrier);
}

// Collect email recipients from the DOM rows
function _getEmailRecipients() {
    return [...document.querySelectorAll('#email_recip_list .recip-row-email')]
        .map(row => row.querySelector('input').value.trim())
        .filter(Boolean);
}

async function showNotifications() {
    let cfg = {};
    try { cfg = await api('/api/sms-config'); } catch {}

    const html = `
<!-- ── Gmail / SMTP setup ── -->
<div class="notif-section">
  <div class="notif-section-title">📧 Gmail / SMTP Setup</div>
  <div class="notif-info-box">
    <div class="notif-info-title">📋 How to create a Gmail App Password</div>
    <ol class="notif-info-steps">
      <li>Sign in to your Google Account at
          <a href="https://myaccount.google.com" target="_blank">myaccount.google.com</a></li>
      <li>Click <strong>Security</strong> in the left sidebar</li>
      <li>Under "How you sign in to Google," make sure
          <strong>2-Step Verification is ON</strong>
          — App Passwords will not appear until it is enabled</li>
      <li>In the Security page search bar type <strong>App passwords</strong> or go directly to
          <a href="https://myaccount.google.com/apppasswords" target="_blank">myaccount.google.com/apppasswords</a></li>
      <li>In the name box type <code>NOC Dashboard</code>, then click <strong>Create</strong></li>
      <li>Google shows a <strong>16-character password</strong> (like <code>abcd efgh ijkl mnop</code>) —
          copy it and paste it (with or without spaces) in the App Password field below</li>
      <li>Use your full Gmail address in the Email field (e.g. <code>yourname@gmail.com</code>).
          Leave SMTP Server and Port at their defaults.</li>
    </ol>
    <div class="notif-info-warn">⚠️ Use the App Password — NOT your regular Gmail password.
    If "App passwords" doesn't appear, 2-Step Verification is not yet enabled.</div>
  </div>
  <div class="notif-grid-2">
    <div class="form-row"><label>SMTP Server</label>
      <input id="sms_smtp" value="${escAttr(cfg.smtp_server||'smtp.gmail.com')}" placeholder="smtp.gmail.com">
    </div>
    <div class="form-row"><label>Port</label>
      <input id="sms_port" type="number" value="${cfg.smtp_port||587}">
    </div>
  </div>
  <div class="notif-grid-eq">
    <div class="form-row"><label>Gmail Address</label>
      <input id="sms_user" type="email" value="${escAttr(cfg.smtp_user||'')}" placeholder="yourname@gmail.com">
    </div>
    <div class="form-row"><label>App Password</label>
      <div class="notif-pw-wrap">
        <input id="sms_pass" type="password" value="${escAttr(cfg.smtp_pass||'')}" placeholder="16-char App Password" autocomplete="new-password">
        <button class="notif-pw-eye" onclick="
            var i=document.getElementById('sms_pass');
            i.type=i.type==='password'?'text':'password';
            this.textContent=i.type==='password'?'👁':'🙈';" title="Show/hide">👁</button>
      </div>
    </div>
  </div>
</div>

<!-- ── SMS text alerts ── -->
<div class="notif-section">
  <div class="notif-section-title">📱 SMS Text Alerts</div>
  <label class="notif-toggle-row">
    <input type="checkbox" id="sms_enabled" ${cfg.enabled?'checked':''}>
    <span>Enable SMS text alerts (sends via email-to-SMS gateway)</span>
  </label>
  <div class="recip-col-hdr">
    <span>Name</span><span>Phone Number</span><span>Carrier</span><span></span>
  </div>
  <div class="recip-list" id="sms_recip_list"></div>
  <button class="add-recip-btn" onclick="addSmsRow(document.getElementById('sms_recip_list'))">+ Add Recipient</button>
</div>

<!-- ── Email alerts ── -->
<div class="notif-section">
  <div class="notif-section-title">✉️ Email Alerts</div>
  <label class="notif-toggle-row">
    <input type="checkbox" id="email_enabled" ${cfg.email_enabled?'checked':''}>
    <span>Enable email alerts (uses the same Gmail / SMTP settings above)</span>
  </label>
  <div class="recip-list" id="email_recip_list"></div>
  <button class="add-recip-btn" onclick="addEmailRow(document.getElementById('email_recip_list'))">+ Add Email Address</button>
</div>

<!-- ── Webhooks ── -->
<div class="notif-section">
  <div class="notif-section-title">🔗 Webhook Alerts</div>
  <div class="form-row"><label>Discord Webhook URL</label>
    <input id="discord_webhook" placeholder="https://discord.com/api/webhooks/…" value="${escAttr(cfg.discord_webhook||'')}">
  </div>
  <div class="form-row"><label>Slack Webhook URL</label>
    <input id="slack_webhook" placeholder="https://hooks.slack.com/services/…" value="${escAttr(cfg.slack_webhook||'')}">
  </div>
</div>

<!-- ── Alert triggers ── -->
<div class="notif-section">
  <div class="notif-section-title">🔔 Alert Triggers</div>
  <label class="notif-toggle-row">
    <input type="checkbox" id="sms_offline" ${cfg.alert_offline!==false?'checked':''}>
    <span>Alert when a server goes <strong style="color:var(--red)">OFFLINE</strong></span>
  </label>
  <label class="notif-toggle-row">
    <input type="checkbox" id="sms_online" ${cfg.alert_online!==false?'checked':''}>
    <span>Alert when a server comes back <strong style="color:var(--green)">ONLINE</strong></span>
  </label>
  <div class="form-row" style="max-width:200px;margin-top:0.4rem;">
    <label>Cooldown between repeat alerts (minutes)</label>
    <input id="sms_cooldown" type="number" min="1" max="1440" value="${cfg.cooldown_minutes||5}">
  </div>
</div>`;

    openModal('🔔 Notifications', html, [
        { text: '💾 Save',        class: 'btn-success', onclick: saveNotifications },
        { text: '📱 Test SMS',    class: 'btn-primary',  onclick: sendTestSms },
        { text: '✉️ Test Email',  class: 'btn-primary',  onclick: sendTestEmail },
    ]);

    // Populate recipient rows after modal is in the DOM
    const smsBox   = document.getElementById('sms_recip_list');
    const emailBox = document.getElementById('email_recip_list');
    (cfg.recipients || []).forEach(r => addSmsRow(smsBox, r));
    (cfg.email_recipients || []).forEach(e => addEmailRow(emailBox, e));
    // Ensure at least one empty row each
    if (!smsBox.children.length)   addSmsRow(smsBox);
    if (!emailBox.children.length) addEmailRow(emailBox);
}

async function saveNotifications() {
    const cfg = {
        enabled:          document.getElementById('sms_enabled').checked,
        smtp_server:      document.getElementById('sms_smtp').value.trim(),
        smtp_port:        parseInt(document.getElementById('sms_port').value) || 587,
        smtp_user:        document.getElementById('sms_user').value.trim(),
        smtp_pass:        document.getElementById('sms_pass').value,
        alert_offline:    document.getElementById('sms_offline').checked,
        alert_online:     document.getElementById('sms_online').checked,
        cooldown_minutes: parseInt(document.getElementById('sms_cooldown').value) || 5,
        recipients:       _getSmsRecipients(),
        email_enabled:    document.getElementById('email_enabled').checked,
        email_recipients: _getEmailRecipients(),
        discord_webhook:  document.getElementById('discord_webhook').value.trim(),
        slack_webhook:    document.getElementById('slack_webhook').value.trim(),
    };
    try {
        await api('/api/sms-config', { method: 'POST', body: JSON.stringify(cfg) });
        closeModal();
        toast('💾 Notification settings saved!', 'success');
    } catch (err) {
        toast('❌ Save failed: ' + err.message, 'error');
    }
}

async function sendTestSms() {
    try {
        await api('/api/sms-test', { method: 'POST' });
        toast('📱 Test SMS sent! Check your phone in ~30 seconds.', 'success');
    } catch (err) {
        toast('❌ SMS test failed: ' + err.message, 'error');
    }
}

async function sendTestEmail() {
    try {
        await api('/api/email-test', { method: 'POST' });
        toast('✉️ Test email sent! Check your inbox (and spam folder).', 'success');
    } catch (err) {
        toast('❌ Email test failed: ' + err.message, 'error');
    }
}

// Keep old name as alias so any cached references still work
const showSmsSettings = showNotifications;

// ─── Export/Import ───────────────────────────────────────────────────────
function showExportImport() {
    const html = `
        <div class="form-row">
            <button class="btn btn-primary" onclick="exportConfig()">📥 Export Config</button>
            <span style="font-size:0.8rem;color:var(--text-dim);margin-left:0.5rem;">Download JSON config file</span>
        </div>
        <hr style="border-color:var(--card-border);margin:1rem 0;">
        <div class="form-row"><label>Import Config (paste JSON)</label>
            <textarea id="importJson" rows="8" style="font-family:monospace;font-size:0.75rem;" placeholder='{"version":2,"nodes":[...]}'></textarea>
        </div>`;
    openModal('💾 Config Management', html, [
        { text: '📤 Import', class: 'btn-warning', onclick: importConfig },
    ]);
}

async function exportConfig() {
    const data = await api('/api/config/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `noc_config_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    toast('📥 Config exported!', 'success');
}

async function importConfig() {
    try {
        const data = JSON.parse(document.getElementById('importJson').value);
        await api('/api/config/import', { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        toast('📤 Config imported!', 'success');
        fetchStatus();
    } catch (e) {
        toast('❌ Invalid JSON: ' + e.message, 'error');
    }
}

// ─── Modal System ────────────────────────────────────────────────────────
function openModal(title, bodyHtml, buttons = []) {
    const container = document.getElementById('modalContainer');
    container.innerHTML = `<div class="modal-overlay" id="modalOverlay">
        <div class="modal">
            <div class="modal-header"><h2>${title}</h2><button class="modal-close" id="modalCloseX">&times;</button></div>
            <div class="modal-body">${bodyHtml}</div>
            <div class="modal-footer" id="modalFooter"></div>
        </div>
    </div>`;
    // Wire up overlay click-to-close and X button
    document.getElementById('modalOverlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });
    document.getElementById('modalCloseX').addEventListener('click', closeModal);
    // Wire up action buttons using DOM so arrow-function onclicks (with closures) work correctly
    const footer = document.getElementById('modalFooter');
    buttons.forEach(b => {
        const btn = document.createElement('button');
        btn.className = `btn ${b.class || 'btn-primary'}`;
        btn.textContent = b.text;
        btn.addEventListener('click', b.onclick || closeModal);
        footer.appendChild(btn);
    });
    const closeBtn = document.createElement('button');
    closeBtn.className = 'btn btn-outline';
    closeBtn.textContent = 'Close';
    closeBtn.addEventListener('click', closeModal);
    footer.appendChild(closeBtn);
}

function closeModal() {
    document.getElementById('modalContainer').innerHTML = '';
}

// ─── Helpers ─────────────────────────────────────────────────────────────
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function escAttr(s) { return String(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }

// ─── Dark / Light Theme ───────────────────────────────────────────────────
function initTheme() {
    if (localStorage.getItem('noc_theme') === 'light') {
        document.body.classList.add('light');
        const btn = document.getElementById('themeToggle');
        if (btn) btn.textContent = '☀️';
    }
}
function toggleTheme() {
    const isLight = document.body.classList.toggle('light');
    const btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = isLight ? '☀️' : '🌙';
    localStorage.setItem('noc_theme', isLight ? 'light' : 'dark');
}

// ─── Speed Test ───────────────────────────────────────────────────────────
async function runSpeedTest() {
    openModal('🚀 Speed Test', `
        <div style="text-align:center;padding:1.5rem 0;">
            <div style="font-size:2rem;margin-bottom:0.5rem;">⏳</div>
            <div style="font-size:0.9rem;color:var(--text-dim);">Running speed test — this takes about 20–30 seconds…</div>
        </div>
        <div id="speedResult" style="display:none;">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem;text-align:center;margin-top:0.5rem;">
                <div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:1rem;">
                    <div style="font-size:1.6rem;font-weight:700;color:var(--green);" id="spd_dl">—</div>
                    <div style="font-size:0.72rem;color:var(--text-dim);margin-top:0.2rem;">↓ Download (Mbps)</div>
                </div>
                <div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:1rem;">
                    <div style="font-size:1.6rem;font-weight:700;color:var(--accent);" id="spd_ul">—</div>
                    <div style="font-size:0.72rem;color:var(--text-dim);margin-top:0.2rem;">↑ Upload (Mbps)</div>
                </div>
                <div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:1rem;">
                    <div style="font-size:1.6rem;font-weight:700;color:var(--yellow);" id="spd_ping">—</div>
                    <div style="font-size:0.72rem;color:var(--text-dim);margin-top:0.2rem;">⚡ Ping (ms)</div>
                </div>
            </div>
            <div style="text-align:center;margin-top:0.6rem;font-size:0.75rem;color:var(--text-dim);">
                Test server: <span id="spd_server">—</span>
            </div>
        </div>
        <div id="speedError" style="display:none;color:var(--red);font-size:0.82rem;text-align:center;padding:0.5rem;"></div>`, []);
    try {
        const res = await api('/api/speedtest', { method: 'POST' });
        if (res.error) {
            document.getElementById('speedError').textContent = '❌ ' + res.error;
            document.getElementById('speedError').style.display = 'block';
        } else {
            document.getElementById('spd_dl').textContent   = res.download_mbps;
            document.getElementById('spd_ul').textContent   = res.upload_mbps;
            document.getElementById('spd_ping').textContent = res.ping_ms;
            document.getElementById('spd_server').textContent = res.server;
            document.querySelector('#speedResult').style.display = 'block';
            document.querySelector('.modal-body > div:first-child').style.display = 'none';
        }
    } catch(e) {
        document.getElementById('speedError').textContent = '❌ Speed test failed: ' + e;
        document.getElementById('speedError').style.display = 'block';
    }
}

// ─── RDP One-Click ────────────────────────────────────────────────────────
function downloadRdp(ip) {
    window.location.href = `/api/server/${encodeURIComponent(ip)}/rdp`;
}

// ─── Init ────────────────────────────────────────────────────────────────
initTheme();
fetchStatus();
startCountdown();
setInterval(fetchStatus, (""" + str(SCAN_INTERVAL) + r""") * 1000);

// Keyboard shortcuts
document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.key === 'r') { e.preventDefault(); forceRefresh(); }
    if (e.ctrlKey && e.key === 'f') { e.preventDefault(); document.getElementById('searchBox').focus(); }
    if (e.key === 'Escape') { closeModal(); closeSetupMenu(); document.getElementById('searchBox').value = ''; filterCards(); }
});

// ─── Setup Dropdown ────────────────────────────────────────────────────────
function toggleSetupMenu(e) {
    e.stopPropagation();
    document.getElementById('setupMenu').classList.toggle('open');
}
function closeSetupMenu() {
    document.getElementById('setupMenu').classList.remove('open');
}
document.addEventListener('click', function(e) {
    const menu = document.getElementById('setupMenu');
    if (menu && !menu.closest('.setup-dropdown').contains(e.target)) {
        menu.classList.remove('open');
    }
});

// ─── Backup & Restore ─────────────────────────────────────────────────────
function formatBackupName(filename) {
    // backup_20260521_143022_pre-edit.zip  →  May 21 2026 02:30:22 PM  (pre-edit)
    const m = filename.match(/^backup_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(.+)\.zip$/);
    if (!m) return filename;
    const [,yr,mo,dy,hh,mm,ss,reason] = m;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const h = parseInt(hh), ampm = h >= 12 ? 'PM' : 'AM', h12 = h % 12 || 12;
    return `${months[parseInt(mo)-1]} ${dy} ${yr}  ${h12}:${mm}:${ss} ${ampm}  <span style="color:var(--text-dim)">(${reason})</span>`;
}
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
    return (bytes/1048576).toFixed(1) + ' MB';
}

async function loadBackupList() {
    const list = document.getElementById('backupList');
    if (!list) return;
    list.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem;padding:0.5rem 0;">Loading…</div>';
    try {
        const backups = await api('/api/backups');
        if (!backups.length) {
            list.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem;padding:0.5rem 0;">No backups yet. Click <b>Create Backup Now</b> to make one.</div>';
            return;
        }
        list.innerHTML = backups.map(b => `
            <div class="backup-row">
                <div>
                    <div class="backup-name">${formatBackupName(b.filename)}</div>
                    <div class="backup-meta">${formatSize(b.size)}</div>
                </div>
                <button class="btn btn-outline" style="font-size:0.72rem;padding:0.25rem 0.6rem;"
                    onclick="restoreBackup('${b.filename}')">↩ Restore</button>
            </div>`).join('');
    } catch(e) {
        list.innerHTML = '<div style="color:var(--danger);font-size:0.8rem;">Failed to load backups.</div>';
    }
}

async function createBackup() {
    try {
        const res = await api('/api/backup', { method: 'POST', body: JSON.stringify({reason:'manual'}) });
        toast('✅ Backup created! (' + (res.filename || '') + ')', 'success');
        loadBackupList();
    } catch(e) {
        toast('❌ Backup failed', 'danger');
    }
}

async function restoreBackup(filename) {
    if (!confirm('Restore from:\n' + filename + '\n\nThis will overwrite your current server config. Continue?')) return;
    try {
        await api('/api/restore', { method: 'POST', body: JSON.stringify({filename}) });
        toast('✅ Restored from backup!', 'success');
        closeModal();
        fetchStatus();
    } catch(e) {
        toast('❌ Restore failed: ' + (e.message||e), 'danger');
    }
}

// ─── App Settings ─────────────────────────────────────────────────────────
async function showAppSettings() {
    const s = await api('/api/settings');
    const html = `
        <div style="font-size:0.75rem;color:var(--accent);background:rgba(59,130,246,0.1);
                    border:1px solid rgba(59,130,246,0.3);border-radius:8px;
                    padding:0.5rem 0.75rem;margin-bottom:0.85rem;">
            ℹ️ <b>Name, Username, Password, Secret Key,</b> and <b>Port</b> take effect after
            restarting noc_web.py.&nbsp; Scan &amp; Ping intervals apply immediately.
        </div>

        <div class="form-row"><label>Dashboard Name</label>
            <input id="s_title" value="${escAttr(s.title||'REGTeches NOC Web Dashboard')}"></div>

        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.78rem;font-weight:600;margin-bottom:0.35rem;color:var(--text-dim);">Login Credentials</div>
        <div class="form-row"><label>Username</label>
            <input id="s_auth_user" value="${escAttr(s.auth_user||'admin')}"></div>
        <div class="form-row"><label>Password</label>
            <input id="s_auth_pass" type="password" value="${escAttr(s.auth_pass||'')}">
            <label style="margin-top:0.3rem;font-size:0.72rem;cursor:pointer;display:flex;align-items:center;gap:0.35rem;">
                <input type="checkbox" onchange="
                    var inp=this.closest('.form-row').querySelector('#s_auth_pass');
                    inp.type=this.checked?'text':'password';">
                Show password</label></div>

        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.78rem;font-weight:600;margin-bottom:0.35rem;color:var(--text-dim);">Network</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;">
            <div class="form-row"><label>Server Port</label>
                <input id="s_port" type="number" min="1" max="65535" value="${s.port||8082}"></div>
            <div class="form-row"><label>Scan Interval <span style="font-size:0.68rem;color:var(--text-dim)">(sec)</span></label>
                <input id="s_scan_interval" type="number" min="5" max="3600" value="${s.scan_interval||30}"></div>
            <div class="form-row"><label>Ping Timeout <span style="font-size:0.68rem;color:var(--text-dim)">(sec)</span></label>
                <input id="s_ping_timeout" type="number" min="1" max="30" value="${s.ping_timeout||2}"></div>
        </div>

        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.78rem;font-weight:600;margin-bottom:0.35rem;color:var(--text-dim);">Flask Secret Key</div>
        <div class="form-row">
            <input id="s_secret_key" value="${escAttr(s.secret_key||'')}">
            <span style="font-size:0.7rem;color:var(--text-dim);margin-top:0.2rem;">
                Used to sign session cookies. Change this to a long random string.</span></div>`;
    openModal('🛠️ App Settings', html, [
        { text: '💾 Save Settings', class: 'btn-success', onclick: saveAppSettings },
    ]);
}

async function saveAppSettings() {
    const data = {
        title:         document.getElementById('s_title').value.trim(),
        auth_user:     document.getElementById('s_auth_user').value.trim(),
        auth_pass:     document.getElementById('s_auth_pass').value,
        secret_key:    document.getElementById('s_secret_key').value.trim(),
        scan_interval: parseInt(document.getElementById('s_scan_interval').value) || 30,
        ping_timeout:  parseInt(document.getElementById('s_ping_timeout').value) || 2,
        port:          parseInt(document.getElementById('s_port').value) || 8082,
    };
    if (!data.title)     { toast('❌ Dashboard name cannot be empty', 'danger'); return; }
    if (!data.auth_user) { toast('❌ Username cannot be empty', 'danger'); return; }
    if (!data.auth_pass) { toast('❌ Password cannot be empty', 'danger'); return; }
    await api('/api/settings', { method: 'POST', body: JSON.stringify(data) });
    closeModal();
    toast('✅ Settings saved! Restart noc_web.py to apply name / login / port changes.', 'success');
}

async function showBackupRestore() {
    const html = `
        <div style="margin-bottom:0.75rem;display:flex;align-items:center;gap:0.75rem;">
            <button class="btn btn-success" style="font-size:0.82rem;" onclick="createBackup()">➕ Create Backup Now</button>
            <span style="font-size:0.75rem;color:var(--text-dim);">Auto-backup runs before every save.</span>
        </div>
        <div style="font-size:0.78rem;color:var(--text-dim);margin-bottom:0.4rem;">
            Each backup is a <b>ZIP of every file</b> in the NOC folder, stored in
            <code style="background:rgba(0,0,0,0.3);padding:1px 5px;border-radius:4px;">backups/</code>.
            The 5 most recent are kept; the oldest is dropped automatically (first-in, first-out).
        </div>
        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.82rem;font-weight:600;margin-bottom:0.4rem;">Saved Backups</div>
        <div id="backupList" style="max-height:320px;overflow-y:auto;"></div>`;
    openModal('💾 Backup &amp; Restore', html, []);
    loadBackupList();
}
</script>
</body>
</html>"""


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
