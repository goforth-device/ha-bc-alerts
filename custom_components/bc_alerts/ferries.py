"""BC Ferries sailings between Swartz Bay and Tsawwassen.

The data comes from bcferriesapi.ca, an unofficial JSON copy of BC Ferries'
current conditions pages. Like the other feeds it has no Home Assistant imports
so it can be tested on its own.

The API has no cancelled or delayed sailing status. Cancellations and delays
show up as route notices, as free text on a sailing, or as a sailing that
leaves (or still hasn't left) well after its scheduled time, so all three are
checked. Its newer v2 data doesn't always carry the Tsawwassen to Swartz Bay
direction, so that direction falls back to the older per-route endpoint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientSession

from .api import Alert, _fetch_json

FERRY_V2_URL = "https://bcferriesapi.ca/v2/capacity/"
FERRY_LEGACY_URL = "https://bcferriesapi.ca/api/{origin}/{destination}/"
FERRY_PAGE_URL = "https://www.bcferries.com/current-conditions/{origin}-{destination}"

CATEGORY_FERRY = "ferry"
# The API's times are BC wall-clock times. Home Assistant passes its own time
# zone in, so sailings line up with the clock you see even if the system's time
# zone data is out of date about BC's switch to permanent daylight time.
BC_TIME = ZoneInfo("America/Vancouver")

# Terminal code: (name, latitude, longitude).
TERMINALS = {
    "SWB": ("Swartz Bay", 48.6889, -123.4103),
    "TSA": ("Tsawwassen", 49.0067, -123.1313),
}
ROUTES = {"SWBTSA": ("SWB", "TSA"), "TSASWB": ("TSA", "SWB")}

# A sailing counts as delayed when it leaves this late, or hasn't left by then.
DELAY_MINUTES = 15
# Notices of these types are about delays or cancellations; others are news.
NOTICE_TYPES = {"delay", "cancellation"}
# A sailing that still hasn't left this long after its time is dropped: it was
# most likely cancelled, and the cancellation notice says so better.
GIVE_UP_HOURS = 3
# How many upcoming sailings each direction lists for dashboards.
LISTED_SAILINGS = 5


@dataclass(frozen=True)
class Sailing:
    """One sailing in one direction."""

    route: str
    scheduled: datetime
    vessel: str
    departed: datetime | None = None
    arrived: bool = False
    # Percent full, or None when BC Ferries hasn't published it.
    fill: int | None = None
    cancelled: bool = False
    note: str = ""

    @property
    def full(self) -> bool:
        """Return True if there's no vehicle space left."""
        return self.fill is not None and self.fill >= 100

    @property
    def delay_minutes(self) -> int:
        """Return how late it left, or 0."""
        if self.departed is None:
            return 0
        return max(0, int((self.departed - self.scheduled).total_seconds() // 60))


def _clock(value: str) -> time:
    """Read a time like "7:00 am"."""
    return datetime.strptime(value.strip(), "%I:%M %p").time()  # noqa: DTZ007


def _at(day: date, value: str, zone: tzinfo) -> datetime:
    """Return a BC local time on a day."""
    return datetime.combine(day, _clock(value), zone)


def _after(start: datetime, value: str) -> datetime:
    """Return the first time like "1:05 am" at or after a start, within a day."""
    moment = _at(start.date(), value, start.tzinfo)
    # Allow for a clock read a little early, then roll past midnight.
    if moment < start - timedelta(hours=1):
        moment += timedelta(days=1)
    return moment


def _route_name(route: str) -> str:
    """Return a route as "Swartz Bay to Tsawwassen"."""
    origin, destination = ROUTES[route]
    return f"{TERMINALS[origin][0]} to {TERMINALS[destination][0]}"


def _page_url(route: str) -> str:
    """Return BC Ferries' current conditions page for a route."""
    origin, destination = ROUTES[route]
    return FERRY_PAGE_URL.format(origin=origin, destination=destination)


def _fill(sailing: dict[str, Any]) -> int | None:
    """Return how full the car deck is, falling back to the whole ship."""
    if sailing.get("carCapacityKnown"):
        return int(sailing["carFill"])
    if sailing.get("capacityKnown"):
        return int(sailing["fill"])
    return None


def parse_v2_sailings(route: dict[str, Any], zone: tzinfo = BC_TIME) -> list[Sailing]:
    """Turn a v2 capacity route into sailings."""
    code = route["routeCode"]
    sailings = []
    for row in route.get("sailings") or []:
        day = date.fromisoformat(row.get("serviceDate") or route["serviceDate"])
        scheduled = _at(day, row.get("scheduledTime") or row["time"], zone)
        status = row.get("status") or ""
        departed = None
        actual = row.get("actualDepartureTime")
        if actual and status in ("departed", "arrived"):
            departed = _after(scheduled, actual)
        note = row.get("statusText") or row.get("vesselStatus") or ""
        sailings.append(
            Sailing(
                route=code,
                scheduled=scheduled,
                vessel=row.get("vesselName") or "",
                departed=departed,
                arrived=status == "arrived",
                fill=None if departed else _fill(row),
                cancelled="cancel" in note.lower(),
                note=note,
            )
        )
    return sailings


def parse_legacy_sailings(
    payload: dict[str, Any], route: str, now: datetime, zone: tzinfo = BC_TIME
) -> list[Sailing]:
    """Turn the older per-route list into sailings.

    It lists upcoming sailings only, without dates, so each one is placed at the
    first time on or after the one before it, starting from now.
    """
    local_now = now.astimezone(zone)
    previous = local_now - timedelta(hours=1)
    sailings = []
    for row in payload["sailings"]:
        scheduled = _after(previous, row["time"])
        previous = scheduled
        fill = row.get("carFill", row.get("fill"))
        note = row.get("vesselStatus") or ""
        sailings.append(
            Sailing(
                route=route,
                scheduled=scheduled,
                vessel=row.get("vesselName") or "",
                fill=None if fill is None else int(fill),
                cancelled=bool(row.get("isCancelled")) or "cancel" in note.lower(),
                note=note,
            )
        )
    return sailings


def parse_v2(
    payload: dict[str, Any], zone: tzinfo = BC_TIME
) -> tuple[dict[str, list[Sailing]], list[dict[str, Any]]]:
    """Return this pair's sailings by route, and its route notices."""
    sailings: dict[str, list[Sailing]] = {}
    notices: dict[str, dict[str, Any]] = {}
    for route in payload["routes"]:
        code = route.get("routeCode")
        for notice in route.get("notices") or []:
            if not set(notice.get("routeCodes") or [code]) & ROUTES.keys():
                continue
            # The same notice can be typed differently on different routes.
            seen = notices.setdefault(str(notice["id"]), dict(notice))
            if notice.get("type") in NOTICE_TYPES:
                seen["type"] = notice["type"]
            if notice.get("title"):
                seen["title"] = notice["title"]
        if code in ROUTES and route.get("dataStatus") == "available":
            sailings[code] = parse_v2_sailings(route, zone)
    return sailings, list(notices.values())


# "7:00 pm departing Swartz Bay" in a cancellation notice's text.
CANCELLED_SAILING = re.compile(
    r"(\d{1,2}:\d{2})\s*([ap])\.?m\.?\s+(?:sailing\s+)?(?:departing|from|leaving)\s+"
    r"(Swartz Bay|Tsawwassen)",
    re.IGNORECASE,
)


def notice_cancellations(
    sailings: dict[str, list[Sailing]], notices: list[dict[str, Any]], now: datetime
) -> dict[str, list[Sailing]]:
    """Mark the sailings a cancellation notice names as cancelled.

    BC Ferries lists cancelled sailings only in the notice's text, so the
    sailings themselves still look scheduled. Each named time is matched to the
    sailing at that clock time nearest to now, in the direction it departs.
    """
    by_name = {name.lower(): code for code, (name, _, _) in TERMINALS.items()}
    named: dict[str, set[time]] = {}
    for notice in notices:
        if notice.get("type") != "cancellation":
            continue
        text = " ".join(str(notice.get(k) or "") for k in ("title", "body"))
        for clock, half, terminal in CANCELLED_SAILING.findall(text):
            origin = by_name[terminal.lower()]
            route = next(r for r, (o, _) in ROUTES.items() if o == origin)
            named.setdefault(route, set()).add(_clock(f"{clock} {half}m"))
    result = {}
    for route, rows in sailings.items():
        times = named.get(route, set())
        rows = list(rows)
        for clock in times:
            matches = [
                i
                for i, s in enumerate(rows)
                if s.scheduled.time() == clock and s.departed is None
            ]
            if matches:
                i = min(matches, key=lambda i: abs(rows[i].scheduled - now))
                rows[i] = replace(rows[i], cancelled=True)
        result[route] = rows
    return result


def upcoming(sailings: list[Sailing], now: datetime) -> list[Sailing]:
    """Return the sailings that haven't left, plus any still crossing."""
    crossing = now - timedelta(hours=2)
    give_up = now - timedelta(hours=GIVE_UP_HOURS)
    return [
        s
        for s in sailings
        if not s.arrived
        and (s.departed > crossing if s.departed else s.scheduled > give_up)
    ]


def _pin(route: str) -> tuple[float, float]:
    """Return where a route's alerts go on the map: its departure terminal."""
    _, latitude, longitude = TERMINALS[ROUTES[route][0]]
    return latitude, longitude


def _clock_text(moment: datetime) -> str:
    """Return a time as "3:00 pm"."""
    return moment.strftime("%I:%M %p").lstrip("0").lower()


def sailing_alerts(route: str, sailings: list[Sailing], now: datetime) -> list[Alert]:
    """Return alerts for cancelled, late and full sailings on a route."""
    latitude, longitude = _pin(route)
    origin = TERMINALS[ROUTES[route][0]][0]
    url = _page_url(route)
    late = timedelta(minutes=DELAY_MINUTES)
    alerts = []
    ahead = upcoming(sailings, now)

    for s in ahead:
        when = _clock_text(s.scheduled)
        key = f"ferry-{route}-{s.scheduled:%Y%m%d%H%M}"
        extra = {
            "route": _route_name(route),
            "vessel": s.vessel,
            "scheduled": s.scheduled,
        }
        if s.cancelled:
            kind, title = "cancelled", f"{origin} {when} sailing cancelled"
        elif s.delay_minutes >= DELAY_MINUTES:
            kind = "delayed"
            title = f"{origin} {when} sailing left {s.delay_minutes} min late"
        elif s.departed is None and now - s.scheduled >= late:
            minutes = int((now - s.scheduled).total_seconds() // 60)
            kind = "delayed"
            title = f"{origin} {when} sailing hasn't left, {minutes} min late"
        elif "delay" in s.note.lower():
            kind, title = "delayed", f"{origin} {when} sailing delayed"
        else:
            continue
        alerts.append(
            Alert(
                id=key,
                source="BC Ferries",
                category=CATEGORY_FERRY,
                title=title,
                detail=f"{_route_name(route)}, {s.vessel}. {s.note}".strip(),
                latitude=latitude,
                longitude=longitude,
                url=url,
                extra={"kind": kind, **extra},
            )
        )

    # A sailing wait: the next sailing that can still take cars is full.
    # A sailing past its time is boarding or late, so it can't make you wait.
    waiting = [
        s for s in ahead if s.departed is None and not s.cancelled and s.scheduled > now
    ]
    full = 0
    for s in waiting:
        if not s.full:
            break
        full += 1
    if full:
        open_sailing = next((s for s in waiting[full:] if not s.full), None)
        if open_sailing:
            space = (
                ""
                if open_sailing.fill is None
                else f", {100 - open_sailing.fill}% space"
            )
            when = _clock_text(open_sailing.scheduled)
            detail = f"Next sailing with vehicle space: {when} ({open_sailing.vessel}{space})."
        else:
            detail = "No listed sailing has vehicle space."
        plural = "sailing" if full == 1 else "sailings"
        alerts.append(
            Alert(
                id=f"ferry-{route}-wait",
                source="BC Ferries",
                category=CATEGORY_FERRY,
                title=f"{full}-{plural} wait at {origin}",
                detail=f"{_route_name(route)}. {detail}",
                latitude=latitude,
                longitude=longitude,
                url=url,
                extra={
                    "kind": "wait",
                    "route": _route_name(route),
                    "sailing_wait": full,
                },
            )
        )
    return alerts


def notice_alerts(notices: list[dict[str, Any]]) -> list[Alert]:
    """Return alerts for delay and cancellation notices on the route."""
    alerts = []
    for notice in notices:
        if notice.get("type") not in NOTICE_TYPES:
            continue
        routes = [r for r in notice.get("routeCodes") or [] if r in ROUTES] or [
            "SWBTSA"
        ]
        terminals = notice.get("terminalCodes") or []
        terminal = next((t for t in terminals if t in TERMINALS), ROUTES[routes[0]][0])
        name, latitude, longitude = TERMINALS[terminal]
        body = " ".join((notice.get("body") or "").split())
        alerts.append(
            Alert(
                id=f"ferry-notice-{notice['id']}",
                source="BC Ferries",
                category=CATEGORY_FERRY,
                title=notice.get("title") or f"Ferry notice at {name}",
                detail=body[:500] or "See BC Ferries for details.",
                latitude=latitude,
                longitude=longitude,
                updated=_iso(notice.get("observedAt")),
                url=notice.get("url") or _page_url(routes[0]),
                extra={
                    "kind": notice["type"],
                    "severity": notice.get("severity"),
                    "route": _route_name(routes[0]),
                },
            )
        )
    return alerts


def _iso(value: str | None) -> datetime | None:
    """Read an RFC 3339 time, trimming nanoseconds Python can't parse."""
    if not value:
        return None
    head, _, rest = value.partition(".")
    zone = rest.lstrip("0123456789") if rest else ""
    fraction = rest[: len(rest) - len(zone)][:6] if rest else ""
    text = f"{head}.{fraction}{zone}" if fraction else f"{head}{zone}"
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def summary(sailings: list[Sailing], now: datetime) -> list[dict[str, Any]]:
    """Return the next few sailings on a route as plain attributes."""
    rows = []
    for s in upcoming(sailings, now)[:LISTED_SAILINGS]:
        if s.cancelled:
            status = "Cancelled"
        elif s.departed is not None:
            status = f"Left {_clock_text(s.departed)}"
            if s.delay_minutes >= DELAY_MINUTES:
                status += f" ({s.delay_minutes} min late)"
        elif s.full:
            status = "Full"
        elif s.fill is not None:
            status = f"{100 - s.fill}% space"
        else:
            status = "Scheduled"
        rows.append(
            {
                "time": _clock_text(s.scheduled),
                "scheduled": s.scheduled,
                "vessel": s.vessel,
                "status": status,
                "space_pct": None if s.fill is None else 100 - s.fill,
                "note": s.note,
            }
        )
    return rows


def route_key(route: str) -> str:
    """Return a route as an attribute name, like "swartz_bay_to_tsawwassen"."""
    return _route_name(route).lower().replace(" ", "_")


async def load_ferries(
    session: ClientSession, now: datetime, zone: tzinfo = BC_TIME
) -> tuple[list[Alert], dict[str, list[dict[str, Any]]]]:
    """Load both directions, returning alerts and the next sailings each way."""
    sailings, notices = parse_v2(await _fetch_json(session, FERRY_V2_URL), zone)
    for route, (origin, destination) in ROUTES.items():
        if route not in sailings:
            url = FERRY_LEGACY_URL.format(origin=origin, destination=destination)
            sailings[route] = parse_legacy_sailings(
                await _fetch_json(session, url), route, now, zone
            )
    sailings = notice_cancellations(sailings, notices, now)
    alerts = notice_alerts(notices)
    for route, rows in sailings.items():
        alerts.extend(sailing_alerts(route, rows, now))
    return alerts, {route_key(r): summary(rows, now) for r, rows in sailings.items()}
