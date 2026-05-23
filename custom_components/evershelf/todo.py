"""Todo list entity for EverShelf shopping list."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
    async_add_entities([EverShelfShoppingList(coordinator, entry)])


class EverShelfShoppingList(CoordinatorEntity[EverShelfCoordinator], TodoListEntity):
    """EverShelf shopping list as a Home Assistant todo entity.

    Supports creating, deleting, and completing items.
    Completing an item removes it from the EverShelf shopping list.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_icon = "mdi:cart"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(
        self, coordinator: EverShelfCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_shopping_list"
        self._attr_device_info = evershelf_device_info(coordinator, entry)

    @property
    def todo_items(self) -> list[TodoItem]:
        items: list[dict[str, Any]] = self.coordinator.data.get("shopping_list", [])
        return [
            TodoItem(
                uid=str(item.get("id") or item.get("name", "")),
                summary=item.get("name", ""),
                status=TodoItemStatus.NEEDS_ACTION,
                description=item.get("note") or None,
            )
            for item in items
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a new item to the EverShelf shopping list."""
        await self.coordinator.async_add_to_shopping(item.summary, None, None)
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove items from the EverShelf shopping list."""
        for uid in uids:
            await self.coordinator.async_remove_from_shopping(uid)
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Handle item status change — completed = remove from shopping list."""
        if item.status == TodoItemStatus.COMPLETE:
            await self.coordinator.async_remove_from_shopping(item.uid)
            await self.coordinator.async_request_refresh()
