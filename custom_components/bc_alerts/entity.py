"""Shared entity helpers for BC Alerts."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .api import Alert
from .const import DOMAIN
from .coordinator import BcAlertsConfigEntry


def device_info(entry: BcAlertsConfigEntry) -> DeviceInfo:
    """Return the service device every sensor belongs to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="BC Alerts",
        entry_type=DeviceEntryType.SERVICE,
    )


def alert_attributes(alert: Alert, distance: float) -> dict[str, Any]:
    """Return an alert as plain attributes."""
    return {
        "title": alert.title,
        "detail": alert.detail,
        "source": alert.source,
        "distance_km": distance,
        "updated": alert.updated,
        "url": alert.url,
        **alert.extra,
    }
