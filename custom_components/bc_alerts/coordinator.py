"""Polling coordinator for BC Alerts."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import (
    CATEGORY_POWER,
    CATEGORY_WATER,
    FEEDS,
    Alert,
    Bounds,
    distance_km,
    fetch_all,
    point_in_polygon,
)
from .const import (
    CONF_EAST,
    CONF_ISLAND_ONLY,
    CONF_NEARBY_KM,
    CONF_NORTH,
    CONF_SOUTH,
    CONF_WEST,
    DEFAULT_ISLAND_ONLY,
    DEFAULT_NEARBY_KM,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type BcAlertsConfigEntry = ConfigEntry[BcAlertsCoordinator]


@dataclass(frozen=True)
class BcAlertsData:
    """The current alerts, closest first."""

    alerts: dict[str, Alert]
    distances: dict[str, float]
    home_outage: Alert | None
    nearby_water: tuple[Alert, ...]
    failed_feeds: dict[str, str]

    def in_category(self, category: str) -> list[Alert]:
        """Return the alerts in a category."""
        return [a for a in self.alerts.values() if a.category == category]


class BcAlertsCoordinator(DataUpdateCoordinator[BcAlertsData]):
    """Polls the feeds and keeps the last good result for any that fail."""

    config_entry: BcAlertsConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BcAlertsConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        settings = {**entry.data, **entry.options}
        self._bounds = Bounds(
            south=settings[CONF_SOUTH],
            west=settings[CONF_WEST],
            north=settings[CONF_NORTH],
            east=settings[CONF_EAST],
            island_only=settings.get(CONF_ISLAND_ONLY, DEFAULT_ISLAND_ONLY),
        )
        self._nearby_km = settings.get(CONF_NEARBY_KM, DEFAULT_NEARBY_KM)
        self._session = async_get_clientsession(hass)
        self._last_good: dict[str, list[Alert]] = {}

    async def _async_update_data(self) -> BcAlertsData:
        """Fetch every feed."""
        fresh, errors = await fetch_all(self._session, self._bounds, dt_util.utcnow())
        if len(errors) == len(FEEDS):
            raise UpdateFailed(f"All feeds failed: {errors}")
        for name, error in errors.items():
            _LOGGER.warning("BC Alerts feed %s failed: %s", name, error)
        self._last_good.update(fresh)

        home_lat = self.hass.config.latitude
        home_lon = self.hass.config.longitude
        distances = {
            alert.id: round(
                distance_km(home_lat, home_lon, alert.latitude, alert.longitude), 1
            )
            for alerts in self._last_good.values()
            for alert in alerts
        }
        alerts = {
            alert.id: alert
            for group in self._last_good.values()
            for alert in sorted(group, key=lambda a: distances[a.id])
        }
        return BcAlertsData(
            alerts=dict(sorted(alerts.items(), key=lambda i: distances[i[0]])),
            distances=distances,
            home_outage=next(
                (
                    alert
                    for alert in alerts.values()
                    if alert.category == CATEGORY_POWER
                    and point_in_polygon(home_lat, home_lon, alert.polygon)
                ),
                None,
            ),
            nearby_water=tuple(
                alert
                for alert in alerts.values()
                if alert.category == CATEGORY_WATER
                and distances[alert.id] <= self._nearby_km
            ),
            failed_feeds=errors,
        )
