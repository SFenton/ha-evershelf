# EverShelf for Home Assistant

[![HACS Integration](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/dadaloop82/ha-evershelf)](https://github.com/dadaloop82/ha-evershelf/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Integrate your self-hosted [EverShelf](https://github.com/dadaloop82/EverShelf) pantry manager with Home Assistant.

Auto-discover via Zeroconf/mDNS, track expiry dates, sync your shopping list as a native todo entity, and trigger automations when products expire.

---

## Features

| Feature | Description |
|---|---|
| **Auto-discovery** | Detected automatically via Zeroconf/mDNS when `avahi-daemon` runs on the EverShelf host |
| **4 Sensors** | Expiring soon, Expired items, Total items, Shopping list count |
| **2 Binary Sensors** | Problem indicators: has expired / has expiring items |
| **Todo entity** | EverShelf shopping list as a native HA todo — add, delete, check off items |
| **Refresh button** | Force an immediate data sync |
| **3 Services** | `add_to_shopping`, `mark_used`, `refresh` |
| **5 languages** | English, Italian, German, French, Spanish |
| **Read-only mode** | Works without a token — sensors update every 5 min |
| **Write mode** | Optional `SETTINGS_TOKEN` for full bidirectional sync |

---

## Installation

### Via HACS (recommended)

1. Open **HACS** → **Integrations** → click the **⋮** menu → **Custom repositories**
2. Add `https://github.com/dadaloop82/ha-evershelf` with category **Integration**
3. Find **EverShelf** and click **Download**
4. Restart Home Assistant
5. Go to **Settings** → **Devices & Services** → **Add Integration** → search **EverShelf**

### Manual

1. Copy the `custom_components/evershelf/` folder to your HA config directory
2. Restart Home Assistant
3. Add the integration via the UI

---

## Configuration

### Auto-discovery (Zeroconf/mDNS)

If your EverShelf server runs `avahi-daemon`, Home Assistant will detect it automatically.  
A notification will appear in the HA UI — just confirm the device and optionally enter your token.

**To enable mDNS broadcasting on your EverShelf server:**

```bash
# Install avahi-daemon (Debian/Ubuntu)
sudo apt-get install -y avahi-daemon

# Copy the service file (included with EverShelf)
sudo cp /var/www/html/evershelf/docker/avahi-evershelf.xml /etc/avahi/services/evershelf.xml
sudo systemctl restart avahi-daemon
```

Or, when the EverShelf cron job runs, it will automatically try to register the service file if avahi-daemon is detected.

### Manual setup

If auto-discovery is not available, go to:  
**Settings** → **Devices & Services** → **Add Integration** → **EverShelf**

Enter the URL of your EverShelf server, e.g. `http://192.168.1.100` or `http://evershelf.local`.

### Authentication (optional)

Set `SETTINGS_TOKEN` in your EverShelf `.env` file to protect write operations.  
Enter the same token during HA setup to enable:
- Adding items to the shopping list via the todo entity
- Marking inventory items as used via the `mark_used` service

Without a token, the integration runs in **read-only mode** — all sensors still update normally.

### Options

After setup, click **Configure** on the integration card to adjust:

| Option | Default | Description |
|---|---|---|
| Expiry alert threshold | 3 days | Products expiring within N days count as "expiring soon" |
| Update interval | 300 s | How often to poll EverShelf (60–3600 s) |

---

## Entities

### Sensors

| Entity | Description | Attributes |
|---|---|---|
| `sensor.evershelf_expiring_soon` | Count of products expiring within threshold | `expiring_list`, `last_updated` |
| `sensor.evershelf_expired_items` | Count of expired products | — |
| `sensor.evershelf_total_items` | Total products in pantry | — |
| `sensor.evershelf_shopping_items` | Number of items on shopping list | — |

### Binary Sensors

| Entity | Device class | On when |
|---|---|---|
| `binary_sensor.evershelf_has_expired_items` | `problem` | Any product is expired |
| `binary_sensor.evershelf_has_expiring_items` | `problem` | Any product expires within threshold |

### Todo entity

`todo.evershelf_shopping_list` — bidirectional sync with the EverShelf shopping list.

- **Add** items from the HA todo interface → they appear in EverShelf
- **Delete** items from the HA todo interface → removed from EverShelf
- **Check off** items in HA → removed from EverShelf shopping list

### Button

`button.evershelf_refresh` — force an immediate data refresh.

---

## Services

### `evershelf.add_to_shopping`

Add a product to the EverShelf shopping list.

```yaml
service: evershelf.add_to_shopping
data:
  name: "Milk"
  quantity: 2      # optional
  unit: "l"        # optional
```

### `evershelf.mark_used`

Reduce the stock of an inventory item (finds by name, case-insensitive).

```yaml
service: evershelf.mark_used
data:
  name: "Olive Oil"
  quantity: 0.1
  unit: "l"
```

### `evershelf.refresh`

Force an immediate data refresh.

```yaml
service: evershelf.refresh
```

---

## Automation examples

### Announce expiring products via TTS

```yaml
automation:
  - alias: "EverShelf — Expiry announcement"
    trigger:
      - platform: state
        entity_id: binary_sensor.evershelf_has_expiring_items
        to: "on"
    action:
      - service: tts.speak
        data:
          media_player_entity_id: media_player.living_room
          message: >
            Attention: {{ states('sensor.evershelf_expiring_soon') }} product(s)
            are expiring soon in your pantry.
```

### Send a notification when products expire

```yaml
automation:
  - alias: "EverShelf — Expired items alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.evershelf_has_expired_items
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "EverShelf — Expired products"
          message: >
            {{ states('sensor.evershelf_expired_items') }} expired product(s)
            in your pantry. Check EverShelf.
```

### Auto-add to shopping list when stock is low

Set up a webhook in EverShelf (`HA_WEBHOOK_ID` in `.env`) to receive `stock_update` events, then create an automation that calls `evershelf.add_to_shopping` when a webhook arrives with low stock data.

---

## Requirements

- **Home Assistant** 2024.1.0 or newer
- **EverShelf** 1.7.0 or newer (self-hosted)
- Network connectivity between HA and EverShelf server

---

## Troubleshooting

**Integration not found after install**  
Restart Home Assistant.

**Cannot connect**  
- Make sure EverShelf is accessible from the HA host: `curl http://YOUR_IP/api/index.php?action=ha_info`
- Check firewall rules

**Zeroconf not working**  
- Install `avahi-daemon` on the EverShelf host
- Copy `docker/avahi-evershelf.xml` to `/etc/avahi/services/`
- Restart avahi: `sudo systemctl restart avahi-daemon`
- HA and EverShelf must be on the same local network (mDNS doesn't cross routers)

**Token error**  
Make sure `SETTINGS_TOKEN` in your EverShelf `.env` matches what you entered in HA.

**Todo items not syncing**  
Write operations require a valid `SETTINGS_TOKEN`. Configure it in EverShelf `.env` and re-add the integration with the token.

---

## EverShelf project

EverShelf is an open-source, self-hosted pantry manager.  
👉 [github.com/dadaloop82/EverShelf](https://github.com/dadaloop82/EverShelf)

---

## License

MIT © [dadaloop82](https://github.com/dadaloop82)
