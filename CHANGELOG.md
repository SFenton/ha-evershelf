# Changelog

All notable changes to the EverShelf Home Assistant integration are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.11] - 2026-06-26

### Added
- `evershelf.delete_inventory` response-capable service for deleting a specific EverShelf inventory row by inventory ID.

---

## [1.2.10] - 2026-06-26

### Added
- `evershelf.add_to_shopping` now sends a default quantity of `1` and supports incrementing an existing EverShelf cart row when a quantity is provided.
- `todo.evershelf_shopping_list` displays quantity context returned by EverShelf for shopping-list items.

---

## [1.2.7] - 2026-06-25

### Added
- `evershelf.list_inventory` response-capable service for dashboard frontends. It returns current inventory rows and supports optional location filtering for Pantry, Fridge, Freezer, and Other views.

---

## [1.2.6] - 2026-06-25

### Added
- `evershelf.add_scanned_item` response-capable service for scanner frontends. It creates or merges a product when needed, adds inventory with quantity/location/expiry metadata, and returns the product/inventory API responses.

---

## [1.2.5] - 2026-06-25

### Added
- `evershelf.read_expiry_image` response-capable service for expiry-label photos. It accepts a base64 image, allowlisted image path, or camera entity snapshot and returns EverShelf's parsed expiry date response.

---

## [1.2.4] - 2026-06-25

### Added
- `evershelf.resolve_barcode` response-capable service for barcode scanner frontends. It proxies EverShelf's `resolve_barcode` API and returns product match data to Home Assistant callers.

---

## [1.2.3] - 2026-06-03

### Changed
- **API authentication**: supports EverShelf `API_TOKEN` (and legacy `SETTINGS_TOKEN`) via `X-API-Token`, `Authorization: Bearer`, and `api_token` query parameter
- Config flow now **requires the token** when the server reports `api_token_required`
- Updated strings/translations (IT, EN, DE, FR, ES)

### Fixed
- Integration broken after EverShelf security hardening (401 Unauthorized on all API calls)
- Discovery still works without token (`ha_info` returns minimal info); full sensors need `API_TOKEN`

---

## [1.2.1] - 2026-05-29

### Fixed
- **Coordinator safety-net** — `total_items` sensor value is guaranteed to be populated even if a future PHP API change moves the field out of `attributes`. Falls back to the response `state` value.
- **Confirmed non-issues** — audited and verified that `expiring_soon`/`expiring_items` key names, `shopping_total` float/currency handling, and product list pass-through are all correctly implemented and working as designed.


## [1.2.0] - 2026-05-29

### Added
- **`expired_list` attribute** on `sensor.evershelf_expired_items` — full per-item details for every expired product (location, brand, category, days_remaining, opened_at, vacuum_sealed, default_quantity, package_unit, product_id, inventory_id). Requires EverShelf ≥ v1.7.27.
- **`low_stock_list` attribute** on `sensor.evershelf_low_stock_items` — same full details for items with quantity ≤ 1.
- `expiring_list` on `sensor.evershelf_expiring_soon` now also includes `location`, `brand`, `category`, `days_remaining`, `opened_at`, `vacuum_sealed` and more (EverShelf ≥ v1.7.27 required; older EverShelf continues to work with the previous subset of fields).

### Notes
- Minimum EverShelf version for new attributes: **v1.7.27**
- No HA restart required after updating — entities update on the next poll

---

## [1.1.0] - 2026-05-24

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
