"""BC Alerts: outages, road closures, water notices and emergencies in BC."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import BcAlertsConfigEntry, BcAlertsCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.GEO_LOCATION, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: BcAlertsConfigEntry) -> bool:
    """Set up BC Alerts from a config entry."""
    coordinator = BcAlertsCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BcAlertsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
