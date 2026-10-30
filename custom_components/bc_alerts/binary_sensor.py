"""Yes/no sensors for BC Alerts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import BcAlertsConfigEntry, BcAlertsCoordinator, BcAlertsData
from .entity import alert_attributes, device_info


def _home_outage_attributes(data: BcAlertsData) -> dict[str, Any]:
    """Describe the outage covering home."""
    outage = data.home_outage
    return alert_attributes(outage, data.distances[outage.id]) if outage else {}


def _nearby_water_attributes(data: BcAlertsData) -> dict[str, Any]:
    """List the water notices near home."""
    return {
        "alerts": [
            alert_attributes(alert, data.distances[alert.id])
            for alert in data.nearby_water
        ]
    }


@dataclass(frozen=True, kw_only=True)
class BcAlertBinaryDescription(BinarySensorEntityDescription):
    """Describes a yes/no sensor."""

    is_on_fn: Callable[[BcAlertsData], bool]
    attributes_fn: Callable[[BcAlertsData], dict[str, Any]]


BINARY_SENSORS = (
    BcAlertBinaryDescription(
        key="outage_at_home",
        name="Outage at home",
        icon="mdi:home-lightning-bolt",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.home_outage is not None,
        attributes_fn=_home_outage_attributes,
    ),
    BcAlertBinaryDescription(
        key="water_notice_nearby",
        name="Water notice nearby",
        icon="mdi:water-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: bool(data.nearby_water),
        attributes_fn=_nearby_water_attributes,
    ),
    BcAlertBinaryDescription(
        key="feed_problem",
        name="Feed problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda data: bool(data.failed_feeds),
        attributes_fn=lambda data: {"failed_feeds": data.failed_feeds},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BcAlertsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    async_add_entities(
        BcAlertBinarySensor(entry.runtime_data, description)
        for description in BINARY_SENSORS
    )


class BcAlertBinarySensor(CoordinatorEntity[BcAlertsCoordinator], BinarySensorEntity):
    """A yes/no summary of the current alerts."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"alerts"})
    entity_description: BcAlertBinaryDescription

    def __init__(
        self,
        coordinator: BcAlertsCoordinator,
        description: BcAlertBinaryDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        """Return True if the condition is met."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the alerts behind the state."""
        return self.entity_description.attributes_fn(self.coordinator.data)
