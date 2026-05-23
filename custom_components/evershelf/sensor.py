"""Sensor platform for EverShelf."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
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
    # If True, the sensor is only available when price tracking is enabled
    requires_price: bool = False


SENSOR_DESCRIPTIONS: tuple[EverShelfSensorDescription, ...] = (
    EverShelfSensorDescription(
        key="expiring_soon",
        translation_key="expiring_soon",
        icon="mdi:food-apple-outline",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="expiring_soon",
        extra_attr_keys=("expiring_list", "next_expiry_name", "next_expiry_date", "last_updated"),
    ),
    EverShelfSensorDescription(
        key="expiring_today",
        translation_key="expiring_today",
        icon="mdi:food-alert",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="expiring_today",
        extra_attr_keys=("next_expiry_name", "next_expiry_date"),
    ),
    EverShelfSensorDescription(
        key="expiring_3d",
        translation_key="expiring_3d",
        icon="mdi:food-clock",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="expiring_3d",
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
        key="opened_items",
        translation_key="opened_items",
        icon="mdi:fridge-outline",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="opened_items",
    ),
    EverShelfSensorDescription(
        key="shopping_items",
        translation_key="shopping_items",
        icon="mdi:cart",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="shopping_items",
    ),
    EverShelfSensorDescription(
        key="shopping_total",
        translation_key="shopping_total",
        icon="mdi:cart-percent",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="shopping_total",
        requires_price=True,
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
    def native_unit_of_measurement(self) -> str | None:
        """Return currency from data for monetary sensor, otherwise use description value."""
        if self.entity_description.device_class == SensorDeviceClass.MONETARY:
            return self.coordinator.data.get("price_currency", "EUR")
        return self.entity_description.native_unit_of_measurement

    @property
    def available(self) -> bool:
        """Monetary sensor only available when price tracking is enabled."""
        if not super().available:
            return False
        if self.entity_description.requires_price:
            return bool(self.coordinator.data.get("price_tracking_enabled", False))
        return True

    @property
    def native_value(self) -> int | float | None:
        return self.coordinator.data.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {k: data.get(k) for k in self.entity_description.extra_attr_keys if k in data}
