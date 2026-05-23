"""Text entity for EverShelf — quick-add to shopping list."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import EverShelfCoordinator
from .sensor import evershelf_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EverShelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EverShelfQuickAddText(coordinator, entry)])


class EverShelfQuickAddText(TextEntity, RestoreEntity):
    """Type a product name to add it instantly to the EverShelf shopping list."""

    _attr_has_entity_name = True
    _attr_translation_key = "quick_add"
    _attr_icon = "mdi:cart-plus"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 1
    _attr_native_max = 100
    _attr_native_value = ""

    def __init__(self, coordinator: EverShelfCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_quick_add"
        self._attr_device_info = evershelf_device_info(coordinator, entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_native_value = last.state or ""

    async def async_set_value(self, value: str) -> None:
        """Add the typed product to the shopping list and clear the field."""
        name = value.strip()
        if not name:
            return
        ok = await self._coordinator.async_add_to_shopping(name=name, quantity=None, unit=None)
        if ok:
            _LOGGER.info("EverShelf quick-add: '%s' added to shopping list", name)
            await self._coordinator.async_request_refresh()
        else:
            _LOGGER.warning("EverShelf quick-add: failed to add '%s'", name)
        # Clear the field after sending
        self._attr_native_value = ""
        self.async_write_ha_state()
