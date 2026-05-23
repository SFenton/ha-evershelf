"""Sensor platform for EverShelf."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EverShelfCoordinator


@dataclass(frozen=True, kw_only=True)
class EverShelfSensorDescription(SensorEntityDescription):
    """Extended sensor description for EverShelf."""

    data_key: str = ""
    extra_attr_keys: tuple[str, ...] = ()


SENSOR_DESCRIPTIONS: tuple[EverShelfSensorDescription, ...] = (
    EverShelfSensorDescription(
        key="expiring_soon",
        translation_key="expiring_soon",
        icon="mdi:food-apple-outline",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="expiring_soon",
        extra_attr_keys=("expiring_list", "last_updated"),
    ),
    EverShelfSensorDescription(
        key="expired_items",
        translation_key="expired_items",
        icon="mdi:food-off",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="expired_items",
    ),
    EverShelfSensorDescription(
        key="total_items",
        translation_key="total_items",
        icon="mdi:fridge",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="total_items",
    ),
    EverShelfSensorDescription(
        key="shopping_items",
        translation_key="shopping_items",
        icon="mdi:cart",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="shopping_items",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EverShelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EverShelfSensor(coordinator, entry, desc) for desc in SENSOR_DESCRIPTIONS
    )


def evershelf_device_info(
    coordinator: EverShelfCoordinator, entry: ConfigEntry
) -> DeviceInfo:
    """Shared device info for all EverShelf entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="EverShelf",
        model="Pantry Manager",
        configuration_url=coordinator.url,
    )


class EverShelfSensor(CoordinatorEntity[EverShelfCoordinator], SensorEntity):
    """An EverShelf inventory/shopping sensor."""

    entity_description: EverShelfSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EverShelfCoordinator,
        entry: ConfigEntry,
        description: EverShelfSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = evershelf_device_info(coordinator, entry)

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {k: data.get(k) for k in self.entity_description.extra_attr_keys if k in data}
