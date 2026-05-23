"""EverShelf sensor platform."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EverShelfCoordinator


@dataclass(frozen=True, kw_only=True)
class EverShelfSensorDescription(SensorEntityDescription):
    """Describes an EverShelf sensor."""

    data_key: str = ""
    extra_attrs: tuple[str, ...] = field(default_factory=tuple)


SENSOR_DESCRIPTIONS: tuple[EverShelfSensorDescription, ...] = (
    EverShelfSensorDescription(
        key="expiring_soon",
        data_key="expiring_soon",
        translation_key="expiring_soon",
        icon="mdi:food-apple-outline",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        extra_attrs=("expiring_list", "last_updated"),
    ),
    EverShelfSensorDescription(
        key="expired_items",
        data_key="expired_items",
        translation_key="expired_items",
        icon="mdi:food-off",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    EverShelfSensorDescription(
        key="shopping_items",
        data_key="shopping_items",
        translation_key="shopping_items",
        icon="mdi:cart-outline",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    EverShelfSensorDescription(
        key="total_items",
        data_key="total_items",
        translation_key="total_items",
        icon="mdi:fridge-outline",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EverShelf sensor entities."""
    coordinator: EverShelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EverShelfSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class EverShelfSensor(CoordinatorEntity[EverShelfCoordinator], SensorEntity):
    """Representation of an EverShelf sensor."""

    _attr_has_entity_name = True
    entity_description: EverShelfSensorDescription

    def __init__(
        self,
        coordinator: EverShelfCoordinator,
        description: EverShelfSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry_id)},
            name="EverShelf",
            manufacturer="EverShelf",
            model="Pantry Manager",
            configuration_url=coordinator.url,
        )

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self.entity_description.data_key)
        return int(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return {
            k: self.coordinator.data[k]
            for k in self.entity_description.extra_attrs
            if k in self.coordinator.data
        }
