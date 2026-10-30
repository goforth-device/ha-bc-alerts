"""Fetch and normalise the public BC alert feeds.

This module has no Home Assistant imports so it can be tested on its own.
None of these feeds is a documented public API, so a feed that fails or changes
shape is reported per source and never stops the others.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import math
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

HYDRO_URL = "https://www.bchydro.com/power-outages/app/outages-map-data.json"
HYDRO_MAP_URL = "https://www.bchydro.com/power-outages/app/outage-map.html"
DRIVEBC_URL = "https://api.open511.gov.bc.ca/events"
DRIVEBC_MAP_URL = "https://www.drivebc.ca/"
ALERTABLE_URL = "https://feeds.alertable.ca/mobile/v2/feed.json"
EVACUATION_URL = (
    "https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/"
    "Evacuation_Orders_and_Alerts/FeatureServer/0/query"
)
EVACUATION_MAP_URL = "https://www.emergencyinfobc.gov.bc.ca/"

USER_AGENT = "HomeAssistant-bc_alerts"
REQUEST_TIMEOUT = ClientTimeout(total=30)

CATEGORY_POWER = "power"
CATEGORY_ROAD_CLOSURE = "road_closure"
CATEGORY_ROAD = "road"
CATEGORY_WATER = "water"
CATEGORY_EMERGENCY = "emergency"
CATEGORY_WEATHER = "weather"
CATEGORY_COMMUNITY = "community"

ALERTABLE_CATEGORIES = {
    "water": CATEGORY_WATER,
    "drinkingwate": CATEGORY_WATER,
    "sewer": CATEGORY_WATER,
    "roadclose": CATEGORY_ROAD_CLOSURE,
    "road": CATEGORY_ROAD,
    "rdcondition": CATEGORY_ROAD,
    "traffic": CATEGORY_ROAD,
    "construction": CATEGORY_ROAD,
    "utility": CATEGORY_POWER,
    "civilemerg": CATEGORY_EMERGENCY,
    "dangerperson": CATEGORY_EMERGENCY,
    "health": CATEGORY_EMERGENCY,
    "wind": CATEGORY_WEATHER,
    "rainfall": CATEGORY_WEATHER,
    "stormsurge": CATEGORY_WEATHER,
    "freezedrzl": CATEGORY_WEATHER,
}

# A feed that changes shape raises one of these while it is being parsed.
FEED_ERRORS = (
    ClientError,
    TimeoutError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    AttributeError,
)


@dataclass(frozen=True)
class Bounds:
    """The area to watch, in decimal degrees."""

    south: float
    west: float
    north: float
    east: float
    island_only: bool = False

    def contains(self, latitude: float, longitude: float) -> bool:
        """Return True if the point is inside the area."""
        return (
            self.south <= latitude <= self.north
            and self.west <= longitude <= self.east
            and not (self.island_only and _is_mainland(latitude, longitude))
        )


def _is_mainland(latitude: float, longitude: float) -> bool:
    """Return True east of a line up the Strait of Georgia.

    The line runs north-west from east of Saturna, between Galiano and Delta,
    then between Gabriola and Richmond. No box can keep all the Gulf Islands
    without also taking in Steveston and Tsawwassen.
    """
    return latitude > 48.95 and longitude > -123.0 - (latitude - 48.95) * 7 / 3


@dataclass(frozen=True)
class Alert:
    """One alert from any feed."""

    id: str
    source: str
    category: str
    title: str
    detail: str
    latitude: float
    longitude: float
    updated: datetime | None = None
    url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, hash=False)
    polygon: tuple[tuple[float, float], ...] = field(default=(), hash=False)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def point_in_polygon(
    latitude: float, longitude: float, polygon: tuple[tuple[float, float], ...]
) -> bool:
    """Return True if the point is inside a (lat, lon) polygon."""
    inside = False
    previous_lat, previous_lon = polygon[-1] if polygon else (0.0, 0.0)
    for lat, lon in polygon:
        if (lat > latitude) != (previous_lat > latitude):
            crossing = (previous_lon - lon) * (latitude - lat) / (
                previous_lat - lat
            ) + lon
            if longitude < crossing:
                inside = not inside
        previous_lat, previous_lon = lat, lon
    return inside


def _from_millis(value: int | None) -> datetime | None:
    """Convert epoch milliseconds to a datetime."""
    return datetime.fromtimestamp(value / 1000, UTC) if value else None


def _from_iso(value: str | None) -> datetime | None:
    """Convert an ISO timestamp to a datetime."""
    return datetime.fromisoformat(value) if value else None


def parse_hydro(rows: list[dict[str, Any]], bounds: Bounds) -> list[Alert]:
    """Turn the BC Hydro outage list into alerts."""
    alerts = []
    for row in rows:
        latitude, longitude = row["latitude"], row["longitude"]
        if not bounds.contains(latitude, longitude):
            continue
        cause = row.get("cause") or "Unknown cause"
        customers = row.get("numCustomersOut") or 0
        area = row.get("area") or "Unknown area"
        # The polygon is a flat list of longitude, latitude pairs.
        points = row.get("polygon") or []
        restoring = row.get("crewEtr") if row.get("showEtr") else row.get("dateOn")
        alerts.append(
            Alert(
                id=f"hydro-{row['id']}",
                source="BC Hydro",
                category=CATEGORY_POWER,
                title=f"{row.get('municipality') or 'Unknown'} outage",
                detail=f"{area}. {cause}. {customers} customers affected.",
                latitude=latitude,
                longitude=longitude,
                updated=_from_millis(row.get("lastUpdated")),
                url=HYDRO_MAP_URL,
                extra={
                    "area": area,
                    "cause": cause,
                    "customers_out": customers,
                    "planned": cause.lower().startswith("planned"),
                    "crew_status": row.get("crewStatusDescription"),
                    "power_off_since": _from_millis(row.get("dateOff")),
                    "estimated_restoration": _from_millis(restoring),
                },
                polygon=tuple(zip(points[1::2], points[0::2], strict=True)),
            )
        )
    return alerts


def _interval_is_active(interval: str, now: datetime) -> bool:
    """Return True if a UTC Open511 start/end interval covers now."""
    start, _, end = interval.partition("/")
    if datetime.fromisoformat(start).replace(tzinfo=UTC) > now:
        return False
    return not end or datetime.fromisoformat(end).replace(tzinfo=UTC) >= now


def _midpoint(geography: dict[str, Any]) -> tuple[float, float]:
    """Return a (lat, lon) point on an Open511 geometry."""
    kind, coordinates = geography["type"], geography["coordinates"]
    if kind == "Point":
        longitude, latitude = coordinates
    elif kind == "LineString":
        longitude, latitude = coordinates[len(coordinates) // 2]
    else:
        line = coordinates[0]
        longitude, latitude = line[len(line) // 2]
    return latitude, longitude


def parse_drivebc(
    payload: dict[str, Any], bounds: Bounds, now: datetime
) -> list[Alert]:
    """Turn DriveBC events into alerts, leaving out routine construction."""
    alerts = []
    for event in payload["events"]:
        latitude, longitude = _midpoint(event["geography"])
        if not bounds.contains(latitude, longitude):
            continue
        intervals = event.get("schedule", {}).get("intervals")
        if intervals and not any(_interval_is_active(i, now) for i in intervals):
            continue
        roads = event.get("roads") or [{}]
        closed = any(road.get("state") == "CLOSED" for road in roads)
        routine = (
            event.get("event_type") == "CONSTRUCTION"
            and event.get("severity") == "MINOR"
        )
        if routine and not closed:
            continue
        road = roads[0].get("name") or "Road"
        if road == "Other Roads":
            road = roads[0].get("from") or road
        headline = (event.get("headline") or "Event").replace("_", " ").capitalize()
        alerts.append(
            Alert(
                id=f"drivebc-{event['id'].rsplit('/', 1)[-1]}",
                source="DriveBC",
                category=CATEGORY_ROAD_CLOSURE if closed else CATEGORY_ROAD,
                title=f"{road} closed" if closed else f"{road}: {headline}",
                detail=event.get("description") or headline,
                latitude=latitude,
                longitude=longitude,
                updated=_from_iso(event.get("updated")),
                url=DRIVEBC_MAP_URL,
                extra={
                    "severity": event.get("severity"),
                    "event_type": event.get("event_type"),
                },
            )
        )
    return alerts


def parse_alertable(payload: dict[str, Any], bounds: Bounds) -> list[Alert]:
    """Turn the Alertable feed into alerts."""
    alerts = []
    for entry in payload["entries"]:
        if entry.get("state") == "ended" or entry.get("type_en") == "Cancelled":
            continue
        # DriveBC alerts come straight from the DriveBC feed instead.
        if entry.get("author_en") == "DriveBC":
            continue
        latitude, longitude = (float(part) for part in entry["point"].split())
        if not bounds.contains(latitude, longitude):
            continue
        event = entry.get("event_en") or "Alert"
        areas = [a["name_en"] for a in entry.get("area", []) if a.get("name_en")]
        alerts.append(
            Alert(
                id=f"alertable-{entry['id']}",
                source="Alertable",
                category=ALERTABLE_CATEGORIES.get(
                    entry.get("code"), CATEGORY_COMMUNITY
                ),
                title=event[:1].upper() + event[1:],
                detail=entry.get("summary_en") or event,
                latitude=latitude,
                longitude=longitude,
                updated=_from_iso(entry.get("updated")),
                url=entry.get("html_link"),
                extra={"issued_by": entry.get("author_en"), "areas": areas},
            )
        )
    return alerts


def _centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    """Return the (lat, lon) average of a polygon's outer ring."""
    coordinates = geometry["coordinates"]
    ring = coordinates[0] if geometry["type"] == "Polygon" else coordinates[0][0]
    return (
        sum(point[1] for point in ring) / len(ring),
        sum(point[0] for point in ring) / len(ring),
    )


def parse_evacuation(payload: dict[str, Any]) -> list[Alert]:
    """Turn evacuation orders and alerts into alerts."""
    alerts = []
    for feature in payload["features"]:
        properties = feature["properties"]
        status = properties.get("ORDER_ALERT_STATUS")
        if status not in ("Order", "Alert"):
            continue
        latitude, longitude = _centroid(feature["geometry"])
        name = properties.get("EVENT_NAME") or "Unnamed event"
        agency = properties.get("ISSUING_AGENCY")
        alerts.append(
            Alert(
                id=f"evacuation-{properties['OBJECTID']}",
                source="EmergencyInfoBC",
                category=CATEGORY_EMERGENCY,
                title=f"Evacuation {status.lower()}: {name}",
                detail=f"{properties.get('EVENT_TYPE')} issued by {agency}.",
                latitude=latitude,
                longitude=longitude,
                updated=_from_millis(properties.get("DATE_MODIFIED")),
                url=EVACUATION_MAP_URL,
                extra={"issued_by": agency, "status": status},
            )
        )
    return alerts


async def _fetch_json(
    session: ClientSession, url: str, params: dict[str, str] | None = None
) -> Any:
    """Fetch a URL and decode it as JSON whatever its content type says."""
    async with session.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    ) as response:
        response.raise_for_status()
        return json.loads(await response.text())


async def _load_hydro(
    session: ClientSession, bounds: Bounds, now: datetime
) -> list[Alert]:
    """Load BC Hydro outages."""
    return parse_hydro(await _fetch_json(session, HYDRO_URL), bounds)


async def _load_drivebc(
    session: ClientSession, bounds: Bounds, now: datetime
) -> list[Alert]:
    """Load DriveBC events."""
    params = {
        "format": "json",
        "status": "ACTIVE",
        "limit": "500",
        "bbox": f"{bounds.west},{bounds.south},{bounds.east},{bounds.north}",
    }
    return parse_drivebc(await _fetch_json(session, DRIVEBC_URL, params), bounds, now)


async def _load_alertable(
    session: ClientSession, bounds: Bounds, now: datetime
) -> list[Alert]:
    """Load Alertable alerts."""
    return parse_alertable(await _fetch_json(session, ALERTABLE_URL), bounds)


async def _load_evacuation(
    session: ClientSession, bounds: Bounds, now: datetime
) -> list[Alert]:
    """Load evacuation orders and alerts that touch the area."""
    params = {
        "where": "1=1",
        "geometry": f"{bounds.west},{bounds.south},{bounds.east},{bounds.north}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
    }
    return parse_evacuation(await _fetch_json(session, EVACUATION_URL, params))


Loader = Callable[[ClientSession, Bounds, datetime], Awaitable[list[Alert]]]

FEEDS: dict[str, Loader] = {
    "BC Hydro": _load_hydro,
    "DriveBC": _load_drivebc,
    "Alertable": _load_alertable,
    "EmergencyInfoBC": _load_evacuation,
}


async def fetch_all(
    session: ClientSession, bounds: Bounds, now: datetime
) -> tuple[dict[str, list[Alert]], dict[str, str]]:
    """Load every feed, returning the alerts and any per-feed errors."""

    async def load(name: str, loader: Loader) -> tuple[str, list[Alert] | str]:
        try:
            return name, await loader(session, bounds, now)
        except FEED_ERRORS as err:
            return name, f"{type(err).__name__}: {err}"

    results = await asyncio.gather(
        *(load(name, loader) for name, loader in FEEDS.items())
    )
    alerts = {name: value for name, value in results if isinstance(value, list)}
    errors = {name: value for name, value in results if isinstance(value, str)}
    return alerts, errors
