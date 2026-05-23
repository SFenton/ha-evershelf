# EverShelf — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/dadaloop82/ha-evershelf)](https://github.com/dadaloop82/ha-evershelf/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A custom [Home Assistant](https://www.home-assistant.io/) integration for [EverShelf](https://github.com/dadaloop82/EverShelf) — a self-hosted pantry manager.

Monitor your pantry status, detect expired products, track your shopping list and automate notifications — all from Home Assistant.

---

## Features

- **4 sensors** — expiring soon, expired items, shopping list count, total pantry items
- **2 binary sensors** — `problem` class, turn ON when expired / expiring items exist
- **3 services** — add to shopping list, mark item as used, force refresh
- **UI Config Flow** — set up from HA Settings, no YAML required
- **5 languages** — English, Italian, German, French, Spanish

---

## Requirements

- Home Assistant 2023.9 or newer
- A running [EverShelf](https://github.com/dadaloop82/EverShelf) instance (Docker or bare-metal)  
  Minimum EverShelf version: **1.10.0** (requires the `ha_sensor` API endpoint)

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/dadaloop82/ha-evershelf` — category **Integration**
3. Search for **EverShelf** and click **Download**
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/evershelf/` folder into your HA `custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **EverShelf**
3. Enter:
   - **EverShelf URL** — e.g. `http://192.168.1.100` (no trailing slash)
   - **Access Token** *(optional)* — the value of `SETTINGS_TOKEN` in your EverShelf `.env` file
4. Click **Submit**

---

## Entities

After setup, the following entities are created under a single **EverShelf** device:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.evershelf_expiring_soon` | Sensor | Items expiring within the configured alert window |
| `sensor.evershelf_expired_items` | Sensor | Items past their expiry date |
| `sensor.evershelf_shopping_list` | Sensor | Number of items on the shopping list |
| `sensor.evershelf_total_items` | Sensor | Total items in the pantry |
| `binary_sensor.evershelf_has_expired_items` | Binary Sensor | `ON` when any item is expired |
| `binary_sensor.evershelf_has_expiring_items` | Binary Sensor | `ON` when any item is expiring soon |

The `sensor.evershelf_expiring_soon` entity also exposes an `expiring_list` attribute containing the names of items that will expire soon.

Data is refreshed every **5 minutes** by default.

---

## Services

### `evershelf.add_to_shopping`

Add a product to the EverShelf shopping list.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Product name |
| `quantity` | float | No | Quantity to add |
| `unit` | string | No | Unit, e.g. `pz`, `kg`, `l` |

**Example automation:**
```yaml
action: evershelf.add_to_shopping
data:
  name: Milk
  quantity: 2
  unit: l
```

### `evershelf.mark_used`

Reduce the stock of an inventory item (case-insensitive name match).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Item name |
| `quantity` | float | Yes | Amount to subtract |
| `unit` | string | No | Unit (informational) |

**Example automation:**
```yaml
action: evershelf.mark_used
data:
  name: Olive Oil
  quantity: 0.1
  unit: l
```

### `evershelf.refresh`

Force an immediate data refresh.

```yaml
action: evershelf.refresh
```

---

## Automation Examples

### Notify when something is expired

```yaml
automation:
  alias: "EverShelf — Expired item alert"
  trigger:
    - platform: state
      entity_id: binary_sensor.evershelf_has_expired_items
      to: "on"
  action:
    - action: notify.mobile_app_your_phone
      data:
        title: "Pantry Alert"
        message: >
          {{ states('sensor.evershelf_expired_items') }} item(s) have expired in your pantry!
```

### Auto-add to shopping when a sensor exceeds a threshold

```yaml
automation:
  alias: "EverShelf — Low stock auto-add"
  trigger:
    - platform: numeric_state
      entity_id: sensor.evershelf_total_items
      below: 10
  action:
    - action: evershelf.add_to_shopping
      data:
        name: Restock reminder
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Unable to connect" during setup | Check that the EverShelf URL is reachable from HA (same network or reverse proxy) |
| Entities unavailable | HA cannot reach EverShelf; check firewall and Docker port binding |
| `invalid_auth` error | Add `SETTINGS_TOKEN=` to your EverShelf `.env` and use the same value as Access Token |
| Sensors always show 0 | EverShelf version too old; upgrade to 1.10.0+ to get the `ha_sensor` endpoint |

---

## Contributing

Pull requests are welcome. Please follow the [EverShelf contributing guidelines](https://github.com/dadaloop82/EverShelf/blob/main/CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).
