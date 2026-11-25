"""The alerts as a map feed, for cards that read the Map Feed format.

The format is described at
https://github.com/jesmak/map-feed-card/blob/main/docs/map-feed-format.md.
Tapping an alert on such a map opens its text and a link to the alert's page,
which the stock map card can't do.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
from .ferries import CATEGORY_FERRY
from .geo_location import CATEGORY_LABELS

MAP_FEED_VERSION = 1
ATTRIBUTION = (
    "BC Hydro, DriveBC, Alertable, EmergencyInfoBC, Environment Canada, "
    "UVic, BC Ferries"
)

# The colours of the pins' own pictures, so the two maps look alike.
CATEGORY_COLORS = {
    CATEGORY_POWER: "#facc15",
    CATEGORY_ROAD_CLOSURE: "#dc2626",
    CATEGORY_ROAD: "#f97316",
    CATEGORY_WATER: "#0284c7",
    CATEGORY_EMERGENCY: "#991b1b",
    CATEGORY_WEATHER: "#475569",
    CATEGORY_AIR: "#92702a",
    CATEGORY_COMMUNITY: "#0f766e",
    CATEGORY_FERRY: "#1d4ed8",
}
ROAD_WORK_COLOR = "#ca8a04"
FERRY_COLORS = {
    "cancelled": "#dc2626",
    "cancellation": "#dc2626",
    "wait": "#d97706",
}

# Map Feed kinds pick the marker's symbol. Anything without a close match is
# "other", which the card draws as a dot in the alert's colour.
CATEGORY_KINDS = {
    CATEGORY_ROAD_CLOSURE: "road.accident",
    CATEGORY_ROAD: "road.announcement",
    CATEGORY_WEATHER: "weather.warning",
    CATEGORY_FERRY: "ferry",
}

# Extra fields worth showing as rows, with their labels.
DETAIL_ROWS = (
    ("issued_by", "Issued by"),
    ("area", "Area"),
    ("areas", "Areas"),
    ("severity", "Severity"),
    ("status", "Status"),
    ("cause", "Cause"),
    ("customers_out", "Customers out"),
    ("crew_status", "Crew"),
    ("power_off_since", "Off since"),
    ("estimated_restoration", "Estimated restoration"),
    ("alert_type", "Type"),
    ("expires", "Expires"),
)


def _text(value: Any) -> str | int | float | None:
    """Return a value as something a details row can show, or None to skip it."""
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _kind(alert: Alert) -> str:
    """Return the Map Feed kind for an alert."""
    if alert.category == CATEGORY_ROAD and alert.extra.get("event_type") == "CONSTRUCTION":
        return "road.roadwork"
    return CATEGORY_KINDS.get(alert.category, "other")


def _color(alert: Alert) -> str:
    """Return the marker colour for an alert."""
    if alert.category == CATEGORY_ROAD and alert.extra.get("event_type") == "CONSTRUCTION":
        return ROAD_WORK_COLOR
    if alert.category == CATEGORY_FERRY and alert.extra.get("kind") in FERRY_COLORS:
        return FERRY_COLORS[alert.extra["kind"]]
    return CATEGORY_COLORS[alert.category]


def alert_feature(alert: Alert, distance: float) -> dict[str, Any]:
    """Return one alert as a Map Feed item."""
    label = CATEGORY_LABELS[alert.category]
    properties: dict[str, Any] = {
        "name": alert.title,
        "kind": _kind(alert),
        "color": _color(alert),
        "subtitle": f"{label} · {alert.source} · {distance:g} km away",
        "stationary": True,
        "list": {"title": alert.title, "text": label, "value": f"{distance:g} km"},
    }
    if alert.updated is not None:
        properties["updated"] = alert.updated.isoformat()
    rows = [
        {"label": name, "value": value}
        for key, name in DETAIL_ROWS
        if (value := _text(alert.extra.get(key))) is not None
    ]
    if rows:
        properties["details"] = rows
    if alert.detail:
        properties["notices"] = [alert.detail]
    if alert.url and alert.url.startswith("https://"):
        properties["link"] = {"url": alert.url, "label": f"Open alert on {alert.source}"}
    properties["footer"] = f"From {alert.source}"
    return {
        "type": "Feature",
        "id": f"bc_alerts:{alert.id}",
        "geometry": {
            "type": "Point",
            "coordinates": [round(alert.longitude, 5), round(alert.latitude, 5)],
        },
        "properties": properties,
    }


def map_feed_attributes(
    alerts: list[Alert],
    distances: dict[str, float],
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    """Return the attributes of a Map Feed sensor for some alerts.

    bbox is south, west, north, east.
    """
    return {
        "map_feed_version": MAP_FEED_VERSION,
        "feed_type": "other",
        "attribution": ATTRIBUTION,
        "area": {"bbox": list(bbox)},
        "legend": [
            {"color": CATEGORY_COLORS[category], "label": label}
            for category, label in CATEGORY_LABELS.items()
            if any(alert.category == category for alert in alerts)
        ],
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                alert_feature(alert, distances[alert.id]) for alert in alerts
            ],
        },
    }
