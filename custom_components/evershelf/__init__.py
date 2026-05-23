"""EverShelf Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from .const import CONF_TOKEN, CONF_URL, DOMAIN, PLATFORMS
from .coordinator import EverShelfCoordinator

_LOGGER = logging.getLogger(__name__)

_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

# ── Service schemas ────────────────────────────────────────────────────────────

_ADD_TO_SHOPPING_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("quantity"): vol.Coerce(float),
        vol.Optional("unit"): cv.string,
    }
)

_MARK_USED_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
        vol.Optional("unit"): cv.string,
    }
)


# ── Entry setup / teardown ────────────────────────────────────────────────────


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EverShelf from a config entry."""
    coordinator = EverShelfCoordinator(
        hass,
        entry_id=entry.entry_id,
        url=entry.data[CONF_URL],
        token=entry.data.get(CONF_TOKEN, ""),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    # ── Register services (once per HA instance) ──────────────────────────────
    if not hass.services.has_service(DOMAIN, "add_to_shopping"):

        async def _handle_add_to_shopping(call: ServiceCall) -> None:
            _coord = _get_coordinator(hass, call)
            await _coord.async_add_to_shopping(
                name=call.data["name"],
                quantity=call.data.get("quantity"),
                unit=call.data.get("unit"),
            )
            await _coord.async_request_refresh()

        async def _handle_mark_used(call: ServiceCall) -> None:
            _coord = _get_coordinator(hass, call)
            ok = await _coord.async_mark_used(
                name=call.data["name"],
                quantity=float(call.data["quantity"]),
                unit=call.data.get("unit"),
            )
            if not ok:
                raise ServiceValidationError(
                    f"EverShelf: could not find or update item '{call.data['name']}'"
                )
            await _coord.async_request_refresh()

        async def _handle_refresh(call: ServiceCall) -> None:
            _coord = _get_coordinator(hass, call)
            await _coord.async_request_refresh()

        hass.services.async_register(
            DOMAIN, "add_to_shopping", _handle_add_to_shopping, schema=_ADD_TO_SHOPPING_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, "mark_used", _handle_mark_used, schema=_MARK_USED_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, "refresh", _handle_refresh
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an EverShelf config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove services when the last entry is unloaded
    if not hass.data.get(DOMAIN):
        for svc in ("add_to_shopping", "mark_used", "refresh"):
            hass.services.async_remove(DOMAIN, svc)

    return unload_ok


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> EverShelfCoordinator:
    """Return the first available EverShelf coordinator.

    For multi-instance setups the caller may add a 'config_entry_id' field to
    the service call; otherwise the first registered entry is used.
    """
    entries: dict[str, EverShelfCoordinator] = hass.data.get(DOMAIN, {})
    entry_id: str | None = call.data.get("config_entry_id")
    if entry_id:
        coord = entries.get(entry_id)
        if coord is None:
            raise ServiceValidationError(f"EverShelf: unknown config entry '{entry_id}'")
        return coord
    if not entries:
        raise ServiceValidationError("EverShelf: no instances configured")
    return next(iter(entries.values()))
