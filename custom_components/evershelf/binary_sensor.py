"""EverShelf binary sensor platform."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EverShelfCoordinator


@dataclass(frozen=True, kw_only=True)
class EverShelfBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an EverShelf binary sensor."""

    data_key: str = ""
    threshold: int = 0  # is_on when data_key value > threshold


BINARY_SENSOR_DESCRIPTIONS: tuple[EverShelfBinarySensorDescription, ...] = (
    EverShelfBinarySensorDescription(
        key="has_expired_items",
        data_key="expired_items",
        translation_key="has_expired_items",
        icon="mdi:food-off",
        device_class=BinarySensorDeviceClass.PROBLEM,
        threshold=0,
    ),
    EverShelfBinarySensorDescription(
        key="has_expiring_items",
        data_key="expiring_soon",
        translation_key="has_expiring_items",
        icon="mdi:food-apple-outline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        threshold=0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EverShelf binary sensor entities."""
    coordinator: EverShelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EverShelfBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class EverShelfBinarySensor(CoordinatorEntity[EverShelfCoordinator], BinarySensorEntity):
    """A binary sensor that turns ON when a pantry problem is detected."""

    _attr_has_entity_name = True
    entity_description: EverShelfBinarySensorDescription

    def __init__(
        self,
        coordinator: EverShelfCoordinator,
        description: EverShelfBinarySensorDescription,
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
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        val = self.coordinator.data.get(self.entity_description.data_key, 0)
        return (val or 0) > self.entity_description.threshold
