# Changelog

Reconstructed from the original development history (March - June 2026).

## [Unreleased]
- Web edition: left navigation sidebar. One click filters the cards by group (with a live online/total count and a status dot), Favorites or Offline; click the active item again to clear. The ☰ button hides it, light and dark themes are supported, and it is hidden on narrow screens.
- Web edition: the header now names the servers that are down under the Offline counter (up to 3, then "+N more", full list on hover) so you can find them without scanning every card.
- Windows desktop EXE (2.5.0) published on the Releases page with SHA-256.
- Security: web edition no longer ships default `admin` / `changeme` credentials or a fixed session key - random ones are generated on first run and saved to `noc_settings.json`
- Desktop tool launcher uses portable paths (sibling folders or `REGTECHES_TOOLS_DIR`) instead of `C:\code\...`
- Example server list added; example IPs use the 192.168.1.x documentation range

## Web 5.12.0 - 2026-06-02
- Flask web dashboard with login, SMS/ntfy-style alerts, speed test, sub-hosts, maintenance windows, remote reboot/shutdown via agent
- `noc_agent.py` (psutil over HTTP), `noc_local.py` (agent + desktop widget), `noc_sysmon.py` (local monitor)

## Desktop 2.5.0 - 2026-03-29
- Remote system info (WMI / Synology / ZimaOS), disk usage charts, full server report, HTML master report, disk-space alerts, tool launcher
- Earlier 2.x: SMS alerts, maintenance mode, network tools, share browser, sub-hosts, JSON editor
