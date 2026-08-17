# EverShelf for Home Assistant

> **Requires a self-hosted [EverShelf](https://github.com/dadaloop82/EverShelf) instance.**
> This integration does **not** work with any cloud service — EverShelf runs on your own server.

[![HACS Integration](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/SFenton/ha-evershelf)](https://github.com/SFenton/ha-evershelf/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![HA Minimum Version](https://img.shields.io/badge/HA-2024.1%2B-41BDF5.svg)](https://www.home-assistant.io)
[![Platforms](https://img.shields.io/badge/platforms-sensor%20|%20binary__sensor%20|%20button%20|%20todo%20|%20calendar%20|%20text-blue.svg)](#entities)

Bring your pantry into Home Assistant.
**EverShelf for HA** auto-discovers your self-hosted pantry server, exposes expiry dates as a native calendar, syncs your shopping list as a todo entity, fires automations when products expire, and lets you ask the AI for recipes — all without leaving HA.

---

## Quick install

### Step 1 — Add via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SFenton&repository=ha-evershelf&category=integration)

> Don't have HACS yet? [Install HACS first](https://hacs.xyz/docs/setup/download/).

1. Click the badge above (or go to **HACS → Integrations → ⋮ → Custom repositories** and add `https://github.com/SFenton/ha-evershelf` with category **Integration**)
2. Find **EverShelf** and click **Download**
3. Restart Home Assistant

### Step 2 — Add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=evershelf)

Click the badge above, or go to **Settings → Devices & Services → Add Integration → EverShelf**.

If your EverShelf server is on the same network and runs `avahi-daemon`, it will be **discovered automatically** — a notification will appear in HA.

---

## What you need

| Requirement | Details |
|---|---|
| **EverShelf** (self-hosted) | v1.7.0+ for existing inventory features; atomic `mark_used` requires `inventory_decrement_v1` (EverShelf v1.10.0+), recipe browse/hydration requires `recipe_catalog_v2`, detail requires `recipe_detail_v1`, grocery actions require `recipe_grocery_v1`, atomic ingredient decisions require `recipe_ingredient_feedback_v2`, and the default-off account planner requires `recipe_planner_v1` |
| **Home Assistant** | 2024.1.0 or newer |
| **Network** | HA host must be able to reach the EverShelf server (same LAN or routed) |
| **SETTINGS_TOKEN** | Optional — needed only for write operations (add to shopping, mark used) |

---

## Features at a glance

| Category | What you get |
|---|---|
| **22 Sensors** | Inventory, expiry, processing phase/queue depth, recipe-score freshness, ontology coverage, shopping, and backup state |
| **11 Binary Sensors** | Inventory alerts plus processing activity/failures, stale recipe scores, and ontology-provider availability |
| **5 Buttons** | Refresh, Refresh Prices, Suggest Recipe (AI), Sync Smart Shopping, Clear Expired |
| **1 Todo entity** | Shopping list — bidirectional sync (add, remove, check off) |
| **1 Calendar entity** | All product expiry dates as calendar events |
| **1 Text entity** | Quick-add a product to the shopping list by typing its name |
| **21 Services** | Existing inventory/scanning services plus response services for recipe query, hydration, bounded detail, atomic ingredient decisions, account planning, and idempotent grocery actions |
| **Auto-discovery** | Zeroconf/mDNS — no manual URL entry needed if `avahi-daemon` runs on EverShelf host |
| **5 languages** | English, Italian, German, French, Spanish |
| **Read-only mode** | All sensors work without a token; write operations need `SETTINGS_TOKEN` |

---

## Entities

### Sensors (22)

| Entity ID | Name | Unit | Notes |
|---|---|---|---|
| `sensor.evershelf_expiring_soon` | Expiring Soon | items | Threshold configurable (default 3 days). Attribute `expiring_list` contains per-item details. |
| `sensor.evershelf_expiring_today` | Expiring Today | items | Items whose expiry date is today |
| `sensor.evershelf_expiring_3d` | Expiring in 3 Days | items | Always uses a 3-day window regardless of threshold |
| `sensor.evershelf_expired_items` | Expired Items | items | Items past their expiry date with stock > 0 |
| `sensor.evershelf_total_items` | Total Items | items | All products currently in inventory |
| `sensor.evershelf_opened_items` | Opened Items | items | Partially-opened packages being tracked |
| `sensor.evershelf_shopping_items` | Shopping List | items | Number of items on the shopping list |
| `sensor.evershelf_shopping_total` | Shopping Total | — | Estimated cost of the shopping list (e.g. `€12.40`) |
| `sensor.evershelf_items_dispensa` | Items in Pantry | items | Stock count for the pantry location |
| `sensor.evershelf_items_frigo` | Items in Fridge | items | Stock count for the fridge location |
| `sensor.evershelf_items_freezer` | Items in Freezer | items | Stock count for the freezer location |
| `sensor.evershelf_items_spice_rack` | Items in Spice Rack | items | Stock count for the spice rack location |
| `sensor.evershelf_items_cabinet` | Items in Cabinet | items | Stock count for the cabinet location |
| `sensor.evershelf_low_stock_items` | Low Stock Items | items | Items below their reorder threshold |
| `sensor.evershelf_zero_stock_items` | Out of Stock Items | items | Items with quantity = 0 |
| `sensor.evershelf_ai_calls_month` | AI Calls This Month | calls | Gemini API calls used in the current billing month |
| `sensor.evershelf_last_backup` | Last Backup | — | Timestamp of the latest EverShelf backup |
| `sensor.evershelf_days_to_next_expiry` | Days to Next Expiry | d | Days until the soonest upcoming expiry across all locations |
| `sensor.evershelf_processing_phase` | Processing Phase | — | Current backend phase: idle, recipes, ontology, scoring, activating, or degraded |
| `sensor.evershelf_processing_pending` | Pending Processing Work | jobs | Compact queue total with recipe, ontology, deferred, and missing-observation attributes |
| `sensor.evershelf_recipe_score_revision` | Recipe Score Revision | — | Active score revision with current and built inventory/catalog/source revisions |
| `sensor.evershelf_recipe_source_ontology_coverage` | Source Ingredient Ontology Coverage | % | Cookidoo/source ingredient rows with active ontology occurrences |

### Binary Sensors (11)

| Entity ID | Name | Device Class | ON when |
|---|---|---|---|
| `binary_sensor.evershelf_has_expired_items` | Has Expired Items | `problem` | At least one product is expired |
| `binary_sensor.evershelf_has_expiring_items` | Has Expiring Items | `problem` | At least one product expires within the threshold |
| `binary_sensor.evershelf_has_expiring_today` | Expiring Today (Urgent) | `problem` | At least one product expires today |
| `binary_sensor.evershelf_has_shopping_items` | Shopping List Active | — | Shopping list has at least one item |
| `binary_sensor.evershelf_price_tracking_enabled` | Price Tracking | — | Price estimation is enabled in EverShelf |
| `binary_sensor.evershelf_backup_overdue` | Backup Overdue | `problem` | No backup in the last 7 days, or no backup ever taken |
| `binary_sensor.evershelf_bring_connected` | Bring! Connected | `connectivity` | Bring! shopping app is linked and authenticated |
| `binary_sensor.evershelf_processing_active` | Processing Active | `running` | Any recipe, ontology, activation, observation-backfill, or score-publication work remains |
| `binary_sensor.evershelf_processing_problem` | Processing Problem | `problem` | Backend reports a worker, activation, logging, queue, or observation-coverage problem |
| `binary_sensor.evershelf_recipe_scores_stale` | Recipe Scores Stale | `problem` | Active scores do not match current inventory, catalog, source, or score date |
| `binary_sensor.evershelf_ontology_provider_unavailable` | Ontology Provider Unavailable | `problem` | Ontology intake needs the configured model provider but it is unavailable |

### Buttons (5)

| Entity ID | Name | What it does |
|---|---|---|
| `button.evershelf_refresh` | Refresh | Forces an immediate poll of all sensor data |
| `button.evershelf_refresh_prices` | Refresh Prices | Recomputes shopping list estimated total from price cache — no AI calls |
| `button.evershelf_suggest_recipe` | Suggest Recipe | Asks EverShelf AI for a recipe using items expiring soonest; result arrives as a **persistent notification** in HA |
| `button.evershelf_sync_smart_shopping` | Sync Smart Shopping | Triggers the EverShelf smart shopping AI analysis |
| `button.evershelf_clear_expired` | Clear Expired | Removes expired zero-stock inventory rows from EverShelf |

### Todo entity

`todo.evershelf_shopping_list` — Native HA todo, bidirectional sync.

- **Add** items from the HA interface → they appear in EverShelf (and Bring!, if connected)
- Adding an existing item increases its EverShelf cart quantity when quantity support is available
- **Delete** items → removed from EverShelf
- **Check off** items → removed from the active shopping list

### Calendar entity

`calendar.evershelf_expiry_calendar` — Every product's expiry date is a calendar event.

- Works with the standard HA calendar card and any calendar integration
- Trigger automations on specific expiry dates
- Event title = product name; description includes location and quantity
- Supports arbitrary date ranges — great for a month-ahead food planning view

### Text entity

`text.evershelf_quick_add` — Type a product name to instantly add it to the shopping list.

- Set the value from a Lovelace text card, an automation, or a voice assistant blueprint
- The field clears automatically after each submission
- Ideal for Assist / voice: *"Add eggs"* → set text → item appears on shopping list

---

## Services

### `evershelf.add_to_shopping`

Adds a product to the EverShelf shopping list. If the item already exists, `quantity` increases the cart quantity instead of creating a duplicate row.

```yaml
service: evershelf.add_to_shopping
data:
  name: "Milk"
  quantity: 2      # optional
  unit: "l"        # optional
```

### `evershelf.mark_used`

Reduce one matching inventory row (case-insensitive name match). When supplied,
`unit` must match the item unit in EverShelf. The reduction is applied
atomically to the row's current quantity, so concurrent inventory additions or
consumption are preserved. This service fails closed unless EverShelf advertises
`inventory_decrement_v1` and confirms that a positive quantity was consumed.

```yaml
service: evershelf.mark_used
data:
  name: "Olive Oil"
  quantity: 0.1
  unit: "l"
```

### `evershelf.refresh`

```yaml
service: evershelf.refresh
```

### `evershelf.suggest_recipe`

Ask EverShelf AI for a recipe using the items expiring soonest. The result is delivered as a **persistent notification** in Home Assistant.

```yaml
service: evershelf.suggest_recipe
data:
  location: "frigo"   # optional — focus on fridge, freezer, spice_rack, cabinet, or any location name
```

### `evershelf.refresh_prices`

Recompute the shopping list estimated total from the EverShelf price cache. No AI calls are triggered.

```yaml
service: evershelf.refresh_prices
```

### `evershelf.clear_expired`

Remove expired inventory rows whose quantity is zero.

```yaml
service: evershelf.clear_expired
```

### `evershelf.recipe_query`

Returns response data for either a compact 50-card browse page or a responsive
recommendation set of up to 100 cards. Ranking, filtering, deduplication, and paging
remain inside EverShelf.

```yaml
service: evershelf.recipe_query
data:
  kind: browse
  q: chicken
  sort: availability
  availability_weight: 100
  expiry_weight: 25
  minimum_coverage: 0
  limit: 50
```

Use `kind: recommendations` for the Food & Recipes carousel.

### `evershelf.recipe_hydration`

Starts an idempotent Cookidoo metadata search or polls an existing `search_id`.
The service returns immediately; local results remain available while the
background worker imports new cards.

```yaml
service: evershelf.recipe_hydration
data:
  query: chicken
  locale: en
```

### `evershelf.recipe_detail`

Returns the bounded `recipe_detail_v1` envelope for one positive catalog ID.
Cookidoo instructions remain external-link-only; the service does not retrieve or
reconstruct provider instructions.
Backends without `recipe_detail_v1` receive a structured
`unsupported_capability` response only after a successful recent capability
probe. Transient probe failures return `capability_probe_failed`, while periodic
refreshes detect backend upgrades without reloading the integration.
The backend `grocery` projection and ingredient `display_name`, `source_text`,
and optional `closest_match` fields pass through unchanged. The effective
`detail.capabilities.grocery_add` additionally requires current
`recipe_grocery_v1` support. If detail is available but grocery support is
unsupported or temporarily unavailable, detail still succeeds with
`grocery_add: false` plus bounded `grocery_add_state` and
`grocery_add_reason` annotations.
The same pass-through rule applies to additive ingredient-decision and planner
metadata. Home Assistant may only lower `ingredient_feedback_v2` or `planner`
when the corresponding capability is unsupported or temporarily unavailable.

```yaml
service: evershelf.recipe_detail
data:
  recipe_id: 123
```

### `evershelf.recipe_ingredient_override`

Persists a display-only `have`, `missing`, or `clear` assertion for one
revision-bound ingredient. It does not change inventory, ranking, or backend
grocery eligibility.

### `evershelf.recipe_identity_feedback`

Records an explicit `correct` or `wrong` verdict for the matched inventory
product or closest identity label. Evidence settles before it can be exported
into the Gemini-assisted, human-reviewed ontology proposal workflow; it is
never applied automatically.

### `evershelf.recipe_ingredient_decision`

The new dashboard command boundary submits exactly one atomic action:
`assume_have`, `select_inventory_product`, or `reject_current_match`.
The selected/expected IDs are product-level EverShelf IDs. Home Assistant does
not split availability and identity into separate writes, and it preserves
backend 409 `ingredient_feedback_stale`/idempotency responses. `assume_have`
creates no AI evidence; exact positive/negative evidence is queued
asynchronously by EverShelf and never applies ontology changes automatically.

```yaml
service: evershelf.recipe_ingredient_decision
data:
  recipe_id: 123
  ingredient_key: "ri:2:0123456789abcdef"
  position: 2
  action: select_inventory_product
  selected_product_id: 42
  feedback_token: "<64-character token>"
  idempotency_key: "react-recipe-123-decision-01"
  action_origin: react_dashboard
```

### `evershelf.recipe_planner_add`

Assigns a Cookidoo-origin recipe to an ISO date in the configured Cookidoo
account's My Week planner. React supplies only the EverShelf recipe ID,
revision-bound provider token, date, and idempotency key; EverShelf resolves the
provider external ID. This is an account planner action, not a direct Thermomix
device push. The service is absent effectively unless the backend advertises
the dual-default-off `recipe_planner_v1` capability.

```yaml
service: evershelf.recipe_planner_add
data:
  recipe_id: 123
  date: "2026-08-20"
  provider_action_token: "<64-character token>"
  idempotency_key: "react-recipe-123-planner-01"
```

### `evershelf.recipe_grocery_add`

Calls EverShelf's idempotent grocery mutation first, then mirrors only backend
`added` and `already_listed` outcomes to a user-facing Home Assistant todo list.
Backends without `recipe_grocery_v1` receive a structured
`unsupported_capability` response after a successful recent probe; transient
probe failures return `capability_probe_failed`.
EverShelf's internal shopping list and `todo.shopping_list` remain separate,
intentional destinations. Pending todo names are Unicode-normalized,
case-folded, and deduplicated before one `todo.add_item` call per absent item.
Source amounts may be copied to a supported todo description but are never sent
as numeric quantities.

```yaml
service: evershelf.recipe_grocery_add
data:
  recipe_id: 123
  idempotency_key: "ha-recipe-123-command-01"
  selections:
    - key: "ri:2:0123456789abcdef"
      position: 2
  todo_entity_id: todo.shopping_list
```

The response keeps bounded backend outcomes and adds `ha_mirror.outcomes`.
`summary.backend` reports EverShelf results and `summary.ha_mirror` reports
`added`, `already_present`, `skipped`, and `failed` todo outcomes. Successful
mirror outcomes are retained in Home Assistant storage for about 30 days, with
deterministic count and age limits. A backend replay with the same config entry,
todo entity, and idempotency key therefore does not recreate an item that was
completed or removed after the original command. A new idempotency key is a new
command and may add the item again.

`ha_mirror.replay_persistence` reports whether that replay protection is
`durable`. If Home Assistant storage cannot be loaded or saved, todo processing
still uses pending-list deduplication, but the status is `degraded` with
`durable: false`; `ha_mirror.error` identifies the load or save failure and the
top-level response reports `partial_failure`. Failed loads are retried only
after a cooldown and are never treated as an authoritative empty ledger.

### `evershelf.delete_inventory`

Delete a specific EverShelf inventory row by inventory ID.

```yaml
service: evershelf.delete_inventory
data:
  inventory_id: 123
```

### `evershelf.delete_inventory_item`

Delete one item from a specific EverShelf inventory row. If the row quantity is greater than 1, EverShelf decrements it by 1 instead of deleting the row.

```yaml
service: evershelf.delete_inventory_item
data:
  inventory_id: 123
```

### `evershelf.update_inventory_item`

Update one item from a specific EverShelf inventory row. If the row quantity is greater than 1, EverShelf splits one item into a separate row with the new expiry date.

```yaml
service: evershelf.update_inventory_item
data:
  inventory_id: 123
  expiry_date: "2026-09-30"
```

### `evershelf.resolve_barcode`

Resolve a scanned barcode through EverShelf's product database and external lookup chain. Use `return_response: true` when calling the service from Home Assistant or a frontend client.

```yaml
service: evershelf.resolve_barcode
data:
  barcode: "3017620422003"
```

Example response:

```json
{
  "found": true,
  "source": "openfoodfacts_it",
  "product": {
    "name": "Nutella",
    "brand": "Ferrero"
  }
}
```

### `evershelf.suggest_location`

Return the best storage location without applying dashboard page defaults. Exact
barcode history wins first. In `manual` mode, an exact case-insensitive name
match is checked next. Genuinely unseen products may return an AI suggestion or
`unknown`.

```yaml
service: evershelf.suggest_location
data:
  mode: manual
  name: "Milk"
```

Example response:

```json
{
  "success": true,
  "location": "frigo",
  "source": "history_name",
  "confidence": 1
}
```

### `evershelf.read_expiry_image`

Send an expiry-label photo to EverShelf's OCR/Gemini endpoint and return the parsed date. Provide exactly one of `image`, `image_path`, or `camera_entity_id`. Use `return_response: true` from Developer Tools or a `response_variable` in automations/scripts to read the result.

```yaml
service: evershelf.read_expiry_image
data:
  camera_entity_id: camera.kitchen_tablet
```

Example response:

```json
{
  "success": true,
  "expiry_date": "2026-09-30",
  "raw_text": "EXP 30/09/2026",
  "source": "ocr"
}
```

### `evershelf.add_scanned_item`

Save a scanned product if needed, then add it to EverShelf inventory. EverShelf merges into an unopened inventory row only when the product, location, expiry date, and sealed state match; a fresher package with a different expiry date becomes a separate row. Use `return_response: true` from Developer Tools or a `response_variable` in automations/scripts to read the product and inventory API responses.

```yaml
service: evershelf.add_scanned_item
data:
  name: "Milk"
  barcode: "3017620422003"
  quantity: 1
  location: "frigo"
  expiry_date: "2026-06-30"
  expiry_user_set: true
```

Set `prepared_food: true` for a finished dish that should not be classified by ingredient. EverShelf groups it under the existing prepared meal taxonomy term instead of deriving one, which also skips the AI taxonomy review.

```yaml
service: evershelf.add_scanned_item
data:
  name: "Leftover lasagna"
  quantity: 1
  location: "frigo"
  prepared_food: true
```

Example response:

```json
{
  "success": true,
  "product_id": 42,
  "product": {
    "success": true,
    "id": 42,
    "merged": false
  },
  "inventory": {
    "success": true,
    "new_qty": 1,
    "total_qty": 1,
    "unit": "pz"
  }
}
```

---

## Configuration

### Auto-discovery (Zeroconf/mDNS)

If `avahi-daemon` runs on the EverShelf server, HA detects it automatically and shows a notification.

**Enable mDNS on your EverShelf server:**

```bash
sudo apt-get install -y avahi-daemon
sudo cp /var/www/html/evershelf/docker/avahi-evershelf.xml /etc/avahi/services/evershelf.xml
sudo systemctl restart avahi-daemon
```

### Manual setup

Go to **Settings → Devices & Services → Add Integration → EverShelf** and enter the URL of your EverShelf server, e.g. `http://192.168.1.100`.

### Authentication

Set `SETTINGS_TOKEN` in your EverShelf `.env` file:

```ini
SETTINGS_TOKEN=your-strong-random-string
```

Enter the same value in HA when configuring the integration.
The integration sends it only in the `X-API-Token` request header; credentials
are never placed in EverShelf URLs.
Without a token the integration runs **read-only** — all sensors, the calendar, and the todo entity (read) still work. Write operations need the token.

### Options

After setup click **Configure** on the integration card:

| Option | Default | Description |
|---|---|---|
| Expiry alert threshold | 3 days | Products expiring within N days count as "expiring soon" |
| Update interval | 300 s | How often HA polls EverShelf (60–3600 s) |

---

## Automation examples

### Alert when something expires today

```yaml
automation:
  - alias: "EverShelf — Expiring today alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.evershelf_has_expiring_today
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Use it today!"
          message: >
            {{ state_attr('sensor.evershelf_expiring_today', 'expiring_list')
               | map(attribute='name') | join(', ') }} expire today.
```

### Ask for a recipe every evening

```yaml
automation:
  - alias: "EverShelf — Evening recipe"
    trigger:
      - platform: time
        at: "18:30:00"
    action:
      - service: evershelf.suggest_recipe
        data:
          location: "frigo"
      # The recipe arrives as a persistent notification in HA
```

### Add to shopping via voice / Assist

```yaml
script:
  add_to_evershelf_shopping:
    alias: "Add product to EverShelf"
    fields:
      product_name:
        description: "Product name"
    sequence:
      - service: text.set_value
        target:
          entity_id: text.evershelf_quick_add
        data:
          value: "{{ product_name }}"
```

### Expiry calendar card (Lovelace)

```yaml
type: calendar
entities:
  - calendar.evershelf_expiry_calendar
initial_view: listWeek
title: Pantry Expiry Calendar
```

### Backup overdue notification

```yaml
automation:
  - alias: "EverShelf — Backup overdue"
    trigger:
      - platform: state
        entity_id: binary_sensor.evershelf_backup_overdue
        to: "on"
        for: "00:10:00"
    action:
      - service: notify.persistent_notification
        data:
          title: "EverShelf backup overdue"
          message: "No EverShelf backup in the last 7 days. Check Settings → Backup."
```

### Low stock daily digest

```yaml
automation:
  - alias: "EverShelf — Low stock digest"
    trigger:
      - platform: time
        at: "08:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.evershelf_low_stock_items
        above: 0
    action:
      - service: evershelf.refresh_prices
      - service: notify.mobile_app_your_phone
        data:
          title: "EverShelf — Shopping reminder"
          message: >
            {{ states('sensor.evershelf_low_stock_items') }} item(s) are running low.
            Estimated total: {{ states('sensor.evershelf_shopping_total') }}.
```

---

## Troubleshooting

**Integration not found after install** — Restart Home Assistant.

**Cannot connect**
```bash
curl http://YOUR_EVERSHELF_IP/api/index.php?action=ha_info
# Expected: JSON with {"version":...,"items":...}
```

**Zeroconf not working** — Install `avahi-daemon`, copy the service file, restart avahi. HA and EverShelf must be on the same LAN (mDNS does not cross routers).

**Token error** — `SETTINGS_TOKEN` in EverShelf `.env` must match exactly what you entered in HA.

**Shopping total shows "Unknown"** — Open EverShelf → Shopping List → click **€** to fill the price cache, then press **Refresh Prices** in HA.

**Suggest Recipe times out** — Verify `GEMINI_API_KEY` is set in EverShelf `.env`. The AI call can take up to 30 seconds on first use.

**Calendar shows no events** — Only items with expiry dates set in EverShelf appear in the calendar.

**Write operations fail (403)** — Configure `SETTINGS_TOKEN` in EverShelf `.env` and re-enter it via **Settings → Integrations → EverShelf → Reconfigure**.

---

## Manual installation

1. Download the [latest release](https://github.com/dadaloop82/ha-evershelf/releases/latest)
2. Copy `custom_components/evershelf/` to `<your HA config>/custom_components/`
3. Restart Home Assistant
4. **Settings → Devices & Services → Add Integration → EverShelf**

---

## About EverShelf

EverShelf is a free, open-source, self-hosted pantry manager — no cloud, no subscription, no account required.
👉 [github.com/dadaloop82/EverShelf](https://github.com/dadaloop82/EverShelf)

---

## License

MIT © [dadaloop82](https://github.com/dadaloop82)
