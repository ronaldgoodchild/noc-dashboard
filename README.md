# NOC Dashboard

A free, self-hosted **Network Operations Center** for home labs and small IT shops: see at a glance whether your servers, NAS boxes, cameras and services are up, get **text-message alerts** the second something drops, and jump straight into RDP / SMB / SSH / web UIs.

> Built by a working IT technician who wanted to know a server was down *before* the client called. Two editions, both free.

| Edition | Folder | Stack | Best for |
|---------|--------|-------|----------|
| **Desktop** (v2.5.0) | [`desktop/`](desktop/) | Python + Tkinter, Windows | A wall-display PC or your admin workstation |
| **Web** (v5.12.0) | [`web/`](web/) | Python + Flask, any OS | Always-on box (NAS, mini-PC), view from any browser |

Plus light **agents** in [`web/`](web/) that report CPU / RAM / disks / processes from any Windows or Linux PC.

## Features

- Real-time ping monitoring (15 s to 10 min), uptime %, latency sparklines
- **SMS alerts** through carrier email gateways (13+ carriers) - just a Gmail app password, no paid API
- Multi-protocol server cards: SMB, RDP, SSH, FTP/FTPS, Telnet, HTTP/HTTPS, Plex, custom ports
- Network share browser, saved credentials and one-click drive mapping (desktop)
- Sub-hosts (VMs, clusters, multi-service boxes) under one card, tags, filters, search
- Maintenance mode with timed windows (alerts suppressed)
- Built-in tools: port scanner, traceroute, nslookup, Wake-on-LAN
- Remote system info (WMI, Synology DSM API, ZimaOS/CasaOS API), disk usage bars, HTML master report
- JSON config import/export and automatic backups
- Dark theme designed for wall displays

## Quick start

**Desktop (Windows):**
```powershell
git clone https://github.com/ronaldgoodchild/noc-dashboard.git
cd noc-dashboard
python desktop\noc_dashboard.py
```

**Web:**
```bash
pip install -r web/requirements.txt
python web/noc_web.py        # then open http://localhost:5000
```
On first run the web app **generates a random admin password** and prints it in the console (also saved to `noc_settings.json` - change it under Settings). Copy `web/noc_servers.example.json` to `web/noc_servers.json` and edit it to list your own servers.

**Agent** (on each PC you want CPU/RAM/disk stats from): `pip install psutil` then `python web/noc_agent.py` - it prints an API key on first run to paste into the server card.

## Security notes

- Server lists, share passwords and SMS/email settings are stored in **plain-text JSON** next to the app and are git-ignored. Never commit or share them. (Moving secrets into an encrypted store is on the [roadmap](ROADMAP.md).)
- Run the web edition on a trusted LAN or behind a reverse proxy with HTTPS. Do not expose it directly to the internet.

## Launching other REGTeches tools

The desktop app can launch [DriveMapper Pro](https://github.com/ronaldgoodchild/drivemapper-pro), [BackupPro](https://github.com/ronaldgoodchild/backuppro), [Tech Sentinel Monitor](https://github.com/ronaldgoodchild/tech-sentinel-monitor), [Technician's Toolkit](https://github.com/ronaldgoodchild/technicians-toolkit), [AppForge](https://github.com/ronaldgoodchild/appforge) and [Nmap Studio](https://github.com/ronaldgoodchild/cyberscan), [REGWinTool](https://github.com/ronaldgoodchild/regwintool) if you clone them next to this repo (or set `REGTECHES_TOOLS_DIR`).

## Contributing

Ideas, bug reports and pull requests are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md) and [ROADMAP.md](ROADMAP.md).

## License

[MIT](LICENSE) (c) 2026 Ronald Goodchild / REGTeches
