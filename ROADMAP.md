# Roadmap / ideas

Comment on (or open) an issue first so we don't duplicate work.

## Good first issues
- [ ] Add screenshots of both editions to the README (use sample data, no real IPs)
- [ ] Split `noc_web.py` (~5,000 lines with embedded HTML/JS) into templates + static files
- [ ] Add a tested `Dockerfile` / `docker-compose.yml` for the web edition
- [ ] Add a `--port` / `--host` command-line option to the web app
- [ ] Unit tests for the ping/uptime logic

## Security
- [ ] Encrypt saved share and SMTP credentials (Windows Credential Manager / keyring / Fernet)
- [ ] Hash the web login password instead of storing it in plain text
- [ ] Optional HTTPS / reverse-proxy guide; login rate limiting

## Features
- [ ] More alert channels: ntfy, Telegram, Discord, Microsoft Teams, email
- [ ] SNMP checks (UPS, switches, printers)
- [ ] SSL certificate expiry checks
- [ ] Historical charts stored in SQLite
- [ ] Linux/macOS build of the desktop edition (replace `winsound`, WMI)
- [ ] Import from Tech Sentinel Monitor / Uptime Kuma
