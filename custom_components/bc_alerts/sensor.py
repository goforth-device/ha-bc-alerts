"""Alert count sensors for BC Alerts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
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
)
from .const import CONF_EAST, CONF_NORTH, CONF_SOUTH, CONF_WEST
from .coordinator import BcAlertsConfigEntry, BcAlertsCoordinator
from .entity import alert_attributes, device_info
from .ferries import CATEGORY_FERRY
from .map_feed import map_feed_attributes

MAX_LISTED_ALERTS = 25


@dataclass(frozen=True, kw_only=True)
class BcAlertSensorDescription(SensorEntityDescription):
    """Describes a count of alerts in one category."""

    category: str


SENSORS = (
    BcAlertSensorDescription(
        key="power_outages",
        name="Power outages",
        icon="mdi:transmission-tower-off",
        category=CATEGORY_POWER,
    ),
    BcAlertSensorDescription(
        key="road_closures",
        name="Road closures",
        icon="mdi:road-variant",
        category=CATEGORY_ROAD_CLOSURE,
    ),
    BcAlertSensorDescription(
        key="road_incidents",
        name="Road incidents",
        icon="mdi:car-emergency",
        category=CATEGORY_ROAD,
    ),
    BcAlertSensorDescription(
        key="water_notices",
        name="Water notices",
        icon="mdi:water-alert",
        category=CATEGORY_WATER,
    ),
    BcAlertSensorDescription(
        key="emergencies",
        name="Emergencies",
        icon="mdi:alert-octagon",
        category=CATEGORY_EMERGENCY,
    ),
    BcAlertSensorDescription(
        key="weather_alerts",
        name="Weather alerts",
        icon="mdi:weather-lightning-rainy",
        category=CATEGORY_WEATHER,
    ),
    BcAlertSensorDescription(
        key="air_quality",
        name="Air quality",
        icon="mdi:smog",
        category=CATEGORY_AIR,
    ),
    BcAlertSensorDescription(
        key="community_notices",
        name="Community notices",
        icon="mdi:bullhorn",
        category=CATEGORY_COMMUNITY,
    ),
    BcAlertSensorDescription(
        key="ferries",
        name="Ferries",
        icon="mdi:ferry",
        category=CATEGORY_FERRY,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BcAlertsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(BcAlertCountSensor(coordinator, description) for description in SENSORS),
            BcAlertMapFeedSensor(coordinator),
        ]
    )


class BcAlertCountSensor(CoordinatorEntity[BcAlertsCoordinator], SensorEntity):
    """The number of alerts in a category, listed closest first."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset(
        {"alerts", "swartz_bay_to_tsawwassen", "tsawwassen_to_swartz_bay"}
    )
    entity_description: BcAlertSensorDescription

    def __init__(
        self,
        coordinator: BcAlertsCoordinator,
        description: BcAlertSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> int:
        """Return the number of alerts."""
        data = self.coordinator.data
        return len(data.in_category(self.entity_description.category))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the closest alerts."""
        data = self.coordinator.data
        alerts = data.in_category(self.entity_description.category)
        attributes: dict[str, Any] = {
            "alerts": [
                alert_attributes(alert, data.distances[alert.id])
                for alert in alerts[:MAX_LISTED_ALERTS]
            ]
        }
        if self.entity_description.category == CATEGORY_FERRY:
            attributes.update(data.ferry_sailings)
        if self.entity_description.category == CATEGORY_POWER:
            attributes["customers_out"] = sum(
                alert.extra.get("customers_out", 0) for alert in alerts
            )
        return attributes


class BcAlertMapFeedSensor(CoordinatorEntity[BcAlertsCoordinator], SensorEntity):
    """Every alert in the Map Feed format, for maps whose pins open the alert."""

    _attr_has_entity_name = True
    _attr_name = "Map feed"
    _attr_icon = "mdi:map-marker-alert"
    _unrecorded_attributes = frozenset(
        {"geojson", "legend", "area", "attribution", "feed_type", "map_feed_version"}
    )

    def __init__(self, coordinator: BcAlertsCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_map_feed"
        self._attr_device_info = device_info(entry)
        settings = {**entry.data, **entry.options}
        self._bbox = (
            settings[CONF_SOUTH],
            settings[CONF_WEST],
            settings[CONF_NORTH],
            settings[CONF_EAST],
        )

    @property
    def native_value(self) -> int:
        """Return the number of alerts on the map."""
        return len(self.coordinator.data.alerts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the alerts as a map feed."""
        data = self.coordinator.data
        return map_feed_attributes(list(data.alerts.values()), data.distances, self._bbox)
