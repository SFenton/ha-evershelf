# Changelog

All notable changes to the EverShelf Home Assistant integration are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.5.0] - 2026-08-17

### Added
- `prepare_scanned_product` commits or updates a scanned product without adding
  inventory and returns EverShelf's server-derived product fingerprint.
- Processing entities expose pending score-product counts, active incremental
  overlays, and accepted, unresolved, and rejected inventory identity counts.

### Changed
- `suggest_location` accepts the committed product ID and fingerprint required
  by EverShelf's stale-safe AI gate.

### Fixed
- Scanner clients can prepare a product on the first Next transition, request
  one committed location suggestion, and reuse the same product ID for the
  final idempotent inventory add.
- Barcode inventory adds now require a committed product ID instead of falling
  through to an ID-less save that could overwrite a new barcode owner.
- Explicit `prepared_food: false` requests clear existing prepared-food state
  through the dedicated product endpoint before inventory is added.

## [1.4.0] - 2026-08-16

### Added
- Processing phase, pending-work, recipe-score revision, and source-ingredient
  ontology coverage sensors.
- Processing activity/problem, stale-score, and ontology-provider availability
  binary sensors.

### Fixed
- Safe GET requests such as barcode resolution now retry explicit HTTP 503
  database-busy responses without retrying ambiguous network failures.
- Mark-used inventory updates call the supported row-specific EverShelf route,
  require the `inventory_decrement_v1` capability before posting, request an
  atomic decrement, validate an optional unit, and succeed only when EverShelf
  confirms a positive consumed quantity. They use the same explicit
  database-busy retry policy without retrying unrelated HTTP 503 responses.
- Barcode service calls now raise curated backend failures instead of
  returning a failure envelope as a successful Home Assistant response.
- Generic backend request failures no longer expose server exception details
  through Home Assistant service validation messages.
- Processing-status entities expose a safe operator message while raw
  activation diagnostics remain in EverShelf server logs.

## [1.3.6] - 2026-08-14

### Changed
- Expiry requests now allow the bounded Gemini-first vision pass plus local OCR
  fallback to complete within the service deadline.

## [1.3.5] - 2026-08-14

### Fixed
- Extended the bounded expiry service deadline to allow the local Copilot
  Gemini vision fallback to complete after Tesseract returns no text.

## [1.3.4] - 2026-08-14

### Fixed
- `add_scanned_item` now carries a stable idempotency key through inventory
  writes so a retry cannot add the same scanned package twice.
- Product and inventory scan requests retry only explicit HTTP 503 database-busy
  responses with a bounded delay; ambiguous network failures are not retried.
- Barcode, location, and expiry scan calls now use bounded client deadlines
  aligned with EverShelf's local/Copilot processing limits.

## [1.3.3] - 2026-08-12

### Added
- Capability-gated `recipe_ingredient_override` service for display-only have/missing assertions.
- Capability-gated `recipe_identity_feedback` service for revision-bound correct/wrong ingredient match evidence.
- Capability-gated `recipe_ingredient_decision` response service for one atomic
  assume/select/reject command with strict product-level IDs and stale-token
  propagation.
- Capability-gated `recipe_planner_add` response service for revision-bound,
  account-level Cookidoo My Week date assignment.

### Safety
- Ingredient overrides never change EverShelf inventory, recipe scores, or confirmed-missing grocery eligibility.
- Identity feedback remains proposal-only and cannot mutate ontology automatically.
- Atomic decisions preserve one backend transaction/idempotency boundary;
  `assume_have` never creates AI evidence.
- Planner requests never accept a provider external ID from React and are
  suppressed unless `recipe_planner_v1` is currently advertised.

## [1.3.2] - 2026-08-12

### Added
- Response-only recipe browse, recommendation, hydration, detail, and grocery services with strict capability gates.
- Idempotent EverShelf grocery mutation with a deduplicated Home Assistant todo mirror.
- Bounded, TTL-limited replay persistence across integration reloads and Home Assistant restarts.

### Changed
- EverShelf credentials are sent only in the `X-API-Token` header.
- Recipe capability probes preserve known-good support through transient backend failures.
- Recipe grocery calls pre-authorize todo access and serialize an in-lock pending-list reread.

### Fixed
- Durable replay state now verifies the persisted Home Assistant storage payload.
- Multiple EverShelf instances require an explicit config entry for grocery mutations.
- Responsive recommendation limits pass through to EverShelf unchanged.

## [1.2.16] - 2026-07-31

### Added
- `evershelf.suggest_location` exposes EverShelf's history-first storage-location suggestion API to dashboard frontends. It returns explicit `unknown` and unavailable responses without blocking item entry.
- `evershelf.resolve_barcode` transparently passes through exact barcode-history location suggestions returned by EverShelf.

## [1.2.15] - 2026-07-27

### Added
- `evershelf.set_inventory_prepared_food` marks some or all units of an inventory row as a prepared food item. Passing a quantity below the row quantity splits those units onto their own row, so part of a batch can be prepared while the rest is not.

## [1.2.14] - 2026-07-27

### Added
- `evershelf.add_scanned_item` accepts `prepared_food` to mark finished dishes that should not be classified by ingredient. EverShelf groups them under the existing prepared meal taxonomy term. Works for both newly created products and existing ones.

## [1.2.13] - 2026-06-28

### Added
- `evershelf.list_inventory` now accepts `q` / `search` to use EverShelf's taxonomy-aware inventory search while preserving the existing response shape for dashboards.

---

## [1.2.12] - 2026-06-26

### Added
- `evershelf.delete_inventory_item` service for deleting one item from an inventory row, decrementing rows with quantity greater than 1.
- `evershelf.update_inventory_item` service for updating one item from an inventory row, splitting rows with quantity greater than 1 when needed.

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
