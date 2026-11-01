"""Map pins for BC Alerts."""

from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    CATEGORY_AIR,
    CATEGORY_COMMUNITY,
    CATEGORY_EMERGENCY,
    CATEGORY_POWER,
    CATEGORY_ROAD,
    CATEGORY_ROAD_CLOSURE,
    CATEGORY_WATER,
    CATEGORY_WEATHER,
    Alert,
)
from .const import DOMAIN, IMAGES_URL
from .coordinator import BcAlertsConfigEntry, BcAlertsCoordinator
from .entity import alert_attributes

CATEGORY_LABELS = {
    CATEGORY_POWER: "Power",
    CATEGORY_ROAD_CLOSURE: "Road closed",
    CATEGORY_ROAD: "Road",
    CATEGORY_WATER: "Water",
    CATEGORY_EMERGENCY: "Emergency",
    CATEGORY_WEATHER: "Weather",
    CATEGORY_AIR: "Air",
    CATEGORY_COMMUNITY: "Notice",
}

CATEGORY_ICONS = {
    CATEGORY_POWER: "mdi:transmission-tower-off",
    CATEGORY_ROAD_CLOSURE: "mdi:road-variant",
    CATEGORY_ROAD: "mdi:car-emergency",
    CATEGORY_WATER: "mdi:water-alert",
    CATEGORY_EMERGENCY: "mdi:alert-octagon",
    CATEGORY_WEATHER: "mdi:weather-lightning-rainy",
    CATEGORY_AIR: "mdi:smog",
    CATEGORY_COMMUNITY: "mdi:bullhorn",
}

CATEGORY_IMAGES = {
    CATEGORY_POWER: "power.svg",
    CATEGORY_ROAD_CLOSURE: "road_closed.svg",
    CATEGORY_ROAD: "road_incident.svg",
    CATEGORY_WATER: "water.svg",
    CATEGORY_EMERGENCY: "emergency.svg",
    CATEGORY_WEATHER: "weather.svg",
    CATEGORY_AIR: "air_quality.svg",
    CATEGORY_COMMUNITY: "notice.svg",
}


def pin_image(alert: Alert) -> str:
    """Return the URL of the picture for an alert's pin."""
    if alert.extra.get("event_type") == "CONSTRUCTION" and (
        alert.category == CATEGORY_ROAD
    ):
        return f"{IMAGES_URL}/road_work.svg"
    return f"{IMAGES_URL}/{CATEGORY_IMAGES[alert.category]}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BcAlertsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Keep one pin per alert, adding and removing them as alerts change."""
    coordinator = entry.runtime_data
    pins: dict[str, BcAlertPin] = {}

    @callback
    def sync_pins() -> None:
        """Match the pins to the current alerts."""
        current = coordinator.data.alerts
        for alert_id in pins.keys() - current.keys():
            hass.async_create_task(pins.pop(alert_id).async_remove())
        new_pins = [
            BcAlertPin(coordinator, alert)
            for alert_id, alert in current.items()
            if alert_id not in pins
        ]
        pins.update({pin.alert.id: pin for pin in new_pins})
        if new_pins:
            async_add_entities(new_pins)

    entry.async_on_unload(coordinator.async_add_listener(sync_pins))
    sync_pins()


class BcAlertPin(CoordinatorEntity[BcAlertsCoordinator], GeolocationEvent):
    """One alert on the map.

    Pins have no unique ID so that short-lived alerts don't fill up the entity
    registry. The map card finds them through their source.
    """

    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator: BcAlertsCoordinator, alert: Alert) -> None:
        """Initialize the pin."""
        super().__init__(coordinator)
        self.alert = alert
        self._attr_name = f"{CATEGORY_LABELS[alert.category]}: {alert.title}"
        self._attr_icon = CATEGORY_ICONS[alert.category]
        self._attr_entity_picture = pin_image(alert)
        self._attr_latitude = alert.latitude
        self._attr_longitude = alert.longitude
        self._attr_distance = coordinator.data.distances[alert.id]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the pin, unless its alert has just ended."""
        alert = self.coordinator.data.alerts.get(self.alert.id)
        if alert is None:
            return
        self.alert = alert
        self._attr_latitude = alert.latitude
        self._attr_longitude = alert.longitude
        self._attr_distance = self.coordinator.data.distances[alert.id]
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the alert's details."""
        attributes = alert_attributes(self.alert, self._attr_distance)
        attributes["feed"] = attributes.pop("source")
        return {"category": self.alert.category, **attributes}
