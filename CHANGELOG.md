# Changelog

All notable changes to the EverShelf Home Assistant integration are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.1] - 2026-05-23

### Changed
- **Setup UX**: when adding the integration, HA now automatically probes `http://evershelf.local` first instead of showing a blank URL form
- If auto-discovery fails, the UI shows a menu with **"Try auto-discovery again"** and **"Enter URL manually"** options
- Discovery failure message now explains that **avahi-daemon** (mDNS) must be installed and running on the EverShelf server for auto-discovery to work

### Fixed
- Removed `info.md` that was overriding `render_readme: true` and hiding the full README (with badges) in HACS
- GitHub repository description set — HACS validation now fully passing (8/8 checks)

---

## [1.0.0] - 2026-05-23

### Added
- Initial release
- Auto-discovery via Zeroconf/mDNS (`_evershelf._tcp.local.`) when `avahi-daemon` is running on the EverShelf host
- **4 sensors**: Expiring Soon, Expired Items, Total Items, Shopping List count
- **2 binary sensors**: Has Expired Items, Has Expiring Items
- **Todo entity**: bidirectional shopping list sync (add, delete, check off items)
- **Button entity**: force data refresh
- **3 services**: `evershelf.add_to_shopping`, `evershelf.mark_used`, `evershelf.refresh`
- Optional `SETTINGS_TOKEN` for write operations; read-only mode works without a token
- **5 languages**: English, Italian, German, French, Spanish
- Options flow: configurable expiry alert threshold (days) and polling interval (seconds)
- Supports EverShelf 1.7.0+ running on Docker or bare-metal Apache/PHP
